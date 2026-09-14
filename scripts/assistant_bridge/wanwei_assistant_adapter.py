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
#!/usr/bin/env python3
"""宛委 <-> 麒麟个人助手 adapter.

调用: WanweiAssistant().chat("你好") -> "..."（sidecar: POST http://127.0.0.1:8021/chat）

跨会话记忆（v2）：`chat_with_memory()` 在对话前检索宛委记忆注入上下文，
对话后把用户消息中的显式记忆/偏好写回宛委（经服务端 policy_gate 过滤）。

失败语义（评审修复点）：
- 记忆链路失败**不阻塞对话**（fail-open），但只吞「预期的传输类失败」；
  被拒绝的写入与真实错误都会出现在返回值里（`memories_rejected` /
  `memory_errors`），不再静默丢信息。
- sidecar 的 `reply` 是**原始流式分片拼接**（见 README「API」）；本模块的
  `chat()`/`chat_with_memory()` 返回解析后的纯文本。
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:  # 包导入与脚本直跑都要能解析同目录模块
    sys.path.insert(0, str(_HERE))

try:  # 包导入路径（from scripts.assistant_bridge.wanwei_assistant_adapter import ...）
    from . import memory_link
    from .memory_link import build_context, remember_statements
except ImportError:  # 脚本直跑（python wanwei_assistant_adapter.py）
    import memory_link  # type: ignore[no-redef]
    from memory_link import build_context, remember_statements  # type: ignore[no-redef]

SIDECAR = os.getenv("WANWEI_SIDECAR_URL", "http://127.0.0.1:8021").rstrip("/")
# 可选共享令牌：sidecar 侧配置 WANWEI_SIDECAR_TOKEN 后，请求必须带同一令牌。
_SIDECAR_TOKEN = os.getenv("WANWEI_SIDECAR_TOKEN", "").strip()


def _sidecar_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if _SIDECAR_TOKEN:
        headers["X-Bridge-Token"] = _SIDECAR_TOKEN
    return headers


# 受限 opener：仅注册 HTTP/HTTPS 处理器，从源头排除 file:/ftp: 等自定义 scheme
_OPENER = urllib.request.OpenerDirector()
for _handler_cls in (
    urllib.request.HTTPHandler,
    urllib.request.HTTPSHandler,
    urllib.request.HTTPErrorProcessor,
    urllib.request.UnknownHandler,
):
    _OPENER.add_handler(_handler_cls())


def _open(url, timeout: int, **kwargs):
    """用受限 opener 发起请求，仅支持 http/https。"""
    target = url.full_url if isinstance(url, urllib.request.Request) else url
    if not target.startswith(("http://", "https://")):
        raise ValueError(f"unexpected url scheme: {target}")
    return _OPENER.open(url, timeout=timeout, **kwargs)


# 记忆链路的预期失败：传输/协议/后端明确的错误响应。编程错误（TypeError、
# AttributeError 等）不在其中——它们要抛出来，不能被 fail-open 掩盖。
_MEMORY_FAILURES = (
    urllib.error.HTTPError,
    urllib.error.URLError,
    OSError,
    ValueError,
    json.JSONDecodeError,
    RuntimeError,
)


def chat(text: str, timeout: int = 120, *, memory_context: str | None = None) -> str:
    """发一条消息给麒麟个人助手，返回解析后的纯文本回复。

    `memory_context` 为可选的记忆块（由 memory_link.build_context 生成并已净化限长）；
    sidecar 只负责加「数据非指令」标注后拼接，自身不访问网络。
    """
    req = urllib.request.Request(
        f"{SIDECAR}/chat",
        data=json.dumps(_chat_payload(text, memory_context)).encode(),
        headers=_sidecar_headers(),
        method="POST",
    )
    with _open(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    if "error" in data:
        raise RuntimeError(data["error"])
    raw = data.get("reply", "")
    if data.get("partial"):
        # 硬超时截断：调用方需要知道回复不完整
        raise RuntimeError(f"assistant reply truncated (partial stream, chunks={data.get('chunks')})")
    return _extract_text(raw)


def chat_raw(text: str, timeout: int = 120, *, memory_context: str | None = None) -> dict:
    """返回 sidecar 的原始响应（流式分片、chunks、elapsed、partial、memory_injected）。"""
    req = urllib.request.Request(
        f"{SIDECAR}/chat",
        data=json.dumps(_chat_payload(text, memory_context)).encode(),
        headers=_sidecar_headers(),
        method="POST",
    )
    with _open(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _chat_payload(text: str, memory_context: str | None) -> dict:
    payload: dict[str, object] = {"text": text}
    if memory_context:
        payload["memory_context"] = memory_context
    return payload


def chat_with_memory(text: str, timeout: int = 120, *, owner_id: str | None = None) -> dict:
    """带宛委记忆的一轮对话。

    1. 记忆写回：提取用户消息中的显式记忆/偏好，经宛委 policy_gate 写入；
    2. 记忆检索：以用户消息查询宛委，命中时把已知记忆注入发给助手的消息；
    3. 调用个人助手并返回
       {reply, memories_used, memories_written, memories_rejected, memory_errors}。

    记忆链路失败不影响对话本身（fail-open），但失败会记录在 `memory_errors`，
    被治理层拒绝的写入单列在 `memories_rejected`。
    """
    memories_used: list[str] = []
    memories_written: list[str] = []
    memories_rejected: list[str] = []
    memory_errors: list[str] = []
    outbound = text

    # 1) 写回（在检索前写，下一轮即可召回）
    try:
        for result in remember_statements(text, owner_id=owner_id):
            statement = result.get("_statement", "")
            if memory_link.capsule_write_rejected(result):
                memories_rejected.append(statement)
            elif result.get("capsule_id"):
                memories_written.append(statement)
    except _MEMORY_FAILURES as exc:
        memory_errors.append(f"write:{type(exc).__name__}:{exc}")

    # 2) 检索注入：记忆块作为独立字段交给 sidecar 标注拼接（不混入用户正文，
    #    避免用户文本与记忆内容在提示词里互相污染/互相伪装）
    try:
        context_block, memories_used = build_context(text, owner_id=owner_id)
        if not context_block:
            memories_used = []
    except _MEMORY_FAILURES as exc:
        memory_errors.append(f"read:{type(exc).__name__}:{exc}")
        context_block = ""

    reply = chat(outbound, timeout=timeout, memory_context=context_block or None)
    return {
        "reply": reply,
        "memories_used": memories_used,
        "memories_written": memories_written,
        "memories_rejected": memories_rejected,
        "memory_errors": memory_errors,
    }


def _extract_text(raw: str) -> str:
    """sidecar 把流式分片的原始 JSON 串拼接返回，这里解析出所有 result 字段的纯文本。"""
    out = []
    dec = json.JSONDecoder()
    idx = 0
    raw = raw.strip()
    while idx < len(raw):
        nxt = raw.find("{", idx)
        if nxt < 0:
            break
        try:
            obj, end = dec.raw_decode(raw[nxt:])
            idx = nxt + end
        except json.JSONDecodeError:
            idx = nxt + 1
            continue
        # 分片格式: content[0].text.result
        try:
            for block in obj.get("content", []):
                t = block.get("text", {})
                if isinstance(t, dict) and t.get("result") is not None:
                    out.append(str(t["result"]))
        except (AttributeError, TypeError):
            pass
    return "".join(out)


def health(timeout: int = 3) -> bool:
    """sidecar 就绪探针：要求 ok 且 ready（assistant 已初始化并支持文本对话）。"""
    try:
        with _open(f"{SIDECAR}/health", timeout=timeout) as resp:
            data = json.loads(resp.read())
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return False
    return bool(data.get("ok")) and bool(data.get("ready", data.get("ok")))


def health_detail(timeout: int = 3) -> dict:
    """完整健康信息（含 busy 与失败原因），排障用。"""
    try:
        with _open(f"{SIDECAR}/health", timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read())
        except (ValueError, json.JSONDecodeError):
            return {"ok": False, "ready": False, "reason": f"http_{exc.code}"}
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        return {"ok": False, "ready": False, "reason": type(exc).__name__}


if __name__ == "__main__":
    message = sys.argv[1] if len(sys.argv) > 1 else "你好,请用一句话介绍你自己"
    outcome = chat_with_memory(message)
    print(outcome["reply"])
    if outcome["memories_used"]:
        print(f"[注入记忆 {len(outcome['memories_used'])} 条]", file=sys.stderr)
    if outcome["memories_written"]:
        print(f"[写回记忆 {len(outcome['memories_written'])} 条]", file=sys.stderr)
    if outcome["memories_rejected"]:
        print(f"[治理层拒绝 {len(outcome['memories_rejected'])} 条]", file=sys.stderr)
    for error in outcome["memory_errors"]:
        print(f"[记忆链路错误] {error}", file=sys.stderr)
