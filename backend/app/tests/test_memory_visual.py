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

"""视觉记忆子系统测试（VISTA 启发的无损视觉记忆）。

覆盖：
1. 写入闭环：胶囊 + 资产 BLOB + 账本 + sha256 清单
2. 入库校验：坏字节 / 动图 / 超尺寸 / 派生契约
3. VISTA 回看：inspect 区域裁剪放大、read_pixels 等分网格采样 + 调色板
4. 治理闭环：遗忘同步清除资产、verify_deletion 视觉资产与向量取证
"""

from __future__ import annotations

import base64
import hashlib
import importlib
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.app.db import get_conn
from backend.app.memory_runtime.capsule_store import (
    forget_capsules,
    get_capsule,
)
from backend.app.memoryos import governance as gov
from backend.app.memory_visual import inspect as visual_inspect
from backend.app.memory_visual import store as visual_store


def _png(width: int = 8, height: int = 8, color=(255, 0, 0)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


def _quadrant_png() -> bytes:
    """2x2 色块图：左上红、右上绿、左下蓝、右下白。"""
    img = Image.new("RGB", (4, 4))
    px = img.load()
    for y in range(4):
        for x in range(4):
            px[x, y] = (
                (255, 0, 0) if x < 2 and y < 2 else
                (0, 255, 0) if x >= 2 and y < 2 else
                (0, 0, 255) if x < 2 else
                (255, 255, 255)
            )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _write(isolated_db, data: bytes | None = None, caption: str = "一张红色方块", **kw):
    return visual_store.write_visual_capsule(
        data=data or _png(), caption=caption, **kw
    )


# ---------------------------------------------------------------------------
# 写入闭环
# ---------------------------------------------------------------------------


def test_write_visual_capsule_full_loop(isolated_db):
    data = _png(8, 8, (10, 20, 30))
    result = _write(isolated_db, data=data)

    asset = result["asset"]
    assert asset["asset_id"].startswith("vas_")
    assert asset["sha256"] == hashlib.sha256(data).hexdigest()
    assert asset["width"] == 8 and asset["height"] == 8
    assert asset["mime_type"] == "image/png"

    capsule = get_capsule(result["capsule_id"])
    assert capsule["content"]["modality"] == "visual"
    assert capsule["content"]["asset_sha256"] == asset["sha256"]

    # 账本：write + visual_attach 两笔，attach 锚定图片哈希。
    ops = [e["op_type"] for e in gov.ledger_history(result["capsule_id"], limit=10)]
    assert "write" in ops and "visual_attach" in ops

    # 字节无损取回。
    stored = visual_store.get_asset(asset["asset_id"])
    assert stored["data"] == data


def test_list_assets_without_bytes(isolated_db):
    result = _write(isolated_db)
    assets = visual_store.list_assets(result["capsule_id"])
    assert len(assets) == 1
    assert "data" not in assets[0]
    assert assets[0]["kind"] == "current"


def test_policy_reject_stores_no_asset(isolated_db):
    # caption 命中策略闸门敏感词（明文密码形态）→ reject，不落资产行。
    result = _write(isolated_db, caption='password="hunter2" 截图')
    assert result["governance"]["policy_result"] == "reject"
    assert result["asset"] is None
    count = get_conn().execute(
        "SELECT COUNT(*) FROM memory_visual_assets"
    ).fetchone()[0]
    assert count == 0


# ---------------------------------------------------------------------------
# 入库校验
# ---------------------------------------------------------------------------


def test_reject_undecodable_bytes(isolated_db):
    with pytest.raises(visual_store.VisualValidationError):
        _write(isolated_db, data=b"not an image")


def test_reject_animated_gif(isolated_db):
    buf = io.BytesIO()
    frames = [Image.new("RGB", (4, 4), c) for c in [(255, 0, 0), (0, 255, 0)]]
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:])
    with pytest.raises(visual_store.VisualValidationError, match="single-frame"):
        _write(isolated_db, data=buf.getvalue())


def test_reject_oversized_dimension(isolated_db):
    big = _png(visual_store.MAX_VISUAL_DIMENSION + 1, 1)
    with pytest.raises(visual_store.VisualValidationError, match="exceed"):
        _write(isolated_db, data=big)


def test_derived_must_name_source(isolated_db):
    with pytest.raises(visual_store.VisualValidationError, match="derived"):
        _write(isolated_db, kind="derived")
    with pytest.raises(visual_store.VisualValidationError, match="derived"):
        _write(isolated_db, derived_from=["vas_nonexistent"])


def test_derived_chain_links_existing_asset(isolated_db):
    parent = _write(isolated_db)
    child = _write(
        isolated_db,
        data=_png(4, 4, (1, 2, 3)),
        caption="红色方块的裁剪件",
        kind="derived",
        derived_from=[parent["asset"]["asset_id"]],
    )
    assert child["asset"]["derived_from"] == [parent["asset"]["asset_id"]]


# ---------------------------------------------------------------------------
# VISTA 回看：inspect / read_pixels
# ---------------------------------------------------------------------------


def test_inspect_full_view_roundtrip(isolated_db):
    data = _png(16, 8, (200, 100, 50))
    asset = _write(isolated_db, data=data)["asset"]
    result = visual_inspect.inspect_views(
        question="这张图是什么颜色？",
        views=[{"label": "full", "asset_id": asset["asset_id"]}],
    )
    view = result["views"][0]
    assert view["region"] == {"x": 0, "y": 0, "width": 16, "height": 8}
    assert view["sha256"] == asset["sha256"]
    # 放大到 display_size 目标边长（16 -> 1024，8 -> 512）。
    assert view["image_size"] == {"width": 1024, "height": 512}
    decoded = base64.b64decode(result["images"][0]["data"])
    with Image.open(io.BytesIO(decoded)) as rendered:
        assert rendered.size == (1024, 512)
        assert rendered.convert("RGB").getpixel((0, 0)) == (200, 100, 50)


def test_inspect_region_crops_exactly(isolated_db):
    asset = _write(isolated_db, data=_quadrant_png(), caption="四色块")["asset"]
    result = visual_inspect.inspect_views(
        question="右下角是什么颜色？",
        views=[{
            "label": "bottom-right",
            "asset_id": asset["asset_id"],
            "region": {"x": 2, "y": 2, "width": 2, "height": 2},
        }],
    )
    decoded = base64.b64decode(result["images"][0]["data"])
    with Image.open(io.BytesIO(decoded)) as rendered:
        # 2x2 裁剪件最近邻放大到 1024x1024，颜色必须是纯白。
        assert rendered.size == (1024, 1024)
        assert rendered.convert("RGB").getpixel((512, 512)) == (255, 255, 255)


def test_inspect_region_out_of_bounds(isolated_db):
    asset = _write(isolated_db)["asset"]
    with pytest.raises(visual_inspect.InspectionError, match="bounds"):
        visual_inspect.inspect_views(
            question="越界",
            views=[{
                "label": "bad",
                "asset_id": asset["asset_id"],
                "region": {"x": 6, "y": 0, "width": 4, "height": 4},
            }],
        )


def test_read_pixels_palette_and_samples(isolated_db):
    asset = _write(isolated_db, data=_quadrant_png(), caption="四色块")["asset"]
    result = visual_inspect.read_pixels(
        question="四个象限各是什么颜色？",
        views=[{
            "label": "grid",
            "asset_id": asset["asset_id"],
            "rows": 2,
            "columns": 2,
        }],
    )
    assert result["sampling"] == "equal-bin-centers"
    assert result["sample_count"] == 4
    samples = result["views"][0]["samples"]
    palette = result["palette"]
    # 采样网格中心命中四个象限：红 / 绿 / 蓝 / 白。
    decoded = [[palette[symbol] for symbol in row] for row in samples]
    assert decoded == [["#FF0000", "#00FF00"], ["#0000FF", "#FFFFFF"]]


def test_read_pixels_sample_budget_enforced(isolated_db):
    asset = _write(isolated_db, data=_png(100, 100))["asset"]
    with pytest.raises(visual_inspect.InspectionError, match="samples"):
        visual_inspect.read_pixels(
            question="超采样预算",
            views=[{
                "label": "too-many",
                "asset_id": asset["asset_id"],
                "rows": 100,
                "columns": 100,
            }],
        )


def test_inspect_unknown_asset(isolated_db):
    with pytest.raises(visual_inspect.InspectionError, match="not found"):
        visual_inspect.inspect_views(
            question="不存在",
            views=[{"label": "ghost", "asset_id": "vas_000000000000"}],
        )


# ---------------------------------------------------------------------------
# 治理闭环：遗忘清除 + 第六处取证
# ---------------------------------------------------------------------------


def test_soft_delete_purges_visual_assets(isolated_db):
    result = _write(isolated_db)
    capsule_id = result["capsule_id"]
    forget_capsules([capsule_id], mode="soft_delete")

    count = get_conn().execute(
        "SELECT COUNT(*) FROM memory_visual_assets WHERE capsule_id=?",
        (capsule_id,),
    ).fetchone()[0]
    assert count == 0

    verification = gov.verify_deletion(capsule_id)
    assert verification["residue"]["visual_assets"] == 0
    assert verification["complete"] is True


def test_hard_delete_visual_capsule_verifies_complete(isolated_db):
    result = _write(isolated_db)
    capsule_id = result["capsule_id"]
    outcome = forget_capsules([capsule_id], mode="hard_delete")
    assert outcome["deletion_verification"]["all_complete"] is True
    verification = gov.verify_deletion(capsule_id)
    assert verification["residue_total"] == 0
    assert verification["residue"]["visual_assets"] == 0


def test_leftover_asset_is_detected_as_residue(isolated_db):
    """遗留资产必须让取证报 incomplete——第六处不是摆设。"""
    result = _write(isolated_db)
    capsule_id = result["capsule_id"]
    asset_id = result["asset"]["asset_id"]
    forget_capsules([capsule_id], mode="soft_delete")
    # 模拟清除失败现场：把资产行塞回去。
    conn = get_conn()
    assert visual_store.get_asset(asset_id) is None  # 已清除
    conn.execute(
        "INSERT INTO memory_visual_assets (asset_id, capsule_id, sha256, width, "
        "height, mime_type, kind, derived_from, data, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (asset_id, capsule_id, "0" * 64, 8, 8, "image/png", "current", "[]",
         _png(), "2026-01-01T00:00:00Z"),
    )
    conn.commit()
    verification = gov.verify_deletion(capsule_id)
    assert verification["residue"]["visual_assets"] == 1
    assert verification["complete"] is False


def test_verify_deletion_without_visual_table(isolated_db):
    """老库无 visual 表时按 0 处理，不影响既有五处取证。"""
    result = _write(isolated_db)
    capsule_id = result["capsule_id"]
    forget_capsules([capsule_id], mode="hard_delete")
    conn = get_conn()
    conn.execute("DROP TABLE memory_visual_assets")
    conn.commit()
    verification = gov.verify_deletion(capsule_id)
    assert verification["residue"]["visual_assets"] == 0
    assert verification["complete"] is True


# ---------------------------------------------------------------------------
# HTTP 端点
# ---------------------------------------------------------------------------

_VISUAL_API_KEY = "visual-owner-key-0123456789abcdef"


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("WANWEI_API_KEY", _VISUAL_API_KEY)
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)

    from backend.app import init_db
    from backend.app import main as main_module
    from backend.app.db import close_all

    close_all()
    importlib.reload(main_module)
    init_db.main()
    return TestClient(main_module.app, raise_server_exceptions=False)


def _api_write(client: TestClient, data: bytes | None = None,
               caption: str = "一张红色方块") -> dict:
    response = client.post(
        "/memory/visual/write",
        headers={"x-api-key": _VISUAL_API_KEY},
        json={
            "data_base64": base64.b64encode(data or _png()).decode("ascii"),
            "caption": caption,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_api_write_list_inspect_read_pixels(client):
    written = _api_write(client, data=_quadrant_png(), caption="四色块图")
    asset_id = written["asset"]["asset_id"]
    capsule_id = written["capsule_id"]

    listed = client.get(
        f"/memory/visual/{capsule_id}/assets",
        headers={"x-api-key": _VISUAL_API_KEY},
    )
    assert listed.status_code == 200
    assert listed.json()["assets"][0]["asset_id"] == asset_id
    assert "data" not in listed.json()["assets"][0]

    inspected = client.post(
        "/memory/visual/inspect",
        headers={"x-api-key": _VISUAL_API_KEY},
        json={
            "question": "右下角是什么颜色？",
            "views": [{
                "label": "br",
                "asset_id": asset_id,
                "region": {"x": 2, "y": 2, "width": 2, "height": 2},
            }],
        },
    )
    assert inspected.status_code == 200, inspected.text
    assert inspected.json()["views"][0]["image_size"] == {
        "width": 1024, "height": 1024,
    }

    pixels = client.post(
        "/memory/visual/read-pixels",
        headers={"x-api-key": _VISUAL_API_KEY},
        json={
            "question": "四象限颜色？",
            "views": [{"label": "grid", "asset_id": asset_id, "rows": 2, "columns": 2}],
        },
    )
    assert pixels.status_code == 200, pixels.text
    body = pixels.json()
    decoded = [[body["palette"][s] for s in row] for row in body["views"][0]["samples"]]
    assert decoded == [["#FF0000", "#00FF00"], ["#0000FF", "#FFFFFF"]]


def test_api_write_invalid_base64_422(client):
    response = client.post(
        "/memory/visual/write",
        headers={"x-api-key": _VISUAL_API_KEY},
        json={"data_base64": "!!!not-base64!!!", "caption": "坏数据"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "invalid_base64"


def test_api_write_bad_image_422(client):
    response = client.post(
        "/memory/visual/write",
        headers={"x-api-key": _VISUAL_API_KEY},
        json={
            "data_base64": base64.b64encode(b"junk").decode("ascii"),
            "caption": "坏图",
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "visual_validation_failed"


def test_api_inspect_unknown_asset_404(client):
    response = client.post(
        "/memory/visual/inspect",
        headers={"x-api-key": _VISUAL_API_KEY},
        json={
            "question": "幽灵资产",
            "views": [{"label": "ghost", "asset_id": "vas_000000000000"}],
        },
    )
    assert response.status_code == 404


def test_api_requires_api_key(client):
    response = client.post(
        "/memory/visual/write",
        json={"data_base64": base64.b64encode(_png()).decode(), "caption": "无钥"},
    )
    assert response.status_code in {401, 403}

