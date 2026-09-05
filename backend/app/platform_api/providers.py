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
- POST   /providers/auth/{pid}/begin   OAuth 设备授权开始（client_id 就绪即走真实
                                      RFC 8628 设备码流程；未配置/端点未核实如实 501）
- POST   /providers/auth/{pid}/poll    OAuth 设备授权轮询（authorization_pending /
                                      slow_down / expired_token / authorized 四态）

持久化：``JsonStore('providers')``，key 为 provider id；
辅助模型存于保留 key ``_aux``。
密钥加密复用 ``app.security.encryption``（Fernet，密钥派生模式与
``app.model_gateway.service`` 一致：优先 ``WANWEI_ENCRYPTION_KEY``，
否则由平台 API Key 派生）。
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional
from urllib.parse import urlparse, urlsplit, urlunsplit, urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .guards import audit_safe
from .store import JsonStore
from ..security import encryption
from ..security.auth import is_production_mode
from ..soul.ownership import actor_id_for_request, configured_actor_id
from ..security.ssrf import SSRFError, resolve_external_url, validate_external_url
from ..utils.datetime_utils import utc_now_iso

router = APIRouter(tags=['providers'])
logger = logging.getLogger(__name__)

_store = JsonStore('providers')

# 辅助模型在 JsonStore('providers') 中的保留 key（不会与 provider id 冲突）
_AUX_KEY = '_aux'
_OWNER_KEY_PREFIX = '_owner:'

# 本地类 provider：test 时真实探测 base_url（3 秒超时）
_LOCAL_KINDS = {'local'}

# 连通性测试 SSRF 豁免：仅用户显式配置的本机回环地址（Ollama / LM Studio 等
# 本地推理端点）允许探测，其余内网/元数据地址一律按 denylist 拦截。
_LOCAL_PROBE_ALLOWLIST = ['localhost', '127.0.0.1', '::1']


def _ssrf_extra_hosts() -> list[str]:
    """全局 SSRF 主机白名单（security.ssrf 单源，fake-ip 代理等场景的显式信任主机）。

    供配置写入校验与本地探测合并使用，保证「能连的主机也存得进去」。
    取不到时返回空表（不放行）。
    """
    try:
        from ..security.ssrf import extra_allowed_hosts
        return extra_allowed_hosts()
    except Exception:  # noqa: BLE001 —— 解析异常时不放行任何额外主机
        return []


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
        # 已核实：GitHub 官方设备授权流（RFC 8628）固定端点；scope 可选，
        # 由 GitHub App 本身声明，故留空不发送。
        'device_auth': {
            'authorize_url': 'https://github.com/login/device/code',
            'token_url': 'https://github.com/login/oauth/access_token',
            'scope': '',
        },
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
        # 已核实：Google OAuth 2.0 官方设备码端点；Vertex AI 推理需
        # cloud-platform scope。注意 Google 的 token 端点通常还要求
        # client_secret，可通过 extra.client_secret 或对应 env 补充。
        'device_auth': {
            'authorize_url': 'https://oauth2.googleapis.com/device/code',
            'token_url': 'https://oauth2.googleapis.com/token',
            'scope': 'https://www.googleapis.com/auth/cloud-platform',
        },
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
        # 如实边界：阿里云百炼/DashScope 官方文档未公布面向第三方的 OAuth
        # 设备授权端点（Qwen Code CLI 的 chat.qwen.ai 端点属其内部 client，
        # 非公开契约），device_auth 保持 None，begin 时如实 501「待核实」。
        'device_auth': None,
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
    raw_extra = record.get('extra') or {}
    masked_extra: dict[str, Any] = {}
    for k, v in raw_extra.items():
        if isinstance(k, str) and any(s in k.lower() for s in ('secret', 'password', 'token', 'key', 'client_secret')):
            masked_extra[k] = '***'
        else:
            masked_extra[k] = v

    return {
        'pid': pid,
        'configured': bool(record),
        'enabled': bool(record.get('enabled', False)),
        'base_url': record.get('base_url') or meta['base_url'],
        'model': record.get('model') or (meta['models'][0] if meta['models'] else ''),
        'has_api_key': bool(plain),
        'api_key_tail': tail,
        'api_key_masked': f'****{tail}' if tail else '',
        'extra': masked_extra,
        'updated_at': record.get('updated_at') or '',
    }


# ---------------------------------------------------------------------------
# owner 隔离（与 mcp_hub / automation / spaces 同口径）
# ---------------------------------------------------------------------------
def _actor_id(request: Request | None = None) -> str:
    """解析请求 actor；直接函数调用（无 request）视同配置属主。"""
    return actor_id_for_request(request)


def _legacy_owner_allowed(owner_id: str) -> bool:
    """旧记录兼容：anonymous 或当前配置属主可见。"""
    return owner_id == 'anonymous' or owner_id == configured_actor_id()


def _record_visible(record: dict[str, Any], owner_id: str) -> bool:
    owner = record.get('owner_id')
    if owner:
        return str(owner) == owner_id
    return _legacy_owner_allowed(owner_id)


def _materialize_record_owner(record: dict[str, Any], owner_id: str) -> str | None:
    """把无主旧记录绑定到唯一兼容属主；返回生效 owner_id，不兼容返回 None。"""
    if record.get('owner_id'):
        return str(record['owner_id'])
    if not _legacy_owner_allowed(owner_id):
        return None
    record['owner_id'] = owner_id
    return owner_id


def _owner_key(owner_id: str) -> str:
    return f'{_OWNER_KEY_PREFIX}{owner_id}'


def _owner_records(data: dict, owner_id: str, *, create: bool = False) -> dict[str, Any] | None:
    key = _owner_key(owner_id)
    records = data.get(key)
    if isinstance(records, dict):
        return records
    if create:
        records = {}
        data[key] = records
        return records
    return None


def _foreign_owner_has_provider(data: dict, pid: str, owner_id: str) -> bool:
    for key, records in data.items():
        if not key.startswith(_OWNER_KEY_PREFIX) or key == _owner_key(owner_id):
            continue
        if isinstance(records, dict) and isinstance(records.get(pid), dict):
            return True
    return False


def _provider_record_for_owner(
    pid: str,
    owner_id: str | None = None,
    *,
    materialize: bool = False,
) -> dict[str, Any] | None:
    """Return only this actor's record, preserving legacy top-level records."""
    actor = owner_id or configured_actor_id()

    def _read(data: dict) -> dict[str, Any] | None:
        records = _owner_records(data, actor)
        record = records.get(pid) if records else None
        if isinstance(record, dict):
            return dict(record)
        legacy = data.get(pid)
        if not isinstance(legacy, dict):
            return None
        if not _record_visible(legacy, actor):
            return None
        if materialize and not legacy.get('owner_id') and _legacy_owner_allowed(actor):
            # Keep the ownerless legacy record intact so another actor can
            # create a scoped record for the same provider.  The configured
            # actor gets an isolated materialized copy for subsequent writes.
            records = _owner_records(data, actor, create=True)
            records.setdefault(pid, {**legacy, 'owner_id': actor, '_legacy_compat': True})
            return dict(records[pid])
        return dict(legacy)

    return _store.mutate(_read) if materialize else _read(_store.all())


def _assert_provider_access(pid: str, owner_id: str) -> dict[str, Any] | None:
    """Cross-owner records return 404; absent records remain creatable."""
    def _check(data: dict) -> dict[str, Any] | None:
        records = _owner_records(data, owner_id)
        scoped = records.get(pid) if records else None
        if isinstance(scoped, dict):
            return dict(scoped)
        legacy = data.get(pid)
        # An ownerless legacy row is available only to the configured
        # migration actor.  It must remain creatable beside a scoped row for a
        # different actor, so check this fallback before foreign buckets.
        if isinstance(legacy, dict) and not legacy.get('owner_id'):
            if _legacy_owner_allowed(owner_id):
                return dict(legacy)
            if _foreign_owner_has_provider(data, pid, owner_id):
                raise HTTPException(status_code=404, detail=f'provider 配置 {pid} 不存在')
            return None
        if _foreign_owner_has_provider(data, pid, owner_id):
            raise HTTPException(status_code=404, detail=f'provider 配置 {pid} 不存在')
        if isinstance(legacy, dict):
            if not _record_visible(legacy, owner_id):
                raise HTTPException(status_code=404, detail=f'provider 配置 {pid} 不存在')
            return dict(legacy)
        return None

    return _store.mutate(_check)


def _owned_provider_snapshot(owner_id: str) -> dict[str, Any]:
    """Snapshot scoped records and lazily copy compatible legacy records."""
    def _apply(data: dict) -> dict[str, Any]:
        records = _owner_records(data, owner_id, create=True)
        visible: dict[str, Any] = {}
        for pid, value in list(records.items()):
            if isinstance(value, dict) and not value.get('_legacy_compat'):
                visible[pid] = dict(value)
        for pid, value in list(data.items()):
            if (
                pid.startswith(_OWNER_KEY_PREFIX)
                or pid == _OAUTH_PENDING_KEY
                or pid.startswith(_OAUTH_PENDING_KEY + ':')
                or pid == _AUX_KEY
            ):
                continue
            if not isinstance(value, dict) or not _record_visible(value, owner_id):
                continue
            if pid not in records or (
                isinstance(records.get(pid), dict)
                and records[pid].get('_legacy_compat')
            ):
                visible[pid] = dict(value)
        return visible

    return _store.mutate(_apply)


def _remove_config(pid: str, owner_id: str | None = None) -> bool:
    """Delete only this actor's scoped record or its compatible legacy row."""
    def _remove(data: dict) -> bool:
        if owner_id is not None:
            records = _owner_records(data, owner_id)
            if records and pid in records:
                removed = records.pop(pid)
                if isinstance(removed, dict) and removed.get('_legacy_compat'):
                    data.pop(pid, None)
                return True
            legacy = data.get(pid)
            if isinstance(legacy, dict) and _record_visible(legacy, owner_id):
                data.pop(pid, None)
                return True
            return False
        return data.pop(pid, None) is not None

    return _store.mutate(_remove)



# ---------------------------------------------------------------------------
# 对话通路的活动 provider 选择
# ---------------------------------------------------------------------------
# /soul/chat 等真实生成通路暂不参与自动选择的 provider：
# - github_copilot / google_vertex / qwen_oauth：OAuth-only，设备授权状态机虽已实现
#   （client_id 就绪即走真实 device-code 流程），但 OAuth 令牌的对话通路尚未打通，
#   维持不参与自动选择；用户仍可把令牌手动配为 api_key 形态使用其他 provider。
# local 类（lm_studio / ollama_cloud）不参与对话自动选择：本机推理端点请走
# WANWEI_OPENAI_COMPATIBLE_* 既有通路（含显式主机白名单），避免无鉴权回环
# 端点在未配置白名单时被选中后必然 SSRF 拦截的假可用状态。
# 注：aws_bedrock 已移出本集合——SigV4 真实调用已接通（model_gateway
# ._bedrock_smoke），凭据格式 'ACCESS_KEY_ID|SECRET_ACCESS_KEY' 配置启用后
# 即可参与对话选择。
_CHAT_UNSUPPORTED_PIDS = frozenset({
    'github_copilot', 'google_vertex', 'qwen_oauth',
})


def get_active_provider(owner_id: str | None = None) -> Optional[dict[str, str]]:
    """按指定 actor 返回第一个「已启用且可真实调用」的云端 provider 配置。

    「可用」的完整条件：enabled=True + 密钥已存且可解密 + base_url/model 齐备；
    azure_foundry 等占位端点在用户改写 base_url 前视为不可用。OAuth-only 与
    协议未实现者不参与选择（见 _CHAT_UNSUPPORTED_PIDS）。多个 provider 同时
    启用时按目录顺序取第一个——「启用」即用户显式指定其为当前对话引擎。

    返回 {pid, kind, base_url, model, api_key}；没有可用配置时返回 None。
    """
    actor = owner_id or configured_actor_id()
    stored = _owned_provider_snapshot(actor)
    for meta in CATALOG:
        pid = meta['id']
        if pid in _CHAT_UNSUPPORTED_PIDS or meta['kind'] in _LOCAL_KINDS:
            continue
        record = stored.get(pid)
        if not isinstance(record, dict) or not record.get('enabled'):
            continue
        base_url = str(record.get('base_url') or meta['base_url'] or '').strip()
        model = str(
            record.get('model') or (meta['models'][0] if meta['models'] else '')
        ).strip()
        # 占位端点（azure_foundry 的 YOUR_RESOURCE）未经改写前不可真实调用
        if meta.get('placeholder') and base_url == meta['base_url']:
            continue
        api_key = _decrypt_key(record)
        if not (api_key and base_url and model):
            continue
        return {
            'pid': pid,
            'kind': str(meta['kind']),
            'base_url': base_url,
            'model': model,
            'api_key': api_key,
        }
    return None


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
def list_configs(request: Request = None) -> list[dict[str, Any]]:
    """全部 31 家配置视图（未配置的按目录默认值占位），api_key 只回尾 4 位。"""
    stored = _owned_provider_snapshot(_actor_id(request))
    return [_masked_config(p['id'], stored.get(p['id'])) for p in CATALOG]


@router.put('/providers/configs/{pid}')
def put_config(pid: str, body: ConfigIn, request: Request = None) -> dict[str, Any]:
    owner_id = _actor_id(request)
    _assert_provider_access(pid, owner_id)
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
                    exc_info=not is_production_mode(),
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
                    # 本地类豁免回环探测；云端/自定义合并全局显式信任主机白名单
                    # （WANWEI_SSRF_EXTRA_ALLOWED_HOSTS，与连接路径同源），
                    # 保证「能连的主机也存得进去」。
                    allowlist=(
                        _LOCAL_PROBE_ALLOWLIST + _ssrf_extra_hosts()
                        if meta['kind'] in _LOCAL_KINDS
                        else (_ssrf_extra_hosts() or [])
                    ),
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
        records = _owner_records(data, owner_id, create=True)
        stored = records.get(pid)
        if not isinstance(stored, dict):
            legacy = data.get(pid)
            if isinstance(legacy, dict) and _record_visible(legacy, owner_id):
                stored = legacy
        record = dict(stored) if isinstance(stored, dict) else {}
        if isinstance(stored, dict) and not _record_visible(record, owner_id):
            raise HTTPException(status_code=404, detail=f'provider 配置 {pid} 不存在')
        if clear_api_key:
            record.pop('api_key_encrypted', None)
        record.update(patch)
        record.pop('_legacy_compat', None)
        record['owner_id'] = owner_id
        record.setdefault('base_url', meta['base_url'])
        record.setdefault('model', meta['models'][0] if meta['models'] else '')
        record.setdefault('enabled', False)
        record['updated_at'] = utc_now_iso()
        records[pid] = record
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
def delete_config(pid: str, request: Request = None) -> dict[str, Any]:
    owner_id = _actor_id(request)
    _get_provider_meta(pid)
    _assert_provider_access(pid, owner_id)
    removed = _remove_config(pid, owner_id)
    audit_safe('provider_config_deleted', {'pid': pid, 'removed': removed})
    return {'ok': True, 'pid': pid, 'removed': removed}


# ---------------------------------------------------------------------------
# 连通性测试
# ---------------------------------------------------------------------------
@router.post('/providers/test')
def test_provider(body: TestIn, request: Request = None) -> dict[str, Any]:
    owner_id = _actor_id(request)
    meta = _get_provider_meta(body.pid)
    record = _assert_provider_access(body.pid, owner_id) or {}

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
                allowlist=_LOCAL_PROBE_ALLOWLIST + _ssrf_extra_hosts(),
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
                exc_info=not is_production_mode(),
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
    from ..model_gateway.service import probe_openai_compatible

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
            exc_info=not is_production_mode(),
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
def get_aux(request: Request = None) -> dict[str, Any]:
    stored = _provider_record_for_owner(_AUX_KEY, _actor_id(request), materialize=True)
    if not isinstance(stored, dict):
        return dict(_AUX_DEFAULT)
    public = {**_AUX_DEFAULT, **stored}
    public.pop('owner_id', None)
    return public


@router.put('/providers/aux')
def put_aux(body: AuxIn, request: Request = None) -> dict[str, Any]:
    owner_id = _actor_id(request)
    _assert_provider_access(_AUX_KEY, owner_id)
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
        records = _owner_records(data, owner_id, create=True)
        stored = records.get(_AUX_KEY)
        if not isinstance(stored, dict):
            legacy = data.get(_AUX_KEY)
            if isinstance(legacy, dict) and _record_visible(legacy, owner_id):
                stored = legacy
        current = {**_AUX_DEFAULT, **(stored if isinstance(stored, dict) else {})}
        if isinstance(stored, dict) and not _record_visible(stored, owner_id):
            raise HTTPException(status_code=404, detail='provider 配置 _aux 不存在')
        current.update(patch)
        current['owner_id'] = owner_id
        records[_AUX_KEY] = current
        return current

    current = _store.mutate(_apply)
    public = dict(current)
    public.pop('owner_id', None)
    return public


# ---------------------------------------------------------------------------
# OAuth 设备授权状态机（RFC 8628 Device Authorization Grant）
#
# 机器化口径：凭据（client_id）就绪即走真实流程，未就绪保持诚实 501。
# - begin：client_id 来自 provider extra.client_id 或 env
#   WANWEI_OAUTH_CLIENT_ID_{PID大写}；缺失时如实 501「缺少 client_id 配置」，
#   绝不伪造 verification_uri / user_code；就绪时真实 POST authorize_url
#   （pinned-IP + SSRF 校验），pending 态（device_code/user_code/interval/
#   expires_at）存 JsonStore('providers') 保留 key '_oauth_pending'，带过期清理。
# - poll ：真实 POST token_url，按 RFC 8628 处理 authorization_pending /
#   slow_down（后续间隔 +5s）/ expired_token / 成功四态；成功时 access_token
#   经 Fernet 加密写入 api_key_encrypted、标记 authorized、清理 pending；
#   任何路径不回显明文令牌。
# 单节点 alpha 下 pending 以 JsonStore 为单一事实源（重启可恢复），每次
# begin/poll 顺手清除已过期条目。
# ---------------------------------------------------------------------------
_OAUTH_PENDING_KEY = '_oauth_pending'
_OAUTH_HTTP_TIMEOUT_S = 10
_OAUTH_DEFAULT_INTERVAL_S = 5
_OAUTH_MAX_INTERVAL_S = 120
_OAUTH_SLOW_DOWN_EXTRA_S = 5  # RFC 8628 §3.5：slow_down 后轮询间隔增加 5 秒
_OAUTH_DEVICE_GRANT = 'urn:ietf:params:oauth:grant-type:device_code'


def _oauth_missing_client_detail(meta: dict[str, Any]) -> str:
    """缺 client_id 的诚实 501 文案：说明配置方式，不给任何假链接。"""
    return (
        f"缺少 client_id 配置：{meta['name']} 的设备授权需要官方 OAuth 应用 client_id"
        f'（写入该 provider 配置的 extra.client_id，或设置环境变量 '
        f"WANWEI_OAUTH_CLIENT_ID_{meta['id'].upper()}）；"
        '未配置前未接入真实供应商流程，当前版本请改用 API Key 方式配置。'
    )


def _oauth_endpoint_unverified_detail(meta: dict[str, Any]) -> str:
    """官方设备授权端点未核实的诚实 501 文案（如 qwen_oauth）。"""
    return (
        f"官方设备授权端点待核实：{meta['name']} 尚未公布可用的 OAuth 设备授权端点，"
        '无法发起真实设备码流程；请改用 API Key 方式配置。'
    )


def _oauth_client_id(pid: str, record: dict[str, Any]) -> str:
    """解析 client_id：provider extra.client_id 优先，其次环境变量。"""
    extra = record.get('extra') or {}
    from_extra = str(extra.get('client_id') or '').strip()
    if from_extra:
        return from_extra
    return os.environ.get(f'WANWEI_OAUTH_CLIENT_ID_{pid.upper()}', '').strip()


def _oauth_client_secret(pid: str, record: dict[str, Any]) -> str:
    """可选 client_secret（Google 等供应商 token 端点要求）：extra 或 env。"""
    extra = record.get('extra') or {}
    from_extra = str(extra.get('client_secret') or '').strip()
    if from_extra:
        return from_extra
    return os.environ.get(f'WANWEI_OAUTH_CLIENT_SECRET_{pid.upper()}', '').strip()


def _pending_key(owner_id: str | None = None) -> str:
    return f'{_OAUTH_PENDING_KEY}:{owner_id or configured_actor_id()}'


def _load_pending_map(owner_id: str | None = None) -> dict[str, Any]:
    actor = owner_id or configured_actor_id()
    stored = _store.get(_pending_key(actor))
    if isinstance(stored, dict):
        return dict(stored)
    # Read the pre-ownership map only for the configured migration actor.
    if _legacy_owner_allowed(actor):
        stored = _store.get(_OAUTH_PENDING_KEY)
        return dict(stored) if isinstance(stored, dict) else {}
    return {}


def _purge_expired_pending(pending: dict[str, Any]) -> None:
    """原地清除已过期的 pending 条目（单节点 alpha 的过期清理）。"""
    now = time.time()
    for key in list(pending.keys()):
        state = pending.get(key)
        if not isinstance(state, dict):
            pending.pop(key, None)
            continue
        try:
            expires_at = float(state.get('expires_at') or 0)
        except (TypeError, ValueError):
            expires_at = 0.0
        if expires_at < now:
            pending.pop(key, None)


def _save_pending_state(
    pid: str, state: Optional[dict[str, Any]], owner_id: str | None = None,
) -> None:
    actor = owner_id or configured_actor_id()
    key = _pending_key(actor)
    def _apply(data: dict) -> None:
        pending = data.get(key)
        pending = dict(pending) if isinstance(pending, dict) else {}
        _purge_expired_pending(pending)
        if state is None:
            pending.pop(pid, None)
        else:
            pending[pid] = state
        data[key] = pending
        # Preserve the old key only for the configured migration actor.  Reads
        # for other actors never consult it, so it cannot cross owner scopes.
        if _legacy_owner_allowed(actor):
            legacy = data.get(_OAUTH_PENDING_KEY)
            legacy = dict(legacy) if isinstance(legacy, dict) else {}
            _purge_expired_pending(legacy)
            if state is None:
                legacy.pop(pid, None)
            else:
                legacy[pid] = state
            data[_OAUTH_PENDING_KEY] = legacy

    _store.mutate(_apply)


def _bump_slow_down(
    pid: str, state: dict[str, Any], owner_id: str | None = None,
) -> int:
    """slow_down 后把额外等待秒数累加进存储态，返回新的有效间隔。"""
    try:
        base_interval = max(1, min(int(state.get('interval') or _OAUTH_DEFAULT_INTERVAL_S), _OAUTH_MAX_INTERVAL_S))
    except (TypeError, ValueError):
        base_interval = _OAUTH_DEFAULT_INTERVAL_S
    try:
        extra = int(state.get('slow_down_extra') or 0)
    except (TypeError, ValueError):
        extra = 0
    new_extra = extra + _OAUTH_SLOW_DOWN_EXTRA_S

    actor = owner_id or configured_actor_id()
    key = _pending_key(actor)
    def _apply(data: dict) -> int:
        pending = data.get(key)
        pending = dict(pending) if isinstance(pending, dict) else {}
        current = pending.get(pid)
        if isinstance(current, dict):
            current = dict(current)
            current['slow_down_extra'] = new_extra
            pending[pid] = current
            data[key] = pending
            if _legacy_owner_allowed(actor):
                legacy = data.get(_OAUTH_PENDING_KEY)
                legacy = dict(legacy) if isinstance(legacy, dict) else {}
                legacy[pid] = current
                data[_OAUTH_PENDING_KEY] = legacy
        return base_interval + new_extra

    return _store.mutate(_apply)


def _effective_interval(state: dict[str, Any]) -> int:
    try:
        base_interval = max(1, min(int(state.get('interval') or _OAUTH_DEFAULT_INTERVAL_S), _OAUTH_MAX_INTERVAL_S))
    except (TypeError, ValueError):
        base_interval = _OAUTH_DEFAULT_INTERVAL_S
    try:
        extra = int(state.get('slow_down_extra') or 0)
    except (TypeError, ValueError):
        extra = 0
    return base_interval + extra


def _pinned_oauth_post(url: str, pinned_ip: str, form: dict[str, str]) -> tuple[int, dict[str, Any]]:
    """连接到已校验 IP 并 POST 表单，保持原始 HTTP/TLS host（同 _probe_pinned_url 口径）。

    trust_env=False 防止代理替换目的地；sni_hostname 保证证书仍按原主机名校验。
    返回 (HTTP 状态码, JSON dict)；非 JSON 响应回空 dict 由调用方如实报错。
    """
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
    with httpx.Client(
        timeout=_OAUTH_HTTP_TIMEOUT_S,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        response = client.post(
            pinned_url,
            content=urlencode(form),
            headers={
                'Host': original_host,
                'Content-Type': 'application/x-www-form-urlencoded',
                'Accept': 'application/json',
            },
            extensions=extensions,
        )
    try:
        data = response.json()
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return response.status_code, data


def _oauth_form_post(url: str, form: dict[str, str], *, purpose: str) -> tuple[int, dict[str, Any]]:
    """SSRF 校验后走 pinned-IP 通道真实 POST；网络层故障统一转 502。"""
    try:
        from ..security.ssrf import extra_allowed_hosts
        normalized_url, pinned_ip = resolve_external_url(
            url, allowlist=extra_allowed_hosts() or None,
        )
    except SSRFError as exc:
        logger.warning(
            'OAuth %s endpoint rejected by SSRF policy: error_type=%s',
            purpose,
            type(exc).__name__,
        )
        raise HTTPException(status_code=422, detail=f'{purpose} 端点未通过 SSRF 防护校验') from None
    try:
        return _pinned_oauth_post(normalized_url, pinned_ip, form)
    except Exception as exc:  # noqa: BLE001 —— 网络/超时异常统一归为服务不可达
        logger.warning(
            'OAuth %s request failed: error_type=%s',
            purpose,
            type(exc).__name__,
            exc_info=not is_production_mode(),
        )
        raise HTTPException(status_code=502, detail=f'{purpose} 服务不可达') from None


@router.post('/providers/auth/{pid}/begin')
def auth_begin(pid: str, request: Request = None) -> dict[str, Any]:
    meta = _get_provider_meta(pid)
    owner_id = _actor_id(request)
    record = _assert_provider_access(pid, owner_id) or {}
    if 'oauth' not in meta.get('auth_modes', []):
        raise HTTPException(status_code=400, detail=f'{meta["name"]} 不支持 OAuth 授权')
    device = meta.get('device_auth')
    if (
        not isinstance(device, dict)
        or not device.get('authorize_url')
        or not device.get('token_url')
    ):
        # 官方设备授权端点未核实（如 qwen_oauth）：绝不猜测/伪造 URL。
        raise HTTPException(status_code=501, detail=_oauth_endpoint_unverified_detail(meta))

    client_id = _oauth_client_id(pid, record)
    if not client_id:
        # 凭据未就绪：维持诚实 501，一个字的假链接都不能有。
        raise HTTPException(status_code=501, detail=_oauth_missing_client_detail(meta))

    form = {'client_id': client_id}
    scope = str(device.get('scope') or '')
    if scope:
        form['scope'] = scope
    status_code, data = _oauth_form_post(str(device['authorize_url']), form, purpose='设备授权')
    error = str(data.get('error') or '')
    if status_code >= 400 or error:
        detail_msg = error or f'HTTP {status_code}'
        raise HTTPException(
            status_code=502,
            detail=f'设备授权请求被供应商拒绝：{detail_msg}',
        )
    device_code = str(data.get('device_code') or '')
    user_code = str(data.get('user_code') or '')
    verification_uri = str(data.get('verification_uri') or '')
    verification_uri_complete = str(data.get('verification_uri_complete') or '')
    if not (device_code and user_code and verification_uri):
        raise HTTPException(
            status_code=502,
            detail='设备授权响应缺少必要字段（device_code/user_code/verification_uri），流程终止',
        )
    try:
        interval = int(data.get('interval') or _OAUTH_DEFAULT_INTERVAL_S)
    except (TypeError, ValueError):
        interval = _OAUTH_DEFAULT_INTERVAL_S
    interval = max(1, min(interval, _OAUTH_MAX_INTERVAL_S))
    try:
        expires_in = int(data.get('expires_in') or 600)
    except (TypeError, ValueError):
        expires_in = 600
    expires_in = max(30, expires_in)
    now = time.time()
    _save_pending_state(pid, {
        'device_code': device_code,
        'user_code': user_code,
        'verification_uri': verification_uri,
        'verification_uri_complete': verification_uri_complete,
        'interval': interval,
        'slow_down_extra': 0,
        'expires_at': now + expires_in,
        'client_id': client_id,
    }, owner_id=owner_id)
    audit_safe('provider_oauth_device_begin', {
        'pid': pid,
        'verification_uri': verification_uri,
        'interval': interval,
        'expires_in': expires_in,
        # device_code/user_code 属短期一次性凭据，不入审计。
    })
    return {
        'pid': pid,
        'status': 'pending',
        'verification_uri': verification_uri,
        'verification_uri_complete': verification_uri_complete,
        'user_code': user_code,
        'interval': interval,
        'expires_in': expires_in,
    }


@router.post('/providers/auth/{pid}/poll')
def auth_poll(pid: str, request: Request = None) -> dict[str, Any]:
    meta = _get_provider_meta(pid)
    owner_id = _actor_id(request)
    record = _assert_provider_access(pid, owner_id) or {}
    if 'oauth' not in meta.get('auth_modes', []):
        raise HTTPException(status_code=400, detail=f'{meta["name"]} 不支持 OAuth 授权')
    device = meta.get('device_auth')
    if (
        not isinstance(device, dict)
        or not device.get('authorize_url')
        or not device.get('token_url')
    ):
        raise HTTPException(status_code=501, detail=_oauth_endpoint_unverified_detail(meta))

    client_id = _oauth_client_id(pid, record)
    if not client_id:
        raise HTTPException(status_code=501, detail=_oauth_missing_client_detail(meta))

    pending = _load_pending_map(owner_id)
    state = pending.get(pid)
    if not isinstance(state, dict):
        # P0-2 延续：status 只能来自真实设备码轮询结果；没有进行中的 begin
        # 就不得声称 authorized/pending。
        raise HTTPException(
            status_code=409,
            detail='没有进行中的设备授权流程：请先调用 begin 获取 user_code',
        )
    try:
        expires_at = float(state.get('expires_at') or 0)
    except (TypeError, ValueError):
        expires_at = 0.0
    if time.time() >= expires_at:
        _save_pending_state(pid, None, owner_id=owner_id)
        audit_safe('provider_oauth_device_expired', {'pid': pid})
        return {'pid': pid, 'status': 'expired'}

    device_code = str(state.get('device_code') or '')
    if not device_code:
        _save_pending_state(pid, None, owner_id=owner_id)
        raise HTTPException(status_code=409, detail='设备授权状态损坏，请重新发起 begin')
    form = {
        'client_id': client_id,
        'device_code': device_code,
        'grant_type': _OAUTH_DEVICE_GRANT,
    }
    client_secret = _oauth_client_secret(pid, record)
    if client_secret:
        form['client_secret'] = client_secret
    status_code, data = _oauth_form_post(str(device['token_url']), form, purpose='设备令牌')
    error = str(data.get('error') or '')

    if error == 'authorization_pending':
        return {
            'pid': pid,
            'status': 'authorization_pending',
            'interval': _effective_interval(state),
        }
    if error == 'slow_down':
        new_interval = _bump_slow_down(pid, state, owner_id=owner_id)
        return {'pid': pid, 'status': 'slow_down', 'interval': new_interval}
    if error == 'expired_token':
        _save_pending_state(pid, None, owner_id=owner_id)
        audit_safe('provider_oauth_device_expired', {'pid': pid})
        return {'pid': pid, 'status': 'expired'}
    if error == 'access_denied':
        _save_pending_state(pid, None, owner_id=owner_id)
        audit_safe('provider_oauth_device_denied', {'pid': pid})
        return {'pid': pid, 'status': 'denied'}
    if error:
        raise HTTPException(
            status_code=502,
            detail=f'设备令牌端点返回错误：{error}（如持续出现请重新发起授权）',
        )

    access_token = str(data.get('access_token') or '')
    if status_code >= 400 or not access_token:
        raise HTTPException(
            status_code=502,
            detail='设备令牌响应缺少 access_token，授权未完成',
        )
    try:
        encrypted_token = encryption.encrypt(access_token)
    except Exception as exc:  # noqa: BLE001 —— 加密失败不落盘明文
        logger.warning(
            'OAuth token encryption failed: pid=%s error_type=%s',
            pid,
            type(exc).__name__,
            exc_info=not is_production_mode(),
        )
        raise HTTPException(
            status_code=500,
            detail='令牌加密失败，请检查服务端加密配置；本次令牌未被保存',
        ) from None

    def _apply(data: dict) -> None:
        records = _owner_records(data, owner_id, create=True)
        stored = records.get(pid)
        if not isinstance(stored, dict):
            legacy = data.get(pid)
            if isinstance(legacy, dict) and _record_visible(legacy, owner_id):
                stored = legacy
        new_record = dict(stored) if isinstance(stored, dict) else {}
        if isinstance(stored, dict) and not _record_visible(stored, owner_id):
            raise HTTPException(status_code=404, detail=f'provider 配置 {pid} 不存在')
        new_record['owner_id'] = owner_id
        new_record['api_key_encrypted'] = encrypted_token
        extra = dict(new_record.get('extra') or {})
        extra['authorized_via'] = 'oauth_device'
        extra['authorized_at'] = utc_now_iso()
        new_record['extra'] = extra
        new_record.setdefault('base_url', meta['base_url'])
        new_record.setdefault('model', meta['models'][0] if meta['models'] else '')
        new_record.setdefault('enabled', False)
        new_record['updated_at'] = utc_now_iso()
        records[pid] = new_record
        legacy = data.get(pid)
        if (
            _legacy_owner_allowed(owner_id)
            and isinstance(legacy, dict)
            and not legacy.get('owner_id')
        ):
            # OAuth completion for a pre-ownership row claims that legacy row
            # for the configured actor, preserving the old storage contract.
            data[pid] = new_record
        pending_data = data.get(_pending_key(owner_id))
        pending_data = dict(pending_data) if isinstance(pending_data, dict) else {}
        _purge_expired_pending(pending_data)
        pending_data.pop(pid, None)
        data[_pending_key(owner_id)] = pending_data
        if _legacy_owner_allowed(owner_id):
            data[_OAUTH_PENDING_KEY] = pending_data

    _store.mutate(_apply)
    # 审计只记事件与 pid，绝不记录令牌或其片段。
    audit_safe('provider_oauth_device_authorized', {'pid': pid})
    return {'pid': pid, 'status': 'authorized', 'configured': True}
