#!/usr/bin/env python3
"""宛委 <-> 麒麟个人助手 adapter.
调用: WanweiAssistant().chat("你好") -> "..."
sidecar: POST http://127.0.0.1:8021/chat
"""
import json
import urllib.request

SIDECAR = "http://127.0.0.1:8021"


def chat(text: str, timeout: int = 120) -> str:
    """发一条消息给麒麟个人助手,返回拼接后的纯文本回复."""
    req = urllib.request.Request(
        f"{SIDECAR}/chat",
        data=json.dumps({"text": text}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    if "error" in data:
        raise RuntimeError(data["error"])
    return _extract_text(data.get("reply", ""))


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
        with urllib.request.urlopen(f"{SIDECAR}/health", timeout=3) as resp:
            return json.loads(resp.read()).get("ok", False)
    except Exception:
        return False


if __name__ == "__main__":
    import sys
    msg = sys.argv[1] if len(sys.argv) > 1 else "你好,请用一句话介绍你自己"
    print(chat(msg))
