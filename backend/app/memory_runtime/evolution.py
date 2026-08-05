import uuid
from typing import Any
from ..db import get_conn, transaction
from ..audit.service import record
from .capsule_store import get_capsule, update_capsule, write_capsule, dumps, now


def reinforce(
    capsule_id: str,
    amount: float = 0.1,
    *,
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> dict[str, Any]:
    cap = get_capsule(capsule_id, owner_id=owner_id, soul_id=soul_id)
    if not cap:
        raise ValueError(f"Capsule not found: {capsule_id}")
    st = cap["state"]
    st["lifecycle"] = "reinforced" if st.get("lifecycle") == "active" else st.get("lifecycle", "candidate")
    st["importance_score"] = min(1.0, float(st.get("importance_score", 0.5)) + amount)
    st["retention_score"] = min(1.0, float(st.get("retention_score", 0.5)) + amount)
    return update_capsule(
        capsule_id,
        state=st,
        owner_id=owner_id,
        soul_id=soul_id,
    )


def deprecate(
    capsule_id: str,
    reason: str = "misleading",
    *,
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> dict[str, Any]:
    cap = get_capsule(capsule_id, owner_id=owner_id, soul_id=soul_id)
    if not cap:
        raise ValueError(f"Capsule not found: {capsule_id}")
    st = cap["state"]; st["lifecycle"] = "deprecated"; st["deprecation_reason"] = reason
    return update_capsule(
        capsule_id,
        state=st,
        owner_id=owner_id,
        soul_id=soul_id,
    )


def conflict_mark(capsule_id: str, reason: str = "conflict") -> dict[str, Any]:
    cap = get_capsule(capsule_id)
    if not cap:
        raise ValueError(f"Capsule not found: {capsule_id}")
    st = cap["state"]; st["lifecycle"] = "conflicted"; st["conflict_reason"] = reason
    return update_capsule(capsule_id, state=st)


def supersede(old_capsule_id: str, *, new_content: dict[str, Any], memory_class: str = "knowledge") -> dict[str, Any]:
    old = get_capsule(old_capsule_id)
    if not old:
        raise ValueError(f"Capsule not found: {old_capsule_id}")
    new = write_capsule(memory_class=memory_class, content=new_content, source_type="eval", write_intent="explicit")
    old_state = old["state"]; old_state["lifecycle"] = "deprecated"; old_state.setdefault("superseded_by", []).append(new["capsule_id"])
    update_capsule(old_capsule_id, state=old_state)
    new_cap = get_capsule(new["capsule_id"])
    if not new_cap:
        # 理论上不应发生：capsule 刚由 write_capsule 成功创建并落库。
        # 触发说明 write_capsule 或数据库事务层存在一致性 bug，属于内部错误
        # 而非调用方输入错误，因此用 RuntimeError 而不是 ValueError。
        raise RuntimeError(
            f"Internal error: newly created capsule {new['capsule_id']} vanished. "
            "This indicates a critical issue in write_capsule or the database layer."
        )
    st = new_cap["state"]; st.setdefault("supersedes", []).append(old_capsule_id)
    return update_capsule(new["capsule_id"], state=st)


def reflect_task(
    task_id: str,
    payload: dict[str, Any],
    *,
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> dict[str, Any]:
    actions = []
    
    # 04-#03: Batch-fetch all candidate capsules to avoid N+1 queries.
    # helpful_memories 与 misleading_memories 合并成一次批量查询（两者都要先
    # 验证存在性，没有理由分两批查）。
    # Before: helpful=[A,B,C] + misleading=[D] → 8 次单查
    #   - 4× get_capsule（验证存在性）+ 4× reinforce/deprecate 内部的 get_capsule
    # After: 1× get_capsules_batch([A,B,C,D]) + 4× 更新（查询已在 SQLite 页缓存）
    # Performance: 10 条记忆从 20 次查询降到 1 + 10；后 10 次大概率命中页缓存，
    #   实际 I/O 开销接近 0。
    helpful_ids = payload.get("helpful_memories", [])
    misleading_ids = payload.get("misleading_memories", [])
    all_ids = helpful_ids + misleading_ids
    
    if all_ids:
        from .capsule_store import get_capsules_batch
        caps_by_id = get_capsules_batch(
            all_ids,
            owner_id=owner_id,
            soul_id=soul_id,
        )
        
        for cid in helpful_ids:
            if cid in caps_by_id:
                reinforce(cid, owner_id=owner_id, soul_id=soul_id)
                actions.append({"action": "reinforce", "capsule_id": cid})
        
        for cid in misleading_ids:
            if cid in caps_by_id:
                deprecate(cid, owner_id=owner_id, soul_id=soul_id)
                actions.append({"action": "deprecate", "capsule_id": cid})
    
    for risk in payload.get("new_risks", []):
        res = write_capsule(
            memory_class="risk",
            content=risk,
            source_type="eval",
            scene="coding",
            task_type="reflection",
            risk_class="medium",
            owner_id=owner_id,
            soul_id=soul_id,
        )
        actions.append({"action": "promote", "capsule_id": res["capsule_id"], "memory_class": "risk"})
    reflection_id = "refl_" + uuid.uuid4().hex[:12]
    full = {**payload, "evolution_actions": actions}
    with transaction() as conn:
        conn.execute("INSERT INTO memory_reflections VALUES (?,?,?,?)", (reflection_id, task_id, dumps(full), now()))
    audit_id = record("task_reflection", {"reflection_id": reflection_id, "task_id": task_id, "actions": actions})
    return {"reflection_id": reflection_id, "task_id": task_id, "evolution_actions": actions, "audit_id": audit_id}
