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

from datetime import datetime, timedelta, timezone

import pytest

from backend.app.memory_runtime import rrf_fusion as rf


def test_rrf_fuse_exact_scores_and_tie_order():
    out = rf.rrf_fuse([["b", "a"], ["a", "c"]], k=1)
    assert out == {"a": pytest.approx(5 / 6), "b": pytest.approx(1 / 2), "c": pytest.approx(1 / 3)}


def test_accumulate_duplicate_counts_first_seen_only():
    acc = {}
    rf._accumulate_ranking(acc, ["x", "x", "y"], weight=2.0, k=0)
    assert acc == {"x": 2.0, "y": pytest.approx(2 / 3)}


def test_graph_expand_two_hops_with_return_flow(monkeypatch):
    monkeypatch.setattr(rf, "_load_relation_adjacency", lambda **_: ({"a": ["b"], "b": ["a", "c"], "c": ["b"]}, {"a", "b", "c"}))
    assert rf.graph_expand(["a"]) == {"a": 1.125, "b": 0.5, "c": 0.125}
    monkeypatch.setattr(rf, "_load_relation_adjacency", lambda **_: ({}, {"a"}))
    assert rf.graph_expand(["missing"]) == {}


def _cap(cid, *, old=False, denied=False, alpha=None):
    state = {"lifecycle": "active"}
    if old:
        state["last_accessed_at"] = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
    if alpha is not None:
        state["preference_alpha"] = alpha
        state["preference_beta"] = 0
    return {"capsule_id": cid, "state": state, "governance": {"policy_result": "deny" if denied else "allow", "sensitivity_level": "S0"}}


def test_fused_search_channels_multipliers_filter_and_topk(monkeypatch):
    seen = {}
    monkeypatch.setattr(rf, "_weights", lambda: {"fts": 1.0, "vector": 1.0, "graph": 1.0})
    monkeypatch.setattr("backend.app.memory_runtime.capsule_store.get_capsules_batch", lambda ids, **_: {c["capsule_id"]: c for c in [_cap("a"), _cap("b", old=True), _cap("c", denied=True), _cap("d", alpha=20)] if c["capsule_id"] in ids})
    def fts(q, **kw): return ["a", "c"]
    def vec(q, **kw): return ["b", "d"]
    def graph(seeds, **kw): seen["seeds"] = seeds; return ["d", "a"]
    out = rf.fused_search("q", top_k=2, fts=fts, vector=vec, graph=graph, conf_floor=0.9, at=datetime.now(timezone.utc))
    assert seen["seeds"] == ["a", "c", "b", "d"]
    assert [x["capsule_id"] for x in out] == ["d", "a"]
    assert out[0]["rrf_channels"] == {"vector": 2, "graph": 1}
    assert out[1]["rrf_channels"] == {"fts": 1, "graph": 2}
    assert all(x["rrf_confidence"] >= 0.9 for x in out)
    assert out[0]["rrf_fusion_score"] > out[1]["rrf_fusion_score"]
    recency = rf.fused_search("q", top_k=4, fts=fts, vector=vec, graph=None)
    scores = {x["capsule_id"]: x["rrf_fusion_score"] for x in recency}
    assert scores["a"] > scores["b"]
    assert rf.fused_search("q", fts=lambda _q, **kw: ["a"], vector=None, graph=None, top_k=1)


def test_weights_cache_and_tuning_fallback(monkeypatch):
    rf._reload_weights()
    monkeypatch.setitem(__import__("sys").modules, "backend.app.tuning.service", None)
    assert rf._weights() == rf._WEIGHTS_FALLBACK
