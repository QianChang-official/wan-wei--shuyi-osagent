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
B1 Beta 置信度建模测试 — preference capsule 的反馈统计

覆盖设计文档 ``09-algorithm-design-framework.md`` §B1 的验收要求：

1. 纯函数层：``update_confidence`` / ``confidence`` 的收敛性与 CI 单调收窄；
2. 集成层：``evolution.reinforce()`` / ``deprecate()`` 对 preference capsule
   在成功路径上写计数键，非 preference capsule 不受影响；
3. ``reflect_task`` 的 helpful/misleading 钩子同样喂给 Beta 计数。
"""

import pytest
from backend.app.memory_runtime import capsule_store as cs
from backend.app.memory_runtime import evolution as ev
from backend.app.memory_runtime.preference_confidence import (
    ALPHA_KEY,
    BETA_KEY,
    confidence,
    update_confidence,
)
from backend.app.memoryos.lifecycle import restore


# ---------------------------------------------------------------------------
# 纯函数：Beta 后验的收敛与置信区间
# ---------------------------------------------------------------------------

def test_convergence_ten_reinforces_mean_gt_09():
    """连续 10 次 reinforce 后，后验均值收敛到 >0.9（设计文档 B1 验收线）。"""
    meta: dict = {}
    for _ in range(10):
        update_confidence(meta, "reinforce")

    posterior = confidence(meta)
    # 后验 = 先验(1,1) + 计数(10,0)
    assert posterior["alpha"] == 11
    assert posterior["beta"] == 1
    assert posterior["mean"] > 0.9


def test_ci_narrows_monotonically():
    """一致证据（全 reinforce）下样本增多，conf 单调不减。"""
    confs: list[float] = []
    meta: dict = {}
    for _ in range(15):
        update_confidence(meta, "reinforce")
        confs.append(confidence(meta)["conf"])

    assert all(b >= a for a, b in zip(confs, confs[1:]))
    assert confs[-1] > confs[0]


def test_deprecate_raises_beta_lowers_mean():
    """deprecate 抬 β 计数，使后验均值下降。"""
    meta: dict = {}
    for _ in range(5):
        update_confidence(meta, "reinforce")
    before = confidence(meta)
    assert before["beta"] == 1  # 只有先验 β₀
    assert before["mean"] > 0.8

    update_confidence(meta, "deprecate")
    after = confidence(meta)
    assert meta[BETA_KEY] == 1
    assert after["beta"] == 2
    assert after["mean"] < before["mean"]


def test_invalid_outcome_raises_valueerror():
    """非法 outcome → 抛 ValueError（不做静默 no-op）。"""
    with pytest.raises(ValueError, match="outcome"):
        update_confidence({}, "unknown")


# ---------------------------------------------------------------------------
# 集成：evolution.reinforce()/deprecate() 对 preference capsule 写计数
# ---------------------------------------------------------------------------

def test_integration_preference_reinforce_deprecate_updates_meta(isolated_db):
    """preference capsule 走 reinforce/deprecate 后，state 出现计数键。"""
    cid = cs.write_capsule(
        memory_class="preference", content={"text": "用户喜欢喝美式咖啡"}
    )["capsule_id"]

    ev.reinforce(cid)
    st = cs.get_capsule(cid)["state"]
    assert st[ALPHA_KEY] == 1
    assert st[BETA_KEY] == 0  # 只 reinforce 未 deprecate，β 保持 0

    ev.deprecate(cid)
    st = cs.get_capsule(cid)["state"]
    assert st[ALPHA_KEY] == 1
    assert st[BETA_KEY] == 1


def test_integration_non_preference_untouched(isolated_db):
    """非 preference capsule（knowledge）reinforce/deprecate 后无计数键。"""
    cid = cs.write_capsule(
        memory_class="knowledge", content={"text": "一些背景知识"}
    )["capsule_id"]

    ev.reinforce(cid)
    ev.deprecate(cid)
    st = cs.get_capsule(cid)["state"]
    assert ALPHA_KEY not in st
    assert BETA_KEY not in st


def test_integration_reinforce_after_deprecate_reaccumulates(isolated_db):
    """deprecated 不可 reinforce，需先 restore 回 active，计数仍继续累加。

    ``deprecated`` 不在 ``REINFORCEABLE_STATES``（只有 active/reinforced/stale），
    因此「reinforce → deprecate → reinforce」在状态机上是非法路径。这里走
    最短合法路径：reinforce ×1 → deprecate ×1 → restore（deprecated→active）
    → reinforce ×2，验证 α/β 计数在恢复后继续累加、lifecycle 回到 reinforced。
    """
    cid = cs.write_capsule(
        memory_class="preference", content={"text": "用户喜欢美式咖啡"}
    )["capsule_id"]

    ev.reinforce(cid)
    ev.deprecate(cid)
    restore(cid)
    ev.reinforce(cid)
    ev.reinforce(cid)

    st = cs.get_capsule(cid)["state"]
    assert st[ALPHA_KEY] == 3
    assert st[BETA_KEY] == 1
    assert st["lifecycle"] == "reinforced"


def test_integration_reflect_task_counts_preference(isolated_db):
    """reflect_task 的 helpful/misleading 钩子同样给 preference capsule 计数。"""
    pref_good = cs.write_capsule(
        memory_class="preference", content={"text": "用户喜欢美式咖啡"}
    )["capsule_id"]
    pref_bad = cs.write_capsule(
        memory_class="preference", content={"text": "用户喜欢用 Vim"}
    )["capsule_id"]

    ev.reflect_task(
        task_id="task_pref_b1",
        payload={
            "helpful_memories": [pref_good],
            "misleading_memories": [pref_bad],
        },
    )

    good_st = cs.get_capsule(pref_good)["state"]
    bad_st = cs.get_capsule(pref_bad)["state"]
    assert good_st[ALPHA_KEY] == 1
    assert bad_st[BETA_KEY] == 1
