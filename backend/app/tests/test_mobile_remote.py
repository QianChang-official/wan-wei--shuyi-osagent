"""mobile_remote（手机端远程控制）API 测试：SSE 事件流 / 文件上传 / 工具调用查询。"""
import io
import importlib
import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[3]
API_KEY = "test-key"
HEADERS = {"x-api-key": API_KEY}


def _client(tmp_path):
    os.environ["WANWEI_API_KEY"] = API_KEY
    os.environ["WANWEI_MEMORY_DB"] = str(tmp_path / "memory.db")
    os.environ["WANWEI_PLATFORM_DIR"] = str(tmp_path / "platform")
    os.environ.pop("WANWEI_PRODUCTION", None)

    backend_dir = str(PROJECT_ROOT / "backend")
    for path in (backend_dir, str(PROJECT_ROOT)):
        if path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)
    import backend.app.init_db
    import backend.app.main as main_mod

    importlib.reload(main_mod)
    backend.app.init_db.main()
    return TestClient(main_mod.app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _cleanup_files(tmp_path):
    client = _client(tmp_path)
    yield client
    # 清理测试上传的文件
    try:
        items = client.get('/platform/mobile/list', headers=HEADERS).json().get('items', [])
        for it in items:
            if it.get('filename', '').startswith('mobile_test'):
                client.delete(f"/platform/mobile/{it['file_id']}", headers=HEADERS)
    except Exception:
        pass


def test_tool_calls_empty(tmp_path):
    """工具调用查询：未触发时返回空列表（结构完整）。"""
    client = _client(tmp_path)
    resp = client.get('/platform/mobile/tool-calls', headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert 'items' in body
    assert isinstance(body['items'], list)


def test_upload_and_list(tmp_path):
    """文件上传后能在列表里看到，元数据完整。"""
    client = _client(tmp_path)
    resp = client.post(
        '/platform/mobile/upload',
        headers=HEADERS,
        files={'file': ('mobile_test_1.txt', io.BytesIO('hello mobile'.encode()), 'text/plain')},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body['file_id'].startswith('file_')
    assert body['filename'] == 'mobile_test_1.txt'
    assert body['size_bytes'] == len('hello mobile')

    listed = client.get('/platform/mobile/list', headers=HEADERS).json()
    assert any(it['file_id'] == body['file_id'] for it in listed['items'])


def test_read_content_utf8(tmp_path):
    """上传文本文件后可读取内容（UTF-8 原样）。"""
    client = _client(tmp_path)
    up = client.post(
        '/platform/mobile/upload',
        headers=HEADERS,
        files={'file': ('mobile_test_2.txt', io.BytesIO('宛委枢忆测试'.encode('utf-8')), 'text/plain')},
    ).json()
    fid = up['file_id']

    content_resp = client.get(f'/platform/mobile/{fid}/content', headers=HEADERS)
    assert content_resp.status_code == 200
    body = content_resp.json()
    assert body['encoding'] == 'utf-8'
    assert body['content'] == '宛委枢忆测试'


def test_read_content_binary_base64(tmp_path):
    """上传二进制文件时返回 base64（不尝试 UTF-8 解码）。"""
    client = _client(tmp_path)
    raw = bytes(range(256))
    up = client.post(
        '/platform/mobile/upload',
        headers=HEADERS,
        files={'file': ('mobile_test_3.bin', io.BytesIO(raw), 'application/octet-stream')},
    ).json()
    fid = up['file_id']

    content_resp = client.get(f'/platform/mobile/{fid}/content', headers=HEADERS)
    assert content_resp.status_code == 200
    body = content_resp.json()
    assert body['encoding'] == 'base64'
    import base64
    assert base64.b64decode(body['content_b64']) == raw


def test_delete_file(tmp_path):
    """删除后列表里不再出现，且再次读取 404。"""
    client = _client(tmp_path)
    up = client.post(
        '/platform/mobile/upload',
        headers=HEADERS,
        files={'file': ('mobile_test_4.txt', io.BytesIO('delete me'.encode()), 'text/plain')},
    ).json()
    fid = up['file_id']

    del_resp = client.delete(f'/platform/mobile/{fid}', headers=HEADERS)
    assert del_resp.status_code == 200
    assert del_resp.json()['deleted'] == fid

    assert client.get(f'/platform/mobile/{fid}/content', headers=HEADERS).status_code == 404
    listed = client.get('/platform/mobile/list', headers=HEADERS).json()
    assert not any(it['file_id'] == fid for it in listed['items'])


def test_path_traversal_blocked(tmp_path):
    """路径穿越防护：file_id 必须先存在于 DB 白名单（../ 等非法 ID 一律 404/400）。"""
    client = _client(tmp_path)

    # 读：../../etc/passwd → 404（DB 无此 ID，路径从未进入文件系统）
    r = client.get('/platform/mobile/..%2F..%2Fetc%2Fpasswd/content', headers=HEADERS)
    assert r.status_code in (400, 404), r.text

    # 删除：带路径分隔符 → 同上
    r = client.delete('/platform/mobile/..%2Fsecret.txt', headers=HEADERS)
    assert r.status_code in (400, 404), r.text

    # 正常 ID 仍工作（上传+读取不受影响）
    up = client.post(
        '/platform/mobile/upload',
        headers=HEADERS,
        files={'file': ('mobile_test_safe.txt', io.BytesIO('safe'.encode()), 'text/plain')},
    ).json()
    assert client.get(f"/platform/mobile/{up['file_id']}/content", headers=HEADERS).status_code == 200


def test_sse_stream_emits_upload_event(tmp_path):
    """SSE 流能收到 file_upload 事件（backlog 补发机制：先上传产生事件，再连 SSE 收到重放）。"""
    client = _client(tmp_path)

    # 先上传一个文件 → 事件进环形缓冲
    client.post(
        '/platform/mobile/upload',
        headers=HEADERS,
        files={'file': ('mobile_test_5.txt', io.BytesIO('sse event'.encode()), 'text/plain')},
    )

    # 再连 SSE：backlog 机制会补发 ts > 0 的缓冲事件（收到即断开）
    received: list[str] = []
    # max_idle=1：服务端空闲后主动收流，TestClient 不会阻塞在永不结束的长连接上
    with client.stream(
        'GET', '/platform/mobile/events?since=0&max_idle=1', headers=HEADERS
    ) as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            if line.startswith('event:'):
                received.append(line[6:].strip())
            if line.startswith('data:') and 'file_upload' in line:
                break
            # 防御：backlog 补发完没匹配到就提前退出（TestClient 环境 keepalive 会挂住）
            if len(received) >= 20:
                break

    assert any('file_upload' in e for e in received)
