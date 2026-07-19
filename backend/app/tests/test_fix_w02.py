"""W02 数据存储层修复回归测试。

覆盖条目：
- store.py（02-#14/03-#22）：落盘 chmod 0600 尽力收紧、模块级共享锁、
  pid+uuid 唯一临时名、损坏文件 .corrupt-<时间戳> 备份绝不静默丢数据；
- store.py mutate(fn)（06-#9）：锁内原子读-改-写一次落盘，并发不丢更新；
- knowledge.py（06-#8）：批量导入坏条目计入 skipped 不中断整批；
- knowledge.py（06-#10）：list_docs 默认 body 预览 200 字符，full=true 全文；
- knowledge.py + memory_center.py（06-#12）：UTC aware + ISO8601 带 Z 统一时间基准；
- memory_center.py（06-#6）：SessionPut.archived 与 archive/unarchive 端点行为对齐。
"""

from __future__ import annotations

import os
import stat
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def _client(tmp_path, *, api_key: str = "test-key"):
    """构造隔离的 TestClient（与 test_platform_api_smoke 同模式）。"""
    os.environ["WANWEI_API_KEY"] = api_key
    os.environ["WANWEI_MEMORY_DB"] = str(tmp_path / "memory.db")
    os.environ["WANWEI_PLATFORM_DIR"] = str(tmp_path / "platform")
    os.environ.pop("WANWEI_PRODUCTION", None)

    import importlib
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    import backend.app.init_db
    import backend.app.main as main_mod

    importlib.reload(main_mod)
    backend.app.init_db.main()
    return TestClient(main_mod.app, raise_server_exceptions=False)


def _json_store(tmp_path, monkeypatch, name: str):
    """在隔离目录下构造 JsonStore（env 惰性解析，无需 app）。"""
    monkeypatch.setenv("WANWEI_PLATFORM_DIR", str(tmp_path))
    from backend.app.platform_api.store import JsonStore

    return JsonStore(name)


# ---------------------------------------------------------------------------
# store.py：权限收紧（02-#14）
# ---------------------------------------------------------------------------


def test_write_tightens_permissions_best_effort(tmp_path, monkeypatch):
    """落盘后尽力 chmod 0600；Windows 上 chmod 仅只读位有效，断言非只读。"""
    store = _json_store(tmp_path, monkeypatch, "w02_perm")
    store.set("k", "v")
    path = tmp_path / "platform_w02_perm.json"
    assert path.exists()
    mode = stat.S_IMODE(path.stat().st_mode)
    if os.name == "nt":
        # Windows 尽力而为：0600 的实际效果是「非只读」
        assert mode & 0o200
    else:
        assert mode & 0o777 == 0o600
    assert store.get("k") == "v"


# ---------------------------------------------------------------------------
# store.py：模块级共享锁 + 唯一临时名（03-#22）
# ---------------------------------------------------------------------------


def test_lock_shared_across_instances(tmp_path, monkeypatch):
    """同名/异名实例共享同一把模块级锁，跨实例并发写被串行化。"""
    a = _json_store(tmp_path, monkeypatch, "w02_shared")
    b = _json_store(tmp_path, monkeypatch, "w02_shared")
    c = _json_store(tmp_path, monkeypatch, "w02_other")
    assert a._lock is b._lock  # noqa: SLF001 —— 锁身份即本条目修复点
    assert a._lock is c._lock  # noqa: SLF001


def test_concurrent_instances_no_lost_updates_no_tmp_left(tmp_path, monkeypatch):
    """两个实例并发写同一文件：唯一临时名不互相覆盖，共享锁不丢更新。"""
    a = _json_store(tmp_path, monkeypatch, "w02_conc")
    b = _json_store(tmp_path, monkeypatch, "w02_conc")
    errors: list[Exception] = []

    def worker(store, tag: str) -> None:
        try:
            for i in range(20):
                store.set(f"{tag}-{i}", i)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(a, "a")),
        threading.Thread(target=worker, args=(b, "b")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    data = a.all()
    assert len(data) == 40  # 两个实例的写入全部保留，未互相覆盖
    assert not list(tmp_path.glob("*.tmp"))  # 无残留临时文件


# ---------------------------------------------------------------------------
# store.py：损坏文件备份，绝不静默丢数据（03-#22）
# ---------------------------------------------------------------------------


def test_corrupt_file_quarantined_before_empty_fallback(tmp_path, monkeypatch):
    """JSON 损坏：先备份为 .corrupt-<时间戳> 再按空数据继续，后续写入不丢备份。"""
    store = _json_store(tmp_path, monkeypatch, "w02_corrupt")
    path = tmp_path / "platform_w02_corrupt.json"
    path.write_text("{ 这不是合法 JSON", encoding="utf-8")

    assert store.get("anything", "fallback") == "fallback"
    backups = list(tmp_path.glob("platform_w02_corrupt.json.corrupt-*"))
    assert len(backups) == 1
    assert "这不是合法 JSON" in backups[0].read_text(encoding="utf-8")
    # move 式备份：损坏文件已移出主路径，避免每次读取重复备份
    assert not path.exists()

    # 后续写入生成全新文件；损坏备份仍保留（数据未丢）
    store.set("k", "v")
    assert store.get("k") == "v"
    assert list(tmp_path.glob("platform_w02_corrupt.json.corrupt-*"))


def test_non_dict_json_quarantined(tmp_path, monkeypatch):
    """顶层非 dict 的合法 JSON 同样按损坏处理：备份 + 按空数据继续。"""
    store = _json_store(tmp_path, monkeypatch, "w02_nondict")
    path = tmp_path / "platform_w02_nondict.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")

    assert store.all() == {}
    backups = list(tmp_path.glob("platform_w02_nondict.json.corrupt-*"))
    assert len(backups) == 1
    assert "[1, 2, 3]" in backups[0].read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# store.py：mutate(fn) 原子读改写（06-#9）
# ---------------------------------------------------------------------------


def test_mutate_atomic_increment_under_concurrency(tmp_path, monkeypatch):
    """两实例并发 mutate 自增同一计数器：锁内读改写，最终值不丢更新。"""
    a = _json_store(tmp_path, monkeypatch, "w02_mut")
    b = _json_store(tmp_path, monkeypatch, "w02_mut")

    def bump(data: dict) -> int:
        data["n"] = data.get("n", 0) + 1
        return data["n"]

    def worker(store) -> None:
        for _ in range(50):
            store.mutate(bump)

    threads = [threading.Thread(target=worker, args=(s,)) for s in (a, b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert a.get("n") == 100


def test_mutate_passthrough_and_no_write_on_error(tmp_path, monkeypatch):
    """mutate 透传 fn 返回值；fn 抛异常时不落盘（不写半成品）。"""
    store = _json_store(tmp_path, monkeypatch, "w02_muterr")
    store.set("x", 1)

    assert store.mutate(lambda data: "透传结果") == "透传结果"
    assert store.get("x") == 1

    path = tmp_path / "platform_w02_muterr.json"
    before = path.read_bytes()

    def boom(data: dict) -> None:
        data["x"] = 999
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        store.mutate(boom)
    assert path.read_bytes() == before
    assert store.get("x") == 1


# ---------------------------------------------------------------------------
# knowledge.py：list_docs 预览 / full（06-#10）
# ---------------------------------------------------------------------------


def test_knowledge_list_body_preview_and_full(tmp_path):
    """列表默认 body 前 200 字符预览 + body_truncated 标注；full=true 全文。"""
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}
    long_body = "麒麟" * 300  # 600 字

    r = client.post(
        "/platform/knowledge/docs",
        json={"title": "长文", "body": long_body},
        headers=h,
    )
    assert r.status_code == 201, r.text
    long_id = r.json()["id"]
    r = client.post(
        "/platform/knowledge/docs",
        json={"title": "短文", "body": "短内容"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    short_id = r.json()["id"]

    # 默认：预览
    r = client.get("/platform/knowledge/docs", headers=h)
    assert r.status_code == 200, r.text
    items = {d["id"]: d for d in r.json()["items"]}
    assert len(items[long_id]["body"]) == 200
    assert items[long_id]["body_truncated"] is True
    assert items[short_id]["body"] == "短内容"
    assert items[short_id]["body_truncated"] is False

    # full=true：全文
    r = client.get("/platform/knowledge/docs?full=true", headers=h)
    assert r.status_code == 200, r.text
    items = {d["id"]: d for d in r.json()["items"]}
    assert items[long_id]["body"] == long_body
    assert items[long_id]["body_truncated"] is False

    # 单篇 GET 不受预览影响，始终全文
    r = client.get(f"/platform/knowledge/docs/{long_id}", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["body"] == long_body


# ---------------------------------------------------------------------------
# knowledge.py：批量导入坏条目不中断（06-#8）
# ---------------------------------------------------------------------------


def test_knowledge_import_skips_bad_items_without_500(tmp_path):
    """title 超 500 字（ValidationError）/非法 source/空标题均计 skipped。"""
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}
    items = [
        {"title": "正常条目一", "body": "内容一"},
        {"title": "超" * 600, "body": "标题超 500 字触发 DocCreate 校验"},
        {"title": "坏来源", "body": "source 非法", "source": "invalid-source"},
        {"title": "", "body": "空标题预检跳过"},
        {"title": "正常条目二", "body": "内容二"},
    ]
    r = client.post("/platform/knowledge/import", json={"items": items}, headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["imported"] == 2
    assert data["skipped"] == 3

    # 好条目真实入库可检索
    r = client.get("/platform/knowledge/docs?full=true", headers=h)
    titles = [d["title"] for d in r.json()["items"]]
    assert "正常条目一" in titles
    assert "正常条目二" in titles


# ---------------------------------------------------------------------------
# 时间基准统一：UTC aware + ISO8601 带 Z（06-#12）
# ---------------------------------------------------------------------------


def _assert_utc_z(ts: str) -> None:
    assert ts.endswith("Z"), f"应为 ISO8601 带 Z：{ts!r}"
    parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)


def test_memory_center_time_baseline_utc_z(tmp_path):
    """memory_center 的 updated_at/created_at/night 全部为 UTC Z 基准。"""
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}

    r = client.post(
        "/platform/memory/remember",
        json={"text": "每天早餐后喝一杯温水"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    r = client.get("/platform/memory/instructions", headers=h)
    _assert_utc_z(r.json()["updated_at"])

    r = client.post(
        "/platform/memory/phrases", json={"text": "收到，马上处理"}, headers=h
    )
    assert r.status_code == 200, r.text
    _assert_utc_z(r.json()["item"]["created_at"])

    r = client.post("/platform/memory/dreams/archive-now", headers=h)
    assert r.status_code == 200, r.text
    entry = r.json()["entry"]
    _assert_utc_z(entry["created_at"])
    assert entry["night"] == datetime.now(timezone.utc).strftime("%Y-%m-%d")


def test_knowledge_time_baseline_utc_z(tmp_path):
    """knowledge 的 created_at/updated_at 与 memory_center 同一 UTC Z 口径。"""
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}
    r = client.post(
        "/platform/knowledge/docs",
        json={"title": "时间基准", "body": "内容"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    doc = r.json()
    _assert_utc_z(doc["created_at"])
    _assert_utc_z(doc["updated_at"])


# ---------------------------------------------------------------------------
# memory_center：mutate 改写路径行为保持 + SessionPut.archived 对齐（06-#9/06-#6）
# ---------------------------------------------------------------------------


def test_remember_dedup_does_not_touch_updated_at(tmp_path):
    """去重路径无变更不刷新 updated_at（迁到 mutate 后保持旧行为）。"""
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}
    text = "每周一上午开例会"

    r = client.post("/platform/memory/remember", json={"text": text}, headers=h)
    assert r.status_code == 200, r.text
    first = client.get("/platform/memory/instructions", headers=h).json()
    assert first["count"] == 1

    r = client.post("/platform/memory/remember", json={"text": text}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["deduped"] is True
    second = client.get("/platform/memory/instructions", headers=h).json()
    assert second["count"] == 1
    assert second["updated_at"] == first["updated_at"]


def test_concurrent_remember_no_lost_lines(tmp_path):
    """并发 /remember 不再互相覆盖（锁外读改写已迁到 mutate）。"""
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}
    texts = [f"并发记忆第{i}条" for i in range(8)]
    failures: list[str] = []

    def post(text: str) -> None:
        r = client.post("/platform/memory/remember", json={"text": text}, headers=h)
        if r.status_code != 200:
            failures.append(f"{text}: {r.status_code}")

    threads = [threading.Thread(target=post, args=(t,)) for t in texts]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not failures
    lines = client.get("/platform/memory/instructions", headers=h).json()["lines"]
    for text in texts:
        assert text in lines


def test_session_archived_put_aligned_with_endpoints(tmp_path):
    """SessionPut.archived 生效（不再静默丢弃），与 archive/unarchive 行为一致。"""
    client = _client(tmp_path)
    h = {"x-api-key": "test-key"}

    from backend.app.platform_api.store import JsonStore

    JsonStore("sessions").set(
        "items",
        [
            {
                "id": "s-1",
                "title": "示例会话",
                "turns": 3,
                "updated_at": "2026-01-01T00:00:00Z",
            }
        ],
    )

    # PUT archived=true：旧行为会静默丢弃该字段，现与专用端点对齐
    r = client.put(
        "/platform/memory/sessions/s-1", json={"archived": True}, headers=h
    )
    assert r.status_code == 200, r.text
    assert r.json()["session"]["archived"] is True

    r = client.put(
        "/platform/memory/sessions/s-1", json={"archived": False}, headers=h
    )
    assert r.status_code == 200, r.text
    assert r.json()["session"]["archived"] is False

    # 专用端点行为一致
    r = client.post("/platform/memory/sessions/s-1/archive", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["session"]["archived"] is True
    r = client.post("/platform/memory/sessions/s-1/unarchive", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["session"]["archived"] is False

    # 列表读取兼容 + 诚实标注仍在
    r = client.get("/platform/memory/sessions", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "JsonStore" in data["source"]
    assert data["sessions"][0]["id"] == "s-1"

    # 不存在的会话：404
    r = client.post("/platform/memory/sessions/不存在/archive", headers=h)
    assert r.status_code == 404, r.text
