"""Memory Accounting —— 逐条记忆的成本-收益-ROI 经济账本。

规范来源：``AI优化/MemoryOS-Accounting经济账本.md``

为什么这一层在本项目里成本极低
------------------------------
经济账本最难的从来不是算成本（成本是确定性的），而是**收益信号从哪来**——
「这条记忆被召回后到底有没有用」需要有人判定。本项目恰好已经在收集这个信号：
``evolution.reflect_task`` 的入参里就有 ``helpful_memories`` 与
``misleading_memories``（``memory_runtime/evolution.py``）。把它接到
:func:`settle_recall_outcome`，utility 就有了真实来源，不需要任何新的用户输入。

热路径开销
----------
检索侧记账挂在 ``capsule_store.bump_usage_batch`` 已有的那个事务里，并且复用
``retrieval._usage_bump_due`` 的 60 秒时间窗门控。也就是说 **搜索路径不新增任何
一次写往返**——记账与既有的 usage_count 落库共用同一条 executemany 的时机。
改动这里时请保持该性质：不要在 ``search`` 里单独开事务记账。

与参考实现的差异
----------------
``MemoryOS-core参考实现.md`` 的 ``_recompute_roi`` 是「SELECT 出来 → Python 里算
→ UPDATE 回去」，每条记忆一次读+一次写。这里改为在 SQL 内用一条
``UPDATE ... WHERE capsule_id IN (...)`` 批量重算，批量场景下省掉 N 次读往返。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from ..db import get_conn, transaction
from ..utils.datetime_utils import utc_now_iso_compact

#: 召回结果 → 收益值（规范 §3 表格）。
#: harmful 记 -2.0 而不是 -1.0：一条误导性记忆造成的损害大于一条有用记忆的收益，
#: 这样 ROI 会明确转负而不是被几次 neutral 召回稀释掉。
UTILITY_BY_OUTCOME: dict[str, float] = {
    "useful": 1.0,
    "neutral": 0.1,
    "harmful": -2.0,
}

VALID_OUTCOMES = frozenset(UTILITY_BY_OUTCOME)


def _env_float(name: str, default: float) -> float:
    """读取环境变量里的浮点单价，非法值回退默认并不抛异常（配置错不该让写入失败）。"""
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class CostConfig:
    """成本单价。默认值取自规范 §5 示例（deepseek flash 量级）。

    通过环境变量覆盖，便于按实际模型与存储介质调参：
    ``WANWEI_MEMORY_TOKEN_COST`` / ``WANWEI_MEMORY_STORAGE_PER_KB`` /
    ``WANWEI_MEMORY_MAINTENANCE_COST``。
    """

    token_cost: float = 0.000002
    storage_per_kb: float = 0.00001
    maintenance_fixed: float = 0.001

    @classmethod
    def from_env(cls) -> CostConfig:
        return cls(
            token_cost=_env_float("WANWEI_MEMORY_TOKEN_COST", 0.000002),
            storage_per_kb=_env_float("WANWEI_MEMORY_STORAGE_PER_KB", 0.00001),
            maintenance_fixed=_env_float("WANWEI_MEMORY_MAINTENANCE_COST", 0.001),
        )


#: 衰减候选的最小账龄（天）。刚写入还没来得及被召回的记忆 ROI 天然是 -1.0，
#: 若不设宽限期，Decay Panel 会被当天新写的记忆淹没而失去可操作性。
DECAY_MIN_AGE_DAYS = _env_float("WANWEI_MEMORY_DECAY_MIN_AGE_DAYS", 7.0)

#: 判定「受保护」的 importance 阈值（与 tier_manager 的 long_term 阈值同源）。
PROTECTED_IMPORTANCE = _env_float("WANWEI_TIER_LONG_IMPORTANCE", 0.8)

_ROI_EXPR = (
    "CASE WHEN total_cost > 0 "
    "THEN ROUND((utility - total_cost) / total_cost, 4) ELSE 0 END"
)


def now() -> str:
    return utc_now_iso_compact()


def estimate_tokens(text_or_bytes: str | int) -> int:
    """粗估 token 数。

    没有 tokenizer 依赖时按「字符数 × 0.3」估算（规范参考实现同款系数）。
    这是**估算不是实测**，账本里的绝对金额因此只有相对比较意义；
    调用方若能拿到真实 token 用量，应直接传入而不是走这里。
    """
    if isinstance(text_or_bytes, int):
        return max(1, int(text_or_bytes * 0.3))
    return max(1, int(len(text_or_bytes) * 0.3))


def _recompute_roi_in_transaction(conn, capsule_ids: list[str]) -> None:
    """批量重算 ROI（一条 UPDATE 覆盖整批，不做逐条读-算-写）。"""
    if not capsule_ids:
        return
    placeholders = ",".join("?" for _ in capsule_ids)
    conn.execute(
        f"UPDATE memory_accounts SET roi = {_ROI_EXPR} WHERE capsule_id IN ({placeholders})",
        capsule_ids,
    )


def _ensure_accounts_in_transaction(conn, capsule_ids: list[str], ts: str) -> None:
    """为尚无账户的记忆补零行。

    账本上线前写入的历史记忆没有账户，召回/维护时若不补行，UPDATE 会静默影响
    0 行、成本白记。``INSERT OR IGNORE`` 让补行与已有账户共用同一条语句。
    """
    if not capsule_ids:
        return
    conn.executemany(
        "INSERT OR IGNORE INTO memory_accounts(capsule_id, created_at, updated_at) VALUES (?,?,?)",
        [(capsule_id, ts, ts) for capsule_id in capsule_ids],
    )


# ---------------------------------------------------------------------------
# 写入记账
# ---------------------------------------------------------------------------


def record_write_in_transaction(
    conn,
    capsule_id: str,
    *,
    content_bytes: int,
    extraction_tokens: int,
    config: CostConfig | None = None,
) -> None:
    """写入记账：一次性抽取成本 + 初始存储成本。在调用方事务内执行。"""
    cfg = config or CostConfig.from_env()
    storage = content_bytes / 1024 * cfg.storage_per_kb
    cost = extraction_tokens * cfg.token_cost + storage
    ts = now()
    conn.execute(
        """
        INSERT INTO memory_accounts(
            capsule_id, storage_cost, total_cost, roi, created_at, updated_at
        ) VALUES (?,?,?,?,?,?)
        ON CONFLICT(capsule_id) DO UPDATE SET
            storage_cost = storage_cost + excluded.storage_cost,
            total_cost   = total_cost + excluded.total_cost,
            updated_at   = excluded.updated_at
        """,
        (capsule_id, storage, cost, -1.0 if cost > 0 else 0.0, ts, ts),
    )
    _recompute_roi_in_transaction(conn, [capsule_id])


# ---------------------------------------------------------------------------
# 召回记账
# ---------------------------------------------------------------------------


def record_recalls_in_transaction(
    conn,
    entries: list[tuple[str, str, int]],
    *,
    config: CostConfig | None = None,
) -> None:
    """批量召回记账。``entries`` 为 ``(capsule_id, outcome, injected_tokens)``。

    默认 outcome 传 ``neutral``：检索当下还不知道这条记忆有没有帮上忙，
    等 ``reflect_task`` 回来再用 :func:`settle_recall_outcome` 回填成
    useful/harmful。这正是规范 §6 集成点表里写的
    「outcome 由后续回答质量回填，或先记 neutral 后修正」。
    """
    if not entries:
        return
    cfg = config or CostConfig.from_env()
    ts = now()
    capsule_ids = [capsule_id for capsule_id, _, _ in entries]
    _ensure_accounts_in_transaction(conn, capsule_ids, ts)

    rows = []
    for capsule_id, outcome, injected_tokens in entries:
        if outcome not in VALID_OUTCOMES:
            raise ValueError(f"unknown recall outcome: {outcome!r}")
        retrieval_cost = injected_tokens * cfg.token_cost
        rows.append((
            retrieval_cost, retrieval_cost,
            1 if outcome == "useful" else 0,
            1 if outcome == "neutral" else 0,
            1 if outcome == "harmful" else 0,
            UTILITY_BY_OUTCOME[outcome],
            ts, ts, capsule_id,
        ))
    conn.executemany(
        """
        UPDATE memory_accounts SET
            retrieval_cost  = retrieval_cost + ?,
            total_cost      = total_cost + ?,
            useful_recalls  = useful_recalls + ?,
            neutral_recalls = neutral_recalls + ?,
            harmful_recalls = harmful_recalls + ?,
            utility         = utility + ?,
            last_accessed   = ?,
            updated_at      = ?
        WHERE capsule_id = ?
        """,
        rows,
    )
    _recompute_roi_in_transaction(conn, capsule_ids)


def settle_recall_outcome(
    capsule_ids: list[str],
    outcome: str,
    *,
    conn=None,
) -> dict[str, Any]:
    """把既有的 neutral 召回回填为 useful / harmful（反思阶段调用）。

    语义：如果这条记忆此前有过 neutral 召回，就把其中一次**改判**
    （neutral-1、目标+1、utility 补差额 ``目标值 - 0.1``）；如果没有
    （例如记忆是被直接引用而非经检索命中的），则记为一次新的召回，
    utility 加满额。两种情况都在一条 UPDATE 里用 CASE 判定——
    SQLite 的 UPDATE 右值统一取更新前的行值，因此 ``neutral_recalls``
    在 CASE 里读到的是旧值，可安全用于判断。
    """
    if outcome not in VALID_OUTCOMES:
        raise ValueError(f"unknown recall outcome: {outcome!r}")
    ids = list(dict.fromkeys(capsule_ids))
    if not ids:
        return {"settled": 0, "outcome": outcome, "capsule_ids": []}

    target_utility = UTILITY_BY_OUTCOME[outcome]
    neutral_utility = UTILITY_BY_OUTCOME["neutral"]
    column = {"useful": "useful_recalls", "harmful": "harmful_recalls", "neutral": "neutral_recalls"}[outcome]
    ts = now()

    def _apply(active_conn) -> None:
        _ensure_accounts_in_transaction(active_conn, ids, ts)
        active_conn.executemany(
            f"""
            UPDATE memory_accounts SET
                neutral_recalls = CASE WHEN neutral_recalls > 0 AND ? != 'neutral'
                                       THEN neutral_recalls - 1 ELSE neutral_recalls END,
                {column} = {column} + 1,
                utility = utility + CASE WHEN neutral_recalls > 0 AND ? != 'neutral'
                                         THEN ? ELSE ? END,
                updated_at = ?
            WHERE capsule_id = ?
            """,
            [
                (outcome, outcome, target_utility - neutral_utility, target_utility, ts, capsule_id)
                for capsule_id in ids
            ],
        )
        _recompute_roi_in_transaction(active_conn, ids)

    if conn is not None:
        _apply(conn)
    else:
        with transaction() as own_conn:
            _apply(own_conn)
    return {"settled": len(ids), "outcome": outcome, "capsule_ids": ids}


# ---------------------------------------------------------------------------
# 维护记账
# ---------------------------------------------------------------------------


def record_maintenance_in_transaction(
    conn,
    capsule_ids: list[str],
    *,
    config: CostConfig | None = None,
) -> None:
    """维护记账：状态机扫描 / tier 流转 / 巩固每处理一条计一次固定成本。"""
    ids = list(dict.fromkeys(capsule_ids))
    if not ids:
        return
    cfg = config or CostConfig.from_env()
    ts = now()
    _ensure_accounts_in_transaction(conn, ids, ts)
    conn.executemany(
        """
        UPDATE memory_accounts SET
            maintenance_cost = maintenance_cost + ?,
            total_cost = total_cost + ?,
            updated_at = ?
        WHERE capsule_id = ?
        """,
        [(cfg.maintenance_fixed, cfg.maintenance_fixed, ts, capsule_id) for capsule_id in ids],
    )
    _recompute_roi_in_transaction(conn, ids)


def record_maintenance(capsule_ids: list[str], *, config: CostConfig | None = None) -> None:
    with transaction() as conn:
        record_maintenance_in_transaction(conn, capsule_ids, config=config)


# ---------------------------------------------------------------------------
# 查询与衰减面板
# ---------------------------------------------------------------------------


def account_for(capsule_id: str) -> dict[str, Any] | None:
    row = get_conn().execute(
        "SELECT * FROM memory_accounts WHERE capsule_id=?", (capsule_id,)
    ).fetchone()
    return dict(row) if row else None


def _scope_clause(owner_id: str | None, soul_id: str | None) -> tuple[str, list[Any]]:
    """账户表本身不存 owner/soul，作用域过滤靠 JOIN 主表的 provenance。"""
    clauses: list[str] = []
    params: list[Any] = []
    if owner_id is not None:
        clauses.append("json_extract(cap.provenance,'$.owner_id')=?")
        params.append(owner_id)
    if soul_id is not None:
        clauses.append(
            "(json_extract(cap.provenance,'$.soul_id')=? "
            "OR json_extract(cap.provenance,'$.soul_id') IS NULL)"
        )
        params.append(soul_id)
    return (" AND ".join(clauses), params)


def decay_candidates(
    *,
    min_roi: float = 0.0,
    limit: int = 50,
    min_age_days: float | None = None,
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> list[dict[str, Any]]:
    """边际 ROI 低于阈值的记忆 = 衰减候选（Decay Panel 的数据源）。

    按 Health 规范 §3.2 输出**三分类**而不是一个平铺列表：

    - ``protected`` —— long_term 层 / 高 importance / S1 以上敏感。这类记忆即使
      ROI 为负也不该自动清理（合规或高价值），面板上要显示但要禁用清理按钮。
    - ``delete_candidate`` —— 有过 harmful 召回，即已经实际误导过。
    - ``archive_candidate`` —— 其余 ROI 不达标者，建议归档而非删除。

    ``min_age_days`` 提供宽限期（默认 7 天）：刚写入还没机会被召回的记忆 ROI
    天然为 -1.0，不排除的话面板会被当天新写的记忆淹没。
    """
    grace = DECAY_MIN_AGE_DAYS if min_age_days is None else min_age_days
    scope_sql, scope_params = _scope_clause(owner_id, soul_id)
    scope_clause = f" AND {scope_sql}" if scope_sql else ""
    capped = max(1, min(limit, 500))

    rows = get_conn().execute(
        f"""
        SELECT acct.*,
               cap.memory_class,
               cap.memory_tier,
               COALESCE(json_extract(cap.state,'$.importance_score'), 0.5) AS importance_score,
               COALESCE(json_extract(cap.state,'$.lifecycle'), 'active')   AS lifecycle,
               COALESCE(json_extract(cap.governance,'$.sensitivity_level'), 'S0') AS sensitivity_level
        FROM memory_accounts AS acct
        JOIN memory_capsules_v2 AS cap ON cap.capsule_id = acct.capsule_id
        WHERE acct.roi < ?
          AND COALESCE(json_extract(cap.state,'$.lifecycle'),'active')
              NOT IN ('forgotten','deleted','rejected')
          AND julianday('now') - julianday(acct.created_at) >= ?
          {scope_clause}
        ORDER BY acct.roi ASC, acct.harmful_recalls DESC
        LIMIT ?
        """,
        [min_roi, grace, *scope_params, capped],
    ).fetchall()

    candidates = []
    for row in rows:
        item = dict(row)
        protected = (
            item["memory_tier"] == "long_term"
            or float(item["importance_score"] or 0) >= PROTECTED_IMPORTANCE
            or item["sensitivity_level"] not in ("S0", None)
        )
        if protected:
            classification, rationale = "protected", "high_value_or_compliance_hold"
        elif int(item["harmful_recalls"] or 0) > 0:
            classification, rationale = "delete_candidate", "harmful_recall_recorded"
        else:
            classification, rationale = "archive_candidate", "negative_roi"
        item["classification"] = classification
        item["rationale"] = rationale
        candidates.append(item)
    return candidates


def summary(
    *,
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> dict[str, Any]:
    """全库经济汇总（score_report 的 ``economics`` 段与健康面板共用）。"""
    scope_sql, scope_params = _scope_clause(owner_id, soul_id)
    join = "JOIN memory_capsules_v2 AS cap ON cap.capsule_id = acct.capsule_id" if scope_sql else ""
    where = f"WHERE {scope_sql}" if scope_sql else ""
    row = get_conn().execute(
        f"""
        SELECT COUNT(*) AS n,
               COALESCE(SUM(acct.total_cost),0)      AS total_cost,
               COALESCE(SUM(acct.utility),0)         AS total_utility,
               COALESCE(SUM(acct.useful_recalls),0)  AS useful,
               COALESCE(SUM(acct.neutral_recalls),0) AS neutral,
               COALESCE(SUM(acct.harmful_recalls),0) AS harmful,
               COALESCE(SUM(acct.retrieval_cost),0)  AS retrieval_cost,
               SUM(CASE WHEN acct.roi < 0 THEN 1 ELSE 0 END) AS negative_roi
        FROM memory_accounts AS acct {join} {where}
        """,
        scope_params,
    ).fetchone()

    total_cost = float(row["total_cost"] or 0)
    total_utility = float(row["total_utility"] or 0)
    useful = int(row["useful"] or 0)
    return {
        "memories": int(row["n"] or 0),
        "total_cost": round(total_cost, 6),
        "total_utility": round(total_utility, 4),
        "useful_recalls": useful,
        "neutral_recalls": int(row["neutral"] or 0),
        "harmful_recalls": int(row["harmful"] or 0),
        "negative_roi_memories": int(row["negative_roi"] or 0),
        "avg_roi": round((total_utility - total_cost) / total_cost, 4) if total_cost > 0 else 0.0,
        "cost_per_useful_recall": round(total_cost / useful, 6) if useful else None,
        "cost_config": CostConfig.from_env().__dict__,
    }


__all__ = [
    "DECAY_MIN_AGE_DAYS",
    "UTILITY_BY_OUTCOME",
    "VALID_OUTCOMES",
    "CostConfig",
    "account_for",
    "decay_candidates",
    "estimate_tokens",
    "record_maintenance",
    "record_maintenance_in_transaction",
    "record_recalls_in_transaction",
    "record_write_in_transaction",
    "settle_recall_outcome",
    "summary",
]
