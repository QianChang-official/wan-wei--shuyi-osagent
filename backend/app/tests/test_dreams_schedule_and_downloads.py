"""梦境每日归档调度 + 系统服务真实化（镜像下载 / 语音转写）回归测试。

覆盖：
- A. ``/memory/dreams/schedule``：PUT 持久化 enabled/time（HH:MM，默认
  03:00），GET 返回 enabled/time/last_run/next_run 全部真实计算；注入
  时钟（tick 的 now 参数）覆盖 到点触发 / 同日不重复 / enabled=false
  不触发 / 宕机跨点当天补跑一次、跨天不补。
- B. 模拟器镜像下载：未配置 WANWEI_EMULATOR_IMAGE_URL 时保持模拟推进
  行为与 simulated:true 标注一字不改；配置后 httpx 流式真实下载到
  data/platform/downloads/（本地文件服务器实测）、进度按真实字节/
  Content-Length 推进、SHA256 不匹配报错、cancel 真正中断、SSRF 照拦。
- C. 语音转写：未配置 WANWEI_ASR_* 保持「仅存档」stub 一字不改；配置
  后对已存档音频发 OpenAI 兼容 multipart POST（monkeypatch httpx.Client
  收包断言字段），失败时如实降级为仅存档，API key 绝不落盘。

诚实红线：未配置 env 的路径行为与标注必须与改动前逐字一致。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]

_H = {"x-api-key": "test-key"}
_UTC = timezone.utc

# 合法 WAV 文件头样本（过魔数校验）
_WAV = b"RIFF" + b"\x24\x00\x00\x00" + b"WAVE" + b"fmt " + b"\x00" * 16


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


@pytest.fixture(autouse=True)
def _clean_capability_env(monkeypatch):
    """本批能力 env 默认全部未配置（诚实红线基线，防测试间泄漏）。"""
    for var in (
        "WANWEI_EMULATOR_IMAGE_URL",
        "WANWEI_EMULATOR_IMAGE_SHA256",
        "WANWEI_ASR_BASE_URL",
        "WANWEI_ASR_API_KEY",
        "WANWEI_ASR_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)


def _isolate_platform(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WANWEI_PLATFORM_DIR", str(tmp_path / "platform"))
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(tmp_path / "memory.db"))


def _runtime():
    from backend.app.platform_api import system_svc  # shim 别名到 _system_svc_runtime

    return system_svc


def _mc():
    from backend.app.platform_api import memory_center

    return memory_center


def _client(tmp_path, monkeypatch):
    """隔离的 TestClient（平台 JSON 与 SQLite DB 均落在 tmp_path）。"""
    _isolate_platform(monkeypatch, tmp_path)
    os.environ["WANWEI_API_KEY"] = "test-key"
    os.environ.pop("WANWEI_PRODUCTION", None)

    import importlib

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    import backend.app.init_db
    import backend.app.app_runtime as runtime_mod
    import backend.app.main as main_mod

    importlib.reload(runtime_mod)
    importlib.reload(main_mod)
    backend.app.init_db.main()
    from fastapi.testclient import TestClient

    return TestClient(main_mod.app, raise_server_exceptions=False)


def _wait_until(fn, timeout: float = 10.0, interval: float = 0.05):
    """轮询直到 fn() 返回真值；超时返回最后一次取值（通常为假值）。"""
    deadline = time.monotonic() + timeout
    value = fn()
    while not value and time.monotonic() < deadline:
        time.sleep(interval)
        value = fn()
    return value


# ---------------------------------------------------------------------------
# A. dreams 调度：默认状态 / PUT 持久化 / 注入时钟 tick 语义
# ---------------------------------------------------------------------------


def test_schedule_default_state_disabled(tmp_path, monkeypatch):
    """默认（从未配置）保持诚实占位语义：disabled/manual/无 next_run。"""
    _isolate_platform(monkeypatch, tmp_path)
    mc = _mc()
    view = mc._schedule_view(now=datetime(2026, 8, 24, 12, 0, tzinfo=_UTC))
    assert view["enabled"] is False
    assert view["mode"] == "manual"
    assert view["time"] == "03:00"
    assert view["last_run"] == ""
    assert view["next_run"] is None


def test_schedule_put_persists_and_next_run_real(tmp_path, monkeypatch):
    """PUT 持久化 enabled/time 且保留 last_run；GET next_run 真实现算。"""
    _isolate_platform(monkeypatch, tmp_path)
    mc = _mc()

    mc._schedule_store.set(mc._SCHEDULE_KEY, {
        "enabled": False, "time": "03:00", "last_run": "2026-08-23T03:00:05Z",
    })
    mc.put_dream_schedule(mc.SchedulePut(enabled=True, time="04:30"))

    # last_run 未被覆盖
    before = mc._schedule_view(now=datetime(2026, 8, 24, 2, 0, tzinfo=_UTC))
    assert before["enabled"] is True and before["mode"] == "scheduled"
    assert before["time"] == "04:30"
    assert before["last_run"] == "2026-08-23T03:00:05Z"
    assert before["next_run"] == "2026-08-24T04:30:00Z"

    # 当日已过点 → next_run 翻到明天
    after = mc._schedule_view(now=datetime(2026, 8, 24, 5, 0, tzinfo=_UTC))
    assert after["next_run"] == "2026-08-25T04:30:00Z"

    # 关闭后 next_run 归 None
    mc.put_dream_schedule(mc.SchedulePut(enabled=False))
    off = mc._schedule_view(now=datetime(2026, 8, 24, 2, 0, tzinfo=_UTC))
    assert off["enabled"] is False and off["next_run"] is None


def test_schedule_time_validation_rejects_bad_formats(tmp_path, monkeypatch):
    """非法 HH:MM 一律拒绝（pydantic 校验层 + 兜底解析层双闸）。"""
    _isolate_platform(monkeypatch, tmp_path)
    mc = _mc()
    from pydantic import ValidationError

    for bad in ("24:00", "3:00", "03:60", "0300", ""):
        with pytest.raises(ValidationError):
            mc.SchedulePut(enabled=True, time=bad)

    # 「03:00\n」strip 后合法：validator 归一化接受而非拒绝
    accepted = mc.SchedulePut(enabled=True, time="03:00\n")
    assert accepted.time == "03:00"


def test_tick_fires_at_due_and_writes_last_run(tmp_path, monkeypatch):
    _isolate_platform(monkeypatch, tmp_path)
    mc = _mc()
    # 冻结模块级时钟：dream_archive_now 的「夜」基准经 utc_now() 取钟，
    # 与注入 tick 的 now 同源后断言不随真实日期漂移（跨日运行依旧稳定）。
    monkeypatch.setattr(
        mc, "utc_now", lambda: datetime(2026, 8, 24, 3, 0, 5, tzinfo=_UTC),
    )
    mc._schedule_store.set(mc._SCHEDULE_KEY, {
        "enabled": True, "time": "03:00", "last_run": "",
    })

    # 未到点不触发
    early = mc.dream_schedule_tick(now=datetime(2026, 8, 24, 2, 59, 0, tzinfo=_UTC))
    assert early is None
    assert mc._read_dreams() == []

    # 到点触发一次，night 为执行当天，last_run 与注入时钟同源
    result = mc.dream_schedule_tick(now=datetime(2026, 8, 24, 3, 0, 5, tzinfo=_UTC))
    assert result is not None and result["ok"] is True
    assert result["entry"]["night"] == "2026-08-24"
    cfg = mc._read_schedule_cfg()
    assert cfg["last_run"].startswith("2026-08-24T03:00:05")
    assert len(mc._read_dreams()) == 1


def test_tick_same_day_no_repeat(tmp_path, monkeypatch):
    """同日已跑过不再触发（重启/多次扫描幂等）。"""
    _isolate_platform(monkeypatch, tmp_path)
    mc = _mc()
    monkeypatch.setattr(
        mc, "utc_now", lambda: datetime(2026, 8, 24, 3, 1, tzinfo=_UTC),
    )
    mc._schedule_store.set(mc._SCHEDULE_KEY, {
        "enabled": True, "time": "03:00", "last_run": "",
    })
    first = mc.dream_schedule_tick(now=datetime(2026, 8, 24, 3, 1, tzinfo=_UTC))
    assert first is not None
    second = mc.dream_schedule_tick(now=datetime(2026, 8, 24, 23, 0, tzinfo=_UTC))
    assert second is None
    assert len(mc._read_dreams()) == 1


def test_tick_disabled_is_noop(tmp_path, monkeypatch):
    """enabled=false 协程空转零副作用：不归档、不写 last_run。"""
    _isolate_platform(monkeypatch, tmp_path)
    mc = _mc()
    mc._schedule_store.set(mc._SCHEDULE_KEY, {
        "enabled": False, "time": "03:00", "last_run": "",
    })
    result = mc.dream_schedule_tick(now=datetime(2026, 8, 24, 9, 0, tzinfo=_UTC))
    assert result is None
    assert mc._read_dreams() == []
    assert mc._read_schedule_cfg()["last_run"] == ""


def test_tick_restart_catch_up_same_day_only(tmp_path, monkeypatch):
    """宕机跨过当日时刻：当天内补跑一次；跨天不回填昨夜的错过。"""
    _isolate_platform(monkeypatch, tmp_path)
    mc = _mc()

    # dream_archive_now 本体经 utc_now()（真实时钟）定「夜」基准；冻结
    # 模块级时钟使其与注入 tick 的时钟同源，night 断言方可完全确定。
    frozen = {"now": datetime(2026, 8, 24, 9, 30, tzinfo=_UTC)}
    monkeypatch.setattr(mc, "utc_now", lambda: frozen["now"])

    # 场景一：昨天跑过，今天进程跨过 03:00 后重启 → 补跑今天这一次
    mc._schedule_store.set(mc._SCHEDULE_KEY, {
        "enabled": True, "time": "03:00", "last_run": "2026-08-23T03:00:02Z",
    })
    fired = mc.dream_schedule_tick(now=datetime(2026, 8, 24, 9, 30, tzinfo=_UTC))
    assert fired is not None and fired["entry"]["night"] == "2026-08-24"
    assert mc.dream_schedule_tick(now=datetime(2026, 8, 24, 10, 0, tzinfo=_UTC)) is None

    # 场景二（冻结钟同步翻到 08-25）：昨晚完全宕机（无 last_run），今晨
    # 01:00 重启 → 昨夜不补，等今天的 03:00 过点后才跑（night 基准始终
    # 是执行当天）
    frozen["now"] = datetime(2026, 8, 25, 3, 0, 1, tzinfo=_UTC)
    mc._schedule_store.set(mc._SCHEDULE_KEY, {
        "enabled": True, "time": "03:00", "last_run": "",
    })
    missed = mc.dream_schedule_tick(now=datetime(2026, 8, 25, 1, 0, tzinfo=_UTC))
    assert missed is None
    caught_up = mc.dream_schedule_tick(now=datetime(2026, 8, 25, 3, 0, 1, tzinfo=_UTC))
    assert caught_up is not None and caught_up["entry"]["night"] == "2026-08-25"


def test_dream_schedule_http_roundtrip_and_validation(tmp_path, monkeypatch):
    """HTTP 层：PUT→GET 回显真实计算；非法 time / 未知字段 → 422。"""
    client = _client(tmp_path, monkeypatch)

    r = client.put(
        "/platform/memory/dreams/schedule",
        json={"enabled": True, "time": "04:30"},
        headers=_H,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    assert body["mode"] == "scheduled"
    assert body["time"] == "04:30"
    assert body["next_run"].endswith("Z")

    got = client.get("/platform/memory/dreams/schedule", headers=_H)
    assert got.status_code == 200, got.text
    assert got.json()["enabled"] is True
    assert got.json()["time"] == "04:30"
    assert got.json()["last_run"] == ""

    bad_time = client.put(
        "/platform/memory/dreams/schedule",
        json={"enabled": True, "time": "25:99"},
        headers=_H,
    )
    assert bad_time.status_code == 422, bad_time.text

    extra_field = client.put(
        "/platform/memory/dreams/schedule",
        json={"enabled": True, "time": "03:00", "cron": "* * * * *"},
        headers=_H,
    )
    assert extra_field.status_code == 422, extra_field.text

    # 关闭恢复 manual 语义
    off = client.put(
        "/platform/memory/dreams/schedule",
        json={"enabled": False},
        headers=_H,
    )
    assert off.status_code == 200, off.text
    assert off.json()["mode"] == "manual"


# ---------------------------------------------------------------------------
# B. 镜像下载真实化：本地文件服务器实测 / SHA256 / cancel / SSRF / 模拟保留
# ---------------------------------------------------------------------------


class _FileHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):  # noqa: N802 —— stdlib Handler 命名约定
        payload = self.server.ww_payload
        chunk = self.server.ww_chunk_size
        delay = self.server.ww_chunk_delay
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            for i in range(0, len(payload), chunk):
                self.wfile.write(payload[i:i + chunk])
                self.wfile.flush()
                if delay:
                    time.sleep(delay)
        except (BrokenPipeError, ConnectionError):
            pass  # cancel 测试中客户端主动断开属预期

    def log_message(self, *args):  # 静音测试输出
        pass


@pytest.fixture
def file_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FileHandler)
    server.ww_payload = b""
    server.ww_chunk_size = 64 * 1024
    server.ww_chunk_delay = 0.0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def pinned_loopback(monkeypatch):
    """把 resolve_external_url 替换为「校验即通过并 pin 到 URL 主机」。

    本地 127.0.0.1 文件服务器本身在 SSRF 黑名单内，这里只放行解析步骤，
    其余 hardened 逻辑（pinned 连接、trust_env=False）仍走真实代码路径；
    返回调用记录以便断言确实经过了该闸门。
    """
    rt = _runtime()
    calls: list[str] = []

    def fake_resolve(url, allowlist=None):
        calls.append(url)
        return url, urlparse(url).hostname

    monkeypatch.setattr(rt, "resolve_external_url", fake_resolve)
    return calls


def _downloads_dir(tmp_path) -> Path:
    return tmp_path / "platform" / "downloads"


def _rec(did: str):
    return _runtime()._load_downloads().get(did)


def _wait_status(did: str, status: str, timeout: float = 10.0):
    """轮询直到下载记录到达指定状态；返回记录本体（超时返回 None）。"""

    def probe():
        rec = _rec(did) or {}
        return rec if rec.get("status") == status else None

    return _wait_until(probe, timeout=timeout)


def test_emulator_unconfigured_stays_simulated_verbatim(tmp_path, monkeypatch):
    """未配置 env：模拟行为与标注一字不改（诚实红线）。"""
    _isolate_platform(monkeypatch, tmp_path)
    rt = _runtime()
    did = "kylin-v11-x86_64-qemu"

    resp = rt.emulator_download_start(did)
    try:
        assert resp["simulated"] is True
        assert resp["note"] == "模拟下载已启动：每 0.5s 推进 2%，不真实拉取大文件"

        # 下载目录不应被创建（模拟模式不落盘）
        assert not _downloads_dir(tmp_path).exists()

        # 模拟推进仍然工作
        def progress_reached():
            rec = _rec(did) or {}
            return rec if int(rec.get("progress", 0) or 0) >= 4 else None

        rec = _wait_until(progress_reached)
        assert rec and rec["status"] == "downloading" and rec["simulated"] is True

        # 重复 start 幂等文案逐字保持
        again = rt.emulator_download_start(did)
        assert again["note"] == "已在模拟下载中"
    finally:
        # 无论断言成败都必须停掉模拟线程：泄漏线程会在 monkeypatch 恢复
        # 共享 WANWEI_PLATFORM_DIR 后继续向「当时 env 指向的目录」推进进度，
        # 污染同进程后续用例（曾致 success_with_progress 的 total_bytes
        # KeyError 假失败）。
        cancelled = rt.emulator_download_cancel(did)

    # cancel 文案逐字保持
    assert cancelled["status"] == "idle"
    assert cancelled["note"] == "已取消（进度保留，可继续）"


def test_emulator_real_download_success_with_progress(tmp_path, monkeypatch, file_server, pinned_loopback):
    """配置 env：httpx 流式真实下载、进度按真实字节/Content-Length 推进、原子落盘。"""
    _isolate_platform(monkeypatch, tmp_path)
    payload = (b"\x89QEMU" + bytes(range(256)) * 4096) * 2  # ~2MB 非平凡内容
    file_server.ww_payload = payload
    file_server.ww_chunk_size = 64 * 1024
    file_server.ww_chunk_delay = 0.03  # 放慢以观察中间进度
    url = f"http://127.0.0.1:{file_server.server_address[1]}/kylin-v11.qcow2"
    monkeypatch.setenv("WANWEI_EMULATOR_IMAGE_URL", url)
    monkeypatch.setenv("WANWEI_EMULATOR_IMAGE_SHA256", hashlib.sha256(payload).hexdigest())

    rt = _runtime()
    did = "kylin-v11-x86_64-qemu"
    resp = rt.emulator_download_start(did)
    assert resp["simulated"] is False, resp.get("note")
    assert "真实下载已启动" in resp["note"]
    assert len(pinned_loopback) == 1  # 确实经过 resolve_external_url 闸门

    # 中间进度：真实字节推进且不超过 Content-Length
    def mid_progress():
        rec = _rec(did) or {}
        progress = int(rec.get("progress", 0) or 0)
        return rec if 0 < progress < 100 else None

    mid = _wait_until(mid_progress, timeout=8.0)
    assert mid is not None, f"未观察到中间进度：{_rec(did)}"
    assert mid["total_bytes"] == len(payload)
    assert 0 < mid["received_bytes"] <= len(payload)

    done = _wait_status(did, "done", timeout=15.0)
    assert done, f"下载未完成：{_rec(did)}"
    assert done["progress"] == 100
    assert done["received_bytes"] == len(payload)
    assert done["sha256_verified"] is True
    assert done["simulated"] is False

    final_file = _downloads_dir(tmp_path) / "kylin-v11.qcow2"
    assert final_file.is_file()
    assert final_file.read_bytes() == payload
    assert not list(_downloads_dir(tmp_path).glob("*.part"))  # 原子改名无残留

    # 完成后重复 start 幂等
    again = rt.emulator_download_start(did)
    assert again["status"] == "done"
    assert again["note"] == "镜像文件已真实下载完成，无需重复开始"


def test_emulator_real_download_sha256_mismatch_fails(tmp_path, monkeypatch, file_server, pinned_loopback):
    """SHA256 不匹配：标 error、丢弃内容、不留最终文件与 .part。"""
    _isolate_platform(monkeypatch, tmp_path)
    payload = b"authentic-image-bytes" * 1024
    file_server.ww_payload = payload
    url = f"http://127.0.0.1:{file_server.server_address[1]}/img.qcow2"
    monkeypatch.setenv("WANWEI_EMULATOR_IMAGE_URL", url)
    wrong_sha = hashlib.sha256(b"tampered").hexdigest()
    assert wrong_sha != hashlib.sha256(payload).hexdigest()
    monkeypatch.setenv("WANWEI_EMULATOR_IMAGE_SHA256", wrong_sha)

    rt = _runtime()
    did = "ubuntukylin-2404-amd64-vm"
    rt.emulator_download_start(did)

    failed = _wait_status(did, "error")
    assert failed, f"未进入 error：{_rec(did)}"
    assert "SHA256" in failed["note"]
    assert failed["simulated"] is False
    # 状态置 error 与 finally 块清理 .part 之间存在竞态窗口（产品代码先标
    # error 后在 finally unlink）；等待清理完成后再断言全空，与 cancel 测试
    # 同款 _wait_until 口径，避免 Windows 上 .part 句柄延迟释放导致误红。
    cleaned = _wait_until(lambda: not list(_downloads_dir(tmp_path).glob("*")), timeout=5.0)
    assert cleaned, f"下载目录未清空：{list(_downloads_dir(tmp_path).glob('*'))}"


def test_emulator_cancel_interrupts_real_download(tmp_path, monkeypatch, file_server, pinned_loopback):
    """cancel 真正中断：状态回 idle、清理 .part、不产生最终文件。"""
    _isolate_platform(monkeypatch, tmp_path)
    file_server.ww_payload = b"x" * (16 * 1024 * 1024)
    file_server.ww_chunk_size = 128 * 1024
    file_server.ww_chunk_delay = 0.05  # ~6.4s，足够在完成前取消
    url = f"http://127.0.0.1:{file_server.server_address[1]}/big.img"
    monkeypatch.setenv("WANWEI_EMULATOR_IMAGE_URL", url)

    rt = _runtime()
    did = "kylin-v10-sp3-arm64-qemu"
    rt.emulator_download_start(did)

    started = _wait_until(lambda: (_rec(did) or {}).get("received_bytes", 0) > 0, timeout=8.0)
    assert started, "下载未产生任何字节"

    cancelled = rt.emulator_download_cancel(did)
    assert cancelled["status"] == "idle"
    assert cancelled["note"] == "已取消（真实下载已中断，重新开始将从头下载）"

    gone = _wait_until(lambda: not list(_downloads_dir(tmp_path).glob("*.part")), timeout=5.0)
    assert gone, ".part 残留未被清理"
    assert not list(_downloads_dir(tmp_path).glob("*.img"))
    # 取消后再 GET 不应被误判为「重启丢线程」error
    assert _rec(did)["status"] == "idle"


def test_emulator_real_url_still_ssrf_checked(tmp_path, monkeypatch):
    """即使 env 配置了 loopback 地址，SSRF 闸门依旧拦截（fail-closed）。"""
    _isolate_platform(monkeypatch, tmp_path)
    monkeypatch.setenv("WANWEI_EMULATOR_IMAGE_URL", "http://127.0.0.1:9/img.qcow2")

    rt = _runtime()
    did = "kylin-v11-x86_64-qemu"
    rt.emulator_download_start(did)

    failed = _wait_status(did, "error")
    assert failed, f"未进入 error：{_rec(did)}"
    assert "SSRF" in failed["note"]
    assert not _downloads_dir(tmp_path).exists() or not list(_downloads_dir(tmp_path).glob("*"))


# ---------------------------------------------------------------------------
# C. 语音转写真实化：multipart 字段断言 / 失败诚实降级 / stub 逐字保持
# ---------------------------------------------------------------------------


class _FakeASRResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:  # noqa: F811 - mock HTTP 响应方法，有意遮蔽模块级 import json
        return self._payload


def _install_fake_asr_client(monkeypatch, *, status_code: int = 200, payload: dict | None = None):
    """monkeypatch httpx.Client：捕获 multipart POST 全部字段。"""
    captured: dict = {}

    class Client:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def post(self, url, headers=None, files=None, data=None, extensions=None):
            captured.update(
                url=url, headers=headers or {}, files=files, data=data,
                extensions=extensions,
            )
            return _FakeASRResponse(status_code, payload if payload is not None else {})

    monkeypatch.setattr(httpx, "Client", Client)
    return captured


def test_voice_unconfigured_stub_note_verbatim(tmp_path, monkeypatch):
    """未配置 ASR：响应与落盘记录逐字保持既有 stub 标注。"""
    _isolate_platform(monkeypatch, tmp_path)
    rt = _runtime()
    legacy_note = "转写待配置语音识别 provider，当前仅存档"

    resp = rt.voice_save(rt.VoiceIn(audio_b64=_b64(_WAV), mime="audio/wav"))
    assert resp["transcription"] is None
    assert resp["note"] == legacy_note
    assert resp["stub"] is True

    history = rt.voice_list()
    assert len(history) == 1
    assert history[0]["note"] == legacy_note
    assert history[0]["stub"] is True
    assert history[0]["transcription"] is None


def test_voice_asr_multipart_fields_and_backfill(tmp_path, monkeypatch):
    """配置 ASR：OpenAI 兼容 multipart 字段齐全，转写文本回填、标注转真实。"""
    _isolate_platform(monkeypatch, tmp_path)
    monkeypatch.setenv("WANWEI_ASR_BASE_URL", "https://asr.example.com/v1")
    monkeypatch.setenv("WANWEI_ASR_API_KEY", "sk-asr-secret-123")
    monkeypatch.setenv("WANWEI_ASR_MODEL", "my-whisper")

    captured = _install_fake_asr_client(monkeypatch, payload={"text": "你好，万枢"})
    # 放行解析步骤（本地测试环境无法解析 example.com；hardened 逻辑其余照走）
    rt = _runtime()
    monkeypatch.setattr(
        rt, "resolve_external_url",
        lambda url, allowlist=None: (url, urlparse(url).hostname),
    )

    raw = _WAV + b"\x00" * 32
    resp = rt.voice_save(rt.VoiceIn(audio_b64=_b64(raw), mime="audio/wav"))

    # 请求要素：URL / 鉴权头 / Host / model / multipart 文件
    assert captured["url"] == "https://asr.example.com/v1/audio/transcriptions"
    assert captured["headers"]["Authorization"] == "Bearer sk-asr-secret-123"
    assert captured["headers"]["Host"] == "asr.example.com"
    assert captured["data"] == {"model": "my-whisper"}
    (filename, content, content_type) = captured["files"]["file"]
    assert filename.startswith("vo_") and filename.endswith(".wav")
    assert content == raw
    assert content_type == "audio/wav"
    client_kwargs = captured["client_kwargs"]
    assert client_kwargs["trust_env"] is False
    assert client_kwargs["follow_redirects"] is False
    assert client_kwargs["timeout"] >= 10  # 10s × MB 上限口径（小文件下限 10s）

    # 响应回填：真实标注替换 stub
    assert resp["transcription"] == "你好，万枢"
    assert resp["stub"] is False
    assert "完成真实转写" in resp["note"]

    # 落盘记录同步回填，且 API key 绝不落盘
    history = rt.voice_list()
    assert history[0]["transcription"] == "你好，万枢"
    assert history[0]["stub"] is False
    store_raw = (tmp_path / "platform" / "platform_system.json").read_text(encoding="utf-8")
    assert "sk-asr-secret-123" not in store_raw


def test_voice_asr_default_model_whisper(tmp_path, monkeypatch):
    """未设 WANWEI_ASR_MODEL 时默认 whisper-1。"""
    _isolate_platform(monkeypatch, tmp_path)
    monkeypatch.setenv("WANWEI_ASR_BASE_URL", "https://asr.example.com/v1")
    monkeypatch.setenv("WANWEI_ASR_API_KEY", "sk-asr-secret-123")
    monkeypatch.delenv("WANWEI_ASR_MODEL", raising=False)

    captured = _install_fake_asr_client(monkeypatch, payload={"text": "ok"})
    rt = _runtime()
    monkeypatch.setattr(
        rt, "resolve_external_url",
        lambda url, allowlist=None: (url, urlparse(url).hostname),
    )
    rt.voice_save(rt.VoiceIn(audio_b64=_b64(_WAV), mime="audio/wav"))
    assert captured["data"] == {"model": "whisper-1"}


def test_voice_asr_failure_degrades_to_archive_honestly(tmp_path, monkeypatch):
    """ASR 调用失败：存档不受影响、如实降级为仅存档 stub 标注。"""
    _isolate_platform(monkeypatch, tmp_path)
    monkeypatch.setenv("WANWEI_ASR_BASE_URL", "https://asr.example.com/v1")
    monkeypatch.setenv("WANWEI_ASR_API_KEY", "sk-asr-secret-123")

    _install_fake_asr_client(monkeypatch, status_code=401, payload={"error": "bad key"})
    rt = _runtime()
    monkeypatch.setattr(
        rt, "resolve_external_url",
        lambda url, allowlist=None: (url, urlparse(url).hostname),
    )

    resp = rt.voice_save(rt.VoiceIn(audio_b64=_b64(_WAV), mime="audio/wav"))
    assert resp["transcription"] is None
    assert resp["stub"] is True
    assert "转写失败" in resp["note"]
    assert "401" in resp["note"]

    # 音频本体已存档
    saved_name = Path(resp["saved_path"]).name
    assert (tmp_path / "platform" / "voice" / saved_name).is_file()
    history = rt.voice_list()
    assert len(history) == 1
    assert history[0]["stub"] is True


def test_voice_asr_network_error_note_sanitized(tmp_path, monkeypatch):
    """网络层异常：对外 note 只含异常类名，绝不携带内网 IP/URL 等细节。

    回归 CodeQL py/stack-trace-exposure（code-scanning alert #56）：修复前
    `except Exception` 分支把 str(exc) 直接插值进响应 note。
    """
    _isolate_platform(monkeypatch, tmp_path)
    monkeypatch.setenv("WANWEI_ASR_BASE_URL", "https://asr.example.com/v1")
    monkeypatch.setenv("WANWEI_ASR_API_KEY", "sk-asr-secret-123")

    leak_marker = "10.0.0.5:8443"

    class _RaisingClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def post(self, *args, **kwargs):
            raise httpx.ConnectError(
                f"All connection attempts failed to {leak_marker}"
            )

    monkeypatch.setattr(httpx, "Client", _RaisingClient)
    rt = _runtime()
    monkeypatch.setattr(
        rt, "resolve_external_url",
        lambda url, allowlist=None: (url, urlparse(url).hostname),
    )

    resp = rt.voice_save(rt.VoiceIn(audio_b64=_b64(_WAV), mime="audio/wav"))
    assert resp["transcription"] is None
    assert resp["stub"] is True
    assert "转写失败" in resp["note"]
    assert "ConnectError" in resp["note"]  # 类名可对外，便于排障
    # 细节红线：内网地址/主机名绝不进响应
    assert leak_marker not in resp["note"]
    assert "asr.example.com" not in resp["note"]
    assert "sk-asr-secret-123" not in resp["note"]


def test_voice_asr_ssrf_rejection_note_sanitized(tmp_path, monkeypatch):
    """SSRF 拦截：对外 note 为固定受控文案，不回显校验细节与目标 URL。"""
    from backend.app.security.ssrf import SSRFError

    _isolate_platform(monkeypatch, tmp_path)
    monkeypatch.setenv("WANWEI_ASR_BASE_URL", "https://asr.example.com/v1")
    monkeypatch.setenv("WANWEI_ASR_API_KEY", "sk-asr-secret-123")

    rt = _runtime()

    def _reject(url, allowlist=None):
        raise SSRFError(f"blocked by policy: {url} resolves to 169.254.169.254")

    monkeypatch.setattr(rt, "resolve_external_url", _reject)

    resp = rt.voice_save(rt.VoiceIn(audio_b64=_b64(_WAV), mime="audio/wav"))
    assert resp["stub"] is True
    assert "SSRF 防护校验" in resp["note"]
    # 细节红线：目标 URL 与解析 IP 绝不进响应
    assert "asr.example.com" not in resp["note"]
    assert "169.254.169.254" not in resp["note"]


def test_asr_timeout_formula_ten_seconds_per_mb():
    """超时上限公式：10s × ceil(MB)，小文件下限 10s。"""
    rt = _runtime()
    assert rt._asr_timeout_seconds(512 * 1024) == 10.0  # <1MB → 下限
    assert rt._asr_timeout_seconds(1024 * 1024) == 10.0  # 恰 1MB
    assert rt._asr_timeout_seconds(3 * 1024 * 1024) == 30.0
    assert rt._asr_timeout_seconds(3 * 1024 * 1024 + 1) == 40.0  # 进位
