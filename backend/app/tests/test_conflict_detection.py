"""写入时冲突候选检测测试 — 规则式最小实现。

锁定行为:
1. 覆盖标记词 + 共享实体 → 命中候选
2. 无覆盖标记词 → 不报警(负例防误报)
3. 无共享实体 → 不报警
4. 跨 memory_class 不参与判定
5. candidate/quarantined 等非活跃状态不参与判定
6. write_capsule 返回带 conflict_candidates 字段(向后兼容)
7. 检测失败不阻断写入(fail-open,检测是增强不是前置)
"""
from __future__ import annotations

import pytest

from backend.app.memory_runtime.conflict_detection import (
    detect_conflict_candidates,
)


def _cap(cid: str, text: str, lifecycle: str = "active", mclass: str = "preference") -> dict:
    return {
        "capsule_id": cid,
        "memory_class": mclass,
        "state": {"lifecycle": lifecycle},
        "content": {"text": text},
    }


# ---------------------------------------------------------------------------
# 纯函数判定
# ---------------------------------------------------------------------------


def test_override_marker_plus_shared_entity_hits():
    hits = detect_conflict_candidates(
        "用户的咖啡偏好改成拿铁了,不再是美式",
        [_cap("cap_old", "用户喜欢喝美式咖啡")],
    )
    assert len(hits) == 1
    assert hits[0]["capsule_id"] == "cap_old"
    assert "咖啡" in hits[0]["shared_entities"]
    assert hits[0]["detector"] == "rule_v1"


def test_no_override_marker_no_hit():
    """陈述事实(无覆盖词)即使共享实体也不判冲突 — 防误报。"""
    hits = detect_conflict_candidates(
        "用户也喜欢手冲咖啡",
        [_cap("cap_old", "用户喜欢喝美式咖啡")],
    )
    assert hits == []


def test_override_marker_without_shared_entity_no_hit():
    """有覆盖词但主题完全不同 → 不报警。"""
    hits = detect_conflict_candidates(
        "项目的数据库改成 PostgreSQL 了",
        [_cap("cap_old", "用户喜欢喝美式咖啡")],
    )
    assert hits == []


def test_english_override_markers():
    hits = detect_conflict_candidates(
        "I no longer use Vim, switched to Neovim instead",
        [_cap("cap_old", "My editor is Vim with plugins")],
    )
    assert len(hits) == 1


def test_empty_text_no_hit():
    assert detect_conflict_candidates("", [_cap("c1", "任意内容")]) == []


# ---------------------------------------------------------------------------
# 写入路径集成
# ---------------------------------------------------------------------------


def test_write_capsule_returns_conflict_candidates(isolated_db):
    from backend.app.memory_runtime.capsule_store import write_capsule

    write_capsule(memory_class="preference", content={"text": "用户喜欢喝美式咖啡"})
    r = write_capsule(
        memory_class="preference",
        content={"text": "用户的咖啡偏好改成拿铁了,不再是美式"},
    )
    assert "conflict_candidates" in r
    assert len(r["conflict_candidates"]) >= 1


def test_conflict_detection_scoped_by_memory_class(isolated_db):
    """不同 memory_class 的记忆不参与冲突判定。"""
    from backend.app.memory_runtime.capsule_store import write_capsule

    write_capsule(memory_class="knowledge", content={"text": "用户喜欢喝美式咖啡"})
    r = write_capsule(
        memory_class="preference",
        content={"text": "用户的咖啡偏好改成拿铁了,不再是美式"},
    )
    assert r["conflict_candidates"] == []


def test_conflict_detection_failure_does_not_block_write(isolated_db, monkeypatch):
    """检测异常时写入照常成功,conflict_candidates 为空(fail-open)。"""
    import backend.app.memory_runtime.conflict_detection as cd
    from backend.app.memory_runtime.capsule_store import write_capsule

    def _boom(**kwargs):
        raise RuntimeError("simulated detector failure")

    monkeypatch.setattr(cd, "find_conflict_candidates_for_write", _boom)
    r = write_capsule(memory_class="preference", content={"text": "正常写入内容"})
    assert r["capsule_id"].startswith("cap_")
    assert r["conflict_candidates"] == []
