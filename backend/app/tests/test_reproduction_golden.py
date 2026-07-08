"""Golden/behavior tests for reproduction modules (v0.9.6.1 static-scan follow-up).

These lock the observable behavior of hippo_lite.recall() and
reflexion_evaluator.evaluate() BEFORE the cognitive-complexity refactor, so the
helper extraction can be verified as behavior-preserving.
"""
from __future__ import annotations

import pytest

from backend.app.reproduction import hippo_lite
from backend.app.reproduction.reflexion_evaluator import evaluate
from backend.app.reproduction.schemas import HippoRecallIn, ReflexionEvaluateIn


# ---------------------------------------------------------------------------
# hippo_lite.recall — deterministic via a fixed capsule fixture
# ---------------------------------------------------------------------------

_FIXED_CAPSULES = [
    {
        "capsule_id": "cap-a",
        "memory_class": "semantic",
        "content": {"text": "alpha memory about rate limits"},
        "state": {"lifecycle": "active"},
        "relation_edges": [{"target": "cap-b", "type": "related"}],
    },
    {
        "capsule_id": "cap-b",
        "memory_class": "episodic",
        "content": {"text": "beta memory about workflows"},
        "state": {"lifecycle": "active"},
        "relation_edges": [],
    },
    {
        "capsule_id": "cap-c",
        "memory_class": "semantic",
        "content": {"text": "gamma note about alpha and beta"},
        "state": {"lifecycle": "active"},
        "relation_edges": [{"target": "cap-a", "type": "related"}],
    },
]


@pytest.fixture()
def fixed_capsules(monkeypatch):
    monkeypatch.setattr(hippo_lite, "list_capsules", lambda limit: list(_FIXED_CAPSULES))


def test_recall_seeds_and_ranking_golden(fixed_capsules):
    out = hippo_lite.recall(HippoRecallIn(query="alpha", hops=1, top_k=3))
    assert out["status"] == "hippo_lite_partial"
    assert out["query"] == "alpha"
    seeds = {s["capsule_id"]: s["seed_score"] for s in out["seeds"]}
    # 'alpha' appears in cap-a and cap-c content.
    assert seeds == {"cap-a": 1.0, "cap-c": 1.0}
    ranked = {r["capsule_id"]: r["graph_recall_score"] for r in out["ranked_nodes"]}
    # 1-hop spread: cap-a has 2 neighbors (b, c) -> 0.225 each; cap-c has 1 (a) -> 0.45.
    assert ranked["cap-a"] == pytest.approx(1.45)   # seed 1.0 + 0.45 from cap-c
    assert ranked["cap-c"] == pytest.approx(1.225)  # seed 1.0 + 0.225 from cap-a
    assert ranked["cap-b"] == pytest.approx(0.225)  # 0.225 from cap-a
    # Evidence paths pair each seed with ranked nodes (excluding itself).
    for path in out["evidence_paths"]:
        assert path["path"] == [path["from_seed"], path["to_node"]]
        assert path["from_seed"] != path["to_node"]


def test_recall_no_match_falls_back_to_first_node(fixed_capsules):
    out = hippo_lite.recall(HippoRecallIn(query="zzz-no-match", hops=0, top_k=2))
    assert out["seeds"] == [{"capsule_id": "cap-a", "seed_score": 0.2}]
    assert out["ranked_nodes"][0]["capsule_id"] == "cap-a"


def test_recall_zero_hops_keeps_only_seed_scores(fixed_capsules):
    out = hippo_lite.recall(HippoRecallIn(query="beta", hops=0, top_k=5))
    ranked = {r["capsule_id"]: r["graph_recall_score"] for r in out["ranked_nodes"]}
    # 'beta' appears in cap-b and cap-c; no propagation at 0 hops.
    assert ranked == {"cap-b": 1.0, "cap-c": 1.0}


# ---------------------------------------------------------------------------
# reflexion_evaluator.evaluate — pure function, table-driven golden cases
# ---------------------------------------------------------------------------

def _req(**kw):
    base = dict(task_id="t1", goal_achieved=False, notes="", evidence_cards=[], used_memories=[])
    base.update(kw)
    return ReflexionEvaluateIn(**base)


@pytest.mark.parametrize(
    "req,expected_type,expected_quality",
    [
        (_req(goal_achieved=True, evidence_cards=[{"id": 1}]), "no_failure", 0.88),
        (_req(notes="unsafe operation attempted", evidence_cards=[{"id": 1}]), "unsafe_plan", 0.35),
        (_req(notes="检测到误报", evidence_cards=[{"id": 1}]), "false_positive_echo", 0.42),
        (_req(), "weak_evidence", 0.45),
        (_req(evidence_cards=[{"id": 1}]), "missing_memory", 0.5),
        (_req(evidence_cards=[{"id": 1}], used_memories=["m1"], notes="conflict detected"),
         "conflict_ignored", 0.55),
        (_req(evidence_cards=[{"id": 1}], used_memories=["m1"], notes="plain notes"),
         "missing_memory", 0.55),
    ],
)
def test_evaluate_failure_classification_golden(req, expected_type, expected_quality):
    out = evaluate(req)
    assert out["evaluator"]["failure_type"] == expected_type
    assert out["evaluator"]["reflection_quality_score"] == pytest.approx(expected_quality)
    assert out["status"] == "dry_run_only"
    assert out["mutates_real_memory"] is False
    assert len(out["self_reflection"]["suggested_actions"]) >= (
        0 if expected_type == "conflict_ignored" else 1
    )
    assert out["self_reflection"]["suggested_memory_update"] is (expected_type != "no_failure")


def test_evaluate_goal_without_evidence_is_not_no_failure():
    out = evaluate(_req(goal_achieved=True))
    assert out["evaluator"]["failure_type"] == "weak_evidence"
