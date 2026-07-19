"""Mission B 后端核心稳定性回归测试。

覆盖：
- B1: 关键写路径使用 transaction() / 异常回滚，不污染后续请求。
- B2: runtime schema 与 vector schema 每个 db_path 只初始化一次。
- B3: /soul/chat 只 intake 当轮新增 user 消息；模型不可达时返回 provider_error。
- B4: soul 核心记忆按 provenance.soul_id 隔离。
"""

from __future__ import annotations

import os
from unittest import mock

import pytest
from fastapi.testclient import TestClient


def _client(tmp_path, *, api_key: str = "test-key", **env):
    """构造一个使用隔离临时 DB 的 TestClient。"""
    os.environ["WANWEI_API_KEY"] = api_key
    os.environ["WANWEI_MEMORY_DB"] = str(tmp_path / "memory.db")
    os.environ.pop("WANWEI_PRODUCTION", None)
    for k, v in env.items():
        os.environ[k] = v
    # 避免之前的 import 缓存影响
    import importlib
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    import backend.app.init_db
    import backend.app.main as main_mod

    importlib.reload(main_mod)
    backend.app.init_db.main()
    return TestClient(main_mod.app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# B1 事务隔离
# ---------------------------------------------------------------------------


def test_write_capsule_rollback_does_not_leak(isolated_db, monkeypatch):
    """write_capsule 内部使用 transaction()，失败时 rollback，不残留悬挂事务。"""
    import uuid as uuid_mod

    from backend.app.db import get_conn, transaction
    from backend.app.memory_runtime.capsule_store import write_capsule

    # 固定 capsule_id，确保第二次写入触发主键冲突
    fixed_uuid = uuid_mod.UUID("12345678-1234-5678-1234-567812345678")
    monkeypatch.setattr(
        "backend.app.memory_runtime.capsule_store.uuid.uuid4", lambda: fixed_uuid
    )

    res = write_capsule(
        memory_class="working",
        content={"text": "first"},
        source_type="user_input",
        provenance={"soul_id": "soul_a"},
    )
    cid = res["capsule_id"]

    with pytest.raises(Exception):
        write_capsule(
            memory_class="working",
            content={"text": "second"},
            source_type="user_input",
            provenance={"soul_id": "soul_a"},
        )

    # 悬挂事务必须已 rollback，连接回到干净状态
    assert not get_conn().in_transaction

    # 后续写入应正常
    with transaction() as txn:
        txn.execute("CREATE TABLE IF NOT EXISTS b1_probe (id INTEGER PRIMARY KEY)")
        txn.execute("INSERT INTO b1_probe (id) VALUES (1)")

    row = get_conn().execute("SELECT id FROM b1_probe").fetchone()
    assert row["id"] == 1

    # 第一次写入的 capsule 仍存在
    assert get_conn().execute(
        "SELECT 1 FROM memory_capsules_v2 WHERE capsule_id=?", (cid,)
    ).fetchone() is not None


# ---------------------------------------------------------------------------
# B2 schema 初始化一次化
# ---------------------------------------------------------------------------


def test_runtime_schema_initialized_once_per_path(isolated_db):
    """同一 db_path 下多次 write_capsule 只触发一次 init_db main()。"""
    from backend.app import init_db
    from backend.app.memory_runtime import capsule_store

    call_count = [0]
    original_main = init_db.main

    def counting_main():
        call_count[0] += 1
        return original_main()

    with mock.patch.object(init_db, "main", side_effect=counting_main):
        capsule_store.write_capsule(
            memory_class="working",
            content={"text": "first"},
            source_type="user_input",
        )
        capsule_store.write_capsule(
            memory_class="working",
            content={"text": "second"},
            source_type="user_input",
        )

    assert call_count[0] == 1


def test_vector_schema_initialized_once_per_path(isolated_db):
    """同一 db_path 下多次 init_vector_schema 只触发一次 _init_vector_schema_impl。"""
    from backend.app.memory_runtime import vector_index

    call_count = [0]
    original_impl = vector_index._init_vector_schema_impl

    def counting_impl():
        call_count[0] += 1
        return original_impl()

    with mock.patch.object(vector_index, "_init_vector_schema_impl", side_effect=counting_impl):
        vector_index.init_vector_schema()
        vector_index.init_vector_schema()

    assert call_count[0] == 1


# ---------------------------------------------------------------------------
# B3 /soul/chat 去重与错误诚实
# ---------------------------------------------------------------------------


def _create_soul(client):
    from backend.app.soul.persona import create_persona

    return create_persona()


def test_soul_chat_intakes_only_new_user_turn(tmp_path):
    """OpenAI 风格客户端重发历史时，只把最后一条 user 消息 intake 一次。"""
    client = _client(tmp_path)
    soul_id = _create_soul(client)

    r = client.post(
        "/soul/chat",
        json={
            "soul_id": soul_id,
            "messages": [{"role": "user", "content": "第一轮问题"}],
        },
        headers={"x-api-key": "test-key"},
    )
    assert r.status_code == 200, r.text

    # 第二轮请求携带完整历史（模拟客户端行为）
    r = client.post(
        "/soul/chat",
        json={
            "soul_id": soul_id,
            "messages": [
                {"role": "user", "content": "第一轮问题"},
                {"role": "assistant", "content": "模拟回复"},
                {"role": "user", "content": "第二轮问题"},
            ],
        },
        headers={"x-api-key": "test-key"},
    )
    assert r.status_code == 200, r.text

    from backend.app.db import get_conn

    user_turns = get_conn().execute(
        "SELECT COUNT(*) AS c FROM conversation_turns WHERE soul_id=? AND role='user'",
        (soul_id,),
    ).fetchone()["c"]
    assert user_turns == 2, f"user turns={user_turns}, expected 2"


def test_soul_chat_reports_provider_error(tmp_path):
    """模型端点不可达时，/soul/chat 返回 provider_error 而非静默 local_mock。"""
    client = _client(
        tmp_path,
        WANWEI_OPENAI_COMPATIBLE_BASE="http://127.0.0.1:1/v1",
        WANWEI_OPENAI_COMPATIBLE_MODEL="unreachable-model",
    )
    soul_id = _create_soul(client)

    r = client.post(
        "/soul/chat",
        json={
            "soul_id": soul_id,
            "messages": [{"role": "user", "content": "你好"}],
        },
        headers={"x-api-key": "test-key"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    completion = data["completion"]
    assert completion["status"] == "provider_error"
    assert completion["provider"] == "openai_compatible"


# ---------------------------------------------------------------------------
# B4 soul 记忆隔离
# ---------------------------------------------------------------------------


def test_core_memories_are_isolated_by_soul_id(isolated_db):
    """soul_A 的高重要性记忆不应出现在 soul_B 的 injection prompt 中。"""
    from backend.app.memory_runtime.capsule_store import update_capsule, write_capsule
    from backend.app.soul.injector import build_injection_prompt
    from backend.app.soul.persona import create_persona

    soul_a = create_persona("soul_a_test")
    soul_b = create_persona("soul_b_test")

    # 为 soul_a 写入一条高重要性核心记忆
    cap = write_capsule(
        memory_class="working",
        content={"text": "这是 soul_a 的独家秘密记忆"},
        source_type="user_input",
        provenance={"soul_id": soul_a},
    )
    state = cap["state"]
    state["importance_score"] = 1.0
    update_capsule(cap["capsule_id"], state=state)

    prompt_b = build_injection_prompt(soul_b)
    assert "独家秘密记忆" not in prompt_b

    prompt_a = build_injection_prompt(soul_a)
    assert "独家秘密记忆" in prompt_a
