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

"""视觉语义检索测试（167 维感知嵌入 + 暴力余弦）。

覆盖：
1. 嵌入质量：确定性、归一化、同色/异色排序方向正确
2. 索引生命周期：active 写入即索引；candidate 确认后补写；遗忘即清除
3. 治理闭环：verify_deletion 第七处取证、作用域隔离
4. 延迟：宣称可复核（latency_ms 在响应里，基准用例兜底回归）
"""

from __future__ import annotations

import base64
import importlib
import io
import math
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.app.db import get_conn
from backend.app.memory_runtime.capsule_store import forget_capsules
from backend.app.memory_visual import embedding as ve
from backend.app.memory_visual import store as visual_store
from backend.app.memoryos import governance as gov
from backend.app.memoryos import lifecycle as lc


def _png(width: int = 32, height: int = 32, color=(255, 0, 0)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


def _noisy_png(color, seed: int = 7) -> bytes:
    """带噪色块：与纯色图颜色分布相近但结构不同。"""
    import random

    rng = random.Random(seed)
    img = Image.new("RGB", (32, 32), color)
    px = img.load()
    for _ in range(120):
        x, y = rng.randrange(32), rng.randrange(32)
        px[x, y] = (255, 255, 255)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _write(isolated_db, data: bytes, caption: str = "图", **kw) -> dict:
    return visual_store.write_visual_capsule(data=data, caption=caption, **kw)


# ---------------------------------------------------------------------------
# 嵌入质量
# ---------------------------------------------------------------------------


def test_embed_is_deterministic_normalized_fixed_dim(isolated_db):
    data = _noisy_png((200, 30, 30))
    a, b = ve.embed_image(data), ve.embed_image(data)
    assert a == b
    assert len(a) == ve.EMBED_DIM == 167
    assert math.isclose(math.sqrt(sum(x * x for x in a)), 1.0, rel_tol=1e-6)


def test_similar_color_ranks_above_dissimilar(isolated_db):
    _write(isolated_db, _png(color=(0, 0, 255)), "纯蓝")
    red = _write(isolated_db, _png(color=(255, 0, 0)), "纯红")
    _write(isolated_db, _png(color=(0, 255, 0)), "纯绿")

    result = ve.search_similar(query_data=_png(color=(250, 10, 10)))
    assert result["hits"], "索引为空"
    assert result["hits"][0]["asset_id"] == red["asset"]["asset_id"]
    assert result["hits"][0]["score"] > 0.99


def test_search_by_asset_id(isolated_db):
    target = _write(isolated_db, _noisy_png((10, 200, 10)), "噪点绿")
    _write(isolated_db, _png(color=(255, 255, 0)), "纯黄")
    result = ve.search_similar(query_asset_id=target["asset"]["asset_id"])
    assert result["hits"][0]["asset_id"] == target["asset"]["asset_id"]


def test_min_score_filters_tail(isolated_db):
    _write(isolated_db, _png(color=(255, 0, 0)), "红")
    _write(isolated_db, _png(color=(0, 0, 255)), "蓝")
    result = ve.search_similar(query_data=_png(color=(255, 0, 0)), min_score=0.95)
    assert len(result["hits"]) == 1


def test_query_asset_not_indexed_reports_reason(isolated_db):
    result = ve.search_similar(query_asset_id="vas_000000000000")
    assert result["hits"] == []
    assert result["reason"] == "query_asset_not_indexed"


# ---------------------------------------------------------------------------
# 索引生命周期
# ---------------------------------------------------------------------------


def test_active_write_indexes_vector(isolated_db):
    result = _write(isolated_db, _png())
    row = get_conn().execute(
        "SELECT dim FROM memory_visual_vectors WHERE asset_id=?",
        (result["asset"]["asset_id"],),
    ).fetchone()
    assert row and row["dim"] == ve.EMBED_DIM


def test_candidate_not_indexed_until_confirmed(isolated_db):
    """闸门 require_confirmation → candidate：先不索引，确认后补写。"""
    result = _write(
        isolated_db, _png(), "推断的偏好配图",
        write_intent="inferred", affects_future_behavior=True,
    )
    assert result["state"]["lifecycle"] == "candidate"
    asset_id = result["asset"]["asset_id"]
    capsule_id = result["capsule_id"]

    conn = get_conn()
    assert conn.execute(
        "SELECT COUNT(*) FROM memory_visual_vectors WHERE asset_id=?", (asset_id,)
    ).fetchone()[0] == 0
    assert ve.search_similar(query_data=_png())["hits"] == []

    lc.confirm_candidate(capsule_id)
    assert conn.execute(
        "SELECT COUNT(*) FROM memory_visual_vectors WHERE asset_id=?", (asset_id,)
    ).fetchone()[0] == 1
    hits = ve.search_similar(query_data=_png())["hits"]
    assert hits and hits[0]["asset_id"] == asset_id


def test_forget_purges_vector_and_verifies_seventh_place(isolated_db):
    result = _write(isolated_db, _png())
    capsule_id = result["capsule_id"]
    forget_capsules([capsule_id], mode="soft_delete")
    conn = get_conn()
    assert conn.execute(
        "SELECT COUNT(*) FROM memory_visual_vectors WHERE capsule_id=?",
        (capsule_id,),
    ).fetchone()[0] == 0
    verification = gov.verify_deletion(capsule_id)
    assert verification["residue"]["visual_vectors"] == 0
    assert verification["complete"] is True


def test_leftover_vector_is_detected_as_residue(isolated_db):
    result = _write(isolated_db, _png())
    capsule_id = result["capsule_id"]
    asset_id = result["asset"]["asset_id"]
    forget_capsules([capsule_id], mode="hard_delete")
    # 模拟清除失败现场：把向量行塞回去。
    get_conn().execute(
        "INSERT INTO memory_visual_vectors (asset_id, capsule_id, embedding, dim, "
        "owner_id, soul_id, updated_at) VALUES (?,?,?,?,?,?,?)",
        (asset_id, capsule_id, b"\x00" * ve.EMBED_DIM * 4, ve.EMBED_DIM,
         None, None, "2026-01-01T00:00:00Z"),
    )
    get_conn().commit()
    verification = gov.verify_deletion(capsule_id)
    assert verification["residue"]["visual_vectors"] == 1
    assert verification["complete"] is False


def test_scope_isolation(isolated_db):
    mine = _write(isolated_db, _png(color=(255, 0, 0)), "我的红图", owner_id="owner-a")
    _write(isolated_db, _png(color=(250, 5, 5)), "别人的红图", owner_id="owner-b")
    result = ve.search_similar(query_data=_png(color=(255, 0, 0)), owner_id="owner-a")
    assert [h["asset_id"] for h in result["hits"]] == [mine["asset"]["asset_id"]]


# ---------------------------------------------------------------------------
# 延迟基准（宣称值必须可复核）
# ---------------------------------------------------------------------------


def test_search_latency_at_300_assets(isolated_db):
    """300 条索引下单次检索 < 100ms（CI 冗余阈值；本机实测通常 <10ms）。"""
    for i in range(300):
        _write(
            isolated_db,
            _png(color=(i % 256, (i * 7) % 256, (i * 13) % 256)),
            f"色块{i}",
        )
    ve.search_similar(query_data=_png())  # 预热连接与 numpy
    started = time.perf_counter()
    result = ve.search_similar(query_data=_png(), top_k=10)
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert result["scanned"] == 300
    assert result["latency_ms"] >= 0
    assert elapsed_ms < 100, f"单次检索 {elapsed_ms:.1f}ms 超出 100ms 阈值"


# ---------------------------------------------------------------------------
# HTTP 端点
# ---------------------------------------------------------------------------

_SEARCH_API_KEY = "visual-search-key-0123456789ab"


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("WANWEI_API_KEY", _SEARCH_API_KEY)
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)

    from backend.app import init_db
    from backend.app import main as main_module
    from backend.app.db import close_all

    close_all()
    importlib.reload(main_module)
    init_db.main()
    return TestClient(main_module.app, raise_server_exceptions=False)


def _api_write(client: TestClient, data: bytes, caption: str) -> dict:
    response = client.post(
        "/memory/visual/write",
        headers={"x-api-key": _SEARCH_API_KEY},
        json={
            "data_base64": base64.b64encode(data).decode("ascii"),
            "caption": caption,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_api_search_by_image(client):
    red = _api_write(client, _png(color=(255, 0, 0)), "红色截图")
    _api_write(client, _png(color=(0, 0, 255)), "蓝色截图")
    response = client.post(
        "/memory/visual/search",
        headers={"x-api-key": _SEARCH_API_KEY},
        json={"data_base64": base64.b64encode(_png(color=(254, 1, 1))).decode()},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["hits"][0]["asset_id"] == red["asset"]["asset_id"]
    assert body["index"] == "brute_force_cosine"
    assert body["scanned"] == 2 and body["latency_ms"] >= 0


def test_api_search_by_asset_id(client):
    written = _api_write(client, _png(), "库内查询")
    response = client.post(
        "/memory/visual/search",
        headers={"x-api-key": _SEARCH_API_KEY},
        json={"query_asset_id": written["asset"]["asset_id"]},
    )
    assert response.status_code == 200
    assert response.json()["hits"][0]["asset_id"] == written["asset"]["asset_id"]


def test_api_search_requires_query(client):
    response = client.post(
        "/memory/visual/search",
        headers={"x-api-key": _SEARCH_API_KEY},
        json={},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "query_required"


def test_api_search_rejects_bad_image(client):
    response = client.post(
        "/memory/visual/search",
        headers={"x-api-key": _SEARCH_API_KEY},
        json={"data_base64": base64.b64encode(b"junk").decode()},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "visual_validation_failed"
