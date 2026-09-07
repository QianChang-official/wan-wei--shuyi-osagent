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

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

VALID_METRICS = {
    "total_cases": 5,
    "total_assertions": 16,
    "assertions_passed": 16,
    "assertion_pass_rate": 1.0,
    "unsafe_autonomy_rate": 0.0,
    "evidence_card_coverage_rate": 1.0,
    "policy_gate_hit_rate": 1.0,
    "lifecycle_correct_rate": 1.0,
    "memory_reuse_success_rate": 0.4,
    "post_reflection_update_rate": 1.0,
    "misleading_memory_rate": "pending",
    "production_task_success_rate": "pending",
}


@pytest.fixture
def app_runtime_mod():
    # Issue #90: main.py 不再做 sys.modules 自替换，直接从 app_runtime 导入。
    from backend.app import app_runtime
    return app_runtime


def test_arena_metrics_returns_valid_report(tmp_path, monkeypatch, app_runtime_mod):
    metrics_path = tmp_path / "metrics.json"
    metrics_path.write_text(json.dumps(VALID_METRICS), encoding="utf-8")
    monkeypatch.setattr(app_runtime_mod, "ARENA_METRICS_PATH", metrics_path)

    assert app_runtime_mod.arena_metrics() == VALID_METRICS


def test_arena_metrics_missing_report_is_not_a_success_payload(
    tmp_path, monkeypatch, app_runtime_mod
):
    monkeypatch.setattr(app_runtime_mod, "ARENA_METRICS_PATH", tmp_path / "missing.json")

    with pytest.raises(HTTPException) as exc_info:
        app_runtime_mod.arena_metrics()

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "arena_metrics_not_found"


def test_arena_metrics_malformed_report_is_unavailable(
    tmp_path, monkeypatch, app_runtime_mod
):
    metrics_path = tmp_path / "metrics.json"
    metrics_path.write_text("{", encoding="utf-8")
    monkeypatch.setattr(app_runtime_mod, "ARENA_METRICS_PATH", metrics_path)

    with pytest.raises(HTTPException) as exc_info:
        app_runtime_mod.arena_metrics()

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "arena_metrics_unavailable"


@pytest.mark.parametrize(
    "payload",
    [
        {"error": "metrics_not_found"},
        {**VALID_METRICS, "assertion_pass_rate": None},
        {**VALID_METRICS, "assertion_pass_rate": "pending"},
        {**VALID_METRICS, "assertion_pass_rate": 0.5},
        {**VALID_METRICS, "unsafe_autonomy_rate": "pending"},
        {**VALID_METRICS, "assertions_passed": 17},
    ],
)
def test_arena_metrics_rejects_incomplete_or_inconsistent_reports(
    tmp_path, monkeypatch, app_runtime_mod, payload
):
    metrics_path = tmp_path / "metrics.json"
    metrics_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(app_runtime_mod, "ARENA_METRICS_PATH", metrics_path)

    with pytest.raises(HTTPException) as exc_info:
        app_runtime_mod.arena_metrics()

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "arena_metrics_invalid"
