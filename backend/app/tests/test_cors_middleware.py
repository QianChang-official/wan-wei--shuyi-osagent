"""手机端 H5 跨源放行（WANWEI_CORS_ORIGINS）的行为契约。

覆盖四条不变式：
1. 未配置时**完全不挂载** CORS 中间件 —— 默认保持同源收敛姿态；
2. 显式白名单命中时返回 ``access-control-allow-origin`` 且值为该来源本身
   （不是 ``*``）；
3. 白名单外的来源不获得放行头；
4. 配置 ``*`` 被拒绝（视作未配置），避免任意网页读取本后端响应。

另外验证预检 ``OPTIONS`` 不携带 ``X-API-Key`` 也能成功 —— 浏览器规范禁止在
预检里带自定义头，若被鉴权中间件拦成 401，真实请求根本不会发出。
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path

from fastapi.testclient import TestClient

_ALLOWED = "http://192.168.100.173:3015"
_FOREIGN = "http://evil.example.com"


def _client(tmp_path, *, cors: str | None, api_key: str = "test-key-cors"):
    """按给定 WANWEI_CORS_ORIGINS 重建 app（中间件在导入期挂载，必须 reload）。"""
    os.environ["WANWEI_API_KEY"] = api_key
    os.environ["WANWEI_MEMORY_DB"] = str(tmp_path / "memory.db")
    os.environ["WANWEI_PLATFORM_DIR"] = str(tmp_path / "platform")
    os.environ.pop("WANWEI_PRODUCTION", None)
    if cors is None:
        os.environ.pop("WANWEI_CORS_ORIGINS", None)
    else:
        os.environ["WANWEI_CORS_ORIGINS"] = cors

    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    import backend.app.init_db
    import backend.app.main as main_mod

    importlib.reload(main_mod)
    backend.app.init_db.main()
    return TestClient(main_mod.app, raise_server_exceptions=False)


def _cleanup():
    os.environ.pop("WANWEI_CORS_ORIGINS", None)


def test_no_cors_header_when_unset(tmp_path):
    """未配置 → 不放行任何跨源，响应里没有 ACAO 头。"""
    try:
        client = _client(tmp_path, cors=None)
        res = client.get("/health", headers={"Origin": _ALLOWED})
        assert res.status_code == 200
        assert "access-control-allow-origin" not in res.headers
    finally:
        _cleanup()


def test_allowed_origin_is_echoed_not_wildcard(tmp_path):
    """白名单命中 → ACAO 回显该来源本身，而不是通配符。"""
    try:
        client = _client(tmp_path, cors=_ALLOWED)
        res = client.get("/health", headers={"Origin": _ALLOWED})
        assert res.status_code == 200
        assert res.headers["access-control-allow-origin"] == _ALLOWED
        assert res.headers["access-control-allow-origin"] != "*"
    finally:
        _cleanup()


def test_foreign_origin_is_not_allowed(tmp_path):
    """白名单外的来源 → 不获得放行头（浏览器侧即被拦下）。"""
    try:
        client = _client(tmp_path, cors=_ALLOWED)
        res = client.get("/health", headers={"Origin": _FOREIGN})
        assert "access-control-allow-origin" not in res.headers
    finally:
        _cleanup()


def test_wildcard_configuration_is_refused(tmp_path):
    """配置 '*' → 按未配置处理，不得放行任意来源。"""
    try:
        client = _client(tmp_path, cors="*")
        res = client.get("/health", headers={"Origin": _FOREIGN})
        assert "access-control-allow-origin" not in res.headers
    finally:
        _cleanup()


def test_preflight_succeeds_without_api_key(tmp_path):
    """预检不带 X-API-Key 也要 2xx —— 否则真实请求永远发不出去。"""
    try:
        client = _client(tmp_path, cors=_ALLOWED)
        res = client.options(
            "/platform/mobile/list",
            headers={
                "Origin": _ALLOWED,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "x-api-key",
            },
        )
        assert res.status_code < 300
        assert res.headers["access-control-allow-origin"] == _ALLOWED
        assert "x-api-key" in res.headers.get(
            "access-control-allow-headers", ""
        ).lower()
    finally:
        _cleanup()


def test_real_request_still_requires_api_key(tmp_path):
    """跨源放行不等于免鉴权：真实请求缺 key 仍是 401。"""
    try:
        client = _client(tmp_path, cors=_ALLOWED)
        res = client.get("/platform/mobile/list", headers={"Origin": _ALLOWED})
        assert res.status_code == 401
    finally:
        _cleanup()
