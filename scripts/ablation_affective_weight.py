#!/usr/bin/env python3
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

"""情感证据权重消融 —— A.Unit / B.Random / C.Affect 三臂对比（issue #179）。

问题：情感显著性调制偏好证据权重（α += w_affect / β += w_affect）到底带不带来
收益？本脚本用**合成证据流**做受控消融，验证机制本身是否按预期工作：

- 对每条「真实偏好」记忆，先生成一个真值 θ ∈ {0,1}（1=用户确实偏好）；
- 逐条生成 N 条证据事件。每条事件带一个情感显著性 a ∈ [0,1]，事件方向
  （reinforce/deprecate）的可靠性 r(a) = 0.5 + 0.4·a 随 a 单调上升——a 越大，
  该条证据越可能真实反映偏好（这就是 issue 179 的**前提假设**）；
- 三臂对同一批事件做 Beta 更新，只改权重策略：

    A.Unit      w ≡ 1.0                    —— 旧等权基线
    B.Random    w 分布与 C 相同但打乱      —— 控制「任意变权」本身的作用
    C.Affect    w = clamp(0.5 + 2.5·a)     —— 情感显著性单调调制

输出每臂的 Brier Score（预测后验均值 vs 真值 θ）、0.5 阈值分类准确率与
假偏好形成率，然后打印对比。

诚实口径：
- 这是**合成数据上的机制自检**（sanity check），不是真实用户情感数据的评测——
  数据生成器里已经把「a 越大证据越可靠」当成前提，所以 C 优于 A 只能说明
  「前提成立时机制生效」，**不能**当作真实世界情感加权的效果证据；
- 数字全部由本次运行实算得出并原样打印，不预设结论；前提参数调弱/调强结果
  会相应变化，改默认 seed 或 N 即可复现/反驳。

用法::

    python scripts/ablation_affective_weight.py [--items 200] [--obs 30] [--seed 179]

依赖：无第三方库；直接复用 backend.app.memory_runtime.preference_confidence 的
``update_confidence`` / ``confidence``，路径与既有评测脚本一致。
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from backend.app.memory_runtime.preference_confidence import (  # noqa: E402
    DEFAULT_W_MAX,
    DEFAULT_W_MIN,
    confidence,
    update_confidence,
)

#: 合成数据参数（模块常量，方便评审按需调整）。
TRUE_PREFERENCE_RATE = 0.5   # P(θ=1)
RELIABILITY_FLOOR = 0.5      # a=0 时方向仍只有一半可靠（纯噪声）
RELIABILITY_GAIN = 0.4       # a 每 +1，方向可靠度 +0.4（a=1 时 0.9）
AFFECT_BETA_A = 1.5          # 情感显著性先验形状（右偏：多数事件平淡、少数强烈）
AFFECT_BETA_B = 3.0
W_GAIN = DEFAULT_W_MAX - DEFAULT_W_MIN  # w 随 a 的斜率：0.5 + 2.5·a → [0.5, 3.0]


def _draw_stream(rng: random.Random, n_items: int, n_obs: int) -> list[dict]:
    """生成 n_items 条真实偏好的证据流，每条事件带方向与情感显著性。"""
    stream = []
    for item_id in range(n_items):
        theta = 1 if rng.random() < TRUE_PREFERENCE_RATE else 0
        events = []
        for _ in range(n_obs):
            affect = rng.betavariate(AFFECT_BETA_A, AFFECT_BETA_B)
            reliability = RELIABILITY_FLOOR + RELIABILITY_GAIN * affect
            correct = rng.random() < reliability
            # 方向：θ=1 时 reinforce 才算对；θ=0 时 deprecate 才算对。
            if (theta == 1 and correct) or (theta == 0 and not correct):
                direction = "reinforce"
            else:
                direction = "deprecate"
            events.append({"affect": affect, "direction": direction})
        stream.append({"theta": theta, "events": events})
    return stream


def _weight_for_arm(arm: str, events: list[dict], rng: random.Random) -> list[float]:
    """把每条事件映射成该臂的 w_affect。

    - A：一律 1.0；
    - C：w = clamp(0.5 + 2.5·a, [w_min, w_max])（值域本来就落在界内，clamp 是保险）；
    - B：先算 C 的权重序列再整体洗牌——与 C **分布相同但排序无关**，用来隔离
      「只要把权重从常数改成随机变量」这件事本身的效应。
    """
    if arm == "A":
        return [1.0] * len(events)
    c_weights = [
        min(max(DEFAULT_W_MIN + W_GAIN * e["affect"], DEFAULT_W_MIN), DEFAULT_W_MAX)
        for e in events
    ]
    if arm == "C":
        return c_weights
    shuffled = list(c_weights)
    rng.shuffle(shuffled)
    return shuffled


def _run_arm(stream: list[dict], arm: str, seed: int) -> list[float]:
    """跑完一整条证据流，返回每件 item 的后验均值（p_i）。"""
    rng = random.Random(seed * 1_000 + {"A": 1, "B": 2, "C": 3}[arm[0]])
    predictions = []
    for item in stream:
        meta: dict = {}
        weights = _weight_for_arm(arm, item["events"], rng)
        for event, w in zip(item["events"], weights):
            update_confidence(
                meta, event["direction"],
                w_affect=w, enabled=True,  # 三臂都开 flag：只让权重策略不同
            )
        predictions.append(confidence(meta)["mean"])
    return predictions


def _brier(predictions: list[float], truths: list[int]) -> float:
    return sum((p - t) ** 2 for p, t in zip(predictions, truths)) / len(truths)


def _evaluate(predictions: list[float], truths: list[int]) -> dict:
    correct = sum(1 for p, t in zip(predictions, truths) if (p >= 0.5) == (t == 1))
    # 假偏好形成：θ=0（用户其实不偏好）却被系统判成偏好（p>0.5）的比例。
    negatives = [p for p, t in zip(predictions, truths) if t == 0]
    false_positives = sum(1 for p in negatives if p > 0.5)
    positives = [p for p, t in zip(predictions, truths) if t == 1]
    return {
        "brier": _brier(predictions, truths),
        "accuracy": correct / len(truths),
        "false_preference_rate": false_positives / len(negatives) if negatives else float("nan"),
        "mean_p_pos": sum(positives) / len(positives) if positives else float("nan"),
        "mean_p_neg": sum(negatives) / len(negatives) if negatives else float("nan"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="情感证据权重三臂消融（issue #179）")
    parser.add_argument("--items", type=int, default=200, help="合成真实偏好条数")
    parser.add_argument("--obs", type=int, default=30, help="每条偏好的证据事件数")
    parser.add_argument("--seed", type=int, default=179, help="随机种子（复现用）")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    stream = _draw_stream(rng, args.items, args.obs)
    truths = [item["theta"] for item in stream]

    arms = ["A.Unit(w=1)", "B.Random Weight", "C.Affect Weight"]
    results = {}
    for arm in arms:
        results[arm] = _evaluate(_run_arm(stream, arm, args.seed), truths)

    # ---- 打印 ----
    title = (
        f"issue #179 情感证据权重消融（合成证据流: items={args.items}, "
        f"obs/item={args.obs}, seed={args.seed}）"
    )
    print("\n" + "=" * len(title))
    print(title)
    print("=" * len(title))
    print("前提: 方向可靠度 r(a) = 0.5 + 0.4·a，a~Beta(1.5,3)，"
          "即「情感越强证据越可靠」在数据生成器里为真。")
    print("指标: Brier 越低越好（后验均值 vs 真值 θ 的均方误差）。\n")

    header = f"{'臂':<18}{'Brier':>10}{'准确率(>0.5)':>16}{'假偏好率':>12}{'均值差(θ1-θ0)':>16}"
    print(header)
    print("-" * len(header))
    for arm in arms:
        r = results[arm]
        sep = r["mean_p_pos"] - r["mean_p_neg"]
        print(
            f"{arm:<18}{r['brier']:>10.4f}{r['accuracy']:>16.2%}"
            f"{r['false_preference_rate']:>12.2%}{sep:>16.4f}"
        )

    base = results["A.Unit(w=1)"]
    # 诚实口径：只报告实测差异的方向与幅度，不预设「C 一定赢」。
    for arm in ("B.Random Weight", "C.Affect Weight"):
        delta = results[arm]["brier"] - base["brier"]
        direction = "低于" if delta < 0 else "不低于"
        print(f"\n{arm} 的 Brier 相对 A.Unit {direction}基线 "
              f"({'改善' if delta < 0 else '无改善/退步'}): Δ={delta:+.4f}")

    print(
        "\n解读（务必连同前提一起读）: 这是合成机制自检——结果只在 "
        "「a 越大方向越可靠」这一前提成立时才有意义，不能外推到真实情感数据。"
        "真实情感信号未必与证据可靠性单调相关，上线收益需另行用真实反馈评测。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
