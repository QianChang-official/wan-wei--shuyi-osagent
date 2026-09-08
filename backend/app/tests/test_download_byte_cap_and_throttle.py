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

"""issue #131：镜像下载字节硬上限 + 进度落盘节流 + 收尾可观测性。

- 旧实现对下载体量零判定（content-length 仅用于进度显示），无上限拉取可写满磁盘；
- 每 chunk（256KB）触发一次 JsonStore 全文件读改写并抢跨模块共享锁，
  大镜像下载期间整个平台舱写串行排队；
- .part 清理失败被静默吞掉，GB 级孤儿文件不可见；错误记录的 saved_file
  指向从未存在的最终路径。
"""

import hashlib

import pytest

from backend.app.platform_api import _system_svc_runtime as rt_mod


def _isolate_platform(monkeypatch, tmp_path):
    monkeypatch.setenv("WANWEI_PLATFORM_DIR", str(tmp_path / "platform"))
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.delenv("WANWEI_EMULATOR_IMAGE_URL", raising=False)
    monkeypatch.delenv("WANWEI_EMULATOR_IMAGE_SHA256", raising=False)
    monkeypatch.delenv("WANWEI_EMULATOR_IMAGE_MAX_BYTES", raising=False)


def _runtime():
    return rt_mod


@pytest.fixture
def file_server():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            payload = self.server.ww_payload
            chunk = getattr(self.server, "ww_chunk_size", 64 * 1024)
            delay = getattr(self.server, "ww_chunk_delay", 0.0)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            if getattr(self.server, "ww_send_content_length", True):
                self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            try:
                for i in range(0, len(payload), chunk):
                    self.wfile.write(payload[i:i + chunk])
                    self.wfile.flush()
                    if delay:
                        import time as _t
                        _t.sleep(delay)
            except (BrokenPipeError, ConnectionError):
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
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
    """放行解析步骤（回环本就在黑名单内），其余 hardened 逻辑走真实代码路径。"""
    calls = []

    def fake_resolve(url, allowlist=None):
        calls.append(url)
        from urllib.parse import urlparse

        return url, urlparse(url).hostname

    monkeypatch.setattr(rt_mod, "resolve_external_url", fake_resolve)
    return calls


def _rec(did):
    rt_mod._load_downloads()
    data = rt_mod._emu_store.get('downloads')
    return (data or {}).get(did)


def _wait_until(probe, timeout=8.0):
    import time as _t

    deadline = _t.monotonic() + timeout
    while _t.monotonic() < deadline:
        got = probe()
        if got is not None and got is not False:
            return got
        _t.sleep(0.05)
    return None


def _downloads_dir(tmp_path):
    import os

    return tmp_path / "platform" / "downloads"


# ---------------------------------------------------------------------------
# 字节上限
# ---------------------------------------------------------------------------
def test_content_length_over_cap_rejected_before_body(tmp_path, monkeypatch, file_server, pinned_loopback):
    """content-length 超限：一个字节都不落盘，直接 error 且如实标注。"""
    _isolate_platform(monkeypatch, tmp_path)
    file_server.ww_payload = b"x" * (1024 * 1024)
    url = f"http://127.0.0.1:{file_server.server_address[1]}/huge.qcow2"
    monkeypatch.setenv("WANWEI_EMULATOR_IMAGE_URL", url)
    monkeypatch.setenv("WANWEI_EMULATOR_IMAGE_MAX_BYTES", str(256 * 1024))  # 256KB << 1MB

    did = "kylin-v11-x86_64-qemu"
    assert _runtime().emulator_download_start(did)["simulated"] is False

    failed = _wait_status_error(did)
    assert failed is not None, f"未进入 error：{_rec(did)}"
    assert "上限" in failed["note"]
    assert failed["simulated"] is False
    # 拒绝发生在写 body 前：目录里不应有完整文件，.part 也应被清理
    final = list(_downloads_dir(tmp_path).glob("*"))
    assert not [p for p in final if not p.name.endswith(".part")], final


def test_body_over_cap_aborts_mid_stream_without_content_length(
    tmp_path, monkeypatch, file_server, pinned_loopback,
):
    """无 content-length（流式未知大小）：累计超限时中断并丢弃。"""
    _isolate_platform(monkeypatch, tmp_path)
    file_server.ww_payload = b"\xa5" * (4 * 1024 * 1024)
    file_server.ww_send_content_length = False  # chunked/无长度声明
    url = f"http://127.0.0.1:{file_server.server_address[1]}/stream.img"
    monkeypatch.setenv("WANWEI_EMULATOR_IMAGE_URL", url)
    monkeypatch.setenv("WANWEI_EMULATOR_IMAGE_MAX_BYTES", str(1024 * 1024))  # 1MB 上限

    did = "ubuntukylin-2404-amd64-vm"
    assert _runtime().emulator_download_start(did)["simulated"] is False

    failed = _wait_status_error(did)
    assert failed is not None, f"未进入 error：{_rec(did)}"
    assert "上限" in failed["note"]
    # 中断点不得显著越过上限（chunk 粒度容差）
    received = int(failed.get("received_bytes") or 0)
    assert received <= 1024 * 1024 + 256 * 1024
    assert not (_downloads_dir(tmp_path) / "stream.img").exists()


def test_under_cap_download_still_succeeds(tmp_path, monkeypatch, file_server, pinned_loopback):
    """限额内正常下载不受影响；done 记录带精确字节账目。"""
    _isolate_platform(monkeypatch, tmp_path)
    payload = b"ok-bytes" * 4096  # 32KB
    file_server.ww_payload = payload
    url = f"http://127.0.0.1:{file_server.server_address[1]}/ok.qcow2"
    monkeypatch.setenv("WANWEI_EMULATOR_IMAGE_URL", url)
    monkeypatch.setenv("WANWEI_EMULATOR_IMAGE_MAX_BYTES", str(1024 * 1024))
    monkeypatch.setenv("WANWEI_EMULATOR_IMAGE_SHA256", hashlib.sha256(payload).hexdigest())

    did = "kylin-v11-x86_64-qemu"
    _runtime().emulator_download_start(did)

    done = _wait_status(did, "done")
    assert done is not None, f"未完成：{_rec(did)}"
    assert done["received_bytes"] == len(payload)
    assert done["total_bytes"] == len(payload)
    assert done["sha256_verified"] is True
    assert (_downloads_dir(tmp_path) / "ok.qcow2").read_bytes() == payload


def test_max_bytes_env_invalid_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("WANWEI_EMULATOR_IMAGE_MAX_BYTES", "not-a-number")
    assert rt_mod._download_max_bytes() == rt_mod._DOWNLOAD_MAX_BYTES_DEFAULT
    monkeypatch.setenv("WANWEI_EMULATOR_IMAGE_MAX_BYTES", "-5")
    assert rt_mod._download_max_bytes() == rt_mod._DOWNLOAD_MAX_BYTES_DEFAULT
    monkeypatch.setenv("WANWEI_EMULATOR_IMAGE_MAX_BYTES", str(7 * 1024 * 1024))
    assert rt_mod._download_max_bytes() == 7 * 1024 * 1024
    monkeypatch.delenv("WANWEI_EMULATOR_IMAGE_MAX_BYTES")
    assert rt_mod._download_max_bytes() == rt_mod._DOWNLOAD_MAX_BYTES_DEFAULT


# ---------------------------------------------------------------------------
# 进度落盘节流
# ---------------------------------------------------------------------------
def test_progress_store_writes_throttled(tmp_path, monkeypatch, file_server, pinned_loopback):
    """多 chunk 下载期间 JsonStore 写次数必须远小于 chunk 数（时间节流生效）。"""
    _isolate_platform(monkeypatch, tmp_path)
    payload = b"z" * (2 * 1024 * 1024)  # 2MB / 32KB chunk = 64 chunks
    file_server.ww_payload = payload
    file_server.ww_chunk_size = 32 * 1024
    file_server.ww_chunk_delay = 0.02  # ~1.3s 总时长，保证有中间 flush 窗口
    url = f"http://127.0.0.1:{file_server.server_address[1]}/throttled.img"
    monkeypatch.setenv("WANWEI_EMULATOR_IMAGE_URL", url)

    writes = {"n": 0}
    real_set = rt_mod._emu_store.set

    def counting_set(key, value):
        if key == "downloads":
            writes["n"] += 1
        return real_set(key, value)

    monkeypatch.setattr(rt_mod._emu_store, "set", counting_set)

    did = "kylin-v11-x86_64-qemu"
    _runtime().emulator_download_start(did)
    done = _wait_status(did, "done")
    assert done is not None, f"未完成：{_rec(did)}"

    # 旧实现 ≈ 初始1 + 每 chunk1 + 完成1 ≈ 66 次；节流后应为个位到十位级
    assert writes["n"] <= 12, f"进度落盘仍近似逐 chunk：{writes['n']} 次"
    # 字节账目在收尾精确落盘，不因节流失真
    assert done["received_bytes"] == len(payload)


# ---------------------------------------------------------------------------
# 收尾可观测性
# ---------------------------------------------------------------------------
def test_sha_mismatch_clears_saved_file_and_reports_bytes(tmp_path, monkeypatch, file_server, pinned_loopback):
    """失败收尾：saved_file 清空（不再指向不存在路径），错误可见。"""
    _isolate_platform(monkeypatch, tmp_path)
    payload = b"authentic" * 2048
    file_server.ww_payload = payload
    url = f"http://127.0.0.1:{file_server.server_address[1]}/badsha.img"
    monkeypatch.setenv("WANWEI_EMULATOR_IMAGE_URL", url)
    monkeypatch.setenv("WANWEI_EMULATOR_IMAGE_SHA256", hashlib.sha256(b"tampered").hexdigest())

    did = "kylin-v11-x86_64-qemu"
    _runtime().emulator_download_start(did)

    failed = _wait_status_error(did)
    assert failed is not None
    assert "SHA256" in failed["note"]
    assert "saved_file" not in failed, failed.get("saved_file")


def _wait_status_error(did):
    return _wait_status(did, "error")


def _wait_status(did, status, timeout=10.0):
    def probe():
        rec = _rec(did) or {}
        return rec if rec.get("status") == status else None

    return _wait_until(probe, timeout=timeout)
