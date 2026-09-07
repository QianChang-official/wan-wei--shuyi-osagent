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
FIX-03（04-#05）：decay_affect 正常衰减路径的丢失更新回归测试。

背景
----
04-#04（PR #33）只修了"播种分支"的 Check-Then-Act 竞态（row is None 时
两个线程重复 INSERT），改用 `INSERT OR IGNORE` + rowcount 判定。

但**正常衰减路径**仍是跨事务的读-改-写：
    1. 无事务快照读 affect_state
    2. 计算衰减
    3. save_affect() 另开事务 UPSERT

daemon 线程与 API 请求线程（transition()）并发时，daemon 会用步骤 1 的旧
快照算出的值覆盖 transition() 在步骤 2/3 之间提交的新状态，情感更新静默丢失。

为什么不能只靠 transaction() 包裹
--------------------------------
`db.get_conn()` 返回**线程本地**连接，WAL 模式下不同线程各持自己的连接与
读快照。把 decay 的读+写包进同一个 `transaction()` 只能保证本线程内的原子
提交，无法阻止另一线程在中途提交新值——包裹后实测仍然丢失更新。

因此改用**乐观锁（CAS）**：写回时在 WHERE 里带上读快照的值，冲突则放弃本轮。
衰减是幂等的周期性操作，跳过一轮无副作用；覆盖真实情感更新才是错误。

CAS 条件为何不能只用 updated_at
------------------------------
`utc_now_iso_compact()` 是秒级精度（`microsecond=0`），同一秒内的并发写会
产生相同时间戳，单靠时间戳比对会假通过。故条件里同时带 PAD 与 mood_intensity。
"""

import threading

import pytest

from backend.app.affect import decay_daemon
from backend.app.affect.state_machine import (
    AffectState,
    load_affect,
    save_affect,
    transition,
)
from backend.app.soul.persona import create_persona, update_persona


def _seed(name: str) -> str:
    """建 persona 并播种 affect_state，使 decay 走正常衰减路径。"""
    sid = create_persona(name)
    update_persona(
        sid,
        baseline_pleasure=0.6,
        baseline_arousal=0.4,
        baseline_dominance=0.5,
    )
    save_affect(
        sid,
        AffectState(
            pleasure=0.6, arousal=0.4, dominance=0.5,
            current_mood="calm", mood_intensity=0.5,
        ),
    )
    return sid


def test_decay_does_not_overwrite_concurrent_transition(isolated_db, monkeypatch):
    """核心回归：decay 读快照后若状态被并发改写，不得用旧快照覆盖。

    交错注入点选在 `_clamp` 的第 4 次调用（PAD + mood_intensity 算完、
    即将执行 CAS UPDATE 之前），确定性复现 daemon 与 API 线程的交错，
    不依赖真实线程抢跑的时序运气。
    """
    sid = _seed("soul_cas_regression")
    transition(sid, "user_joy", intensity=0.9)
    before = load_affect(sid).pleasure

    real_clamp = decay_daemon._clamp
    calls = {"n": 0}
    concurrent_value = {}

    def clamp_with_interleave(value):
        calls["n"] += 1
        if calls["n"] == 4:
            transition(sid, "user_joy", intensity=0.9)
            concurrent_value["pleasure"] = load_affect(sid).pleasure
        return real_clamp(value)

    monkeypatch.setattr(decay_daemon, "_clamp", clamp_with_interleave)
    returned = decay_daemon.decay_affect(sid)
    monkeypatch.undo()

    assert concurrent_value, "交错未触发，测试未覆盖目标路径"
    committed = concurrent_value["pleasure"]
    assert committed > before, "前置条件失败：并发 transition 应推高 pleasure"

    final = load_affect(sid).pleasure

    # 修复前：decay 用旧快照回写，final 会退回到 before 附近（约 0.753）
    # 修复后：CAS 冲突，decay 放弃本轮，final 保持并发提交的值
    assert final == pytest.approx(committed), (
        f"并发情感更新被 decay 覆盖：committed={committed}, final={final}"
    )
    assert returned.pleasure == pytest.approx(committed), (
        "CAS 冲突时 decay 应返回数据库最新状态，而非过期的本地计算结果"
    )


def test_decay_still_applies_when_no_conflict(isolated_db):
    """无并发时衰减必须照常生效——CAS 不能把正常路径也一起挡掉。"""
    sid = _seed("soul_cas_normal")
    save_affect(
        sid,
        AffectState(
            pleasure=1.0, arousal=1.0, dominance=1.0,
            current_mood="excited", mood_intensity=1.0,
        ),
    )

    state = decay_daemon.decay_affect(sid)

    assert state.pleasure < 1.0, "无冲突时应执行衰减"
    assert state.mood_intensity == pytest.approx(0.85), "mood_intensity 应衰减为 1.0 * 0.85"
    assert load_affect(sid).pleasure == pytest.approx(state.pleasure), "返回值应与落库值一致"


def test_decay_concurrent_threads_no_lost_update(isolated_db):
    """多线程并发 transition + decay：transition 的写入不得丢失。

    衡量标准不是"最终值等于某个数"（衰减与事件交错顺序不确定），而是
    "不出现异常"且"最终值不低于纯衰减基线"——若 decay 用旧快照覆盖了
    transition，最终值会明显低于并发写入的水平。
    """
    sid = _seed("soul_cas_threads")

    errors: list[str] = []
    barrier = threading.Barrier(6)

    def do_transition():
        try:
            barrier.wait(timeout=10)
            for _ in range(5):
                transition(sid, "user_joy", intensity=0.9)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"transition: {exc!r}")

    def do_decay():
        try:
            barrier.wait(timeout=10)
            for _ in range(5):
                decay_daemon.decay_affect(sid)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"decay: {exc!r}")

    threads = [threading.Thread(target=do_transition) for _ in range(3)]
    threads += [threading.Thread(target=do_decay) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"并发执行出现异常：{errors}"

    # 15 次 user_joy 推高 pleasure，15 次衰减拉回 baseline(0.6)。
    # 只要 decay 没有覆盖 transition 的提交，最终值应明显高于 baseline。
    final = load_affect(sid).pleasure
    assert final > 0.6, f"pleasure={final} 已回落到 baseline，transition 的更新疑似被覆盖"
