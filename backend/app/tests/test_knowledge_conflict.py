"""知识冲突检测测试（issue #202 验收：冲突检测 / 冲突分类）。

锁定行为：
1. 四类冲突各自触发且带触发证据（fact / status / config / temporal）。
2. 无冲突情形不误报：无关主题、同 key 同值。
3. 检测优先级：K=V 冲突（fact/config）优先于状态/时效。
4. ``detect_knowledge_conflicts`` 集成层：只对同 scope 的 active/
   reinforced knowledge 记忆检测；deprecated 不参与；非 knowledge 类
   直接返回空。
"""
from __future__ import annotations

from backend.app.memory_runtime import knowledge_evolution as ke
from backend.app.memory_runtime.capsule_store import write_capsule


def test_fact_conflict_same_key_different_value():
    v = ke.classify_conflict("默认浏览器 = Chrome", "默认浏览器 = Firefox")
    assert v is not None
    assert v["type"] == "fact"
    assert v["new_value"] == "Chrome"
    assert v["old_value"] == "Firefox"
    assert v["subject"]
    assert "值不同" in v["evidence"]


def test_fact_conflict_chinese_colon_and_is():
    """K=V 抽取兼容中文冒号与「是/为」连接词。"""
    v1 = ke.classify_conflict("默认浏览器：Chrome", "默认浏览器：Firefox")
    assert v1 is not None and v1["type"] == "fact"
    v2 = ke.classify_conflict("数据库是 MySQL", "数据库为 PostgreSQL")
    assert v2 is not None and v2["type"] == "fact"
    assert v2["new_value"] == "MySQL"


def test_config_conflict_numeric_values():
    v = ke.classify_conflict("服务端口 = 9000", "服务端口 = 8080")
    assert v is not None
    assert v["type"] == "config"
    assert v["new_value"] == "9000"
    assert v["old_value"] == "8080"


def test_status_conflict_mutual_exclusion():
    v = ke.classify_conflict("服务器运行中", "服务器已停止")
    assert v is not None
    assert v["type"] == "status"
    assert "互斥" in v["evidence"]


def test_status_conflict_english():
    v = ke.classify_conflict("redis is online", "redis is offline")
    assert v is not None
    assert v["type"] == "status"


def test_temporal_conflict_override_marker():
    v = ke.classify_conflict("构建流程现在是新流程", "构建流程用旧流程")
    assert v is not None
    assert v["type"] == "temporal"
    assert "覆盖标记词" in v["evidence"]


def test_no_conflict_unrelated_topics():
    assert ke.classify_conflict("我喜欢咖啡", "服务器运行中") is None
    assert ke.classify_conflict("项目用 PostgreSQL", "会议时间是周三") is None


def test_no_conflict_same_value():
    assert ke.classify_conflict("端口 = 8080", "端口 = 8080") is None


def test_empty_text_safe():
    assert ke.classify_conflict("", "x") is None
    assert ke.classify_conflict("x", "") is None


def test_kv_priority_over_status():
    """K=V 冲突优先于状态冲突（先具体后宽泛）。"""
    v = ke.classify_conflict("服务端口 = 9000 且已启用", "服务端口 = 8080 且已禁用")
    assert v is not None and v["type"] == "config"


# ---------------------------------------------------------------------------
# 集成层：detect_knowledge_conflicts
# ---------------------------------------------------------------------------

def test_detect_conflicts_finds_active_same_scope(isolated_db):
    old = write_capsule(
        memory_class="knowledge", content={"text": "默认浏览器 = Firefox"}
    )["capsule_id"]
    new = write_capsule(
        memory_class="knowledge", content={"text": "默认浏览器 = Chrome"}
    )["capsule_id"]

    hits = ke.detect_knowledge_conflicts(new)
    assert len(hits) == 1
    assert hits[0]["capsule_id"] == old
    assert hits[0]["type"] == "fact"
    assert hits[0]["detector"] == "knowledge_v1"


def test_detect_conflicts_ignores_deprecated(isolated_db):
    """已 deprecated 的知识不在决策视野内，不参与冲突判定。"""
    old = write_capsule(
        memory_class="knowledge", content={"text": "默认浏览器 = Firefox"}
    )["capsule_id"]
    new = write_capsule(
        memory_class="knowledge", content={"text": "默认浏览器 = Chrome"}
    )["capsule_id"]
    ke.evolve_knowledge(new, old)  # old → deprecated

    later = write_capsule(
        memory_class="knowledge", content={"text": "默认浏览器 = Edge"}
    )["capsule_id"]
    # 只与 new（active）冲突；old 已 deprecated 不算
    hits = ke.detect_knowledge_conflicts(later)
    assert [h["capsule_id"] for h in hits] == [new]


def test_detect_conflicts_requires_knowledge_class(isolated_db):
    pref = write_capsule(
        memory_class="preference", content={"subject": "e", "statement": "喜欢 X"}
    )["capsule_id"]
    assert ke.detect_knowledge_conflicts(pref) == []


def test_detect_conflicts_missing_capsule(isolated_db):
    assert ke.detect_knowledge_conflicts("cap_missing") == []
