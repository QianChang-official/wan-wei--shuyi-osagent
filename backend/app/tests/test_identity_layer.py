"""身份层解耦测试：owner_id 独立 UUID + key 轮换。

覆盖：
- 首次使用自动注册 identity
- 重复调用返回同一 identity_id
- key 轮换后新 key 继承同一身份
- 旧 key 轮换后失效
- 向后兼容（identity 表未建时回退到 blake2b 派生）
"""
from __future__ import annotations

import importlib
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def db_path(tmp_path):
    return str(tmp_path / "identity_test.db")


@pytest.fixture()
def client(db_path, monkeypatch):
    monkeypatch.setenv("WANWEI_MEMORY_DB", db_path)
    monkeypatch.setenv("WANWEI_API_KEY", "test-owner-key-0123456789abcdef")
    monkeypatch.setenv("WANWEI_ALLOWED_HOSTS", "testserver")
    monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)
    from backend.app import init_db
    from backend.app import main as main_module
    from backend.app.db import close_all

    close_all()
    importlib.reload(main_module)
    init_db.main()
    return TestClient(main_module.app, raise_server_exceptions=False)


class TestIdentityRegistration:
    """首次使用自动注册，后续调用返回同一身份。"""

    def test_first_use_registers_identity(self, client):
        r = client.get("/memory/identity", headers={"x-api-key": "test-owner-key-0123456789abcdef"})
        assert r.status_code == 200
        body = r.json()
        assert body["owner_id"].startswith("id_")
        assert body["identity_layer"] == "uuid"

    def test_repeated_calls_same_identity(self, client):
        r1 = client.get("/memory/identity", headers={"x-api-key": "test-owner-key-0123456789abcdef"})
        r2 = client.get("/memory/identity", headers={"x-api-key": "test-owner-key-0123456789abcdef"})
        assert r1.json()["owner_id"] == r2.json()["owner_id"]

    def test_concurrent_first_use_registers_one_identity(self, isolated_db):
        from backend.app.db import get_conn
        from backend.app.security.auth import _api_key_hash, actor_id_from_api_key

        key = "same-first-use-key"
        with ThreadPoolExecutor(max_workers=8) as executor:
            identity_ids = list(executor.map(actor_id_from_api_key, [key] * 16))

        assert len(set(identity_ids)) == 1
        rows = get_conn().execute(
            "SELECT identity_id FROM identity WHERE api_key_hash=?",
            (_api_key_hash(key),),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["identity_id"] == identity_ids[0]


class TestKeyRotation:
    """key 轮换：新 key 继承身份，旧 key 失效，历史数据保留。"""

    def test_rotate_preserves_identity(self, client):
        old_key = "test-owner-key-0123456789abcdef"
        new_key = "test-owner-key-rotated-0123456789ab"

        # 先写入一条记忆（旧 key）
        r = client.post(
            "/memory/v2/capsules",
            headers={"x-api-key": old_key},
            json={
                "memory_class": "knowledge",
                "content": {"knowledge_type": "fact", "statement": "轮换前写入"},
                "source_type": "manual_config",
            },
        )
        assert r.status_code == 200
        capsule_id = r.json()["capsule_id"]

        # 轮换
        r = client.post(
            "/memory/identity/rotate",
            headers={"x-api-key": old_key},
            json={"new_key": new_key},
        )
        assert r.status_code == 200
        identity_id = r.json()["identity_id"]

        # 新 key 读取同一身份
        r = client.get("/memory/identity", headers={"x-api-key": new_key})
        assert r.json()["owner_id"] == identity_id

        # 新 key 能读到旧 key 写入的记忆
        r = client.get(f"/memory/v2/capsules/{capsule_id}", headers={"x-api-key": new_key})
        assert r.status_code == 200

    def test_old_key_invalid_after_rotation(self, client):
        old_key = "test-owner-key-0123456789abcdef"
        new_key = "test-owner-key-rotated-0123456789ab"

        client.post(
            "/memory/identity/rotate",
            headers={"x-api-key": old_key},
            json={"new_key": new_key},
        )
        # 旧 key 已失效
        r = client.get("/memory/identity", headers={"x-api-key": old_key})
        assert r.status_code == 401

    def test_rotate_requires_min_length(self, client):
        r = client.post(
            "/memory/identity/rotate",
            headers={"x-api-key": "test-owner-key-0123456789abcdef"},
            json={"new_key": "short"},
        )
        assert r.status_code == 422

    @pytest.mark.parametrize("other_key_active", [True, False])
    def test_rotate_rejects_key_owned_by_other_identity(
        self, isolated_db, other_key_active
    ):
        from backend.app.security.auth import (
            _verify_api_key,
            actor_id_from_api_key,
            rotate_api_key,
        )

        first_key = "first-identity-key"
        other_key = "other-identity-key"
        other_replacement = "other-replacement-key"
        first_identity = actor_id_from_api_key(first_key)
        other_identity = actor_id_from_api_key(other_key)
        if not other_key_active:
            assert rotate_api_key(other_key, other_replacement) == other_identity

        with pytest.raises(sqlite3.IntegrityError, match="unavailable"):
            rotate_api_key(first_key, other_key)

        assert _verify_api_key(first_key)
        assert actor_id_from_api_key(first_key) == first_identity
        assert actor_id_from_api_key(other_key) == other_identity

    def test_concurrent_rotations_cannot_claim_same_new_key(self, isolated_db):
        from backend.app.db import get_conn
        from backend.app.security.auth import (
            _api_key_hash,
            _verify_api_key,
            actor_id_from_api_key,
            rotate_api_key,
        )

        old_keys = ["rotation-source-a", "rotation-source-b"]
        identities = {key: actor_id_from_api_key(key) for key in old_keys}
        new_key = "contended-new-key"

        def rotate(old_key):
            try:
                return old_key, "rotated", rotate_api_key(old_key, new_key)
            except sqlite3.IntegrityError as exc:
                return old_key, "collision", str(exc)

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(rotate, old_keys))

        assert sorted(result[1] for result in results) == ["collision", "rotated"]
        winner = next(result for result in results if result[1] == "rotated")
        loser = next(result for result in results if result[1] == "collision")
        assert winner[2] == identities[winner[0]]
        assert loser[2] == "new key is unavailable"
        assert actor_id_from_api_key(new_key) == identities[winner[0]]
        assert not _verify_api_key(winner[0])
        assert _verify_api_key(loser[0])
        assert get_conn().execute(
            "SELECT COUNT(*) FROM identity WHERE api_key_hash=?",
            (_api_key_hash(new_key),),
        ).fetchone()[0] == 1


class TestKeyRevocation:
    """独立撤销：不轮换，仅吊销指定 key。

    注意：identity 表已建时，_verify_api_key 优先查注册表。测试用的
    admin_key 必须先通过 rotate 注册为合法 key，才能通过鉴权调用 revoke。
    撤销目标必须是活跃 key（rotate 后的旧 key 已 is_active=0，再撤销会 409）。
    """

    def test_revoke_unregisters_key(self, client):
        env_key = "test-owner-key-0123456789abcdef"
        admin_key = "admin-key-0123456789abcdef01234567"

        # env key 注册
        r = client.get("/memory/identity", headers={"x-api-key": env_key})
        assert r.status_code == 200

        # admin key 通过 rotate 注册（继承同一 identity，env key 变为 is_active=0）
        r = client.post(
            "/memory/identity/rotate",
            headers={"x-api-key": env_key},
            json={"new_key": admin_key},
        )
        assert r.status_code == 200

        # 撤销 admin key（活跃状态）
        r = client.post(
            "/memory/identity/revoke",
            headers={"x-api-key": admin_key},
            json={"api_key": admin_key},
        )
        # 防自杀保护：不允许撤销当前请求 key
        assert r.status_code == 422

        # 用 env key（已失效）无法鉴权，无法执行撤销
        r = client.post(
            "/memory/identity/revoke",
            headers={"x-api-key": env_key},
            json={"api_key": admin_key},
        )
        assert r.status_code == 401

        # 用 admin key 撤销 env key（env key 已 is_active=0，返回 409）
        r = client.post(
            "/memory/identity/revoke",
            headers={"x-api-key": admin_key},
            json={"api_key": env_key},
        )
        assert r.status_code == 409
        assert r.json()["detail"] == "key_already_inactive"

    def test_revoke_rejects_current_key(self, client):
        key = "test-owner-key-0123456789abcdef"
        client.get("/memory/identity", headers={"x-api-key": key})
        r = client.post(
            "/memory/identity/revoke",
            headers={"x-api-key": key},
            json={"api_key": key},
        )
        assert r.status_code == 422

    def test_revoke_unknown_key_404(self, client):
        env_key = "test-owner-key-0123456789abcdef"
        admin_key = "admin-key-0123456789abcdef01234567"

        # 注册 env key，再 rotate 出 admin key
        client.get("/memory/identity", headers={"x-api-key": env_key})
        r = client.post(
            "/memory/identity/rotate",
            headers={"x-api-key": env_key},
            json={"new_key": admin_key},
        )
        assert r.status_code == 200

        r = client.post(
            "/memory/identity/revoke",
            headers={"x-api-key": admin_key},
            json={"api_key": "never-registered-key-0123456789ab"},
        )
        assert r.status_code == 404


class TestIdentitySchemaMigration:
    def test_legacy_composite_primary_key_migrates_idempotently(
        self, tmp_path, monkeypatch
    ):
        db = str(tmp_path / "legacy-identity.db")
        monkeypatch.setenv("WANWEI_MEMORY_DB", db)
        monkeypatch.setenv("WANWEI_API_KEY", "configured-migration-key")
        from backend.app import init_db
        from backend.app.db import close_all, get_conn

        close_all()
        legacy = sqlite3.connect(db)
        legacy.executescript(
            """
            CREATE TABLE identity(
                identity_id TEXT NOT NULL,
                api_key_hash TEXT NOT NULL,
                display_name TEXT,
                created_at TEXT NOT NULL,
                rotated_from TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY(identity_id, api_key_hash)
            );
            CREATE INDEX idx_identity_key_hash ON identity(api_key_hash);
            """
        )
        duplicate_hash = "legacy-duplicate-hash"
        legacy.executemany(
            "INSERT INTO identity(identity_id, api_key_hash, created_at, is_active) "
            "VALUES (?,?,?,?)",
            [
                ("id_inactive", duplicate_hash, "20200101T000000Z", 0),
                ("id_active", duplicate_hash, "20210101T000000Z", 1),
                ("id_other", "other-hash", "20220101T000000Z", 1),
            ],
        )
        legacy.commit()
        legacy.close()

        init_db.main()
        init_db.main()

        conn = get_conn()
        primary_key = [
            row["name"]
            for row in sorted(
                (row for row in conn.execute("PRAGMA table_info(identity)") if row["pk"]),
                key=lambda row: row["pk"],
            )
        ]
        assert primary_key == ["api_key_hash"]
        indexes = {
            row["name"]: row["unique"]
            for row in conn.execute("PRAGMA index_list(identity)")
        }
        assert indexes["idx_identity_key_hash"] == 1
        duplicate_rows = conn.execute(
            "SELECT identity_id FROM identity WHERE api_key_hash=?",
            (duplicate_hash,),
        ).fetchall()
        assert [row["identity_id"] for row in duplicate_rows] == ["id_active"]
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO identity(identity_id, api_key_hash, created_at) "
                "VALUES (?,?,?)",
                ("id_conflict", duplicate_hash, "20230101T000000Z"),
            )
        conn.rollback()


class TestBackwardCompatibility:
    """向后兼容：identity 表未建时回退到 blake2b 派生。"""

    def test_legacy_derived_when_table_missing(self, tmp_path, monkeypatch):
        db = str(tmp_path / "legacy.db")
        monkeypatch.setenv("WANWEI_MEMORY_DB", db)
        monkeypatch.setenv("WANWEI_API_KEY", "legacy-key-0123456789abcdef01")
        from backend.app.db import close_all
        from backend.app.security.auth import _derive_legacy_owner_id

        close_all()
        # 不跑 init_db，直接调派生函数
        owner = _derive_legacy_owner_id("legacy-key-0123456789abcdef01")
        assert owner.startswith("api_")
