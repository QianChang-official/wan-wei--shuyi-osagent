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
"""宛委记忆后端 link：麒麟个人助手桥的检索注入与写回。

- 检索：GET /memory/v2/search?q=...&top_k=3
- 写回：POST /memory/v2/capsules（服务端 write_capsule 内置 policy_gate，
  PII/敏感内容自动拒绝，本模块不做二次过滤，以服务端裁决为准）

设计原则：fail-open——记忆后端不可用时检索返回空、写回静默失败，
绝不阻塞对话主链路（sidecar → 个人助手）。
"""

import json
import os
import re
import urllib.error
import urllib.request
from urllib.parse import quote

API_BASE = os.getenv("WANWEI_API_BASE", "http://127.0.0.1:8000").rstrip("/")
DEFAULT_OWNER_ID = os.getenv("WANWEI_BRIDGE_OWNER", "kylin-assistant")
DEFAULT_TIMEOUT = float(os.getenv("WANWEI_BRIDGE_TIMEOUT", "5"))
# 后端显式配置了 WANWEI_API_KEY 时回环免密关闭（fail-closed），写请求必须带头。
# 桥侧通过 WANWEI_BRIDGE_API_KEY 提供同一密钥；未设置则不带（裸启动回环免密场景）。
_API_KEY = os.getenv("WANWEI_BRIDGE_API_KEY", "").strip()


def _headers() -> dict[str, str]:
    return {"X-API-Key": _API_KEY} if _API_KEY else {}


# 受限 opener：仅注册 HTTP/HTTPS 处理器，从源头排除 file:/ftp: 等 scheme
# （与 wanwei_assistant_adapter 同一套路，CodeFactor B310 根治法）
_OPENER = urllib.request.OpenerDirector()
for handler_cls in (
    urllib.request.ProxyHandler,
    urllib.request.HTTPHandler,
    urllib.request.HTTPSHandler,
    urllib.request.HTTPErrorProcessor,
    urllib.request.HTTPDefaultErrorHandler,
    urllib.request.UnknownHandler,
):
    _OPENER.add_handler(handler_cls())


def _open(url, timeout: float, **kwargs):
    target = url.full_url if isinstance(url, urllib.request.Request) else url
    if not target.startswith(("http://", "https://")):
        raise ValueError(f"unexpected url scheme: {target}")
    return _OPENER.open(url, timeout=timeout, **kwargs)


# ---------------------------------------------------------------------------
# 检索注入
# ---------------------------------------------------------------------------


def search_memories(
    query: str, *, top_k: int = 3, owner_id: str | None = None, timeout: float = DEFAULT_TIMEOUT
) -> list[dict]:
    """检索宛委记忆，返回公开 capsule 列表（失败返回空列表）。

    显式配置了 WANWEI_BRIDGE_API_KEY 时 GET 也需带头（后端 fail-closed）。
    """
    if not query.strip():
        return []
    owner = owner_id or DEFAULT_OWNER_ID
    req = urllib.request.Request(
        f"{API_BASE}/memory/v2/search" f"?q={quote(query)}&top_k={top_k}&soul_id={quote(owner)}",
        headers=_headers(),
    )
    try:
        with _open(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        return data.get("results", []) or []
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return []


def _statement_of(capsule: dict) -> str:
    """从公开 capsule 提取一句可读陈述。"""
    content = capsule.get("content")
    if isinstance(content, dict):
        text = content.get("statement") or content.get("text") or ""
        if text:
            return str(text)
    return str(capsule.get("summary") or "").strip()


def build_context(query: str, *, top_k: int = 3, owner_id: str | None = None) -> tuple[str, list[str]]:
    """把检索命中拼成注入上下文块。返回 (上下文文本, 命中陈述列表)。"""
    hits = []
    for capsule in search_memories(query, top_k=top_k, owner_id=owner_id):
        statement = _statement_of(capsule)
        if statement:
            hits.append(statement)
    if not hits:
        return "", []
    lines = "\n".join(f"- {s}" for s in hits)
    return f"[已知记忆，回答时可参考]\n{lines}", hits


# ---------------------------------------------------------------------------
# 写回
# ---------------------------------------------------------------------------

# 显式记忆意图：「记住/记一下/帮我记」
_EXPLICIT_RE = re.compile(r"(?:帮我)?记(?:住|得|一下|下来)[：:,， ]?(.+)")
# 偏好自述：整句保留
_PREFERENCE_RE = re.compile(r"(我(?:很|最)?(?:喜欢|不喜欢|讨厌|不爱|最爱|偏好)|我叫|我的名字(?:是|叫))")
_PREFERENCE_WORDS = ("喜欢", "不喜欢", "讨厌", "不爱", "最爱", "偏好", "我叫", "我的名字")


def extract_statements(user_text: str) -> list[tuple[str, str]]:
    """从用户消息提取值得写入的记忆陈述。

    返回 [(statement, memory_class), ...]，memory_class ∈ {preference, knowledge}。
    规则刻意保守：宁漏勿滥，避免把寒暄和噪音灌进记忆库。
    """
    text = user_text.strip()
    if not text or len(text) > 200:
        return []
    found: list[tuple[str, str]] = []
    m = _EXPLICIT_RE.search(text)
    if m:
        found.append((m.group(1).strip("。！!？? "), "knowledge"))
    if _PREFERENCE_RE.search(text):
        found.append((text, "preference"))
    return found


def _ensure_soul(owner_id: str, timeout: float = DEFAULT_TIMEOUT) -> bool:
    """注册（或确认）桥专属 soul；已存在时幂等返回 True。"""
    req = urllib.request.Request(
        f"{API_BASE}/soul/connect",
        data=json.dumps({"soul_id": owner_id}).encode(),
        headers={"Content-Type": "application/json", **_headers()},
        method="POST",
    )
    try:
        with _open(req, timeout=timeout) as resp:
            return bool(json.loads(resp.read()))
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return False


def remember_statement(
    statement: str, memory_class: str = "knowledge", *, owner_id: str | None = None, timeout: float = DEFAULT_TIMEOUT
) -> dict | None:
    """写一条 capsule；返回写入结果（被 policy 拒绝时含 lifecycle=rejected），失败返回 None。

    soul 未注册（404 soul_not_found）时自动补注册并重试一次。
    """
    if not statement.strip():
        return None
    owner = owner_id or DEFAULT_OWNER_ID
    payload = {
        "memory_class": memory_class,
        "content": {"statement": statement.strip()},
        "source_type": "user_input",
        "write_intent": "explicit",
        "affects_future_behavior": memory_class == "preference",
        "soul_id": owner,
    }
    for attempt in (1, 2):
        req = urllib.request.Request(
            f"{API_BASE}/memory/v2/capsules",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", **_headers()},
            method="POST",
        )
        try:
            with _open(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and attempt == 1 and _ensure_soul(owner, timeout):
                continue  # soul 缺失 → 注册后重试一次
            return None
        except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
            return None
    return None


def remember_statements(user_text: str, *, owner_id: str | None = None) -> list[dict]:
    """按启发式规则从用户消息提取并写入，返回每条的写入结果。"""
    out = []
    for statement, memory_class in extract_statements(user_text):
        result = remember_statement(statement, memory_class, owner_id=owner_id)
        if result is not None:
            result["_statement"] = statement
            result["_memory_class"] = memory_class
            out.append(result)
    return out
