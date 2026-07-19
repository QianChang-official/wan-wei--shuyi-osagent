"""W01 加密认证修复的针对性测试。

覆盖任务包四条：
1. (02-#3/03-#9/05-#12) WANWEI_ENCRYPTION_KEY 独立密钥；生产模式拒绝从
   API key 派生；非生产回退派生并打警告日志；dev 默认 key 仍可用。
2. (02-#4/04-#11) decrypt() 删除 base64 明文静默回退：旧数据显式报错
   （LegacyCiphertextError，含迁移指引）+ migrate_legacy_ciphertext 一次性迁移。
3. (02-#13) compare_digest 遇非 ASCII X-API-Key 按认证失败处理（401 而非 500）。
4. (02-#17/03-#12) 保护性 GET 纳入限流；限流面与鉴权面清单单源化。
"""
from __future__ import annotations

import base64
import logging

import pytest
from cryptography.fernet import Fernet

from backend.app.security import auth, encryption
from backend.app.security.rate_limit import (
    RateLimiter,
    RateLimitMiddleware,
    build_default_rate_limiter,
)


# ---------------------------------------------------------------------------
# 1. 密钥派生（02-#3/03-#9/05-#12）
# ---------------------------------------------------------------------------

def test_explicit_encryption_key_roundtrip(monkeypatch):
    """显式 WANWEI_ENCRYPTION_KEY 路径保持既有契约。"""
    key = Fernet.generate_key()
    monkeypatch.setenv("WANWEI_ENCRYPTION_KEY", key.decode("ascii"))

    ciphertext = encryption.encrypt("provider-secret")

    assert Fernet(key).decrypt(ciphertext.encode("ascii")) == b"provider-secret"
    assert encryption.decrypt(ciphertext) == "provider-secret"


def test_production_refuses_api_key_derivation(monkeypatch):
    """生产模式未设 WANWEI_ENCRYPTION_KEY：拒绝从 API key 派生（fail-closed）。"""
    monkeypatch.delenv("WANWEI_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("WANWEI_API_KEY", "a-strong-production-key-with-40-characters")
    monkeypatch.setenv("WANWEI_PRODUCTION", "1")

    with pytest.raises(RuntimeError, match="WANWEI_ENCRYPTION_KEY"):
        encryption.encrypt("secret")
    with pytest.raises(RuntimeError, match="WANWEI_ENCRYPTION_KEY"):
        encryption.decrypt("anything")


def test_non_production_derivation_warns_once_and_works(monkeypatch, caplog):
    """非生产回退：派生自 API key + 打警告日志（每进程一次）；功能不受影响。"""
    monkeypatch.delenv("WANWEI_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)
    monkeypatch.setenv("WANWEI_API_KEY", "development-api-key")
    monkeypatch.setattr(encryption, "_derived_key_warning_emitted", False)

    with caplog.at_level(logging.WARNING, logger=encryption.logger.name):
        ciphertext = encryption.encrypt("derived-secret")
        assert encryption.decrypt(ciphertext) == "derived-secret"
        encryption.encrypt("second-call")

    warnings = [r for r in caplog.records if "WANWEI_ENCRYPTION_KEY" in r.message]
    assert len(warnings) == 1, "回退警告应每进程只打一次，避免日志刷屏"


def test_dev_default_key_still_usable(monkeypatch):
    """dev 默认 key（wanwei-dev-key）零配置可用性不破坏。"""
    monkeypatch.delenv("WANWEI_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)
    monkeypatch.delenv("WANWEI_API_KEY", raising=False)
    monkeypatch.delenv("WANWEI_API_KEY_FILE", raising=False)

    ciphertext = encryption.encrypt("dev-secret")
    assert encryption.decrypt(ciphertext) == "dev-secret"


def test_production_with_explicit_key_works(monkeypatch):
    """生产模式 + 显式 WANWEI_ENCRYPTION_KEY：正常工作。"""
    key = Fernet.generate_key()
    monkeypatch.setenv("WANWEI_ENCRYPTION_KEY", key.decode("ascii"))
    monkeypatch.setenv("WANWEI_API_KEY", "a-strong-production-key-with-40-characters")
    monkeypatch.setenv("WANWEI_PRODUCTION", "1")

    assert encryption.decrypt(encryption.encrypt("prod-secret")) == "prod-secret"


# ---------------------------------------------------------------------------
# 2. decrypt() 删除 base64 静默回退（02-#4/04-#11）
# ---------------------------------------------------------------------------

def test_decrypt_legacy_base64_raises_with_migration_guidance(monkeypatch):
    """旧 base64 明文绝不静默返回：显式报错并给出迁移指引。"""
    monkeypatch.setenv("WANWEI_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    legacy_ciphertext = base64.b64encode(b"legacy-secret").decode("ascii")

    with pytest.raises(encryption.LegacyCiphertextError, match="migrate_legacy_ciphertext"):
        encryption.decrypt(legacy_ciphertext)


def test_legacy_error_is_value_error_for_consumer_compatibility(monkeypatch):
    """异常是 ValueError 子类：既有宽捕获（providers 等）不会变成 500。"""
    monkeypatch.setenv("WANWEI_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    legacy_ciphertext = base64.b64encode(b"legacy-secret").decode("ascii")

    assert issubclass(encryption.LegacyCiphertextError, ValueError)
    with pytest.raises(ValueError):
        encryption.decrypt(legacy_ciphertext)


def test_decrypt_wrong_key_returns_empty_string(monkeypatch):
    """错密钥/损坏数据仍返回 ""：保住 model-gateway「cannot be decrypted」显式路径。"""
    monkeypatch.setenv("WANWEI_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    ciphertext = encryption.encrypt("db-secret-key")
    monkeypatch.setenv("WANWEI_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))

    assert encryption.decrypt(ciphertext) == ""


def test_decrypt_garbage_returns_empty_string(monkeypatch):
    """无法识别的垃圾输入返回 ""（非明文、非旧格式）。"""
    monkeypatch.setenv("WANWEI_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))

    assert encryption.decrypt("not encrypted data") == ""
    assert encryption.decrypt("") == ""


def test_migrate_legacy_ciphertext_reencrypts_and_is_idempotent(monkeypatch):
    """一次性迁移：旧 base64 → Fernet 密文；幂等；垃圾输入显式报错。"""
    monkeypatch.setenv("WANWEI_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    legacy_ciphertext = base64.b64encode(b"legacy-secret").decode("ascii")

    migrated = encryption.migrate_legacy_ciphertext(legacy_ciphertext)
    assert migrated != legacy_ciphertext
    assert encryption.decrypt(migrated) == "legacy-secret"
    # 幂等：已是 Fernet 密文的值原样返回
    assert encryption.migrate_legacy_ciphertext(migrated) == migrated
    # 既非 Fernet 又非旧 base64：无可迁移内容，显式报错
    with pytest.raises(encryption.DecryptionError):
        encryption.migrate_legacy_ciphertext("not encrypted data")


# ---------------------------------------------------------------------------
# 3. compare_digest 非 ASCII（02-#13）
# ---------------------------------------------------------------------------

def test_verify_api_key_non_ascii_returns_false(monkeypatch):
    """非 ASCII 候选 key 不抛 TypeError，按认证失败处理。"""
    monkeypatch.setenv("WANWEI_API_KEY", "test-key")
    monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)

    assert auth._verify_api_key("密钥-non-ascii") is False
    assert auth._verify_api_key("test-key") is True
    assert auth._verify_api_key("wrong") is False


def test_middleware_non_ascii_api_key_gets_401_not_500(monkeypatch):
    """端到端：带非 ASCII 字节的 X-API-Key 得到 401 而非 500。"""
    monkeypatch.setenv("WANWEI_API_KEY", "test-key")
    monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.add_middleware(auth.APIKeyMiddleware)

    @app.get("/audit/logs")
    def logs():
        return {"items": []}

    client = TestClient(app, raise_server_exceptions=False)
    # 以原始字节发送非 ASCII 头，服务端 latin-1 解码后为非 ASCII str
    response = client.get("/audit/logs", headers=[(b"x-api-key", "密".encode("utf-8"))])
    assert response.status_code == 401
    assert client.get("/audit/logs", headers={"x-api-key": "test-key"}).status_code == 200


# ---------------------------------------------------------------------------
# 4. 保护性 GET 限流 + 清单单源化（02-#17/03-#12）
# ---------------------------------------------------------------------------

def test_default_limiter_covers_unlisted_platform_gets():
    """其余 /platform/* 与未列名保护性 GET 纳入默认限流（合理额度 120/min）。"""
    limiter = build_default_rate_limiter()

    assert limiter.limit_for("/platform/agents", method="GET") == 120
    assert limiter.limit_for("/platform/providers/configs", method="GET") == 120
    assert limiter.limit_for("/platform/automation/flows", method="GET") == 120
    assert limiter.limit_for("/model-gateway/configs", method="GET") == 120
    assert limiter.limit_for("/audit/logs", method="GET") == 120
    assert limiter.limit_for("/metrics", method="GET") == 120


def test_default_limiter_keeps_public_paths_unlimited():
    """公开白名单路径（与鉴权同源）不限流。"""
    limiter = build_default_rate_limiter()

    assert limiter.limit_for("/health", method="GET") is None
    assert limiter.limit_for("/health/ready", method="GET") is None
    assert limiter.limit_for("/console", method="GET") is None
    assert limiter.limit_for("/console/assets/app.js", method="GET") is None
    assert limiter.limit_for("/docs", method="GET") is None


def test_default_limiter_explicit_limits_still_win():
    """显式收紧的端点额度不回归。"""
    limiter = build_default_rate_limiter()

    assert limiter.limit_for("/kylin/sdk/status", method="GET") == 10
    assert limiter.limit_for("/workflow/stats", method="GET") == 60
    assert limiter.limit_for("/platform/mcp/servers", method="GET") == 30
    assert limiter.limit_for("/memory/v2/search", method="GET") == 60


def test_rate_limit_single_sources_auth_public_list(monkeypatch):
    """单源化证据：修改 auth 公开白名单，限流面即时跟随（无第二份清单）。"""
    assert build_default_rate_limiter().limit_for("/platform/agents", method="GET") == 120

    monkeypatch.setattr(auth, "_PUBLIC_PATHS", auth._PUBLIC_PATHS | {"/platform/agents"})

    assert build_default_rate_limiter().limit_for("/platform/agents", method="GET") is None


def test_protected_get_budget_enforced_end_to_end():
    """端到端：同源保护性 GET 超限返回 429，公开路径不受影响。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    limiter = RateLimiter(
        {},
        protected_get_limit_per_min=2,
        public_path_checker=auth.is_public_path,
    )
    app.add_middleware(RateLimitMiddleware, limiter=limiter)

    @app.get("/platform/things")
    def things():
        return {"ok": True}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    client = TestClient(app)
    assert client.get("/platform/things").status_code == 200
    assert client.get("/platform/things").status_code == 200
    assert client.get("/platform/things").status_code == 429
    for _ in range(5):
        assert client.get("/health").status_code == 200
