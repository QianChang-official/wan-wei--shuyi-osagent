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

"""
Emotion-memory binding — capsule_store.py 情感写入闭环测试

验证 write_capsule(soul_id=...) 自动从 affect_state 读取情感并绑定到 capsule，
检索排序时 affective 项生效，真正闭合"情感感知记忆"的写入→存储→检索全链路。

v0.11.1 emotion-memory-binding
"""

from backend.app.memory_runtime import capsule_store as cs
from backend.app.memory_runtime import retrieval as rt
from backend.app.affect import state_machine as sm
from backend.app.affect import emotion_memory as em


def _init_soul(soul_id: str, baseline_p: float = 0.6):
    """初始化 soul_persona 和 affect_state（测试辅助）。"""
    from backend.app.db import transaction
    from backend.app.utils.datetime_utils import utc_now_iso_compact

    ts = utc_now_iso_compact()
    with transaction() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO soul_persona(soul_id, baseline_pleasure, baseline_arousal, "
            "baseline_dominance, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (soul_id, baseline_p, 0.4, 0.5, ts, ts),
        )
        conn.execute(
            "INSERT OR IGNORE INTO affect_state(soul_id, pleasure, arousal, dominance, "
            "current_mood, mood_intensity, updated_at) VALUES (?,?,?,?,?,?,?)",
            (soul_id, baseline_p, 0.4, 0.5, "calm", 0.3, ts),
        )


# ---------------------------------------------------------------------------
# 写入侧：自动绑定情感
# ---------------------------------------------------------------------------

def test_write_capsule_binds_affect_when_soul_id_provided(isolated_db):
    soul_id = "soul_test_binding"
    _init_soul(soul_id, baseline_p=0.7)

    # 触发 user_thank 情绪事件 → P 上升
    sm.transition(soul_id, "user_thank")

    # 写入 capsule，显式传 soul_id
    result = cs.write_capsule(
        memory_class="knowledge",
        content={"text": "测试情感绑定"},
        soul_id=soul_id,
    )
    capsule_id = result["capsule_id"]

    # 验证情感元数据已绑定
    cap = cs.get_capsule(capsule_id)
    assert cap is not None
    aff_meta = cap["affective_metadata"]
    assert aff_meta["soul_id"] == soul_id
    assert aff_meta["pleasure"] > 0.7  # user_thank 让 P 上升了
    assert "bound_at" in aff_meta


def test_write_capsule_without_soul_id_no_binding(isolated_db):
    # 未传 soul_id → affective_metadata 保持空
    result = cs.write_capsule(
        memory_class="knowledge",
        content={"text": "无 soul_id 的记忆"},
    )
    capsule_id = result["capsule_id"]

    cap = cs.get_capsule(capsule_id)
    assert cap["affective_metadata"] == {}


def test_write_capsule_rejected_no_binding(isolated_db):
    # policy_result=reject 的 capsule 不绑定情感（lifecycle != active）
    soul_id = "soul_rejected"
    _init_soul(soul_id)

    result = cs.write_capsule(
        memory_class="knowledge",
        content={"text": "密码是 hunter2"},  # 触发 reject
        soul_id=soul_id,
    )

    # rejected capsule 直接返回，未落库
    assert result["governance"]["policy_result"] == "reject"
    cap = cs.get_capsule(result["capsule_id"])
    assert cap is None


# ---------------------------------------------------------------------------
# 完整闭环：写入绑定 + 检索消费
# ---------------------------------------------------------------------------

def test_emotion_binding_affects_retrieval_ranking(isolated_db, monkeypatch):
    monkeypatch.setenv("WANWEI_KYLIN_NATIVE_MODE", "off")
    soul_id = "soul_full_loop"
    _init_soul(soul_id, baseline_p=0.5)

    # 两条内容相同的记忆，一条在平静状态写入，一条在高兴状态写入
    cap_calm = cs.write_capsule(
        memory_class="knowledge",
        content={"text": "工作流程文档记录"},
        soul_id=soul_id,
    )["capsule_id"]

    # 触发 user_joy 情绪事件 → P 大幅上升、mood_intensity 上升
    sm.transition(soul_id, "user_joy")

    cap_joy = cs.write_capsule(
        memory_class="knowledge",
        content={"text": "工作流程文档记录"},
        soul_id=soul_id,
    )["capsule_id"]

    # 检索：语义完全相同，情感权重高的（joy）应该排前
    results = rt.search_capsules("工作流程文档", top_k=5)
    ids = [r["capsule_id"] for r in results]

    assert cap_calm in ids and cap_joy in ids
    assert ids.index(cap_joy) < ids.index(cap_calm), \
        "高情感权重的记忆应该排在前面（affective-aware retrieval）"

    # 验证 retrieval_affective 字段透出情感分
    joy_result = next(r for r in results if r["capsule_id"] == cap_joy)
    calm_result = next(r for r in results if r["capsule_id"] == cap_calm)
    assert joy_result["retrieval_affective"] > calm_result["retrieval_affective"]


def test_emotion_binding_with_explicit_weight(isolated_db, monkeypatch):
    monkeypatch.setenv("WANWEI_KYLIN_NATIVE_MODE", "off")
    soul_id = "soul_explicit_weight"
    _init_soul(soul_id)

    # 写入两条记忆，一条用自动绑定的 affective_metadata，一条显式设置 emotional_weight
    cap_auto = cs.write_capsule(
        memory_class="knowledge",
        content={"text": "自动绑定情感元数据"},
        soul_id=soul_id,
    )["capsule_id"]

    cap_explicit = cs.write_capsule(
        memory_class="knowledge",
        content={"text": "自动绑定情感元数据"},
        soul_id=soul_id,
    )["capsule_id"]

    # 显式设置高情感权重（覆盖自动绑定的 mood_intensity）
    em.apply_emotional_weight(cap_explicit, 0.95)

    # 检索：explicit weight 应该排前（retrieval._affective_score 优先读 emotional_weight）
    results = rt.search_capsules("自动绑定", top_k=5)
    ids = [r["capsule_id"] for r in results]

    assert ids.index(cap_explicit) < ids.index(cap_auto)

    explicit_result = next(r for r in results if r["capsule_id"] == cap_explicit)
    assert explicit_result["retrieval_affective"] == 0.95
