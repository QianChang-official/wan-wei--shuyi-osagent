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

"""EGPM 消融运行器。

当前 +Drift 臂使用固定窗口众数变化的代理检测器；并未调用仓库 #168
的 ``compute_preference_drift``，后者依赖数据库日窗，本次尚未接线。
"""
from __future__ import annotations
from .metrics import compute_metrics
from ..memory_runtime.preference_confidence import confidence

DRIFT_LOOKBACK = 6
DRIFT_SPLIT = 3

class BenchmarkRunner:
    CONFIGS=("Baseline", "+Beta", "+Drift", "+Emotion")
    def __init__(self, records): self.records=list(records)
    def run(self):
        results={}
        for cfg in self.CONFIGS:
            counts={}; rows=[]
            history={}
            for r in self.records:
                topic=r.get("topic","format"); counts.setdefault(topic,{})[r["value"]]=counts.setdefault(topic,{}).get(r["value"],0)+1
                pred=max(counts[topic], key=counts[topic].get)
                conf=.5
                if "Beta" in cfg or "Drift" in cfg:
                    st={"preference_alpha":counts[topic].get(pred,0),"preference_beta":sum(counts[topic].values())-counts[topic].get(pred,0)}; c=confidence(st); conf=c["mean"]
                seq=history.setdefault(r.get("topic","format"), [])
                seq.append(r["value"])
                drift_pred=False
                if "Drift" in cfg and len(seq) >= DRIFT_LOOKBACK:
                    prior, recent = seq[-DRIFT_LOOKBACK:-DRIFT_SPLIT], seq[-DRIFT_SPLIT:]
                    drift_pred = max(set(prior), key=prior.count) != max(set(recent), key=recent.count)
                flip_at=r.get("flip_at")
                drift_truth=flip_at is not None and r["timestamp"] >= flip_at
                rows.append({**r,"observed":r["value"],"pred":pred,"confidence":conf,"drift_pred":drift_pred,"drift_truth":drift_truth})
            if cfg == "+Emotion":
                results[cfg] = None
                continue
            results[cfg]=compute_metrics(rows)
        return results
