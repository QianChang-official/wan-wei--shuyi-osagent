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

"""合成/回放数据集。每条记录含 topic、observed preference、truth 和 timestamp。"""
from __future__ import annotations
import json, random
from dataclasses import dataclass, asdict
from pathlib import Path

@dataclass
class Event:
    scenario: str; topic: str; value: str; truth: str; timestamp: int; accepted: bool = True; flip_at: int | None = None

SCENARIOS = ("stable", "weak", "high_emotion", "temporary", "drift", "wrong")

def generate_dataset(seed: int = 42, repeats: int = 12) -> list[dict]:
    rng = random.Random(seed); out=[]
    for scenario in SCENARIOS:
        n = max(4, repeats)
        for i in range(n):
            if scenario == "stable": value, truth = "markdown", "markdown"
            elif scenario == "weak": value, truth = ("markdown" if rng.random() < .35 else "word"), "markdown"
            elif scenario == "high_emotion": value, truth = "markdown", "markdown"
            elif scenario == "temporary": value, truth = ("word" if i == 0 else "markdown"), "markdown"
            elif scenario == "drift": value, truth = ("markdown" if i < n//2 else "word"), ("markdown" if i < n//2 else "word")
            else: value, truth = "markdown", "word"
            flip_at = n // 2 if scenario == "drift" else None
            out.append(asdict(Event(scenario, f"format:{scenario}", value, truth, i, True, flip_at)))
    return out

class DatasetLoader:
    def __init__(self, records=None): self.records = list(records or [])
    @classmethod
    def synthetic(cls, seed=42, repeats=12): return cls(generate_dataset(seed, repeats))
    @classmethod
    def from_jsonl(cls, path):
        with open(path, encoding="utf-8") as f: return cls(json.loads(line) for line in f if line.strip())
    def __iter__(self): return iter(self.records)
    def __len__(self): return len(self.records)
