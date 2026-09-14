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
"""assistant_bridge/memory_link 集成测试。

覆盖桥接组件的三条验收线：
1. 写回 → 重启后端 → 召回（跨会话记忆的核心承诺）；
2. PII 写回被服务端 policy_gate 拒绝（安全红线，桥侧不做二次过滤）；
3. fail-open：后端不可用时检索返回空、不抛异常（不阻塞对话主链路）。

真实 HTTP 链路（uvicorn 线程 + 127.0.0.1）而非 TestClient：
memory_link 走 urllib，端到端才有意义。
"""

from __future__ import annotations

import importlib
import socket
import threading
import time
from pathlib import Path

import pytest

from scripts.assistant_bridge import memory_link
from scripts.assistant_bridge.wanwei_assistant_adapter import chat_with_memory  # noqa: F401  契约存在性
from scripts.assistant_bridge.memory_link import (
    extract_statements,
    remember_statement,
    search_memories,
)

_API_KEY = "test-owner-key-0123456789abcdef"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _ServerHandle:
    """uvicorn 线程句柄：start/stop 可重复，共享同一 SQLite 文件。"""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self._thread = None
        self._server = None

    def start(self) -> None:
        import uvicorn

        from backend.app.main import app as fastapi_app

        host, port = self.base_url.rsplit(":", 1)
        config = uvicorn.Config(
            fastapi_app,
            host=host,
            port=int(port),
            log_level="error",
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        deadline = time.time() + 15
        while time.time() < deadline:
            if self._server.started:
                return
            time.sleep(0.05)
        raise RuntimeError("uvicorn did not start in 15s")

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
            self._thread.join(timeout=10)
            self._server = None
            self._thread = None


@pytest.fixture()
def bridge_server(monkeypatch, tmp_path: Path) -> _ServerHandle:
    """独立 tmp 库 + 真实 uvicorn 实例；用完即弃，不污染其他测试。"""
    db_path = tmp_path / "bridge_memory.db"
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(db_path))
    monkeypatch.setenv("WANWEI_API_KEY", _API_KEY)
    monkeypatch.setenv("WANWEI_ALLOWED_HOSTS", "127.0.0.1,localhost")
    monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)
    # 桥侧密钥与后端配对：显式设置 WANWEI_API_KEY 后回环免密关闭（fail-closed），
    # 写请求必须带 X-API-Key（服务端安全设计，见 security/auth.py）。
    monkeypatch.setattr(memory_link, "_API_KEY", _API_KEY)

    from backend.app import init_db
    from backend.app import main as main_module
    from backend.app.db import close_all

    close_all()
    importlib.reload(main_module)
    init_db.main()

    handle = _ServerHandle(f"127.0.0.1:{_free_port()}")
    handle.start()
    monkeypatch.setattr(memory_link, "API_BASE", f"http://{handle.base_url}")
    try:
        yield handle
    finally:
        handle.stop()
        close_all()


class TestCrossSessionRecall:
    """验收线 1：写回 → 重启 → 召回。"""

    def test_write_then_recall_after_server_restart(self, bridge_server):
        owner = "kylin-assistant-test"
        written = remember_statement(
            "桥接测试最喜欢的语言是 Python",
            "preference",
            owner_id=owner,
        )
        assert written is not None, "写回应答不可达"
        assert written.get("capsule_id"), f"写入未落库: {written}"

        bridge_server.stop()
        bridge_server.start()  # 重启 = 模拟新会话，SQLite 持久层不变

        hits = search_memories("桥接测试最喜欢的语言", owner_id=owner)
        statements = [memory_link._statement_of(c) for c in hits]
        assert any("Python" in s for s in statements), f"跨会话召回失败: {statements}"

    def test_recall_scoped_by_soul_id(self, bridge_server):
        remember_statement("隔离测试唯一标记词 XyZZy", "knowledge", owner_id="soul-a")
        hits_b = search_memories("隔离测试唯一标记词", owner_id="soul-b")
        assert hits_b == [], "soul_id 隔离失效，记忆串库"


class TestPolicyGateRedLine:
    """验收线 2：PII 写回必须被服务端 policy_gate 拒绝（桥侧不做二次过滤）。"""

    def test_pii_id_number_rejected(self, bridge_server):
        result = remember_statement(
            "我的身份证号是 110101200001011234，帮我记一下",
            "knowledge",
            owner_id="kylin-assistant-test",
        )
        assert result is not None
        assert result.get("state", {}).get("lifecycle") == "rejected", f"PII 未被拦截: {result}"
        policy = result.get("governance", {}).get("policy_result")
        assert policy == "reject", f"policy_result 非拒绝: {policy}"


class TestFailOpen:
    """验收线 3：后端不可用时不抛异常、返回空。"""

    def test_search_against_dead_backend_returns_empty(self, monkeypatch):
        monkeypatch.setattr(memory_link, "API_BASE", "http://127.0.0.1:1")
        monkeypatch.setattr(memory_link, "DEFAULT_TIMEOUT", 1.0)
        assert search_memories("任意查询", timeout=1) == []

    def test_remember_against_dead_backend_returns_none(self, monkeypatch):
        monkeypatch.setattr(memory_link, "API_BASE", "http://127.0.0.1:1")
        monkeypatch.setattr(memory_link, "DEFAULT_TIMEOUT", 1.0)
        assert remember_statement("死后端写回测试", "knowledge") is None


class TestExtractStatements:
    """写回启发式：宁漏勿滥。"""

    def test_explicit_remember(self):
        pairs = extract_statements("帮我记住：明早十点开组会")
        assert ("明早十点开组会", "knowledge") in pairs

    def test_preference_keeps_full_sentence(self):
        pairs = extract_statements("我最喜欢雨天听白噪音")
        assert len(pairs) == 1
        statement, memory_class = pairs[0]
        assert memory_class == "preference"
        assert statement == "我最喜欢雨天听白噪音"

    def test_smalltalk_not_captured(self):
        assert extract_statements("今天天气真不错啊") == []

    def test_overlong_message_ignored(self):
        assert extract_statements("记一下" + "长" * 300) == []
