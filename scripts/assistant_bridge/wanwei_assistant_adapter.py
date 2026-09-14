# Copyright (c) 2026 QianChang-official
#
# 宛委·枢忆 is licensed under Mulan PSL v2.
# You can use this software according to the terms of the Mulan PSL v2.
# You may obtain a copy of the Mulan PSL v2 at:
# http://license.coscl.org.cn/MulanPSL2
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.
#!/usr/bin/env python3
"""宛委 <-> 麒麟个人助手 adapter.
调用: WanweiAssistant().chat("你好") -> "..."
sidecar: POST http://127.0.0.1:8021/chat

跨会话记忆（v2）：chat_with_memory() 在对话前检索宛委记忆注入上下文，
对话后把用户消息中的显式记忆/偏好写回宛委（经服务端 policy_gate 过滤）。
记忆后端不可用时自动退化为纯透传（fail-open）。
"""

import json
import urllib.error
import urllib.request

SIDECAR = "http://127.0.0.1:8021"

# 受限 opener:仅注册 HTTP/HTTPS 处理器,从源头排除 file:/ftp: 等自定义 scheme (B310)
_OPENER = urllib.request.OpenerDirector()
for handler_cls in (
    urllib.request.ProxyHandler,
    urllib.request.HTTPHandler,
    urllib.request.HTTPSHandler,
    urllib.request.HTTPErrorProcessor,
    urllib.request.UnknownHandler,
):
    _OPENER.add_handler(handler_cls())


def _open(url, timeout: int, **kwargs):
    """用受限 opener 发起请求,仅支持 http/https."""
    target = url.full_url if isinstance(url, urllib.request.Request) else url
    if not target.startswith(("http://", "https://")):
        raise ValueError(f"unexpected url scheme: {target}")
    try:
        return _OPENER.open(url, timeout=timeout, **kwargs)
    except urllib.error.HTTPError:
        raise


def chat(text: str, timeout: int = 120) -> str:
    """发一条消息给麒麟个人助手,返回拼接后的纯文本回复."""
    req = urllib.request.Request(
        f"{SIDECAR}/chat",
        data=json.dumps({"text": text}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with _open(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    if "error" in data:
        raise RuntimeError(data["error"])
    return _extract_text(data.get("reply", ""))


def chat_with_memory(text: str, timeout: int = 120, *, owner_id: str | None = None) -> dict:
    """带宛委记忆的一轮对话。

    1. 记忆写回：提取用户消息中的显式记忆/偏好，经宛委 policy_gate 写入；
    2. 记忆检索：以用户消息查询宛委，命中时把已知记忆注入发给助手的消息；
    3. 调用个人助手并返回 {reply, memories_used, memories_written}。

    记忆链路任何一步失败都不影响对话本身（fail-open）。
    """
    from memory_link import build_context, remember_statements

    memories_used: list[str] = []
    memories_written: list[str] = []
    outbound = text

    # 1) 写回（在检索前写，下一轮即可召回）
    try:
        for result in remember_statements(text, owner_id=owner_id):
            if result.get("capsule_id"):
                memories_written.append(result["_statement"])
    except Exception:
        pass  # fail-open：写回失败不阻塞对话

    # 2) 检索注入
    try:
        context_block, memories_used = build_context(text, owner_id=owner_id)
        if context_block:
            outbound = f"{context_block}\n\n用户说：{text}"
    except Exception:
        pass  # fail-open

    reply = chat(outbound, timeout=timeout)
    return {
        "reply": reply,
        "memories_used": memories_used,
        "memories_written": memories_written,
    }


def _extract_text(raw: str) -> str:
    """sidecar把流式分片的原始JSON串拼接返回,这里解析出所有result字段的纯文本."""
    out = []
    dec = json.JSONDecoder()
    idx = 0
    raw = raw.strip()
    while idx < len(raw):
        # 跳过到下一个'{'
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


def health() -> bool:
    try:
        with _open(f"{SIDECAR}/health", timeout=3) as resp:
            return json.loads(resp.read()).get("ok", False)
    except Exception:
        return False


if __name__ == "__main__":
    import sys

    msg = sys.argv[1] if len(sys.argv) > 1 else "你好,请用一句话介绍你自己"
    result = chat_with_memory(msg)
    print(result["reply"])
    if result["memories_used"]:
        print(f"[注入记忆 {len(result['memories_used'])} 条]", file=sys.stderr)
    if result["memories_written"]:
        print(f"[写回记忆 {len(result['memories_written'])} 条]", file=sys.stderr)
