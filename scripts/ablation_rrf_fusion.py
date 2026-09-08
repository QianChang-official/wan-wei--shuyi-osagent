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

"""Small deterministic ablation for #164-C (uses the real fusion entry point)."""
from collections import defaultdict

from backend.app.memory_runtime import rrf_fusion as rf


def main():
    # Three query families: lexical, semantic, and graph-only related capsules.
    data = {
        "lexical": ({"l1", "l2"}, ["l1", "l2", "s1"], ["s1", "l1", "g1"], ["g1", "l1"]),
        "semantic": ({"s1", "s2"}, ["l1", "s1", "s2"], ["s1", "s2", "l1"], ["g2", "s1"]),
        "graph": ({"g1", "g2"}, ["l1", "x1"], ["s1", "x1"], ["g1", "g2", "s1"]),
    }
    metrics = defaultdict(list)
    for query, (relevant, fts_ids, vec_ids, graph_ids) in data.items():
        caps = {cid: {"capsule_id": cid, "state": {"lifecycle": "active"}, "governance": {"policy_result": "allow", "sensitivity_level": "S0"}} for ids in (fts_ids, vec_ids, graph_ids) for cid in ids}
        original = rf.get_capsules_batch if hasattr(rf, "get_capsules_batch") else None
        import backend.app.memory_runtime.capsule_store as store
        old = store.get_capsules_batch
        store.get_capsules_batch = lambda ids, **_: {cid: caps[cid] for cid in ids if cid in caps}
        try:
            modes = {
                "FTS only": (fts_ids, None, None), "vector only": (None, vec_ids, None),
                "RRF": (fts_ids, vec_ids, None), "RRF+graph": (fts_ids, vec_ids, graph_ids),
            }
            for mode, (f, v, g) in modes.items():
                out = rf.fused_search(query, top_k=5, fts=(lambda _q, **_: f) if f else None, vector=(lambda _q, **_: v) if v else None, graph=(lambda _s, **_: g) if g else None)
                ids = [x["capsule_id"] for x in out]
                hits = [i for i, cid in enumerate(ids, 1) if cid in relevant]
                metrics[mode].append((len(set(ids[:5]) & relevant) / 5, 1 / hits[0] if hits else 0.0))
        finally:
            store.get_capsules_batch = old
    print("mode        P@5   MRR")
    for mode in ("FTS only", "vector only", "RRF", "RRF+graph"):
        vals = metrics[mode]
        print(f"{mode:<11} {sum(x[0] for x in vals)/len(vals):.3f} {sum(x[1] for x in vals)/len(vals):.3f}")


if __name__ == "__main__":
    main()
