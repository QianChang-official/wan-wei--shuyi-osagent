from __future__ import annotations

from collections import defaultdict

from ..memory_runtime.capsule_store import list_capsules
from .schemas import HippoRecallIn


def _content_text(cap: dict) -> str:
    content = cap.get("content", {})
    return str(content).lower()


def graph() -> dict:
    capsules = [cap for cap in list_capsules(200) if cap]
    nodes = [
        {
            "id": cap["capsule_id"],
            "memory_class": cap.get("memory_class", "unknown"),
            "label": str(cap.get("content", {}))[:90],
            "lifecycle": cap.get("state", {}).get("lifecycle", "unknown"),
        }
        for cap in capsules
    ]
    edges = []
    for cap in capsules:
        for edge in cap.get("relation_edges", []) or []:
            edges.append(
                {
                    "source": cap["capsule_id"],
                    "target": edge.get("target") or edge.get("target_id") or edge.get("capsule_id"),
                    "type": edge.get("type", "related"),
                }
            )
    if not edges and len(nodes) >= 2:
        edges = [
            {"source": nodes[i]["id"], "target": nodes[i + 1]["id"], "type": "demo_similarity"}
            for i in range(min(len(nodes) - 1, 4))
        ]
    return {
        "status": "hippo_lite_graph_partial",
        "boundary": "Capsule graph + relation_edges/demo edges; no vector DB or full HippoRAG reproduction.",
        "nodes": nodes,
        "edges": [edge for edge in edges if edge.get("target")],
        "node_count": len(nodes),
        "edge_count": len([edge for edge in edges if edge.get("target")]),
    }


def recall(req: HippoRecallIn) -> dict:
    g = graph()
    nodes = g["nodes"]
    edge_map = defaultdict(list)
    for edge in g["edges"]:
        edge_map[edge["source"]].append(edge["target"])
        edge_map[edge["target"]].append(edge["source"])
    terms = [part.lower() for part in req.query.split() if part.strip()]
    seed_scores = {}
    capsule_lookup = {cap["capsule_id"]: cap for cap in list_capsules(200) if cap}
    for node in nodes:
        text = _content_text(capsule_lookup.get(node["id"], {}))
        score = sum(1 for term in terms if term in text)
        if score:
            seed_scores[node["id"]] = float(score)
    if not seed_scores and nodes:
        seed_scores[nodes[0]["id"]] = 0.2
    scores = dict(seed_scores)
    frontier = dict(seed_scores)
    for hop in range(max(0, min(req.hops, 4))):
        next_frontier = defaultdict(float)
        for source, score in frontier.items():
            neighbors = edge_map.get(source, [])
            if not neighbors:
                continue
            spread = score * 0.45 / len(neighbors)
            for target in neighbors:
                next_frontier[target] += spread
        for target, score in next_frontier.items():
            scores[target] = scores.get(target, 0.0) + score
        frontier = dict(next_frontier)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)[: req.top_k]
    return {
        "query": req.query,
        "status": "hippo_lite_partial",
        "seeds": [{"capsule_id": key, "seed_score": value} for key, value in seed_scores.items()],
        "ranked_nodes": [{"capsule_id": key, "graph_recall_score": round(value, 4)} for key, value in ranked],
        "evidence_paths": [
            {"from_seed": seed, "to_node": node, "path": [seed, node]}
            for seed in seed_scores
            for node, _ in ranked
            if seed != node
        ][: req.top_k],
    }
