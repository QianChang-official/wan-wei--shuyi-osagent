"""Memory tier management: promotion/demotion for short/mid/long-term memory.

对应 GitHub issue #56: 短期/中期记忆自动流转机制
赛题要求(6): 兼容与记忆模块中短期、中期记忆间的数据流转

Tier 流转顺序: working → short_term → medium_term → long_term（可跳档）

存储约定:
- tier 持久化在 ``memory_capsules_v2.memory_tier`` 列（``write_capsule`` 写入时
  默认 ``'working'``）。本模块不引入第二个 tier 列——初版 MVP 曾误加 ``tier``
  列，已由 ``init_db._migrate_tier_unification`` 统一回收。
- 活跃度信号保存在 ``state`` JSON 内: ``usage_count`` / ``last_accessed_at`` /
  ``importance_score`` / ``lifecycle``。
- 每次流转同时写 ``tier_transition_log`` 表与 audit service，双通道可追溯。
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from ..db import get_conn, transaction
from ..audit.service import record, record_in_transaction
from .capsule_store import get_capsule, now

logger = logging.getLogger(__name__)

VALID_TIERS = ("working", "short_term", "medium_term", "long_term")
_TIER_RANK = {tier: rank for rank, tier in enumerate(VALID_TIERS)}

# ---- 自动流转阈值（可用环境变量覆盖，便于真机调参与测试） -------------------
# working → short_term: 闲置超过该时长（小时）
WORKING_IDLE_HOURS = float(os.environ.get("WANWEI_TIER_WORKING_IDLE_HOURS", "24"))
# short_term 过期: 超过该时长（小时）未访问则降回 working
SHORT_TERM_TTL_HOURS = float(os.environ.get("WANWEI_TIER_SHORT_TERM_TTL_HOURS", "24"))
# short_term → medium_term: 累计使用次数达到该阈值
MEDIUM_USAGE_THRESHOLD = int(os.environ.get("WANWEI_TIER_MEDIUM_USAGE", "5"))
# short_term → medium_term: 或 capsule 存活超过该天数且期间仍被访问
MEDIUM_ACTIVE_DAYS = float(os.environ.get("WANWEI_TIER_MEDIUM_ACTIVE_DAYS", "7"))
# medium_term 闲置超过该天数降回 short_term
MEDIUM_IDLE_DAYS = float(os.environ.get("WANWEI_TIER_MEDIUM_IDLE_DAYS", "7"))
# medium_term → long_term: importance_score 达到该阈值
LONG_TERM_IMPORTANCE = float(os.environ.get("WANWEI_TIER_LONG_IMPORTANCE", "0.8"))

# 只有这些 lifecycle 参与自动流转；quarantined/forgotten/deprecated 等不动
_FLOWABLE_LIFECYCLES = ("active", "reinforced")


def _validate_tier(tier: str) -> None:
    if tier not in _TIER_RANK:
        raise ValueError(f"Invalid tier: {tier!r}, must be one of {VALID_TIERS}")


def _parse_ts(value: Any) -> datetime | None:
    """Parse ISO-8601 timestamps stored by the runtime (``...Z`` or offset form).

    Returns an aware UTC datetime, or None when missing/unparseable.
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


def _last_activity(cap: dict[str, Any]) -> datetime | None:
    """Last activity = state.last_accessed_at, falling back to updated_at/created_at."""
    state = cap.get("state") or {}
    return (
        _parse_ts(state.get("last_accessed_at"))
        or _parse_ts(cap.get("updated_at"))
        or _parse_ts(cap.get("created_at"))
    )


def _transition(
    capsule_id: str,
    to_tier: str,
    reason: str,
    *,
    direction: str,
    trigger_source: str,
    owner_id: str | None,
    soul_id: str | None,
    prefetched: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Shared implementation for promote/demote.

    单事务完成: 读取当前 tier（带 owner/soul 作用域）→ 方向与幂等校验 →
    更新 memory_tier → 写 tier_transition_log → audit 行同事务落库。

    ``prefetched``: 调用方已按作用域过滤查询出的 capsule 数据（至少含
    ``memory_tier``），传入后跳过内部 get_capsule 重查——``run_auto_flow``
    批量场景借此避免每条一次冗余 round-trip。
    """
    _validate_tier(to_tier)
    cap = prefetched if prefetched is not None else get_capsule(
        capsule_id, owner_id=owner_id, soul_id=soul_id
    )
    if not cap:
        raise ValueError(f"Capsule {capsule_id} not found")

    from_tier = cap.get("memory_tier") or "working"
    if from_tier == to_tier:
        return {
            "capsule_id": capsule_id,
            "from_tier": from_tier,
            "to_tier": to_tier,
            "changed": False,
            "reason": "already_at_target_tier",
            "trigger_source": trigger_source,
        }

    from_rank, to_rank = _TIER_RANK[from_tier], _TIER_RANK[to_tier]
    if direction == "promote" and to_rank < from_rank:
        raise ValueError(
            f"tier_promote() cannot move {from_tier} → {to_tier} (downgrade); "
            "use tier_demote() instead"
        )
    if direction == "demote" and to_rank > from_rank:
        raise ValueError(
            f"tier_demote() cannot move {from_tier} → {to_tier} (upgrade); "
            "use tier_promote() instead"
        )

    ts = now()
    with transaction() as conn:
        conn.execute(
            "UPDATE memory_capsules_v2 SET memory_tier=?, updated_at=? WHERE capsule_id=?",
            (to_tier, ts, capsule_id),
        )
        conn.execute(
            """
            INSERT INTO tier_transition_log
                (capsule_id, from_tier, to_tier, reason, trigger_source, created_at)
            VALUES (?,?,?,?,?,?)
            """,
            (capsule_id, from_tier, to_tier, reason, trigger_source, ts),
        )
        # 审计行与业务更新同事务提交：任一失败整体回滚，
        # 保证「tier 变更 ⇔ 审计记录」双通道不脱节。
        record_in_transaction(
            conn,
            "tier_transition",
            {
                "capsule_id": capsule_id,
                "from_tier": from_tier,
                "to_tier": to_tier,
                "reason": reason,
                "trigger_source": trigger_source,
            },
        )
    return {
        "capsule_id": capsule_id,
        "from_tier": from_tier,
        "to_tier": to_tier,
        "changed": True,
        "reason": reason,
        "trigger_source": trigger_source,
        "transitioned_at": ts,
    }


def tier_promote(
    capsule_id: str,
    to_tier: str,
    reason: str,
    trigger_source: str = "manual",
    *,
    owner_id: str | None = None,
    soul_id: str | None = None,
    prefetched: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Promote a capsule to a higher tier (working → … → long_term, 可跳档).

    Raises:
        ValueError: tier 非法、capsule 不存在、或目标 tier 低于当前 tier（此时
            应使用 :func:`tier_demote`）。
    """
    return _transition(
        capsule_id,
        to_tier,
        reason,
        direction="promote",
        trigger_source=trigger_source,
        owner_id=owner_id,
        soul_id=soul_id,
        prefetched=prefetched,
    )


def tier_demote(
    capsule_id: str,
    to_tier: str,
    reason: str,
    trigger_source: str = "manual",
    *,
    owner_id: str | None = None,
    soul_id: str | None = None,
    prefetched: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Demote a capsule to a lower tier（长时间未访问/空间回收/过期清理）。

    Raises:
        ValueError: tier 非法、capsule 不存在、或目标 tier 高于当前 tier（此时
            应使用 :func:`tier_promote`）。
    """
    return _transition(
        capsule_id,
        to_tier,
        reason,
        direction="demote",
        trigger_source=trigger_source,
        owner_id=owner_id,
        soul_id=soul_id,
        prefetched=prefetched,
    )


def promote_capsules_for_workflow(
    capsule_ids: list[str],
    *,
    reason: str = "workflow_completed",
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> list[dict[str, Any]]:
    """workflow 完成回调：把本轮用到的 working 层 capsule 批量晋升 short_term。

    已是更高 tier 的 capsule 保持不动；单条业务失败（not_found 等）不影响
    其余。系统级异常（DB 故障等）记 warning 日志并以
    ``system_error:{类型名}`` 标记，与业务拒绝可区分。
    """
    results: list[dict[str, Any]] = []
    for cid in capsule_ids:
        try:
            cap = get_capsule(cid, owner_id=owner_id, soul_id=soul_id)
            if not cap:
                results.append({"capsule_id": cid, "changed": False, "reason": "not_found"})
                continue
            current = cap.get("memory_tier") or "working"
            if current != "working":
                results.append(
                    {"capsule_id": cid, "changed": False, "reason": f"already_{current}"}
                )
                continue
            results.append(
                tier_promote(
                    cid,
                    "short_term",
                    reason,
                    trigger_source="workflow_callback",
                    owner_id=owner_id,
                    soul_id=soul_id,
                    prefetched=cap,
                )
            )
        except ValueError as exc:  # 业务校验失败：非法参数/状态，正常记入结果
            results.append({"capsule_id": cid, "changed": False, "reason": f"error:{exc}"})
        except Exception as exc:  # 系统级故障：留日志，类型名可见，不阻断批量
            logger.warning("workflow tier promote failed for %s: %s", cid, exc)
            results.append(
                {
                    "capsule_id": cid,
                    "changed": False,
                    "reason": f"system_error:{type(exc).__name__}",
                }
            )
    return results


def _decide_auto_action(
    cap: dict[str, Any], now_dt: datetime
) -> tuple[str, str, str] | None:
    """按 #56 规则表为单条 capsule 判定本轮动作（一轮最多动一次）。

    返回 (direction, to_tier, reason) 或 None。
    优先级: 过期/闲置降级 > 晋升，避免同一轮内来回抖动。
    """
    tier = cap.get("memory_tier") or "working"
    state = cap.get("state") or {}
    last_active = _last_activity(cap)
    usage_count = int(state.get("usage_count") or 0)
    importance = float(state.get("importance_score") or 0.0)
    created = _parse_ts(cap.get("created_at"))

    if tier == "working":
        if last_active and now_dt - last_active >= timedelta(hours=WORKING_IDLE_HOURS):
            return (
                "promote",
                "short_term",
                f"idle_for>{WORKING_IDLE_HOURS:g}h",
            )
    elif tier == "short_term":
        if last_active and now_dt - last_active >= timedelta(hours=SHORT_TERM_TTL_HOURS):
            return (
                "demote",
                "working",
                f"short_term_expired>{SHORT_TERM_TTL_HOURS:g}h_idle",
            )
        if usage_count >= MEDIUM_USAGE_THRESHOLD:
            return (
                "promote",
                "medium_term",
                f"usage_count>={MEDIUM_USAGE_THRESHOLD}",
            )
        if (
            created
            and now_dt - created >= timedelta(days=MEDIUM_ACTIVE_DAYS)
            and _parse_ts(state.get("last_accessed_at"))
        ):
            return (
                "promote",
                "medium_term",
                f"active_for>{MEDIUM_ACTIVE_DAYS:g}d",
            )
    elif tier == "medium_term":
        if importance >= LONG_TERM_IMPORTANCE:
            return (
                "promote",
                "long_term",
                f"importance>={LONG_TERM_IMPORTANCE:g}",
            )
        if last_active and now_dt - last_active >= timedelta(days=MEDIUM_IDLE_DAYS):
            return (
                "demote",
                "short_term",
                f"medium_idle>{MEDIUM_IDLE_DAYS:g}d",
            )
    return None


def run_auto_flow(
    *,
    reference_time: datetime | None = None,
    owner_id: str | None = None,
    soul_id: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """执行一轮自动流转（tier_lifecycle_scheduler 的单次 tick / 手动触发入口）。

    规则（对应 issue #56 的流转表）:

    ============  ==========================================================
    流转           触发条件
    ============  ==========================================================
    working→short   闲置 ≥ ``WORKING_IDLE_HOURS``（默认 24h）
    short→working   超过 ``SHORT_TERM_TTL_HOURS`` 未访问（过期回收，不丢数据）
    short→medium    ``usage_count ≥ MEDIUM_USAGE_THRESHOLD``（默认 5）或
                    存活 ≥ ``MEDIUM_ACTIVE_DAYS`` 天且期间仍被访问
    medium→short    闲置 ≥ ``MEDIUM_IDLE_DAYS``（默认 7 天）
    medium→long     ``importance_score ≥ LONG_TERM_IMPORTANCE``（默认 0.8）
    ============  ==========================================================

    每条 capsule 一轮最多执行一个动作；只处理 lifecycle ∈ active/reinforced。
    """
    now_dt = (reference_time or datetime.now(timezone.utc)).astimezone(timezone.utc)
    scope_sql = ""
    params: list[Any] = []
    if owner_id is not None:
        scope_sql += " AND json_extract(provenance,'$.owner_id') = ?"
        params.append(owner_id)
    if soul_id is not None:
        scope_sql += " AND json_extract(provenance,'$.soul_id') = ?"
        params.append(soul_id)
    lifecycle_placeholders = ",".join("?" for _ in _FLOWABLE_LIFECYCLES)
    rows = get_conn().execute(
        f"""
        SELECT capsule_id, memory_tier, state, created_at, updated_at
        FROM memory_capsules_v2
        WHERE json_extract(state,'$.lifecycle') IN ({lifecycle_placeholders})
          {scope_sql}
        ORDER BY updated_at ASC
        LIMIT ?
        """,
        [*_FLOWABLE_LIFECYCLES, *params, limit],
    ).fetchall()

    promoted: list[dict[str, Any]] = []
    demoted: list[dict[str, Any]] = []
    skipped = 0
    for row in rows:
        try:
            state = json.loads(row["state"]) if row["state"] else {}
        except (TypeError, json.JSONDecodeError):
            state = {}
        cap = {
            "capsule_id": row["capsule_id"],
            "memory_tier": row["memory_tier"],
            "state": state,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        decision = _decide_auto_action(cap, now_dt)
        if decision is None:
            skipped += 1
            continue
        direction, to_tier, reason = decision
        mover = tier_promote if direction == "promote" else tier_demote
        # 传入本轮已按作用域过滤查出的数据，跳过 _transition 内部重查，
        # 避免批量场景下每条一次冗余 round-trip。
        result = mover(
            cap["capsule_id"],
            to_tier,
            reason,
            trigger_source="auto_flow",
            owner_id=owner_id,
            soul_id=soul_id,
            prefetched=cap,
        )
        (promoted if direction == "promote" else demoted).append(result)

    summary = {
        "reference_time": now_dt.isoformat(),
        "scanned": len(rows),
        "promoted": promoted,
        "demoted": demoted,
        "skipped": skipped,
    }
    record(
        "tier_auto_flow",
        {
            "scanned": len(rows),
            "promoted_count": len(promoted),
            "demoted_count": len(demoted),
            "skipped": skipped,
        },
    )
    return summary


def list_capsules_by_tier(
    tier: str,
    *,
    limit: int = 50,
    offset: int = 0,
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> list[dict[str, Any]]:
    """按 tier 列出 capsule（供 GET /memory/tier/{tier} 使用）。

    与 ``list_capsules`` 同一可见性口径：排除 forgotten/deleted/rejected/
    quarantined/candidate，且 policy_result ∈ allow/redact。
    """
    _validate_tier(tier)
    scope_sql = ""
    params: list[Any] = [tier]
    if owner_id is not None:
        scope_sql += " AND json_extract(provenance,'$.owner_id') = ?"
        params.append(owner_id)
    if soul_id is not None:
        scope_sql += " AND json_extract(provenance,'$.soul_id') = ?"
        params.append(soul_id)
    rows = get_conn().execute(
        f"""
        SELECT * FROM memory_capsules_v2
        WHERE memory_tier = ?
          AND json_extract(state,'$.lifecycle') NOT IN (
              'forgotten','deleted','rejected','quarantined','candidate'
          )
          AND json_extract(governance,'$.policy_result') IN ('allow','redact')
          {scope_sql}
        ORDER BY updated_at DESC LIMIT ? OFFSET ?
        """,
        [*params, limit, offset],
    ).fetchall()
    from .capsule_store import _row_to_capsule

    return [_row_to_capsule(row) for row in rows]


def get_tier_stats(
    *,
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> dict[str, int]:
    """各 tier 的 capsule 计数（调试/监控用）。

    合法 tier 固定出现在结果中（缺省 0）；若数据里混入未知 tier 值
    （损坏/手改库），以原值单列计数并记 warning——宁可监控数字看起来
    异常，也不静默丢弃掩盖数据完整性问题。
    """
    scope_sql = ""
    params: list[Any] = []
    if owner_id is not None:
        scope_sql += " AND json_extract(provenance,'$.owner_id') = ?"
        params.append(owner_id)
    if soul_id is not None:
        scope_sql += " AND json_extract(provenance,'$.soul_id') = ?"
        params.append(soul_id)
    rows = get_conn().execute(
        f"""
        SELECT COALESCE(memory_tier, 'working') AS tier, COUNT(*) AS n
        FROM memory_capsules_v2
        WHERE json_extract(state,'$.lifecycle') NOT IN (
            'forgotten','deleted','rejected','quarantined','candidate'
        )
        {scope_sql}
        GROUP BY COALESCE(memory_tier, 'working')
        """,
        params,
    ).fetchall()
    stats = {tier: 0 for tier in VALID_TIERS}
    for row in rows:
        tier = row["tier"]
        if tier not in VALID_TIERS:
            logger.warning("get_tier_stats: unknown memory_tier value %r (%d rows)", tier, row["n"])
        stats[tier] = row["n"]
    return stats


def transition_history(capsule_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    """查询单条 capsule 的流转历史（tier_transition_log）。"""
    rows = get_conn().execute(
        """
        SELECT capsule_id, from_tier, to_tier, reason, trigger_source, created_at
        FROM tier_transition_log
        WHERE capsule_id = ?
        ORDER BY id DESC LIMIT ?
        """,
        (capsule_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]
