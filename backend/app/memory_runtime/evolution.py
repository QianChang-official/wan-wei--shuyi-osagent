import uuid
from typing import Any
from ..db import get_conn, transaction
from ..audit.service import record
from ..memoryos.lifecycle import (
    REINFORCEABLE_STATES,
    IllegalTransitionError,
    LifecycleState,
    apply_transition,
)
from .capsule_store import get_capsule, update_capsule, write_capsule, dumps, now


def reinforce(
    capsule_id: str,
    amount: float = 0.1,
    *,
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> dict[str, Any]:
    """强化一条记忆：提高 importance / retention，并按状态机推进生命周期。

    可强化的状态见 ``memoryos.lifecycle.REINFORCEABLE_STATES``：
    ``active`` 会被推进到 ``reinforced``；``reinforced`` 与 ``stale`` 原地累加
    权重（``stale`` 被重新用到本身就是它还有价值的信号，但要刷新回 active 得走
    显式 ``refresh``）。其余状态一律拒绝：

    - ``conflicted`` 必须先裁决——否则自动强化就等于绕过裁决替系统选边；
    - ``candidate`` / ``quarantined`` / ``deprecated`` 必须先确认、放行、恢复；
    - ``forgotten`` / ``deleted`` / ``rejected`` 是终态，已遗忘的记忆不可复活。

    与改造前的差别：旧实现对非 active 状态是「把原状态写回、静默成功」
    （``"reinforced" if lifecycle == "active" else lifecycle``），因此对一条
    已遗忘的记忆调用 reinforce 会假装成功。现在会抛
    :class:`IllegalTransitionError`（``ValueError`` 子类，既有 except 链不受影响）。
    """
    cap = get_capsule(capsule_id, owner_id=owner_id, soul_id=soul_id)
    if not cap:
        raise ValueError(f"Capsule not found: {capsule_id}")
    st = dict(cap["state"])
    current = str(st.get("lifecycle") or LifecycleState.ACTIVE.value)
    if current not in REINFORCEABLE_STATES:
        raise IllegalTransitionError(current, LifecycleState.REINFORCED.value, capsule_id)
    patch = {
        "importance_score": min(1.0, float(st.get("importance_score", 0.5)) + amount),
        "retention_score": min(1.0, float(st.get("retention_score", 0.5)) + amount),
    }
    # active → reinforced 是唯一改变状态的情形；reinforced/stale 原地累加权重。
    target = (
        LifecycleState.REINFORCED.value
        if current == LifecycleState.ACTIVE.value
        else current
    )
    result = apply_transition(
        capsule_id, target, f"reinforce(+{amount})",
        actor="agent", owner_id=owner_id, soul_id=soul_id, state_patch=patch,
    )
    return result["capsule"]


def deprecate(
    capsule_id: str,
    reason: str = "misleading",
    *,
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> dict[str, Any]:
    """归档一条记忆（规范中的 ``archived``），不再进入上下文注入。

    Raises:
        IllegalTransitionError: 从 ``deleted`` / ``forgotten`` / ``rejected``
            归档——这些终态没有可归档的内容。
    """
    cap = get_capsule(capsule_id, owner_id=owner_id, soul_id=soul_id)
    if not cap:
        raise ValueError(f"Capsule not found: {capsule_id}")
    result = apply_transition(
        capsule_id, LifecycleState.DEPRECATED.value, reason,
        actor="agent", owner_id=owner_id, soul_id=soul_id,
        state_patch={"deprecation_reason": reason},
    )
    return result["capsule"]


def conflict_mark(capsule_id: str, reason: str = "conflict") -> dict[str, Any]:
    """标记为冲突待裁决。裁决走 ``memoryos.lifecycle.resolve_conflict``。"""
    cap = get_capsule(capsule_id)
    if not cap:
        raise ValueError(f"Capsule not found: {capsule_id}")
    result = apply_transition(
        capsule_id, LifecycleState.CONFLICTED.value, reason,
        actor="agent", risk_class="medium",
        state_patch={"conflict_reason": reason},
    )
    return result["capsule"]


def supersede(old_capsule_id: str, *, new_content: dict[str, Any], memory_class: str = "knowledge") -> dict[str, Any]:
    old = get_capsule(old_capsule_id)
    if not old:
        raise ValueError(f"Capsule not found: {old_capsule_id}")
    new = write_capsule(memory_class=memory_class, content=new_content, source_type="eval", write_intent="explicit")
    old_state = old["state"]
    superseded_by = list(old_state.get("superseded_by") or [])
    superseded_by.append(new["capsule_id"])
    apply_transition(
        old_capsule_id, LifecycleState.DEPRECATED.value,
        f"superseded_by:{new['capsule_id']}",
        actor="agent",
        state_patch={
            "superseded_by": superseded_by,
            "deprecation_reason": f"superseded_by:{new['capsule_id']}",
        },
    )
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
    return update_capsule(new["capsule_id"], state=st, reason=f"supersedes:{old_capsule_id}")


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
        from ..memoryos.accounting import settle_recall_outcome
        from .capsule_store import get_capsules_batch
        caps_by_id = get_capsules_batch(
            all_ids,
            owner_id=owner_id,
            soul_id=soul_id,
        )

        # 单条记忆的生命周期已到终态（已遗忘/已删除）时，状态机会拒绝强化或归档。
        # 这属于业务上完全正常的情形——反思报告可能引用了本轮中途被用户删掉的
        # 记忆——因此逐条捕获并记入 actions，不让一条失败掀翻整次反思。
        settled_useful: list[str] = []
        settled_harmful: list[str] = []
        for cid in helpful_ids:
            if cid not in caps_by_id:
                continue
            try:
                reinforce(cid, owner_id=owner_id, soul_id=soul_id)
            except IllegalTransitionError as exc:
                actions.append({"action": "reinforce_skipped", "capsule_id": cid,
                                "reason": f"{exc.from_state}->{exc.to_state}"})
                continue
            actions.append({"action": "reinforce", "capsule_id": cid})
            settled_useful.append(cid)

        for cid in misleading_ids:
            if cid not in caps_by_id:
                continue
            try:
                deprecate(cid, owner_id=owner_id, soul_id=soul_id)
            except IllegalTransitionError as exc:
                actions.append({"action": "deprecate_skipped", "capsule_id": cid,
                                "reason": f"{exc.from_state}->{exc.to_state}"})
                continue
            actions.append({"action": "deprecate", "capsule_id": cid})
            settled_harmful.append(cid)

        # 经济账本的收益回填。这是 Accounting 规范里 utility 的**真实来源**：
        # 检索时只能先记 neutral（当下不知道有没有用），反思阶段人/评估器判定了
        # helpful / misleading，才能把那次召回改判为 useful / harmful。
        # 不需要任何新的用户输入——reflect_task 本来就在收集这两个列表。
        if settled_useful:
            settle_recall_outcome(settled_useful, "useful")
            actions.append({"action": "account_settle", "outcome": "useful",
                            "capsule_ids": settled_useful})
        if settled_harmful:
            settle_recall_outcome(settled_harmful, "harmful")
            actions.append({"action": "account_settle", "outcome": "harmful",
                            "capsule_ids": settled_harmful})

        # #56: workflow/任务完成回调——本轮被判定 helpful 的记忆从 working 层
        # 晋升 short_term，让「用得上的记忆」自动进入短期待复用区。
        # 局部 import 避免模块级耦合（tier_manager 依赖 capsule_store）。
        if helpful_ids:
            from .tier_manager import promote_capsules_for_workflow

            tier_results = promote_capsules_for_workflow(
                helpful_ids,
                reason="workflow_reflection",
                owner_id=owner_id,
                soul_id=soul_id,
            )
            promoted = [r for r in tier_results if r.get("changed")]
            if promoted:
                actions.append(
                    {
                        "action": "tier_promote",
                        "to_tier": "short_term",
                        "capsule_ids": [r["capsule_id"] for r in promoted],
                    }
                )
    
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
