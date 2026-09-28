#!/usr/bin/env python3
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

"""宛委 <-> 麒麟个人助手 adapter.
调用: WanweiAssistant().chat("你好") -> "..."
sidecar: POST http://127.0.0.1:8021/chat
"""
import http.client
import json

_SIDECAR_HOST = "127.0.0.1"
_SIDECAR_PORT = 8021
SIDECAR = f"http://{_SIDECAR_HOST}:{_SIDECAR_PORT}"


def _request(method: str, path: str, body: bytes | None, timeout: int) -> bytes:
    """回环 sidecar 的极简 HTTP 客户端(stdlib http.client,零三方依赖)。

    刻意不用 urllib.request.urlopen:安全审计规则(Bandit B310 等)对一切
    urlopen 调用无条件告警;本模块目标恒为编译期常量回环地址,用
    http.client 显式绑定 host/port,从写法上消除 scheme 注入面。
    """
    conn = http.client.HTTPConnection(_SIDECAR_HOST, _SIDECAR_PORT, timeout=timeout)
    try:
        headers = {"Content-Type": "application/json"} if body is not None else {}
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        payload = resp.read()
        if resp.status != 200:
            raise RuntimeError(f"sidecar HTTP {resp.status}: {payload[:200]!r}")
        return payload
    finally:
        conn.close()


def chat(text: str, timeout: int = 120) -> str:
    """发一条消息给麒麟个人助手,返回拼接后的纯文本回复."""
    data = json.loads(_request("POST", "/chat", json.dumps({"text": text}).encode(), timeout))
    if "error" in data:
        raise RuntimeError(data["error"])
    reply = _extract_text(data.get("reply", ""))
    if data.get("timed_out"):
        # sidecar 90s 硬超时:已收集内容照常返回,但如实提示截断,
        # 调用方可选择向用户预警或重试,而不是把半截回复当完整结果。
        reply += "\n[警告:回复因超时被截断]"
    return reply


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
    if not out and raw:
        # 一个 JSON 分片都没解析出来:说明上游返回的是纯文本而非分片流,
        # 原样返回,避免"链路异常时静默拿到空串"掩盖真实故障。
        return raw
    return "".join(out)


def health() -> bool:
    try:
        return json.loads(_request("GET", "/health", None, 3)).get("ok", False)
    except Exception:
        return False


if __name__ == "__main__":
    import sys
    msg = sys.argv[1] if len(sys.argv) > 1 else "你好,请用一句话介绍你自己"
    print(chat(msg))
