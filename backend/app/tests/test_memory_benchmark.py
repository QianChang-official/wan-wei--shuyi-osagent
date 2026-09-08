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

import pytest
from backend.app.memory_benchmark.dataset import DatasetLoader, generate_dataset
from backend.app.memory_benchmark.metrics import compute_metrics
from backend.app.memory_benchmark.runner import BenchmarkRunner
from backend.app.memory_benchmark.report import render_report

def test_dataset_reproducible_and_six_scenarios():
    a=generate_dataset(7, 4); b=generate_dataset(7, 4)
    assert a == b and {x['scenario'] for x in a} == {'stable','weak','high_emotion','temporary','drift','wrong'}
    assert len({x['topic'] for x in a}) == 6

def test_metrics_manual():
    rows=[{'pred':'a','truth':'a','observed':'a','confidence':.9,'drift_pred':1,'drift_truth':1}, {'pred':'a','truth':'b','observed':'a','confidence':.8,'drift_pred':1,'drift_truth':0}]
    m=compute_metrics(rows)
    assert m['preference_accuracy'] == .5 and m['drift_precision'] == .5 and m['drift_recall'] == 1

def test_runner_and_report():
    result=BenchmarkRunner(DatasetLoader.synthetic(repeats=4)).run()
    assert set(result) == {'Baseline','+Beta','+Drift','+Emotion'}
    text=render_report(result)
    assert '| Method |' in text and '未验证（组件未实现）' in text
    assert result['+Emotion'] is None

def test_drift_end_to_end_and_flip_at():
    result = BenchmarkRunner(DatasetLoader.synthetic(repeats=12)).run()['+Drift']
    assert result['drift_f1'] > 0
    assert result['drift_precision'] > 0 and result['drift_recall'] > 0

def test_from_jsonl_roundtrip(tmp_path):
    import json
    records = generate_dataset(3, 4)
    path = tmp_path / 'data.jsonl'
    path.write_text(''.join(json.dumps(r) + "\n" for r in records), encoding='utf-8')
    assert DatasetLoader.from_jsonl(path).records == records

def test_ece_brier_manual():
    rows = [
        {'pred':'a','truth':'a','confidence':.9},
        {'pred':'a','truth':'b','confidence':.1},
    ]
    m = compute_metrics(rows)
    assert m['brier'] == pytest.approx(0.01)
    assert m['calibration_error'] == pytest.approx(0.1)
