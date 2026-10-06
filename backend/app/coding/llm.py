# Copyright (c) 2026 QianChang-official
#
# 宛委·枢忆 is licensed under Mulan PSL v2.
# You can use this software according to the terms of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
# http://license.coscl.org.cn/MulanPSL2
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""万枢编程框架 —— 模型适配层（复用万枢模型网关）。

框架**不重复造模型接入**：provider 解析与协议分发直接复用
``platform_api.agents._resolve_gateway_target``（多级回退链的唯一定义处）
与 ``model_gateway.service._provider_chat_dispatch``（OpenAI/Anthropic/
Gemini/Bedrock 协议分发的唯一定义处），从而与万枢其余舱位共享同一份
"用户启用哪个模型"的事实源。

**离线优先**：网关未配置时 ``available()`` 返回 False，编排器自动回退到
确定性启发式规划/执行——这保证了本框架在无网络、无密钥环境下依然可用、
可测、可演示，而不是"没有模型就什么都做不了"。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MAX_TOKENS = 1024
DEFAULT_TIMEOUT_S = 20


def resolve_target(owner_id: str | None = None) -> tuple[str, str, str, str] | None:
    """解析当前可用的网关目标，返回 (api_base, api_key, model, provider_label)。"""
    try:
        from ..platform_api.agents import _resolve_gateway_target  # noqa: PLC0415 —— 延迟导入隔离故障
        return _resolve_gateway_target(None, owner_id=owner_id)
    except Exception as exc:  # noqa: BLE001 —— 网关解析失败按"不可用"处理
        logger.warning('[coding.llm] 网关目标解析失败：%r', exc)
        return None


def available(owner_id: str | None = None) -> bool:
    return resolve_target(owner_id) is not None


def complete(
    prompt: str,
    *,
    owner_id: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> dict[str, Any]:
    """同步补全。返回 ``{ok, text, provider, latency_ms}`` 或 ``{ok: False, error}``。"""
    text = (prompt or '').strip()
    if not text:
        return {'ok': False, 'error': 'empty_prompt', 'message': '提示词为空'}
    target = resolve_target(owner_id)
    if target is None:
        return {'ok': False, 'error': 'gateway_unavailable',
                'message': '模型网关未就绪：尚未配置可用服务商（可在「设置 · 模型接入」启用）'}
    api_base, api_key, model, label = target
    try:
        from ..model_gateway import service as mgw  # noqa: PLC0415
        status, latency_ms, output = mgw._provider_chat_dispatch(  # noqa: SLF001
            label, api_base, api_key, model, text, max_tokens,
        )
    except Exception as exc:  # noqa: BLE001 —— 上游故障不外泄堆栈
        # 异常文本可能含内部主机/路径/凭据片段，只进日志不进返回值。
        logger.warning('[coding.llm] 上游调用失败：%r', exc)
        return {'ok': False, 'error': 'upstream_error', 'message': '上游调用失败，详见服务端日志'}
    output = (output or '').strip()
    if status != 'ok' or not output:
        return {'ok': False, 'error': 'upstream_error',
                'message': output or f'上游返回状态 {status}', 'provider': label}
    return {'ok': True, 'text': output, 'provider': label, 'model': model, 'latency_ms': latency_ms}


async def complete_async(
    prompt: str,
    *,
    owner_id: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """异步补全：在线程池执行同步调用，带超时，绝不阻塞事件循环。"""
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(complete, prompt, owner_id=owner_id, max_tokens=max_tokens),
            timeout=timeout_s,
        )
    except Exception as exc:  # noqa: BLE001
        return {'ok': False, 'error': 'timeout', 'message': str(exc)}
