"""W03 系统服务修复的针对性回归测试。

覆盖条目：
- 02-#10  语音上传 12MB vs 5MB 口径统一（语音路由专用正文上限）+ 魔数校验
- 02-#18  saved_path 只回相对路径 + 语音 DELETE 端点
- 02-#19  沙盒 whoami/hostname/id/uname 移出白名单
- 02-#12  _SHELL_META_RE 匹配真实换行；`-` 开头参数显式校验
- 07-#5   防追踪浏览器 host-rules 逗号分隔 MAP 语法、移除无效开关、占位符约定
- 07-#10  模拟器下载落库与线程注册同锁（start 后 GET 不误判 error）
- 07-#14  浏览器规则 update 查重 409 + DELETE 端点
- 07-#19a background_image max_length 上限
- 02-#9   LAN 配对 token TTL + 一次性使用
- 02-#5   guards.root_path 目录白名单 + device 档放行审计标注
"""

from __future__ import annotations

import base64
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anyio
import pytest
from fastapi.testclient import TestClient


def _client(tmp_path, *, api_key: str = "test-key"):
    """构造隔离的 TestClient（与 test_platform_api_smoke 同模式）。"""
    os.environ["WANWEI_API_KEY"] = api_key
    os.environ["WANWEI_MEMORY_DB"] = str(tmp_path / "memory.db")
    os.environ["WANWEI_PLATFORM_DIR"] = str(tmp_path / "platform")
    os.environ.pop("WANWEI_PRODUCTION", None)

    import importlib

    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    import backend.app.init_db
    import backend.app.main as main_mod

    importlib.reload(main_mod)
    backend.app.init_db.main()
    return TestClient(main_mod.app, raise_server_exceptions=False)


_H = {"x-api-key": "test-key"}

# 各类音频文件头样本
_WEBM = b"\x1aE\xdf\xa3" + b"\x00" * 32
_WAV = b"RIFF" + b"\x24\x00\x00\x00" + b"WAVE" + b"fmt " + b"\x00" * 16
_OGG = b"OggS" + b"\x00" * 32


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


# ---------------------------------------------------------------------------
# 02-#10 / 02-#18 语音上传：魔数校验、相对 saved_path、DELETE 端点
# ---------------------------------------------------------------------------


def test_voice_save_returns_relative_path_and_magic_ok(tmp_path):
    client = _client(tmp_path)
    r = client.post(
        "/platform/system/voice",
        json={"audio_b64": _b64(_WEBM), "mime": "audio/webm", "duration_ms": 1200},
        headers=_H,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    saved = body["saved_path"]
    # 只回相对路径：不得含盘符/绝对路径
    assert saved.startswith("voice/"), saved
    assert not os.path.isabs(saved) and ":" not in saved
    # 文件真实落盘在隔离数据目录内
    assert (tmp_path / "platform" / "voice" / Path(saved).name).is_file()


def test_voice_save_rejects_magic_mismatch(tmp_path):
    client = _client(tmp_path)
    # 声明 webm，内容实为 wav 文件头 → 魔数校验拒绝
    r = client.post(
        "/platform/system/voice",
        json={"audio_b64": _b64(_WAV), "mime": "audio/webm"},
        headers=_H,
    )
    assert r.status_code == 422, r.text
    assert "文件头" in r.json()["detail"]


def test_voice_save_accepts_matching_wav_and_ogg(tmp_path):
    client = _client(tmp_path)
    for raw, mime in ((_WAV, "audio/wav"), (_OGG, "audio/ogg")):
        r = client.post(
            "/platform/system/voice",
            json={"audio_b64": _b64(raw), "mime": mime},
            headers=_H,
        )
        assert r.status_code == 200, (mime, r.text)


def test_voice_list_normalizes_legacy_absolute_path(tmp_path):
    client = _client(tmp_path)
    from backend.app.platform_api import system_svc

    # 旧数据：saved_path 为绝对路径，读取时应归一为 voice/<文件名>
    system_svc._sys_store.set("voice_history", [{
        "id": "vo_abcdef012345",
        "saved_path": "C:\\Users\\someone\\data\\platform\\voice\\vo_abcdef012345.webm",
        "mime": "audio/webm",
        "duration_ms": 1,
        "size_bytes": 10,
        "created_at": "2026-01-01T00:00:00+00:00",
    }])
    r = client.get("/platform/system/voice", headers=_H)
    assert r.status_code == 200, r.text
    (rec,) = r.json()
    assert rec["saved_path"] == "voice/vo_abcdef012345.webm"


def test_voice_delete_removes_record_and_file(tmp_path):
    client = _client(tmp_path)
    saved = client.post(
        "/platform/system/voice",
        json={"audio_b64": _b64(_WEBM), "mime": "audio/webm"},
        headers=_H,
    ).json()
    vid = saved["id"]
    file_path = tmp_path / "platform" / "voice" / Path(saved["saved_path"]).name
    assert file_path.is_file()

    r = client.delete(f"/platform/system/voice/{vid}", headers=_H)
    assert r.status_code == 200, r.text
    assert r.json()["file_deleted"] is True
    assert not file_path.exists()
    assert client.get("/platform/system/voice", headers=_H).json() == []

    # 重复删除 → 404
    assert client.delete(f"/platform/system/voice/{vid}", headers=_H).status_code == 404
    # 非法 id 形态 → 404（不得参与路径拼接）
    assert client.delete("/platform/system/voice/..%2F..%2Fevil", headers=_H).status_code == 404


def test_voice_delete_requires_api_key(tmp_path):
    client = _client(tmp_path)
    assert client.delete("/platform/system/voice/vo_abcdef012345").status_code == 401


# ---------------------------------------------------------------------------
# 02-#10 BodySizeLimitMiddleware：语音路由专用 20MB，其余路由仍 5MB
# ---------------------------------------------------------------------------


async def _body_reader_app(scope, receive, send):
    from starlette.responses import JSONResponse

    body = b""
    while True:
        message = await receive()
        if message["type"] != "http.request":
            continue
        body += message.get("body", b"")
        if not message.get("more_body", False):
            break
    response = JSONResponse({"size": len(body)})
    await response(scope, receive, send)


def _call_mw(app, path: str, body: bytes):
    from backend.app.security.input_limits import BodySizeLimitMiddleware

    mw = BodySizeLimitMiddleware(app)
    messages = [{"type": "http.request", "body": body, "more_body": False}]

    async def receive():
        if messages:
            return messages.pop(0)
        return {"type": "http.request", "body": b"", "more_body": False}

    sent = []

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [(b"content-length", str(len(body)).encode())],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }

    async def run():
        await mw(scope, receive, send)

    anyio.run(run)
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    payload = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, payload


def test_body_limit_voice_route_allows_over_5mb():
    body = b"x" * (6 * 1024 * 1024)  # 6MB：超全局 5MB，低于语音路由 20MB
    status, payload = _call_mw(_body_reader_app, "/platform/system/voice", body)
    assert status == 200
    assert json.loads(payload) == {"size": len(body)}


def test_body_limit_other_routes_still_5mb():
    body = b"x" * (6 * 1024 * 1024)
    status, payload = _call_mw(_body_reader_app, "/platform/system/settings", body)
    assert status == 413
    assert b"Request body too large" in payload


# ---------------------------------------------------------------------------
# 02-#19 / 02-#12 沙盒：指纹命令移除、真实换行拒绝、`-` 参数显式校验
# ---------------------------------------------------------------------------


def test_sandbox_fingerprint_commands_removed(tmp_path):
    client = _client(tmp_path)
    wl = client.get("/platform/system/sandbox/whitelist", headers=_H).json()
    for cmd in ("whoami", "hostname", "id", "uname", "env"):
        assert cmd not in wl["commands"], cmd
        r = client.post(
            "/platform/system/sandbox/exec",
            json={"command": cmd, "gear": "sandbox"},
            headers=_H,
        )
        assert r.status_code == 403, (cmd, r.text)


def test_sandbox_rejects_real_newline_not_literal_backslash_n(tmp_path):
    client = _client(tmp_path)
    # 真实换行 → 拒绝
    r = client.post(
        "/platform/system/sandbox/exec",
        json={"command": "echo hello\nwhoami", "gear": "sandbox"},
        headers=_H,
    )
    assert r.status_code == 403, r.text
    # 字面两字符 \n（如 echo 的转义文本）→ 不再误伤（执行与否取决于平台，状态须为 200）
    r = client.post(
        "/platform/system/sandbox/exec",
        json={"command": "echo a\\nb", "gear": "sandbox"},
        headers=_H,
    )
    assert r.status_code == 200, r.text


def test_sandbox_dash_args_explicitly_validated(tmp_path):
    client = _client(tmp_path)
    # 长选项内嵌越界路径 → 拒绝
    r = client.post(
        "/platform/system/sandbox/exec",
        json={"command": "wc --files0-from=../../etc/passwd", "gear": "sandbox"},
        headers=_H,
    )
    assert r.status_code == 403, r.text
    # 短选项内嵌路径 → 拒绝
    r = client.post(
        "/platform/system/sandbox/exec",
        json={"command": "ls -I/etc/passwd", "gear": "sandbox"},
        headers=_H,
    )
    assert r.status_code == 403, r.text
    # 常规短选项束 → 通过校验（能否执行取决于平台，状态须为 200）
    r = client.post(
        "/platform/system/sandbox/exec",
        json={"command": "ls -la", "gear": "sandbox"},
        headers=_H,
    )
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# 07-#5 / 07-#14 防追踪浏览器：启动计划语法、规则 update 查重、DELETE
# ---------------------------------------------------------------------------


def test_browser_launch_plan_uses_valid_host_rules_syntax(tmp_path):
    client = _client(tmp_path)
    r = client.post("/platform/system/browser/launch", json={}, headers=_H)
    assert r.status_code == 200, r.text
    body = r.json()
    plan = body["plan"]
    assert "--do-not-track" not in plan
    assert "--user-data-dir=<临时干净配置目录>" not in plan
    assert "--user-data-dir={tmp_profile}" in plan
    host_rules = next(p for p in plan if p.startswith("--host-rules="))
    rules_part = host_rules.removeprefix("--host-rules=")
    entries = rules_part.split(",")
    # 每条都是独立 MAP 规则，逗号分隔
    assert len(entries) == body["applied_count"] >= 1
    for entry in entries:
        assert entry.startswith("MAP ") and entry.endswith(" ~NOTFOUND"), entry
    # 预置 20 条全部生效（≤ 上限），applied_count 如实反映
    assert body["blocked_count"] == body["applied_count"]


def test_browser_rules_update_conflict_and_delete(tmp_path):
    client = _client(tmp_path)
    r1 = client.post(
        "/platform/system/browser/rules",
        json={"domain": "tracker-a.example.com", "category": "tracker"},
        headers=_H,
    )
    r2 = client.post(
        "/platform/system/browser/rules",
        json={"domain": "tracker-b.example.com", "category": "ad"},
        headers=_H,
    )
    assert r1.status_code == 200 and r2.status_code == 200
    id1, id2 = r1.json()["id"], r2.json()["id"]

    # update 改为已有域名 → 409
    r = client.put(
        f"/platform/system/browser/rules/{id2}",
        json={"domain": "tracker-a.example.com"},
        headers=_H,
    )
    assert r.status_code == 409, r.text
    # update 改为新域名 → 200
    r = client.put(
        f"/platform/system/browser/rules/{id2}",
        json={"domain": "tracker-c.example.com"},
        headers=_H,
    )
    assert r.status_code == 200, r.text
    assert r.json()["domain"] == "tracker-c.example.com"

    # DELETE → 200；重复 DELETE → 404
    r = client.delete(f"/platform/system/browser/rules/{id1}", headers=_H)
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] is True
    assert client.delete(f"/platform/system/browser/rules/{id1}", headers=_H).status_code == 404
    domains = [x["domain"] for x in client.get("/platform/system/browser/rules", headers=_H).json()]
    assert "tracker-a.example.com" not in domains


# ---------------------------------------------------------------------------
# 07-#10 模拟器下载：start 落库与线程注册同锁
# ---------------------------------------------------------------------------


def test_emulator_start_then_list_not_marked_error(tmp_path):
    client = _client(tmp_path)
    did = "kylin-v11-x86_64-qemu"
    r = client.post(f"/platform/system/emulator/downloads/{did}/start", headers=_H)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "downloading"

    # start 响应返回后线程已注册：立即 GET 不得误判「重启丢线程」标 error
    lst = client.get("/platform/system/emulator/downloads", headers=_H).json()
    rec = next(x for x in lst if x["id"] == did)
    assert rec["status"] == "downloading", rec

    # 重复 start 幂等，不起双线程
    r2 = client.post(f"/platform/system/emulator/downloads/{did}/start", headers=_H)
    assert r2.status_code == 200
    assert "已在模拟下载中" in r2.json()["note"]

    # cancel 保留进度、状态回到 idle
    r3 = client.post(f"/platform/system/emulator/downloads/{did}/cancel", headers=_H)
    assert r3.status_code == 200, r.text
    assert r3.json()["status"] == "idle"


# ---------------------------------------------------------------------------
# 07-#19a background_image 上限
# ---------------------------------------------------------------------------


def test_settings_background_image_max_length(tmp_path):
    client = _client(tmp_path)
    r = client.put(
        "/platform/system/settings",
        json={"background_image": "data:image/png;base64," + "A" * (2 * 1024 * 1024)},
        headers=_H,
    )
    assert r.status_code == 422, r.text
    r = client.put(
        "/platform/system/settings",
        json={"background_image": "data:image/png;base64,iVBORw0KGgo="},
        headers=_H,
    )
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# 02-#9 / 07-#13 LAN 配对 token：TTL + 一次性使用
# ---------------------------------------------------------------------------


def test_lan_token_one_time_use_and_ttl_fields(tmp_path):
    client = _client(tmp_path)
    r = client.post("/platform/system/lan/enable", headers=_H)
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    assert r.json()["token_ttl_s"] > 0

    status = client.get("/platform/system/lan/status", headers=_H).json()
    assert status["token_state"] == "ok"

    # 错误 token → 不匹配
    bad = client.post("/platform/system/lan/verify", json={"token": "0" * 12}, headers=_H)
    assert bad.json()["ok"] is False

    # 正确 token 首次 → 成功并即时作废
    first = client.post("/platform/system/lan/verify", json={"token": token}, headers=_H)
    assert first.status_code == 200, first.text
    assert first.json()["ok"] is True

    # 同一 token 再次 → 已使用
    second = client.post("/platform/system/lan/verify", json={"token": token}, headers=_H)
    assert second.json()["ok"] is False
    assert "已使用" in second.json()["reason"]

    # 重新 enable 换新 token 后可用
    token2 = client.post("/platform/system/lan/enable", headers=_H).json()["token"]
    assert token2 != token
    again = client.post("/platform/system/lan/verify", json={"token": token2}, headers=_H)
    assert again.json()["ok"] is True


def test_lan_token_expired_after_ttl(tmp_path):
    client = _client(tmp_path)
    token = client.post("/platform/system/lan/enable", headers=_H).json()["token"]

    # 把创建时间拨回 TTL 之前，模拟过期（旧数据迁移语义同此判定路径）
    from backend.app.platform_api import system_svc

    lan = system_svc._sys_store.get("lan")
    lan["token_created_at"] = (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat()
    system_svc._sys_store.set("lan", lan)

    r = client.post("/platform/system/lan/verify", json={"token": token}, headers=_H)
    assert r.json()["ok"] is False
    assert "过期" in r.json()["reason"]
    assert client.get("/platform/system/lan/status", headers=_H).json()["token_state"] == "expired"


# ---------------------------------------------------------------------------
# 02-#5 guards：root_path 目录白名单 + device 档放行审计
# ---------------------------------------------------------------------------


def test_validate_root_path_default_whitelist_and_sensitive(tmp_path):
    from backend.app.platform_api import guards

    # 默认白名单 = 项目根：项目根及其子目录放行
    project_root = Path(__file__).resolve().parents[3]
    assert guards.validate_root_path(project_root) == project_root.resolve()
    assert guards.validate_root_path(project_root / "data") == (project_root / "data").resolve()

    # 白名单外目录拒绝
    with pytest.raises(ValueError, match="白名单"):
        guards.validate_root_path(tmp_path)

    # 系统敏感目录即使配进白名单也拒绝
    sensitive = "C:\\Windows" if os.name == "nt" else "/etc"
    with pytest.raises(ValueError, match="敏感目录"):
        guards.validate_root_path(sensitive, allowed_roots=[sensitive])


def test_validate_root_path_env_whitelist_extends(tmp_path, monkeypatch):
    from backend.app.platform_api import guards

    monkeypatch.setenv("WANWEI_ROOT_PATH_WHITELIST", str(tmp_path))
    assert guards.validate_root_path(tmp_path / "sub") == (tmp_path / "sub").resolve()
    with pytest.raises(ValueError):
        guards.validate_root_path(Path(__file__).resolve().parents[3])


def test_require_gear_device_audit_annotation(monkeypatch):
    from backend.app.platform_api import guards

    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(guards, "_audit_record", lambda et, payload: events.append((et, payload)))

    monkeypatch.delenv("WANWEI_DEVICE_GEAR_ENABLED", raising=False)
    assert guards.require_gear("device", action="real_commit") == "device_gear_disabled"
    assert events[-1][0] == "gear_denied"

    monkeypatch.setenv("WANWEI_DEVICE_GEAR_ENABLED", "1")
    assert guards.require_gear("device", action="real_commit") is None
    assert events[-1][0] == "gear_device_allowed"
    assert events[-1][1]["action"] == "real_commit"

    # 非 device 档不触发审计
    events.clear()
    assert guards.require_gear("sandbox", action="sandbox_exec") is None
    assert events == []
