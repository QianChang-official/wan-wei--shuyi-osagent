"""万枢平台 · 模型接入舱（B1）。

31 家模型服务商接入目录 + 密钥/端点配置管理。

路由（统一挂在 ``/platform`` 前缀下，由 platform_api 包自动发现）：
- GET    /providers/catalog            31 家 provider 元数据数组
- GET    /providers/configs            全部配置（api_key 脱敏只回尾 4 位）
- PUT    /providers/configs/{pid}      新建/更新配置（api_key Fernet 加密落盘）
- DELETE /providers/configs/{pid}      删除配置
- POST   /providers/test               连通性测试（local 真实探测；云端复用
                                      model_gateway 真实 OpenAI 兼容探测，issue #45 4.5）
- GET    /providers/aux                辅助模型配置
- PUT    /providers/aux                更新辅助模型配置
- POST   /providers/auth/{pid}/begin   OAuth 设备授权开始（真实流程未接入，如实 501）
- POST   /providers/auth/{pid}/poll    OAuth 设备授权轮询（真实流程未接入，如实 501）

持久化：``JsonStore('providers')``，key 为 provider id；
辅助模型存于保留 key ``_aux``。
密钥加密复用 ``app.security.encryption``（Fernet，密钥派生模式与
``app.model_gateway.service`` 一致：优先 ``WANWEI_ENCRYPTION_KEY``，
否则由平台 API Key 派生）。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional
from urllib.parse import urlparse, urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.platform_api.guards import audit_safe
from app.platform_api.store import JsonStore
from app.security import encryption
from app.security.ssrf import SSRFError, resolve_external_url, validate_external_url
from app.utils.datetime_utils import utc_now_iso

router = APIRouter(tags=['providers'])
logger = logging.getLogger(__name__)

_store = JsonStore('providers')

# 辅助模型在 JsonStore('providers') 中的保留 key（不会与 provider id 冲突）
_AUX_KEY = '_aux'

# 本地类 provider：test 时真实探测 base_url（3 秒超时）
_LOCAL_KINDS = {'local'}

# 连通性测试 SSRF 豁免：仅用户显式配置的本机回环地址（Ollama / LM Studio 等
# 本地推理端点）允许探测，其余内网/元数据地址一律按 denylist 拦截。
_LOCAL_PROBE_ALLOWLIST = ['localhost', '127.0.0.1', '::1']


def _same_origin(left: str, right: str) -> bool:
    a = urlparse((left or '').rstrip('/'))
    b = urlparse((right or '').rstrip('/'))
    def norm_host(host: str | None) -> str | None:
        return 'loopback' if host in {'127.0.0.1', 'localhost', '::1'} else host
    try:
        # urlparse 的 .port 对非法端口（如 http://host:abc）抛 ValueError；
        # 畸形 base_url 按「不同源」拒绝探测，不冒泡成 500。
        return (a.scheme, norm_host(a.hostname), a.port) == (b.scheme, norm_host(b.hostname), b.port)
    except ValueError:
        return False

# ---------------------------------------------------------------------------
# 31 家 provider 接入目录（顺序即契约顺序，勿随意调整）
# ---------------------------------------------------------------------------
CATALOG: list[dict[str, Any]] = [
    {
        'id': 'openrouter',
        'name': 'OpenRouter 聚合路由',
        'kind': 'aggregator',
        'base_url': 'https://openrouter.ai/api/v1',
        'models': ['anthropic/claude-sonnet-4.5', 'openai/gpt-4.1', 'google/gemini-2.5-pro'],
        'auth_modes': ['api_key'],
        'docs_url': 'https://openrouter.ai/docs',
        'aux_capable': True,
        'description': '一把密钥接入数百家云端模型的聚合网关。',
    },
    {
        'id': 'mixture_of_agents',
        'name': 'MoA 混合智能体',
        'kind': 'aggregator',
        'base_url': 'https://api.together.xyz/v1',
        'models': ['mistralai/Mixtral-8x22B-Instruct-v0.1', 'meta-llama/Llama-3.3-70B-Instruct-Turbo', 'Qwen/Qwen3-235B-A22B'],
        'auth_modes': ['api_key'],
        'docs_url': 'https://docs.together.ai',
        'aux_capable': False,
        'description': '多模型混合增强架构（Together 承载）。',
    },
    {
        'id': 'novitaai',
        'name': 'Novita AI',
        'kind': 'cloud',
        'base_url': 'https://api.novita.ai/v3/openai',
        'models': ['deepseek/deepseek-v3-0324', 'meta-llama/llama-3.3-70b-instruct', 'qwen/qwen3-235b-a22b'],
        'auth_modes': ['api_key'],
        'docs_url': 'https://novita.ai/llm-api',
        'aux_capable': False,
        'description': '高性价比开源模型推理云。',
    },
    {
        'id': 'lm_studio',
        'name': 'LM Studio 本地推理',
        'kind': 'local',
        'base_url': 'http://127.0.0.1:1234/v1',
        'models': ['qwen/qwen3-8b', 'meta-llama-3.1-8b-instruct', 'mistral-7b-instruct-v0.3'],
        'auth_modes': ['local'],
        'docs_url': 'https://lmstudio.ai/docs',
        'aux_capable': True,
        'description': '桌面本地模型运行时，OpenAI 兼容接口。',
    },
    {
        'id': 'anthropic',
        'name': 'Anthropic Claude',
        'kind': 'cloud',
        'base_url': 'https://api.anthropic.com',
        'models': ['claude-opus-4-1', 'claude-sonnet-4-5', 'claude-haiku-4-5'],
        'auth_modes': ['api_key'],
        'docs_url': 'https://docs.anthropic.com',
        'aux_capable': True,
        'description': 'Claude 系列旗舰模型官方接口。',
    },
    {
        'id': 'openai',
        'name': 'OpenAI',
        'kind': 'cloud',
        'base_url': 'https://api.openai.com/v1',
        'models': ['gpt-4.1', 'gpt-4o', 'o3'],
        'auth_modes': ['api_key', 'oauth'],
        'docs_url': 'https://platform.openai.com/docs',
        'aux_capable': True,
        'description': 'GPT 系列模型官方接口。',
    },
    {
        'id': 'qwen_cloud',
        'name': '阿里云百炼·通义千问',
        'kind': 'cloud',
        'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        'models': ['qwen3-max', 'qwen-plus', 'qwen-flash'],
        'auth_modes': ['api_key'],
        'docs_url': 'https://help.aliyun.com/zh/model-studio',
        'aux_capable': True,
        'description': '阿里云百炼平台通义千问系列。',
    },
    {
        'id': 'xai_grok',
        'name': 'xAI Grok',
        'kind': 'cloud',
        'base_url': 'https://api.x.ai/v1',
        'models': ['grok-4', 'grok-4-fast-reasoning', 'grok-code-fast-1'],
        'auth_modes': ['api_key'],
        'docs_url': 'https://docs.x.ai',
        'aux_capable': False,
        'description': 'xAI Grok 系列模型。',
    },
    {
        'id': 'xiaomi_mimo',
        'name': '小米 MiMo',
        'kind': 'cloud',
        # 已核实：按量付费 OpenAI 兼容入口为 api.xiaomimimo.com/v1（2026 年官方
        # 开放平台）；Token Plan 套餐需改用 token-plan-cn.xiaomimimo.com/v1。
        'base_url': 'https://api.xiaomimimo.com/v1',
        'models': ['mimo-v2-flash', 'mimo-v2.5-pro', 'mimo-v2-omni'],
        'auth_modes': ['api_key'],
        'docs_url': 'https://platform.xiaomimimo.com',
        'aux_capable': False,
        'description': '小米 MiMo 开放平台（按量付费入口；Token Plan 套餐请改 base_url 为 token-plan-cn.xiaomimimo.com/v1）。',
    },
    {
        'id': 'tencent_tokenhub',
        'name': '腾讯混元 TokenHub',
        'kind': 'cloud',
        'base_url': 'https://api.hunyuan.cloud.tencent.com/v1',
        'models': ['hunyuan-turbos-latest', 'hunyuan-large', 'hunyuan-code'],
        'auth_modes': ['api_key'],
        'docs_url': 'https://cloud.tencent.com/document/product/1729',
        'aux_capable': False,
        'description': '腾讯混元大模型统一接入。',
    },
    {
        'id': 'nvidia_nim',
        'name': 'NVIDIA NIM',
        'kind': 'cloud',
        'base_url': 'https://integrate.api.nvidia.com/v1',
        'models': ['meta/llama-3.3-70b-instruct', 'deepseek-ai/deepseek-r1', 'nvidia/llama-3.1-nemotron-ultra-253b-v1'],
        'auth_modes': ['api_key'],
        'docs_url': 'https://docs.api.nvidia.com',
        'aux_capable': False,
        'description': '英伟达 NIM 托管推理目录。',
    },
    {
        'id': 'github_copilot',
        'name': 'GitHub Copilot',
        'kind': 'oauth',
        'base_url': 'https://api.githubcopilot.com',
        'models': ['gpt-4o', 'claude-sonnet-4', 'o3-mini'],
        'auth_modes': ['oauth'],
        'docs_url': 'https://docs.github.com/zh/copilot',
        'aux_capable': False,
        'description': 'GitHub Copilot 订阅内模型（OAuth 设备授权）。',
    },
    {
        'id': 'huggingface',
        'name': 'Hugging Face 推理',
        'kind': 'cloud',
        'base_url': 'https://router.huggingface.co/v1',
        'models': ['meta-llama/Llama-3.3-70B-Instruct', 'deepseek-ai/DeepSeek-R1', 'Qwen/Qwen3-32B'],
        'auth_modes': ['api_key', 'oauth'],
        'docs_url': 'https://huggingface.co/docs/inference-providers',
        'aux_capable': False,
        'description': 'Hugging Face 推理路由（多家承载商）。',
    },
    {
        'id': 'google_ai_studio',
        'name': 'Google AI Studio（Gemini）',
        'kind': 'cloud',
        'base_url': 'https://generativelanguage.googleapis.com/v1beta',
        'models': ['gemini-2.5-pro', 'gemini-2.5-flash', 'gemini-2.5-flash-lite'],
        'auth_modes': ['api_key'],
        'docs_url': 'https://ai.google.dev/gemini-api/docs',
        'aux_capable': True,
        'description': 'Google Gemini 开发者接口。',
    },
    {
        'id': 'google_vertex',
        'name': 'Google Vertex AI',
        'kind': 'oauth',
        'base_url': 'https://aiplatform.googleapis.com/v1',
        'models': ['gemini-2.5-pro', 'gemini-2.5-flash'],
        'auth_modes': ['oauth'],
        'docs_url': 'https://cloud.google.com/vertex-ai/generative-ai/docs',
        'aux_capable': False,
        'description': 'Google Cloud 企业级 Gemini 接入。',
    },
    {
        'id': 'deepseek',
        'name': 'DeepSeek 深度求索',
        'kind': 'cloud',
        'base_url': 'https://api.deepseek.com',
        'models': ['deepseek-chat', 'deepseek-reasoner'],
        'auth_modes': ['api_key'],
        'docs_url': 'https://api-docs.deepseek.com/zh-cn',
        'aux_capable': True,
        'description': 'DeepSeek 官方接口，性价比突出。',
    },
    {
        'id': 'zai',
        'name': '智谱 Z.ai',
        'kind': 'cloud',
        'base_url': 'https://api.z.ai/api/paas/v4',
        'models': ['glm-4.6', 'glm-4.5', 'glm-4.5-air'],
        'auth_modes': ['api_key'],
        'docs_url': 'https://docs.z.ai',
        'aux_capable': True,
        'description': '智谱 GLM 系列模型。',
    },
    {
        'id': 'kimi_moonshot',
        'name': 'Kimi·月之暗面',
        'kind': 'cloud',
        'base_url': 'https://api.moonshot.cn/v1',
        'models': ['kimi-k2-0905-preview', 'kimi-k2-turbo-preview', 'moonshot-v1-128k'],
        'auth_modes': ['api_key'],
        'docs_url': 'https://platform.moonshot.cn/docs',
        'aux_capable': True,
        'description': '月之暗面 Kimi K2 系列模型。',
    },
    {
        'id': 'stepfun',
        'name': '阶跃星辰 StepFun',
        'kind': 'cloud',
        'base_url': 'https://api.stepfun.com/v1',
        'models': ['step-3', 'step-2-16k', 'step-1v-32k'],
        'auth_modes': ['api_key'],
        'docs_url': 'https://platform.stepfun.com/docs',
        'aux_capable': False,
        'description': '阶跃星辰 Step 系列模型。',
    },
    {
        'id': 'minimax',
        'name': 'MiniMax',
        'kind': 'cloud',
        'base_url': 'https://api.minimaxi.com/v1',
        'models': ['MiniMax-M2', 'MiniMax-Text-01', 'abab6.5s-chat'],
        'auth_modes': ['api_key'],
        'docs_url': 'https://platform.minimaxi.com/document',
        'aux_capable': False,
        'description': 'MiniMax 文本与多模态模型。',
    },
    {
        'id': 'ollama_cloud',
        'name': 'Ollama（本地/云）',
        'kind': 'local',
        'base_url': 'http://127.0.0.1:11434',
        'models': ['qwen3:32b', 'llama3.3', 'deepseek-r1:32b'],
        'auth_modes': ['local', 'api_key'],
        'docs_url': 'https://github.com/ollama/ollama',
        'aux_capable': True,
        'description': '本地 Ollama 运行时，亦支持 Ollama 云端模型。',
    },
    {
        'id': 'arcee_ai',
        'name': 'Arcee AI',
        'kind': 'cloud',
        # 已核实：官方 OpenAI 兼容入口为 api.arcee.ai/api/v1（docs.arcee.ai）。
        'base_url': 'https://api.arcee.ai/api/v1',
        'models': ['trinity-mini'],
        'auth_modes': ['api_key'],
        'docs_url': 'https://docs.arcee.ai',
        'aux_capable': False,
        'description': 'Arcee Trinity 系列开源模型云。',
    },
    {
        'id': 'gmi_cloud',
        'name': 'GMI Cloud',
        'kind': 'cloud',
        'base_url': 'https://api.gmi-serving.com/v1',
        'models': ['deepseek-ai/DeepSeek-R1', 'meta-llama/Llama-3.3-70B-Instruct', 'Qwen/Qwen3-235B-A22B'],
        'auth_modes': ['api_key'],
        'docs_url': 'https://docs.gmicloud.ai',
        'aux_capable': False,
        'description': 'GMI GPU 云推理服务。',
    },
    {
        'id': 'kilo_code',
        'name': 'Kilo Code',
        'kind': 'aggregator',
        # 已核实：Kilo AI Gateway 官方入口为 api.kilo.ai/api/gateway（kilo.ai/docs/gateway）。
        'base_url': 'https://api.kilo.ai/api/gateway',
        'models': ['anthropic/claude-sonnet-4.5', 'openai/gpt-4.1', 'google/gemini-2.5-pro'],
        'auth_modes': ['api_key'],
        'docs_url': 'https://kilo.ai/docs/gateway',
        'aux_capable': False,
        'description': 'Kilo Gateway 编码助手模型路由。',
    },
    {
        'id': 'opencode',
        'name': 'OpenCode',
        'kind': 'aggregator',
        'base_url': 'https://opencode.ai/zen/v1',
        'models': ['claude-sonnet-4.5', 'qwen3-coder-plus', 'kimi-k2'],
        'auth_modes': ['api_key'],
        'docs_url': 'https://opencode.ai/docs',
        'aux_capable': False,
        'description': 'OpenCode Zen 编码模型聚合。',
    },
    {
        'id': 'aws_bedrock',
        'name': 'AWS Bedrock',
        'kind': 'cloud',
        'base_url': 'https://bedrock-runtime.us-east-1.amazonaws.com',
        'models': ['anthropic.claude-sonnet-4-5', 'amazon.nova-pro-v1:0', 'meta.llama3-3-70b-instruct-v1:0'],
        'auth_modes': ['api_key'],
        'docs_url': 'https://docs.aws.amazon.com/bedrock',
        'aux_capable': False,
        'description': '亚马逊 Bedrock 托管模型（AWS 凭证）。',
    },
    {
        'id': 'azure_foundry',
        'name': 'Azure AI Foundry',
        'kind': 'cloud',
        # 已核实：官方推理端点格式为 https://<resource>.services.ai.azure.com/models
        # （Microsoft Learn），<resource> 为每用户资源名，无法给出统一默认值。
        'base_url': 'https://YOUR_RESOURCE.services.ai.azure.com/models',
        'placeholder': True,  # base_url 含占位符，须替换 YOUR_RESOURCE 为实际 Azure 资源名
        'models': ['gpt-4o', 'DeepSeek-R1', 'Phi-4'],
        'auth_modes': ['api_key', 'oauth'],
        'docs_url': 'https://learn.microsoft.com/zh-cn/azure/ai-foundry',
        'aux_capable': False,
        'description': '微软 Azure AI Foundry 模型目录（base_url 中 YOUR_RESOURCE 需替换为你的 Azure 资源名）。',
    },
    {
        'id': 'qwen_oauth',
        'name': '通义千问 OAuth 免密',
        'kind': 'oauth',
        'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        'models': ['qwen3-max', 'qwen3-coder-plus', 'qwen-flash'],
        'auth_modes': ['oauth'],
        'docs_url': 'https://help.aliyun.com/zh/model-studio',
        'aux_capable': False,
        'description': '通义千问 OAuth 授权接入，免手动填密钥。',
    },
    {
        'id': 'alibaba_coding_plan',
        'name': '阿里云百炼·编码套餐',
        'kind': 'cloud',
        'base_url': 'https://coding.dashscope.aliyuncs.com/v1',
        'models': ['qwen3-coder-plus', 'qwen3-coder-flash', 'qwen3-max'],
        'auth_modes': ['api_key'],
        'docs_url': 'https://help.aliyun.com/zh/model-studio',
        'aux_capable': False,
        'description': '阿里云百炼编码场景套餐额度。',
    },
    {
        'id': 'siliconflow',
        'name': '硅基流动 SiliconFlow',
        'kind': 'cloud',
        'base_url': 'https://api.siliconflow.cn/v1',
        'models': ['deepseek-ai/DeepSeek-V3.2-Exp', 'Qwen/Qwen3-235B-A22B', 'Pro/deepseek-ai/DeepSeek-R1'],
        'auth_modes': ['api_key'],
        'docs_url': 'https://docs.siliconflow.cn',
        'aux_capable': True,
        'description': '硅基流动国产开源模型推理云。',
    },
    {
        'id': 'custom_endpoint',
        'name': '自定义兼容端点',
        'kind': 'custom',
        'base_url': '',
        'models': [],
        'auth_modes': ['api_key', 'local'],
        'docs_url': '',
        'aux_capable': True,
        'description': '任意 OpenAI 兼容端点，自行填写 base_url 与模型名。',
    },
]

_CATALOG_BY_ID = {p['id']: p for p in CATALOG}

_AUX_DEFAULT = {
    'pid': '',
    'model': '',
    'enabled': False,
    'purpose': '辅助任务（对话标题生成、摘要、标签提取）',
}


# ---------------------------------------------------------------------------
# 请求体模型
# ---------------------------------------------------------------------------
class ConfigIn(BaseModel):
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    enabled: Optional[bool] = None
    extra: Optional[dict[str, Any]] = None


class TestIn(BaseModel):
    pid: str


class AuxIn(BaseModel):
    pid: Optional[str] = None
    model: Optional[str] = None
    enabled: Optional[bool] = None
    purpose: Optional[str] = None


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------
def _get_provider_meta(pid: str) -> dict[str, Any]:
    meta = _CATALOG_BY_ID.get(pid)
    if meta is None:
        raise HTTPException(status_code=404, detail=f'未知的 provider：{pid}')
    return meta


def _decrypt_key(record: dict[str, Any]) -> str:
    enc = record.get('api_key_encrypted') or ''
    if not enc:
        return ''
    try:
        return encryption.decrypt(enc)
    except Exception:  # noqa: BLE001 —— 解密失败视同无密钥，不阻断读取
        return ''


def _masked_config(pid: str, record: Optional[dict[str, Any]]) -> dict[str, Any]:
    """把存储记录转为对外脱敏视图；record 为 None 时回目录默认值。"""
    meta = _CATALOG_BY_ID[pid]
    record = record or {}
    plain = _decrypt_key(record)
    tail = plain[-4:] if plain else ''
    return {
        'pid': pid,
        'configured': bool(record),
        'enabled': bool(record.get('enabled', False)),
        'base_url': record.get('base_url') or meta['base_url'],
        'model': record.get('model') or (meta['models'][0] if meta['models'] else ''),
        'has_api_key': bool(plain),
        'api_key_tail': tail,
        'api_key_masked': f'****{tail}' if tail else '',
        'extra': record.get('extra') or {},
        'updated_at': record.get('updated_at') or '',
    }


def _remove_config(pid: str) -> bool:
    """JsonStore 锁内删除配置，返回删除前是否存在。"""
    def _remove(data: dict) -> bool:
        if pid not in data:
            return False
        data.pop(pid, None)
        return True

    return _store.mutate(_remove)


def _probe_pinned_url(url: str, pinned_ip: str) -> httpx.Response:
    """Connect to the validated IP while preserving the original HTTP/TLS host."""
    parsed = urlsplit(url)
    hostname = parsed.hostname or ''
    hostname_ascii = hostname.encode('idna').decode('ascii')
    pinned_host = f'[{pinned_ip}]' if ':' in pinned_ip else pinned_ip
    original_host = f'[{hostname_ascii}]' if ':' in hostname_ascii else hostname_ascii
    if parsed.port is not None:
        pinned_host = f'{pinned_host}:{parsed.port}'
        original_host = f'{original_host}:{parsed.port}'
    pinned_url = urlunsplit((parsed.scheme, pinned_host, parsed.path, parsed.query, ''))
    extensions = {'sni_hostname': hostname_ascii} if parsed.scheme == 'https' else None

    # trust_env=False prevents a proxy from replacing the validated destination.
    # httpcore consumes sni_hostname for certificate verification against the
    # original host even though the TCP connection is pinned to the resolved IP.
    with httpx.Client(timeout=3.0, follow_redirects=False, trust_env=False) as client:
        return client.get(
            pinned_url,
            headers={'Host': original_host},
            extensions=extensions,
        )


# ---------------------------------------------------------------------------
# 目录与配置
# ---------------------------------------------------------------------------
@router.get('/providers/catalog')
def get_catalog() -> list[dict[str, Any]]:
    """31 家 provider 元数据数组。"""
    return CATALOG


@router.get('/providers/configs')
def list_configs() -> list[dict[str, Any]]:
    """全部 31 家配置视图（未配置的按目录默认值占位），api_key 只回尾 4 位。"""
    stored = _store.all()
    return [_masked_config(p['id'], stored.get(p['id'])) for p in CATALOG]


@router.put('/providers/configs/{pid}')
def put_config(pid: str, body: ConfigIn) -> dict[str, Any]:
    meta = _get_provider_meta(pid)
    patch: dict[str, Any] = {}
    clear_api_key = False
    if body.api_key is not None:
        if body.api_key.strip():
            try:
                patch['api_key_encrypted'] = encryption.encrypt(body.api_key.strip())
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    'Provider credential encryption failed: pid=%s error_type=%s',
                    pid,
                    type(exc).__name__,
                    exc_info=True,
                )
                raise HTTPException(
                    status_code=500,
                    detail='密钥加密失败，请检查服务端加密配置',
                ) from None
        else:
            # 显式传空串 = 清除已存密钥
            clear_api_key = True
    if body.base_url is not None:
        new_url = body.base_url.strip()
        # SSRF 写入即拒：用户显式修改 base_url（非空且非目录默认值）时先做校验
        if new_url and new_url != meta['base_url']:
            try:
                validate_external_url(
                    new_url,
                    allowlist=_LOCAL_PROBE_ALLOWLIST if meta['kind'] in _LOCAL_KINDS else [],
                )
            except SSRFError as exc:
                logger.warning(
                    'Provider base URL rejected by SSRF policy: pid=%s error_type=%s',
                    pid,
                    type(exc).__name__,
                )
                raise HTTPException(
                    status_code=422,
                    detail='base_url 未通过 SSRF 防护校验',
                ) from None
        patch['base_url'] = new_url
    if body.model is not None:
        patch['model'] = body.model.strip()
    if body.enabled is not None:
        patch['enabled'] = bool(body.enabled)
    if body.extra is not None:
        patch['extra'] = body.extra

    def _apply(data: dict) -> dict[str, Any]:
        stored = data.get(pid)
        record = dict(stored) if isinstance(stored, dict) else {}
        if clear_api_key:
            record.pop('api_key_encrypted', None)
        record.update(patch)
        record.setdefault('base_url', meta['base_url'])
        record.setdefault('model', meta['models'][0] if meta['models'] else '')
        record.setdefault('enabled', False)
        record['updated_at'] = utc_now_iso()
        data[pid] = record
        return record

    record = _store.mutate(_apply)
    audit_safe('provider_config_updated', {
        'pid': pid,
        'has_api_key': bool(record.get('api_key_encrypted')),
        'enabled': record.get('enabled'),
        'model': record.get('model'),
    })
    return _masked_config(pid, record)


@router.delete('/providers/configs/{pid}')
def delete_config(pid: str) -> dict[str, Any]:
    _get_provider_meta(pid)
    removed = _remove_config(pid)
    audit_safe('provider_config_deleted', {'pid': pid, 'removed': removed})
    return {'ok': True, 'pid': pid, 'removed': removed}


# ---------------------------------------------------------------------------
# 连通性测试
# ---------------------------------------------------------------------------
@router.post('/providers/test')
def test_provider(body: TestIn) -> dict[str, Any]:
    meta = _get_provider_meta(body.pid)
    record = _store.get(body.pid) or {}

    # 本地类（lm_studio / ollama_cloud）：真实探测 base_url，3 秒超时
    if meta['kind'] in _LOCAL_KINDS:
        base_url = (record.get('base_url') or meta['base_url']).rstrip('/')
        if not base_url:
            return {'ok': False, 'pid': body.pid, 'reason': '未配置 base_url'}
        if not _same_origin(base_url, meta['base_url']):
            return {'ok': False, 'pid': body.pid, 'mode': 'live', 'reason': 'SSRF 防护：本地 provider 仅允许探测内置默认地址，拒绝自定义端口扫描'}
        # SSRF 防护：base_url 用户可控，先过协议白名单 + 内网/元数据地址拦截；
        # 仅显式配置的本机回环地址（Ollama / LM Studio）豁免。
        try:
            normalized_url, pinned_ip = resolve_external_url(
                base_url,
                allowlist=_LOCAL_PROBE_ALLOWLIST,
            )
        except SSRFError as exc:
            logger.warning(
                'Provider probe rejected by SSRF policy: pid=%s error_type=%s',
                body.pid,
                type(exc).__name__,
            )
            return {
                'ok': False,
                'pid': body.pid,
                'mode': 'live',
                'reason': 'base_url 未通过 SSRF 防护校验',
            }
        started = time.perf_counter()
        try:
            resp = _probe_pinned_url(normalized_url, pinned_ip)
            latency_ms = int((time.perf_counter() - started) * 1000)
            return {
                'ok': True,
                'pid': body.pid,
                'mode': 'live',
                'status_code': resp.status_code,
                'latency_ms': latency_ms,
                'note': '本地服务可达（真实探测）。',
            }
        except Exception as exc:  # noqa: BLE001 —— 任何网络异常都归为不可达
            logger.warning(
                'Local provider probe failed: pid=%s error_type=%s',
                body.pid,
                type(exc).__name__,
                exc_info=True,
            )
            return {
                'ok': False,
                'pid': body.pid,
                'mode': 'live',
                'reason': '本地服务不可达',
            }

    # 云端/聚合/OAuth：密钥未配置则明确失败
    if not _decrypt_key(record):
        return {'ok': False, 'pid': body.pid, 'reason': '未配置密钥'}

    # 云端：复用 model_gateway 的真实 OpenAI-compatible 探测（4.5）。
    # 与 /model-gateway/test 走同一套 pinned-IP SSRF 防护与超时，
    # 不再各写一份「模拟通过」的假成功。
    from app.model_gateway.service import probe_openai_compatible

    base_url = (record.get('base_url') or meta['base_url']).rstrip('/')
    model = record.get('model') or (meta['models'][0] if meta['models'] else '')
    api_key = _decrypt_key(record)
    started = time.perf_counter()
    try:
        status, latency_ms, preview = probe_openai_compatible(
            base_url, api_key, model,
        )
        if status != 'ok':
            return {
                'ok': False,
                'pid': body.pid,
                'mode': 'live',
                'reason': f'云端探测失败（{status}），请检查端点/模型与密钥权限',
            }
        return {
            'ok': True,
            'pid': body.pid,
            'mode': 'live',
            'latency_ms': latency_ms,
            'note': f'云端连通正常（真实探测），模型：{model}',
            'response_preview': preview[:80],
        }
    except Exception as exc:  # noqa: BLE001 —— 网络/SSRF/队列异常统一归为不可达
        logger.warning(
            'Cloud provider probe failed: pid=%s error_type=%s',
            body.pid,
            type(exc).__name__,
            exc_info=True,
        )
        elapsed = int((time.perf_counter() - started) * 1000)
        return {
            'ok': False,
            'pid': body.pid,
            'mode': 'live',
            'latency_ms': elapsed,
            'reason': '云端服务不可达或未通过 SSRF 防护校验',
        }


# ---------------------------------------------------------------------------
# 辅助模型
# ---------------------------------------------------------------------------
@router.get('/providers/aux')
def get_aux() -> dict[str, Any]:
    stored = _store.get(_AUX_KEY) or {}
    return {**_AUX_DEFAULT, **stored}


@router.put('/providers/aux')
def put_aux(body: AuxIn) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    if body.pid is not None:
        pid = body.pid.strip()
        if pid:  # 允许空串清除
            meta = _get_provider_meta(pid)
            if not meta.get('aux_capable'):
                raise HTTPException(status_code=400, detail=f'{meta["name"]} 不支持作为辅助模型')
        patch['pid'] = pid
    if body.model is not None:
        patch['model'] = body.model.strip()
    if body.enabled is not None:
        patch['enabled'] = bool(body.enabled)
    if body.purpose is not None:
        patch['purpose'] = body.purpose.strip() or _AUX_DEFAULT['purpose']

    def _apply(data: dict) -> dict[str, Any]:
        stored = data.get(_AUX_KEY)
        current = {**_AUX_DEFAULT, **(stored if isinstance(stored, dict) else {})}
        current.update(patch)
        data[_AUX_KEY] = current
        return current

    current = _store.mutate(_apply)
    return current


# ---------------------------------------------------------------------------
# OAuth 设备授权流程
#
# 诚实化说明：当前没有任何 provider 配置真实的 OAuth client_id / device
# endpoint，无法发起真实的设备授权。此前的 stub 会返回伪造的
# verification_uri（auth.wanwei.local 死链）与 user_code，且 begin/poll 之间
# 无任何语义关联，已按"拿不准就诚实化"原则移除：
# - begin：如实返回 501 not_implemented，不再给出假链接/假设备码；
# - poll ：已手动配置密钥的视为已授权（status=authorized，这是真实状态），
#          否则同样如实 501。
# 待真实 OAuth 流程（官方 client 注册 + device endpoint 对接）就绪后，再在
# 此实现 device code 内存态 + TTL + 轮询语义的状态机。
# ---------------------------------------------------------------------------
_OAUTH_NOT_IMPLEMENTED = (
    'OAuth 设备授权尚未接入真实供应商流程（缺少官方 client_id / device endpoint 配置），'
    '当前版本请改用 API Key 方式配置。'
)


@router.post('/providers/auth/{pid}/begin')
def auth_begin(pid: str) -> dict[str, Any]:
    meta = _get_provider_meta(pid)
    if 'oauth' not in meta.get('auth_modes', []):
        raise HTTPException(status_code=400, detail=f'{meta["name"]} 不支持 OAuth 授权')
    # 无真实 OAuth 配置，诚实返回未实现，绝不伪造 verification_uri / user_code
    raise HTTPException(status_code=501, detail=_OAUTH_NOT_IMPLEMENTED)


@router.post('/providers/auth/{pid}/poll')
def auth_poll(pid: str) -> dict[str, Any]:
    meta = _get_provider_meta(pid)
    if 'oauth' not in meta.get('auth_modes', []):
        raise HTTPException(status_code=400, detail=f'{meta["name"]} 不支持 OAuth 授权')
    # P0-2: 无真实 device authorization endpoint 时，status 只能来自真实
    # 设备码轮询结果；begin 已 501，poll 必须同样 501，不得声称 authorized。
    raise HTTPException(status_code=501, detail=_OAUTH_NOT_IMPLEMENTED)
