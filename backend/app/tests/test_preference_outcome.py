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

import math
import pytest

from backend.app.memory_runtime.preference_outcome import (
    apply_outcome, outcome_summary, outcome_validation_enabled, record_outcome,
)
from backend.app.memory_runtime.preference_confidence import _coerce_count, confidence
from backend.app.memory_runtime import capsule_store as cs


@pytest.fixture(autouse=True)
def outcome_flag(monkeypatch):
    monkeypatch.setenv("WANWEI_OUTCOME_VALIDATION", "1")


def test_outcome_mapping_and_summary():
    meta = {}
    for kind in ("accept", "reject", "undo", "retry", "unknown"):
        apply_outcome(meta, kind)
    assert meta["preference_alpha"] == 1.0
    assert meta["preference_beta"] == 3.5
    assert outcome_summary(meta)["undos"] == 1


def test_fractional_count_is_preserved_in_confidence():
    assert _coerce_count(0.5) == 0.5
    assert _coerce_count(-1.0) == 0
    assert _coerce_count(float("nan")) == 0
    assert confidence({"preference_alpha": 0.5})["alpha"] == 1.5


def test_unknown_does_not_change_posterior_and_log_is_bounded():
    meta = {}
    apply_outcome(meta, "unknown")
    assert "preference_alpha" not in meta and "preference_beta" not in meta
    for _ in range(25):
        apply_outcome(meta, "accept")
    assert len(meta["outcome_log"]) == 20


def test_invalid_numbers_use_defaults():
    meta = {}
    apply_outcome(meta, "accept", reward=math.nan)
    apply_outcome(meta, "retry", weak_penalty=-1)
    assert meta["preference_alpha"] == 1.0
    assert meta["preference_beta"] == 0.5


def test_feature_flag_disabled_is_strict_noop(monkeypatch):
    meta = {"preference_alpha": 2.0, "preference_beta": 3.0, "outcome_log": [{"old": True}]}
    before = dict(meta)
    monkeypatch.setenv("WANWEI_OUTCOME_VALIDATION", "0")
    assert apply_outcome(meta, "accept") is meta
    assert meta == before


def test_feature_flag_enabled_applies(monkeypatch):
    monkeypatch.setenv("WANWEI_OUTCOME_VALIDATION", "1")
    meta = {}
    apply_outcome(meta, "accept")
    assert meta["preference_alpha"] == 1.0
    assert len(meta["outcome_log"]) == 1


def test_record_outcome_persists_preference_state(isolated_db):
    cid = cs.write_capsule(memory_class="preference", content={"text": "喜欢咖啡"})["capsule_id"]
    result = record_outcome(cid, "accept")
    state = cs.get_capsule(cid)["state"]
    assert result["capsule_id"] == cid
    assert state["preference_alpha"] == 1.0
    assert state["preference_beta"] == 0


@pytest.mark.parametrize("value", [None, "0"])
def test_record_outcome_flag_disabled_does_not_persist_or_log(isolated_db, monkeypatch, value):
    if value is None:
        monkeypatch.delenv("WANWEI_OUTCOME_VALIDATION", raising=False)
    else:
        monkeypatch.setenv("WANWEI_OUTCOME_VALIDATION", value)
    cid = cs.write_capsule(memory_class="preference", content={"text": "喜欢咖啡"})["capsule_id"]
    record_outcome(cid, "accept")
    state = cs.get_capsule(cid)["state"]
    assert "preference_alpha" not in state
    assert "preference_beta" not in state
    assert "outcome_log" not in state


def test_record_unknown_only_grows_log(isolated_db):
    cid = cs.write_capsule(memory_class="preference", content={"text": "喜欢咖啡"})["capsule_id"]
    record_outcome(cid, "accept")
    state = cs.get_capsule(cid)["state"]
    counts = (state["preference_alpha"], state["preference_beta"])
    record_outcome(cid, "unknown")
    state = cs.get_capsule(cid)["state"]
    assert (state["preference_alpha"], state["preference_beta"]) == counts
    assert len(state["outcome_log"]) == 2


def test_record_unknown_as_first_event_is_log_only(isolated_db):
    cid = cs.write_capsule(memory_class="preference", content={"text": "喜欢咖啡"})["capsule_id"]
    record_outcome(cid, "unknown")
    state = cs.get_capsule(cid)["state"]
    assert "preference_alpha" not in state and "preference_beta" not in state
    assert len(state["outcome_log"]) == 1
    assert set(state["outcome_log"][0]) == {
        "outcome_type", "action_id", "posterior_before", "posterior_after", "created_at",
    }


def test_record_outcome_rejects_non_preference(isolated_db):
    cid = cs.write_capsule(memory_class="knowledge", content={"text": "背景"})["capsule_id"]
    with pytest.raises(ValueError, match="preference"):
        record_outcome(cid, "accept")
