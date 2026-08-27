"""Memory Lifecycle 状态机 —— 记忆生命周期的合法转移裁决与副作用编排。

规范来源：``AI优化/MemoryOS-Lifecycle状态机.md``

为什么需要它
------------
本项目此前的 ``state.lifecycle`` 是一个各处直接赋值的自由字符串
（``evolution.reinforce`` / ``deprecate`` / ``conflict_mark`` 直接写、
``capsule_store.forget_capsules_in_transaction`` 也直接写），没有任何一处校验
「这个转移是否合法」。后果是 ``deleted → active``、``forgotten → reinforced``
这类「已删除记忆被复活」的写入无人拦截——对一个以记忆治理为卖点的系统而言，
这是数据完整性缺口，不是风格问题。

状态词表：沿用项目既有词，不照搬规范改名
------------------------------------------
规范给的状态是 ``candidate → active → reinforced → stale → conflicted →
archived → quarantined → deleted``。本项目历史上已经在用一套语义等价但命名不同
的词表，且被 60+ 测试文件与 6 处 SQL 过滤条件钉死。因此这里做**映射而非改名**：

===============  =====================  ==================================
规范状态          本项目状态              说明
===============  =====================  ==================================
archived         ``deprecated``         同义：主动归档 / 自动降权
（无对应）        ``rejected``           策略闸门拒绝，内容从未落 FTS
（deleted 细分）  ``forgotten``          软删（保留行，可升级为硬删）
（deleted 细分）  ``deleted``            硬删（行已消失）
stale            ``stale``              **本次新增**，此前完全不存在
===============  =====================  ==================================

与规范的两处有意偏差（连同理由一起记在此，便于审阅）
----------------------------------------------------
1. **``resolve_conflict`` 的败方默认转 ``deprecated`` 而非规范的 ``deleted``。**
   规范 §2 写的是「loser 进 deleted（账本保留）」。但本项目 ``deleted`` 是硬删
   （行消失），裁决失败的一方直接物理删除会让「为什么当初这么裁决」失去现场证据。
   默认改为可审计的 ``deprecated``，需要物理删除的调用方显式传 ``loser_state``。
2. **``stale`` 是「可检索但降权」而不是「不可检索」。**
   规范原表把 stale 标为「⚠️（低权重或弃权）」，因此这里把 ``stale`` 纳入
   :data:`RETRIEVABLE_STATES`，并在 ``retrieval`` 侧给一个固定分数惩罚，而不是
   直接从候选集里剔除。由于此前库中不存在任何 stale 行，这个改动对既有数据的
   检索行为影响为零。

模块结构
--------
本文件分两段：

- **纯词表段**（枚举 / 转移表 / 常量 / 纯函数）：**不 import 任何
  ``memory_runtime`` 模块**，因此 ``capsule_store`` 可以对它做模块级 import 而
  不产生循环依赖。检索可见性的唯一真相源就在这里
  （:data:`RETRIEVABLE_STATES`），避免 SQL 过滤条件与状态机各持一份而漂移。
- **引擎段**（``apply_transition`` 及其命名封装）：对 ``memory_runtime`` 的依赖
  一律函数内局部 import。
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from ..db import get_conn, transaction
from ..utils.datetime_utils import utc_now_iso_compact

# ===========================================================================
# 纯词表段 —— 以下内容不得 import memory_runtime，capsule_store 依赖它做模块级导入
# ===========================================================================


class LifecycleState(str, Enum):
    """记忆生命周期状态。继承 ``str`` 以便直接与库里存的字符串比较。"""

    CANDIDATE = "candidate"
    ACTIVE = "active"
    REINFORCED = "reinforced"
    STALE = "stale"
    CONFLICTED = "conflicted"
    DEPRECATED = "deprecated"
    QUARANTINED = "quarantined"
    REJECTED = "rejected"
    FORGOTTEN = "forgotten"
    DELETED = "deleted"


_S = LifecycleState

#: 合法转移表。键是当前态，值是允许转入的状态集合。
#:
#: 最关键的一条约束：``FORGOTTEN`` 与 ``DELETED`` 都到不了任何可检索状态——
#: 已遗忘的记忆不可复活。``FORGOTTEN → DELETED`` 是唯一出口（软删升级为硬删）。
TRANSITIONS: dict[LifecycleState, frozenset[LifecycleState]] = {
    _S.CANDIDATE: frozenset({_S.ACTIVE, _S.REJECTED, _S.QUARANTINED, _S.FORGOTTEN, _S.DELETED}),
    _S.ACTIVE: frozenset({
        _S.REINFORCED, _S.STALE, _S.CONFLICTED, _S.DEPRECATED,
        _S.QUARANTINED, _S.FORGOTTEN, _S.DELETED,
    }),
    _S.REINFORCED: frozenset({
        _S.ACTIVE, _S.STALE, _S.CONFLICTED, _S.DEPRECATED,
        _S.QUARANTINED, _S.FORGOTTEN, _S.DELETED,
    }),
    _S.STALE: frozenset({_S.ACTIVE, _S.REINFORCED, _S.DEPRECATED, _S.FORGOTTEN, _S.DELETED}),
    _S.CONFLICTED: frozenset({
        _S.ACTIVE, _S.REINFORCED, _S.DEPRECATED, _S.QUARANTINED, _S.FORGOTTEN, _S.DELETED,
    }),
    # 归档可恢复（规范 §1 archived 允许 restore）
    _S.DEPRECATED: frozenset({_S.ACTIVE, _S.FORGOTTEN, _S.DELETED}),
    # 隔离区放行必须是显式动作（release_quarantine），不会自动发生
    _S.QUARANTINED: frozenset({_S.ACTIVE, _S.REJECTED, _S.FORGOTTEN, _S.DELETED}),
    _S.REJECTED: frozenset({_S.DELETED}),
    _S.FORGOTTEN: frozenset({_S.DELETED}),
    _S.DELETED: frozenset(),
}

#: 可进入检索候选集的状态。**这是检索可见性的唯一真相源**：
#: ``capsule_store.RETRIEVABLE_LIFECYCLE`` 与 ``retrieval`` 的 SQL 过滤条件
#: 都从这里派生，防止两处各写一份 ``IN ('active','reinforced',...)`` 而漂移。
RETRIEVABLE_STATES: frozenset[str] = frozenset({
    _S.ACTIVE.value, _S.REINFORCED.value, _S.CONFLICTED.value, _S.STALE.value,
})

#: 检索时需要降权的状态及其分数惩罚（``retrieval`` 消费）。
#: stale = 已过期或长期未用，规范要求「低权重」而非「弃权」。
RETRIEVAL_SCORE_PENALTY: dict[str, float] = {_S.STALE.value: 0.15}

#: 终态：不可再转出。
TERMINAL_STATES: frozenset[str] = frozenset({_S.DELETED.value})

#: 允许写入 FTS 全文索引的策略闸门结果（与 ``capsule_store`` 写入侧口径一致）。
INDEXABLE_POLICIES: frozenset[str] = frozenset({"allow", "redact"})

#: 高风险任务下额外排除的状态：有冲突未裁决、或已过期的记忆不参与高风险决策。
HIGH_RISK_EXCLUDED_STATES: frozenset[str] = frozenset({
    _S.CONFLICTED.value, _S.STALE.value,
})

#: 允许被「强化」的状态（``evolution.reinforce`` 的前置条件）。
#:
#: 注意 ``conflicted`` **有意不在此列**，尽管转移表允许 conflicted → reinforced。
#: 原因：强化是个自动动作（反思判定 helpful 就会触发），若允许它把
#: conflicted 推成 reinforced，就等于绕过裁决替系统选了一边——直接违反规范
#: 「conflicted 必须裁决，不自动覆盖」这条硬规则。有冲突的记忆必须先走
#: :func:`resolve_conflict`，再谈强化。
#: ``candidate`` / ``deprecated`` / ``quarantined`` 同理需先显式确认、恢复、放行。
REINFORCEABLE_STATES: frozenset[str] = frozenset({
    _S.ACTIVE.value, _S.REINFORCED.value, _S.STALE.value,
})

#: ``state.lifecycle_history`` 在 JSON 里保留的最大条数。
#: 完整历史在 ``memory_ledger`` 账本里，这里只留最近若干条便于就地排查，
#: 不设上限会让 capsule 的 state JSON 随转移次数无限膨胀。
_HISTORY_LIMIT = 20


class IllegalTransitionError(ValueError):
    """非法生命周期转移。

    **有意继承 ``ValueError``**：``app_runtime`` 的 tier 端点与
    ``tier_manager.promote_capsules_for_workflow`` 已有成片的
    ``except ValueError`` 处理链，继承可保证既有错误路径的语义不变，
    调用方想区分时再按具体类型捕获。
    """

    def __init__(self, from_state: str, to_state: str, capsule_id: str | None = None):
        self.from_state = from_state
        self.to_state = to_state
        self.capsule_id = capsule_id
        target = f" for capsule {capsule_id}" if capsule_id else ""
        super().__init__(
            f"Illegal lifecycle transition{target}: {from_state} -> {to_state}. "
            f"Legal targets from {from_state}: "
            f"{sorted(s.value for s in TRANSITIONS.get(_coerce(from_state), frozenset()))}"
        )


def _coerce(state: Any) -> LifecycleState | None:
    """把任意输入归一成 :class:`LifecycleState`，无法识别时返回 ``None``。"""
    if isinstance(state, LifecycleState):
        return state
    try:
        return LifecycleState(str(state))
    except ValueError:
        return None


def can_transition(from_state: Any, to_state: Any) -> bool:
    """判断转移是否合法。未知状态一律视为非法（fail closed）。"""
    src, dst = _coerce(from_state), _coerce(to_state)
    if src is None or dst is None:
        return False
    return dst in TRANSITIONS[src]


def assert_transition(from_state: Any, to_state: Any, *, capsule_id: str | None = None) -> None:
    """校验转移，非法时抛 :class:`IllegalTransitionError`。"""
    if not can_transition(from_state, to_state):
        raise IllegalTransitionError(str(from_state), str(to_state), capsule_id)


def legal_next_states(from_state: Any) -> list[str]:
    """列出当前态的全部合法后继（供 API 与控制台展示）。"""
    src = _coerce(from_state)
    if src is None:
        return []
    return sorted(state.value for state in TRANSITIONS[src])


def is_retrievable(state: Any) -> bool:
    """该状态的记忆是否可进入检索候选集。"""
    return str(state) in RETRIEVABLE_STATES


def retrievable_sql_list() -> str:
    """生成 SQL ``IN`` 子句的字面量列表，如 ``'active','conflicted',...``。

    内容全部来自本模块常量（非用户输入），拼接安全；这样 ``retrieval`` 与
    ``capsule_store`` 的过滤条件不会与状态机定义漂移。
    """
    return ",".join(f"'{state}'" for state in sorted(RETRIEVABLE_STATES))


# ===========================================================================
# 引擎段 —— 以下函数对 memory_runtime 的依赖一律局部 import
# ===========================================================================

# stale 扫描阈值：
# - valid_until 到期永远生效（用户显式设了失效时间，就是要求它过期）；
# - 「长期未访问」默认**关闭**（0 = 禁用）。自动把久未使用的记忆降权会静默改变
#   既有数据的检索表现，属于需要运维显式开启的策略，不做默认行为。
STALE_IDLE_DAYS = float(os.environ.get("WANWEI_LIFECYCLE_STALE_IDLE_DAYS", "0"))


def now() -> str:
    return utc_now_iso_compact()


def _parse_ts(value: Any) -> datetime | None:
    """解析 runtime 写入的 ISO-8601 时间戳（``...Z`` 或带偏移量形式）。

    与 ``tier_manager._parse_ts`` 同一口径；无法解析时返回 ``None``。
    """
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _capsule_text(cap: dict[str, Any]) -> str:
    """复用 ``capsule_store.dumps`` 的序列化口径生成 FTS 文本。

    必须与写入侧完全一致，否则重新索引出来的 FTS 文本与首次写入不同，
    同一查询在「确认前后」会得到不同的匹配结果。
    """
    from ..memory_runtime.capsule_store import dumps

    return dumps(cap.get("content") or {})


def _sync_fts(
    conn,
    capsule_id: str,
    cap: dict[str, Any],
    to_state: str,
    *,
    policy_result: str | None = None,
) -> str:
    """按目标状态同步 FTS 索引。返回 ``indexed`` / ``removed``。

    这里修复了一个既有断链：``capsule_store.write_capsule`` 只在
    ``lifecycle == 'active'`` 时写 FTS，而此前**没有任何代码**把 candidate 或
    quarantined 转成 active 并补写索引——也就是说被确认过的记忆永远搜不到。
    经由本函数转移后，确认即可检索、隔离即不可检索，两条规范验收标准才真正成立。

    ``policy_result`` 允许调用方传入**本次事务内刚结清的**策略结果，
    而不是胶囊读取时的旧值（见 :func:`_resolve_policy_gate_in_transaction`）。

    FTS5 虚拟表没有唯一约束，重复 INSERT 会产生重复行，所以一律先 DELETE 再
    按需 INSERT。
    """
    conn.execute("DELETE FROM memory_capsules_v2_fts WHERE capsule_id=?", (capsule_id,))
    policy = policy_result or (cap.get("governance") or {}).get("policy_result")
    if to_state in RETRIEVABLE_STATES and policy in INDEXABLE_POLICIES:
        conn.execute(
            "INSERT INTO memory_capsules_v2_fts(capsule_id,text) VALUES (?,?)",
            (capsule_id, _capsule_text(cap)),
        )
        return "indexed"
    return "removed"


#: 需要人工结清才能变成可检索的策略闸门结果。
_PENDING_POLICY_RESULTS = frozenset({"require_confirmation", "quarantine"})


def _resolve_policy_gate_in_transaction(
    conn,
    capsule_id: str,
    cap: dict[str, Any],
    *,
    actor: str,
    ts: str,
) -> str | None:
    """人工确认/放行时结清策略闸门，返回结清后的 ``policy_result``。

    **为什么必须做这一步**：本项目的可检索性是**两个轴**共同决定的——
    ``state.lifecycle`` 与 ``governance.policy_result``。检索侧的 SQL 过滤和
    ``allowed_for_context`` 都要求 ``policy_result IN ('allow','redact')``。
    因此仅把 lifecycle 从 candidate 推到 active 是不够的：闸门结果还停在
    ``require_confirmation``，这条记忆依然进不了候选集。换句话说，在结清闸门
    之前，``require_confirmation`` 这条产品路径是一条**死路**——需要确认的记忆
    即使确认了也永远用不上。

    结清方式保留完整审计：原判决存入 ``governance.original_policy_result``，
    并记下 ``resolved_by`` / ``resolved_at``，同时账本里另有 before/after 记录。
    不是「把风险标记抹掉」，而是「记录人已经复核并放行」。
    """
    governance = dict(cap.get("governance") or {})
    current = governance.get("policy_result")
    if current not in _PENDING_POLICY_RESULTS:
        return current
    governance.setdefault("original_policy_result", current)
    governance["policy_result"] = "allow"
    governance["gate_resolved_by"] = actor
    governance["gate_resolved_at"] = ts
    from ..memory_runtime.capsule_store import dumps

    conn.execute(
        "UPDATE memory_capsules_v2 SET governance=? WHERE capsule_id=?",
        (dumps(governance), capsule_id),
    )
    cap["governance"] = governance
    return "allow"


def _append_history(state: dict[str, Any], entry: dict[str, Any]) -> None:
    history = state.get("lifecycle_history")
    if not isinstance(history, list):
        history = []
    history.append(entry)
    state["lifecycle_history"] = history[-_HISTORY_LIMIT:]


def apply_transition(
    capsule_id: str,
    to_state: str,
    reason: str,
    *,
    actor: str = "system",
    owner_id: str | None = None,
    soul_id: str | None = None,
    trace_id: str | None = None,
    state_patch: dict[str, Any] | None = None,
    risk_class: str = "low",
    resolve_policy_gate: bool = False,
) -> dict[str, Any]:
    """执行一次生命周期转移：校验 → 落库 → 同步 FTS → 同事务写账本。

    返回值形状对齐 ``tier_manager._transition``（``from_*`` / ``to_*`` /
    ``changed`` / ``reason`` / ``transitioned_at``），额外带上 ``ledger_id``
    与更新后的 ``capsule``。

    Args:
        to_state: 目标状态。等于当前态时按幂等 no-op 处理（``changed=False``），
            但 ``state_patch`` 仍会落库——``reinforce`` 重复调用要能继续累加
            importance，即使 lifecycle 已经是 ``reinforced``。
        state_patch: 与本次转移一同写入 ``state`` 的附加字段
            （如 ``deprecation_reason`` / ``importance_score``）。
        actor: 账本里的操作者（``human`` / ``agent`` / ``system`` / 插件名）。
        resolve_policy_gate: 人工确认/放行专用。同时结清停留在
            ``require_confirmation`` / ``quarantine`` 的策略闸门，否则记忆虽然
            进了 ``active`` 仍进不了检索候选集（见
            :func:`_resolve_policy_gate_in_transaction`）。

    Raises:
        KeyError: capsule 不存在，或不在调用方的 owner/soul 作用域内。
        IllegalTransitionError: 转移不合法（``ValueError`` 子类）。
    """
    from ..memory_runtime.capsule_store import dumps, get_capsule
    from .governance import append_ledger_in_transaction

    target = _coerce(to_state)
    if target is None:
        raise IllegalTransitionError(str(to_state), str(to_state), capsule_id)

    cap = get_capsule(capsule_id, owner_id=owner_id, soul_id=soul_id)
    if not cap:
        raise KeyError(capsule_id)

    state = dict(cap.get("state") or {})
    from_state = str(state.get("lifecycle") or _S.ACTIVE.value)
    changed = from_state != target.value
    if changed:
        assert_transition(from_state, target, capsule_id=capsule_id)
    elif state_patch is None and not resolve_policy_gate:
        # 完全没有变化：不写库、不记账，避免幂等重试制造账本噪音。
        return {
            "capsule_id": capsule_id,
            "from_state": from_state,
            "to_state": target.value,
            "changed": False,
            "reason": "already_at_target_state",
            "actor": actor,
            "ledger_id": None,
            "capsule": cap,
        }

    before_text = _capsule_text(cap)
    before_policy = (cap.get("governance") or {}).get("policy_result")
    ts = now()
    state.update(state_patch or {})
    state["lifecycle"] = target.value
    if changed:
        _append_history(
            state,
            {"from": from_state, "to": target.value, "reason": reason, "actor": actor, "at": ts},
        )

    with transaction() as conn:
        conn.execute(
            "UPDATE memory_capsules_v2 SET state=?, updated_at=? WHERE capsule_id=?",
            (dumps(state), ts, capsule_id),
        )
        effective_policy = before_policy
        if resolve_policy_gate:
            effective_policy = _resolve_policy_gate_in_transaction(
                conn, capsule_id, cap, actor=actor, ts=ts
            )
        fts_action = _sync_fts(
            conn, capsule_id, cap, target.value, policy_result=effective_policy
        )
        ledger_id = append_ledger_in_transaction(
            conn,
            op_type="transition" if changed else "update",
            capsule_id=capsule_id,
            actor=actor,
            before_state=from_state,
            after_state=target.value,
            before_content=before_text,
            after_content=before_text,  # 转移不改内容，哈希相同即为证据
            reason=(
                f"{reason} | policy_gate:{before_policy}->{effective_policy}"
                if effective_policy != before_policy
                else reason
            ),
            risk_class=risk_class,
            trace_id=trace_id,
            owner_id=owner_id or (cap.get("provenance") or {}).get("owner_id"),
            soul_id=soul_id or (cap.get("provenance") or {}).get("soul_id"),
        )

    updated = get_capsule(capsule_id, owner_id=owner_id, soul_id=soul_id)
    return {
        "capsule_id": capsule_id,
        "from_state": from_state,
        "to_state": target.value,
        "changed": changed,
        "reason": reason,
        "actor": actor,
        "fts": fts_action,
        "policy_result": effective_policy,
        "policy_gate_resolved": effective_policy != before_policy,
        "ledger_id": ledger_id,
        "transitioned_at": ts,
        "capsule": updated,
    }


# ---------------------------------------------------------------------------
# 命名封装：规范 §1 表格里的具体动作
# ---------------------------------------------------------------------------


def confirm_candidate(
    capsule_id: str,
    *,
    actor: str = "human",
    reason: str = "human_confirmed",
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> dict[str, Any]:
    """确认待定记忆：``candidate → active``，结清策略闸门，并补写 FTS。

    对应 policy gate 的 ``require_confirmation`` 结果。三件事必须同时做完，
    少任何一件这条记忆都还是用不上的：

    1. lifecycle 推到 ``active``（否则被生命周期过滤挡掉）
    2. ``policy_result`` 从 ``require_confirmation`` 结清为 ``allow``
       （否则被策略过滤挡掉——见 :func:`_resolve_policy_gate_in_transaction`）
    3. 写入 FTS（否则检索候选集里根本没有它）

    同时把 ``alignment_metadata.confirmation_status`` 从 ``pending`` 推进为
    ``confirmed``，让「谁确认的、什么时候确认的」在胶囊上可见而不只在账本里。
    """
    result = apply_transition(
        capsule_id,
        _S.ACTIVE.value,
        reason,
        actor=actor,
        owner_id=owner_id,
        soul_id=soul_id,
        state_patch={"confirmed_at": now(), "confirmed_by": actor},
        resolve_policy_gate=True,
    )
    _mark_confirmation(capsule_id, "confirmed", owner_id=owner_id, soul_id=soul_id)
    return result


def release_quarantine(
    capsule_id: str,
    *,
    actor: str = "human",
    reason: str = "quarantine_released",
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> dict[str, Any]:
    """放行隔离记忆：``quarantined → active``，结清闸门并补写 FTS。

    规范 §2 把「隔离区记忆不可检索注入」列为安全底线，因此放行必须是显式人工
    动作，不存在任何自动路径。原判决保留在
    ``governance.original_policy_result`` 里——放行不是抹掉风险标记，而是记录
    「人已复核并承担这个决定」，账本另有 before/after 双向证据。
    """
    result = apply_transition(
        capsule_id,
        _S.ACTIVE.value,
        reason,
        actor=actor,
        owner_id=owner_id,
        soul_id=soul_id,
        risk_class="medium",
        state_patch={"released_at": now(), "released_by": actor},
        resolve_policy_gate=True,
    )
    _mark_confirmation(capsule_id, "confirmed", owner_id=owner_id, soul_id=soul_id)
    return result


def quarantine(
    capsule_id: str,
    reason: str,
    *,
    actor: str = "system",
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> dict[str, Any]:
    """移入隔离区并从 FTS 摘除（投毒检测 / 敏感未脱敏 / 无法自动裁决的冲突）。"""
    return apply_transition(
        capsule_id,
        _S.QUARANTINED.value,
        reason,
        actor=actor,
        owner_id=owner_id,
        soul_id=soul_id,
        risk_class="medium",
        state_patch={"quarantined_at": now(), "quarantine_reason": reason},
    )


def mark_stale(
    capsule_id: str,
    reason: str = "valid_until_expired",
    *,
    actor: str = "system",
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> dict[str, Any]:
    """标记为过期。stale 仍可检索但会被降权（见 :data:`RETRIEVAL_SCORE_PENALTY`）。"""
    return apply_transition(
        capsule_id,
        _S.STALE.value,
        reason,
        actor=actor,
        owner_id=owner_id,
        soul_id=soul_id,
        state_patch={"stale_at": now(), "stale_reason": reason},
    )


def refresh(
    capsule_id: str,
    *,
    actor: str = "human",
    reason: str = "refreshed",
    valid_until: str | None = None,
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> dict[str, Any]:
    """把过期记忆刷回活跃：``stale → active``，可同时续期 ``valid_until``。"""
    patch: dict[str, Any] = {"refreshed_at": now(), "stale_reason": None}
    if valid_until is not None:
        patch["valid_until"] = valid_until
    return apply_transition(
        capsule_id, _S.ACTIVE.value, reason,
        actor=actor, owner_id=owner_id, soul_id=soul_id, state_patch=patch,
    )


def archive(
    capsule_id: str,
    reason: str = "archived",
    *,
    actor: str = "system",
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> dict[str, Any]:
    """归档（规范中的 ``archived``，本项目叫 ``deprecated``）：不再进入上下文。"""
    return apply_transition(
        capsule_id, _S.DEPRECATED.value, reason,
        actor=actor, owner_id=owner_id, soul_id=soul_id,
        state_patch={"deprecation_reason": reason},
    )


def restore(
    capsule_id: str,
    *,
    actor: str = "human",
    reason: str = "restored",
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> dict[str, Any]:
    """从归档恢复：``deprecated → active``，并补回 FTS。"""
    return apply_transition(
        capsule_id, _S.ACTIVE.value, reason,
        actor=actor, owner_id=owner_id, soul_id=soul_id,
        state_patch={"deprecation_reason": None, "restored_at": now()},
    )


def detect_and_mark_conflict(
    new_capsule_id: str,
    existing_capsule_id: str,
    reason: str,
    *,
    actor: str = "system",
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> dict[str, Any]:
    """新旧事实矛盾：两侧同时进 ``conflicted``，等待显式裁决。

    规范 §2 的硬规则是「conflicted 必须裁决，不自动覆盖」——因此这里只标记，
    绝不替调用方选一个赢家。
    """
    results = []
    for capsule_id in (new_capsule_id, existing_capsule_id):
        results.append(
            apply_transition(
                capsule_id, _S.CONFLICTED.value, reason,
                actor=actor, owner_id=owner_id, soul_id=soul_id,
                risk_class="medium",
                state_patch={"conflict_reason": reason, "conflicts_with": (
                    existing_capsule_id if capsule_id == new_capsule_id else new_capsule_id
                )},
            )
        )
    return {"reason": reason, "marked": results}


def resolve_conflict(
    winner_id: str,
    loser_id: str,
    reason: str,
    *,
    actor: str = "human",
    loser_state: str = _S.DEPRECATED.value,
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> dict[str, Any]:
    """裁决冲突：赢家回 ``active``，败方转 ``loser_state``（默认归档）。

    同时维护规范要求的版本链：赢家 ``state.supersedes`` 追加败方 id，
    败方 ``state.superseded_by`` 追加赢家 id。这两个字段在
    ``write_capsule`` 里就已存在，此处只是第一次真正被写。

    默认把败方归档而不是删除的理由见模块 docstring「有意偏差」第 1 条。
    """
    from ..memory_runtime.capsule_store import get_capsule

    winner = get_capsule(winner_id, owner_id=owner_id, soul_id=soul_id)
    loser = get_capsule(loser_id, owner_id=owner_id, soul_id=soul_id)
    if not winner:
        raise KeyError(winner_id)
    if not loser:
        raise KeyError(loser_id)

    supersedes = list((winner.get("state") or {}).get("supersedes") or [])
    if loser_id not in supersedes:
        supersedes.append(loser_id)
    superseded_by = list((loser.get("state") or {}).get("superseded_by") or [])
    if winner_id not in superseded_by:
        superseded_by.append(winner_id)

    winner_result = apply_transition(
        winner_id, _S.ACTIVE.value, f"resolve_win: {reason}",
        actor=actor, owner_id=owner_id, soul_id=soul_id,
        state_patch={"supersedes": supersedes, "conflict_reason": None},
    )
    loser_result = apply_transition(
        loser_id, loser_state, f"resolve_lose: {reason}",
        actor=actor, owner_id=owner_id, soul_id=soul_id,
        state_patch={"superseded_by": superseded_by, "conflict_reason": None,
                     "deprecation_reason": f"superseded_by:{winner_id}"},
    )
    return {"reason": reason, "winner": winner_result, "loser": loser_result}


# ---------------------------------------------------------------------------
# 过期扫描
# ---------------------------------------------------------------------------


def _valid_until(cap: dict[str, Any]) -> datetime | None:
    """读取失效时间：``state.valid_until`` 优先，回退 ``provenance.valid_until``。

    两处都放是因为 ``write_capsule`` 允许调用方自带 provenance，而 ``refresh``
    续期写的是 state；读取时都认，避免哪边写的哪边才生效。
    """
    state = cap.get("state") or {}
    provenance = cap.get("provenance") or {}
    return _parse_ts(state.get("valid_until")) or _parse_ts(provenance.get("valid_until"))


def scan_stale(
    *,
    reference_time: datetime | None = None,
    idle_days: float | None = None,
    limit: int = 500,
    owner_id: str | None = None,
    soul_id: str | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    """扫描并标记过期记忆（规范 §4 的「valid_until 定时任务」集成点）。

    两条判定，按顺序：

    1. ``valid_until`` 已到期 —— **始终生效**。用户显式设了失效时间就是要求它过期。
    2. 距上次访问超过 ``idle_days`` 天 —— **默认关闭**
       （``WANWEI_LIFECYCLE_STALE_IDLE_DAYS`` 默认 0 = 禁用）。自动把久未使用的
       记忆降权会静默改变既有数据的检索表现，属于需要运维显式开启的策略。
       传 ``idle_days`` 参数可单次开启。

    只处理 ``active`` / ``reinforced``，每条最多标记一次。
    """
    from ..memory_runtime.capsule_store import _row_to_capsule

    now_dt = (reference_time or datetime.now(timezone.utc)).astimezone(timezone.utc)
    threshold_days = STALE_IDLE_DAYS if idle_days is None else idle_days

    clauses = ["json_extract(state,'$.lifecycle') IN ('active','reinforced')"]
    params: list[Any] = []
    if owner_id is not None:
        clauses.append("json_extract(provenance,'$.owner_id')=?")
        params.append(owner_id)
    if soul_id is not None:
        clauses.append(
            "(json_extract(provenance,'$.soul_id')=? "
            "OR json_extract(provenance,'$.soul_id') IS NULL)"
        )
        params.append(soul_id)
    rows = get_conn().execute(
        f"SELECT * FROM memory_capsules_v2 WHERE {' AND '.join(clauses)} "
        "ORDER BY updated_at ASC LIMIT ?",
        [*params, limit],
    ).fetchall()

    marked: list[dict[str, Any]] = []
    scanned = 0
    for row in rows:
        scanned += 1
        cap = _row_to_capsule(row)
        expiry = _valid_until(cap)
        reason: str | None = None
        if expiry is not None and expiry <= now_dt:
            reason = "valid_until_expired"
        elif threshold_days > 0:
            state = cap.get("state") or {}
            last = (
                _parse_ts(state.get("last_accessed_at"))
                or _parse_ts(cap.get("updated_at"))
                or _parse_ts(cap.get("created_at"))
            )
            if last is not None and now_dt - last >= timedelta(days=threshold_days):
                reason = f"idle_for>{threshold_days:g}d"
        if reason is None:
            continue
        marked.append(
            mark_stale(
                cap["capsule_id"], reason,
                actor=actor, owner_id=owner_id, soul_id=soul_id,
            )
        )

    return {
        "reference_time": now_dt.isoformat(),
        "scanned": scanned,
        "marked": marked,
        "marked_count": len(marked),
        "idle_days": threshold_days,
        "idle_scan_enabled": threshold_days > 0,
    }


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------


def _mark_confirmation(
    capsule_id: str,
    status: str,
    *,
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> None:
    """更新 ``alignment_metadata.confirmation_status``（就地 JSON patch）。"""
    scope = ""
    params: list[Any] = [status, now(), capsule_id]
    if owner_id is not None:
        scope += " AND json_extract(provenance,'$.owner_id')=?"
        params.append(owner_id)
    if soul_id is not None:
        scope += (
            " AND (json_extract(provenance,'$.soul_id')=? "
            "OR json_extract(provenance,'$.soul_id') IS NULL)"
        )
        params.append(soul_id)
    with transaction() as conn:
        conn.execute(
            "UPDATE memory_capsules_v2 "
            "SET alignment_metadata=json_set(alignment_metadata,'$.confirmation_status',?), "
            "    updated_at=? "
            f"WHERE capsule_id=?{scope}",
            params,
        )


def lifecycle_status(
    capsule_id: str,
    *,
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> dict[str, Any] | None:
    """当前状态 + 合法后继 + 就地历史（完整历史见 ``governance.ledger_history``）。"""
    from ..memory_runtime.capsule_store import get_capsule

    cap = get_capsule(capsule_id, owner_id=owner_id, soul_id=soul_id)
    if not cap:
        return None
    state = cap.get("state") or {}
    current = str(state.get("lifecycle") or _S.ACTIVE.value)
    return {
        "capsule_id": capsule_id,
        "lifecycle": current,
        "retrievable": is_retrievable(current),
        "terminal": current in TERMINAL_STATES,
        "legal_next_states": legal_next_states(current),
        "history": state.get("lifecycle_history") or [],
        "valid_until": state.get("valid_until") or (cap.get("provenance") or {}).get("valid_until"),
        "supersedes": state.get("supersedes") or [],
        "superseded_by": state.get("superseded_by") or [],
    }


def state_counts(
    *,
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> dict[str, int]:
    """全库各生命周期状态计数（Health 面板的基础输入）。"""
    clauses: list[str] = []
    params: list[Any] = []
    if owner_id is not None:
        clauses.append("json_extract(provenance,'$.owner_id')=?")
        params.append(owner_id)
    if soul_id is not None:
        clauses.append(
            "(json_extract(provenance,'$.soul_id')=? "
            "OR json_extract(provenance,'$.soul_id') IS NULL)"
        )
        params.append(soul_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = get_conn().execute(
        "SELECT COALESCE(json_extract(state,'$.lifecycle'),'active') AS lifecycle, "
        f"COUNT(*) AS n FROM memory_capsules_v2 {where} GROUP BY 1",
        params,
    ).fetchall()
    counts = {state.value: 0 for state in LifecycleState}
    for row in rows:
        counts[row["lifecycle"]] = counts.get(row["lifecycle"], 0) + row["n"]
    return counts


__all__ = [
    "HIGH_RISK_EXCLUDED_STATES",
    "INDEXABLE_POLICIES",
    "IllegalTransitionError",
    "LifecycleState",
    "RETRIEVABLE_STATES",
    "RETRIEVAL_SCORE_PENALTY",
    "TERMINAL_STATES",
    "TRANSITIONS",
    "apply_transition",
    "archive",
    "assert_transition",
    "can_transition",
    "confirm_candidate",
    "detect_and_mark_conflict",
    "is_retrievable",
    "legal_next_states",
    "lifecycle_status",
    "mark_stale",
    "quarantine",
    "refresh",
    "release_quarantine",
    "resolve_conflict",
    "restore",
    "retrievable_sql_list",
    "scan_stale",
    "state_counts",
]
