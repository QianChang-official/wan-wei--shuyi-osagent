"""Memory Health —— MHS 健康度评分与三面板（Health / Decay / Self-Knowledge）。

规范来源：``AI优化/MemoryOS-Health规范.md``

定位：现有基准（LongMemEval / BEAM）测的是「能不能记住」，不是「记忆库健不健康」。
就像操作系统要看磁盘占用而不只看读写正确性，Memory OS 也要有一个把过期率、
冲突率、噪声率、删除残留、投毒事故聚合成单一分数的仪表盘。

诚实边界（重要）
----------------
参考实现 ``AI优化/MemoryOS-core参考实现.md`` 的 ``health_report()`` 里把
``precision_at_5`` 硬编码成了 ``0.9``。本仓库 ``REVIEW.md`` 把「把模拟/未实现
说成实测」列为阻断级问题，因此这里**不照抄**：没有实跑评测报告时
``precision@5`` 如实输出 ``None``，MHS 计算跳过该项，并在 ``issues`` 里注明
「该维度未测量」。宁可分数少一个维度，也不用编造值把仪表盘填满。

同理，``poisoning_incidents`` 只统计**真实事故**（未解决的 MHG 事故），
被隔离闸门成功拦下的投毒尝试单列为 ``poisoning_blocked`` 且**不扣分**——
拦截成功是系统在正常工作，为此扣健康分是反向激励。
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..db import get_conn, transaction
from ..utils.datetime_utils import utc_now_iso_compact
from . import accounting, governance
from .lifecycle import LifecycleState, state_counts

#: MEB 评测报告位置（``precision@5`` 的唯一实测来源）。
_REPORTS_DIR = Path(__file__).resolve().parents[3] / "reports"
MEB_REPORT_PATH = _REPORTS_DIR / "meb_score_report.json"

#: 删除残留抽样条数：从账本里取最近若干条 delete 账目逐条验证。
#: 走账本而不是扫主表，是因为硬删的行已经不存在，主表里根本采不到样本。
DELETION_SAMPLE_SIZE = int(os.environ.get("WANWEI_HEALTH_DELETION_SAMPLE", "50"))

#: 「长期未用」的天数阈值。
UNUSED_DAYS = float(os.environ.get("WANWEI_HEALTH_UNUSED_DAYS", "30"))


def now() -> str:
    return utc_now_iso_compact()


@dataclass(frozen=True)
class HealthThresholds:
    """各指标的健康阈值（超过才开始扣分）与扣满上限。"""

    staleness_max: float = 0.05
    staleness_cap: float = 0.30
    conflict_max: float = 0.02
    conflict_cap: float = 0.15
    noise_max: float = 0.10
    noise_cap: float = 0.50
    unused_max: float = 0.20
    unused_cap: float = 0.60
    precision_min: float = 0.80


@dataclass
class MemoryHealthReport:
    timestamp: str
    mhs: float
    level: str
    metrics: dict[str, Any]
    issues: list[str] = field(default_factory=list)
    unmeasured: list[str] = field(default_factory=list)
    # ``level`` remains the numeric severity band for backward compatibility.
    # ``status`` exposes the operational truth when a high score still carries
    # actionable warnings or measurement gaps.
    status: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "mhs": self.mhs,
            "level": self.level,
            "status": self.status or self.level,
            "metrics": self.metrics,
            "issues": self.issues,
            "unmeasured": self.unmeasured,
        }


class MemoryHealthChecker:
    """把子指标聚合成 MHS 综合分（规范 §2 公式）。"""

    def __init__(self, thresholds: HealthThresholds | None = None):
        self.t = thresholds or HealthThresholds()

    @staticmethod
    def _norm(value: float, threshold: float, cap: float) -> float:
        """阈值以上才开始扣分，线性归一到 [0,1]，超 cap 封顶。"""
        if value <= threshold:
            return 0.0
        if cap <= threshold:
            return 1.0
        return min(1.0, (value - threshold) / (cap - threshold))

    def check(
        self,
        *,
        total: int,
        stale: int,
        conflicted: int,
        noisy: int,
        unused: int,
        sensitive_identified: int,
        sensitive_total: int,
        deletion_residue: bool,
        poisoning_incidents: int,
        precision_at_5: float | None,
        extra_metrics: dict[str, Any] | None = None,
    ) -> MemoryHealthReport:
        def rate(n: int) -> float:
            return n / total if total else 0.0

        staleness = rate(stale)
        conflict = rate(conflicted)
        noise = rate(noisy)
        unused_rate = rate(unused)
        sensitive_cov = sensitive_identified / sensitive_total if sensitive_total else 1.0

        mhs = 100.0
        mhs -= 15 * self._norm(staleness, self.t.staleness_max, self.t.staleness_cap)
        mhs -= 15 * self._norm(conflict, self.t.conflict_max, self.t.conflict_cap)
        mhs -= 15 * self._norm(noise, self.t.noise_max, self.t.noise_cap)
        mhs -= 10 * (1.0 if deletion_residue else 0.0)
        mhs -= 15 * (1.0 - min(1.0, sensitive_cov))
        mhs -= 10 * self._norm(unused_rate, self.t.unused_max, self.t.unused_cap)
        mhs -= 20 * (1.0 if poisoning_incidents > 0 else 0.0)

        issues: list[str] = []
        unmeasured: list[str] = []
        if precision_at_5 is None:
            # 不扣分、不假设——如实登记为「未测量」，让面板显示缺口而不是虚高分。
            unmeasured.append("precision@5: 无实跑评测报告，该维度未纳入 MHS")
        elif precision_at_5 < self.t.precision_min:
            mhs -= 10 * (self.t.precision_min - precision_at_5) / self.t.precision_min
            issues.append(f"precision@5 {precision_at_5:.0%} < {self.t.precision_min:.0%}")

        mhs = max(0.0, min(100.0, mhs))
        level = "healthy" if mhs >= 80 else ("warning" if mhs >= 60 else "critical")

        if staleness > self.t.staleness_max:
            issues.append(f"staleness {staleness:.1%} > {self.t.staleness_max:.0%}")
        if conflict > self.t.conflict_max:
            issues.append(f"conflict {conflict:.1%} > {self.t.conflict_max:.0%}")
        if noise > self.t.noise_max:
            issues.append(f"noise {noise:.1%} > {self.t.noise_max:.0%}")
        if deletion_residue:
            issues.append("deletion residue detected")
        if sensitive_cov < 1.0:
            issues.append(f"sensitive coverage {sensitive_cov:.0%} < 100%")
        if unused_rate > self.t.unused_max:
            issues.append(f"unused {unused_rate:.1%} > {self.t.unused_max:.0%}")
        if poisoning_incidents > 0:
            issues.append(f"unresolved poisoning incidents: {poisoning_incidents}")

        metrics = {
            "total": total,
            "staleness": round(staleness, 4),
            "conflict": round(conflict, 4),
            "noise": round(noise, 4),
            "unused": round(unused_rate, 4),
            "sensitive_coverage": round(sensitive_cov, 4),
            "deletion_residue": deletion_residue,
            "poisoning_incidents": poisoning_incidents,
            "precision@5": precision_at_5,
        }
        metrics.update(extra_metrics or {})
        if level == "healthy" and issues:
            status = "healthy_with_warnings"
        elif level == "healthy" and unmeasured:
            status = "healthy_with_gaps"
        else:
            status = level
        return MemoryHealthReport(
            timestamp=now(), mhs=round(mhs, 1), level=level,
            metrics=metrics, issues=issues, unmeasured=unmeasured, status=status,
        )


# ---------------------------------------------------------------------------
# 真实数据采集
# ---------------------------------------------------------------------------


def _scope(
    owner_id: str | None,
    soul_id: str | None,
    *,
    alias: str = "",
) -> tuple[str, list[Any]]:
    """构造 owner/soul 作用域条件。``alias`` 用于带表别名的 JOIN 查询。

    显式传别名而不是事后对 SQL 做字符串替换——替换会连注释、字面量一起改，
    是那种平时看不出问题、加一个同名列就静默错的写法。
    """
    prefix = f"{alias}." if alias else ""
    clauses: list[str] = []
    params: list[Any] = []
    if owner_id is not None:
        clauses.append(f"json_extract({prefix}provenance,'$.owner_id')=?")
        params.append(owner_id)
    if soul_id is not None:
        clauses.append(
            f"(json_extract({prefix}provenance,'$.soul_id')=? "
            f"OR json_extract({prefix}provenance,'$.soul_id') IS NULL)"
        )
        params.append(soul_id)
    return (" AND ".join(clauses), params)


def measured_precision_at_5() -> tuple[float | None, str]:
    """读取实测 precision@5。返回 ``(值, 来源说明)``，读不到即 ``(None, ...)``。"""
    try:
        payload = json.loads(MEB_REPORT_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "unavailable: 尚未产出 reports/meb_score_report.json"
    value = (payload.get("scores") or {}).get("retrieval_precision_at_5")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None, "unavailable: 报告中无 scores.retrieval_precision_at_5"
    return float(value), f"measured: {payload.get('run_id', 'unknown_run')}"


def _deletion_residue_sample(limit: int) -> dict[str, Any]:
    """从账本抽最近若干条 delete 账目做删除验证。

    走账本而不是扫主表：硬删后主表已无行，只有账本还留着「这条记忆被删过」
    的记录，因此账本是唯一能覆盖软删+硬删两种情形的采样源。
    """
    rows = get_conn().execute(
        "SELECT DISTINCT capsule_id FROM memory_ledger WHERE op_type='delete' "
        "ORDER BY created_at DESC LIMIT ?",
        (max(1, limit),),
    ).fetchall()
    capsule_ids = [row["capsule_id"] for row in rows]
    if not capsule_ids:
        return {"sampled": 0, "residue_found": False, "incomplete": []}
    verdict = governance.verify_deletions(capsule_ids)
    return {
        "sampled": verdict["checked"],
        "residue_found": not verdict["all_complete"],
        "incomplete": verdict["incomplete"][:10],
    }


def collect_metrics(
    *,
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> dict[str, Any]:
    """从真库聚合 MHS 所需的全部子指标。"""
    conn = get_conn()
    scope_sql, scope_params = _scope(owner_id, soul_id)
    scope_clause = f" AND {scope_sql}" if scope_sql else ""
    cap_scope_sql, cap_scope_params = _scope(owner_id, soul_id, alias="cap")
    cap_scope_clause = f" AND {cap_scope_sql}" if cap_scope_sql else ""

    counts = state_counts(owner_id=owner_id, soul_id=soul_id)
    # 「在册记忆」不含已删/已拒——它们不占用检索预算，不该稀释各项比率。
    live_states = [
        state.value for state in LifecycleState
        if state.value not in ("forgotten", "deleted", "rejected")
    ]
    total = sum(counts.get(state, 0) for state in live_states)

    unused = conn.execute(
        f"""
        SELECT COUNT(*) FROM memory_capsules_v2
        WHERE COALESCE(json_extract(state,'$.lifecycle'),'active')
              NOT IN ('forgotten','deleted','rejected')
          AND julianday('now') - julianday(
                COALESCE(json_extract(state,'$.last_accessed_at'), created_at)
              ) >= ?
        {scope_clause}
        """,
        [UNUSED_DAYS, *scope_params],
    ).fetchone()[0]

    sensitive_row = conn.execute(
        f"""
        SELECT
            SUM(CASE WHEN COALESCE(json_extract(governance,'$.sensitivity_level'),'S0')!='S0'
                     THEN 1 ELSE 0 END) AS sensitive_total,
            SUM(CASE WHEN COALESCE(json_extract(governance,'$.sensitivity_level'),'S0')!='S0'
                      AND json_array_length(COALESCE(json_extract(governance,'$.risk_tags'),'[]'))>0
                     THEN 1 ELSE 0 END) AS sensitive_identified
        FROM memory_capsules_v2
        WHERE COALESCE(json_extract(state,'$.lifecycle'),'active')
              NOT IN ('forgotten','deleted','rejected')
        {scope_clause}
        """,
        scope_params,
    ).fetchone()

    noisy = conn.execute(
        f"""
        SELECT COUNT(*) FROM memory_accounts AS acct
        JOIN memory_capsules_v2 AS cap ON cap.capsule_id = acct.capsule_id
        WHERE acct.roi < 0
          AND COALESCE(json_extract(cap.state,'$.lifecycle'),'active')
              NOT IN ('forgotten','deleted','rejected')
          AND julianday('now') - julianday(acct.created_at) >= ?
          {cap_scope_clause}
        """,
        [accounting.DECAY_MIN_AGE_DAYS, *cap_scope_params],
    ).fetchone()[0]

    poisoning_blocked = conn.execute(
        f"""
        SELECT COUNT(*) FROM memory_capsules_v2
        WHERE COALESCE(json_extract(state,'$.lifecycle'),'active')='quarantined'
          AND instr(COALESCE(json_extract(governance,'$.risk_tags'),''), 'memory_poisoning')>0
        {scope_clause}
        """,
        scope_params,
    ).fetchone()[0]

    unresolved_incidents = governance.list_incidents(unresolved_only=True, limit=200)
    poisoning_incidents = sum(
        1 for item in unresolved_incidents if "poison" in (item.get("incident_type") or "").lower()
    )

    residue = _deletion_residue_sample(DELETION_SAMPLE_SIZE)
    precision, precision_source = measured_precision_at_5()

    return {
        "total": total,
        "state_counts": counts,
        "stale": counts.get(LifecycleState.STALE.value, 0),
        "conflicted": counts.get(LifecycleState.CONFLICTED.value, 0),
        "quarantined": counts.get(LifecycleState.QUARANTINED.value, 0),
        "candidate": counts.get(LifecycleState.CANDIDATE.value, 0),
        "noisy": noisy,
        "unused": unused,
        "unused_days_threshold": UNUSED_DAYS,
        "sensitive_total": int(sensitive_row["sensitive_total"] or 0),
        "sensitive_identified": int(sensitive_row["sensitive_identified"] or 0),
        "deletion_residue": residue["residue_found"],
        "deletion_sample": residue,
        "poisoning_incidents": poisoning_incidents,
        "poisoning_blocked": poisoning_blocked,
        "unresolved_incidents": len(unresolved_incidents),
        "precision_at_5": precision,
        "precision_source": precision_source,
    }


def health_report(
    *,
    owner_id: str | None = None,
    soul_id: str | None = None,
    thresholds: HealthThresholds | None = None,
    precision_override: tuple[float | None, str] | None = None,
) -> dict[str, Any]:
    """Health Panel：MHS 总分 + 各子指标 + 问题清单 + 未测量项。

    ``precision_override``: ``(值, 来源说明)``。默认从磁盘上的
    ``meb_score_report.json`` 读取上一次实测值；MEB harness 在**组装本轮报告**
    时会把刚算出来的精度传进来，否则报告里会嵌进上一轮的旧值（差一轮），
    甚至首次运行时自相矛盾——同一份报告 scores 段有精度、health 段说未测量。
    """
    raw = collect_metrics(owner_id=owner_id, soul_id=soul_id)
    if precision_override is not None:
        raw["precision_at_5"], raw["precision_source"] = precision_override
    report = MemoryHealthChecker(thresholds).check(
        total=raw["total"],
        stale=raw["stale"],
        conflicted=raw["conflicted"],
        noisy=raw["noisy"],
        unused=raw["unused"],
        sensitive_identified=raw["sensitive_identified"],
        sensitive_total=raw["sensitive_total"],
        deletion_residue=raw["deletion_residue"],
        poisoning_incidents=raw["poisoning_incidents"],
        precision_at_5=raw["precision_at_5"],
        extra_metrics={
            "state_counts": raw["state_counts"],
            "quarantined": raw["quarantined"],
            "candidate": raw["candidate"],
            "poisoning_blocked": raw["poisoning_blocked"],
            "unresolved_incidents": raw["unresolved_incidents"],
            "precision_source": raw["precision_source"],
            "deletion_sample": raw["deletion_sample"],
            "unused_days_threshold": raw["unused_days_threshold"],
        },
    )
    payload = report.to_dict()
    payload["release_gate"] = governance.release_gate()
    return payload


def decay_panel(
    *,
    limit: int = 50,
    min_roi: float = 0.0,
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> dict[str, Any]:
    """Decay Panel：边际 ROI 为负的记忆，按 应归档 / 应删除 / 受保护 三分类。"""
    candidates = accounting.decay_candidates(
        min_roi=min_roi, limit=limit, owner_id=owner_id, soul_id=soul_id,
    )
    buckets: dict[str, list[dict[str, Any]]] = {
        "archive_candidate": [], "delete_candidate": [], "protected": [],
    }
    for item in candidates:
        buckets[item["classification"]].append(item)
    return {
        "generated_at": now(),
        "min_roi": min_roi,
        "grace_period_days": accounting.DECAY_MIN_AGE_DAYS,
        "counts": {key: len(value) for key, value in buckets.items()},
        "buckets": buckets,
        "economics": accounting.summary(owner_id=owner_id, soul_id=soul_id),
    }


# ---------------------------------------------------------------------------
# 健康度趋势（规范 §3.1「MHS 总分 + 趋势（7 天）」）
# ---------------------------------------------------------------------------


def record_snapshot(
    *,
    owner_id: str | None = None,
    soul_id: str | None = None,
    source: str = "manual",
    precision_override: tuple[float | None, str] | None = None,
) -> dict[str, Any]:
    """算一次健康报告并存成历史快照，供画趋势曲线。

    刻意做成**显式动作**而不是在 ``health_report`` 里顺手写库：读端点写库会让
    前端轮询把快照表撑爆，曲线也会退化成「谁看得勤谁点多」而不是时间序列。
    正常由每日 MEB 评测收尾时调用，或运维手动触发。
    """
    report = health_report(
        owner_id=owner_id, soul_id=soul_id, precision_override=precision_override
    )
    snapshot_id = "hs_" + uuid.uuid4().hex[:12]
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO memory_health_snapshots(
                snapshot_id, owner_id, soul_id, mhs, level, metrics, issues, source, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                snapshot_id, owner_id, soul_id, report["mhs"], report["level"],
                json.dumps(report["metrics"], ensure_ascii=False),
                json.dumps(report["issues"], ensure_ascii=False),
                source, report["timestamp"],
            ),
        )
    return {"snapshot_id": snapshot_id, **report}


def health_trend(
    *,
    days: int = 7,
    owner_id: str | None = None,
    soul_id: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """近 N 天的 MHS 时间序列。

    ``points`` 为空表示还没采过样——如实返回空序列并说明，不用当前即时值
    伪造一条「历史」曲线。

    ``soul_id`` 必须与采样时的作用域一致才能匹配：一个属主下多个 soul 各自
    采样时，不按 soul 过滤会把两条曲线交错成一条锯齿，看着像健康度在剧烈
    震荡，其实只是在两个 soul 的分数之间来回跳。同理，owner 级快照
    （``soul_id`` 为 NULL）不会出现在某个具体 soul 的曲线里——它不是那个
    soul 的数据点。

    每个点带 ``precision_at_5`` 与 ``precision_source``：它们是最该和 MHS 并排
    画的第二条曲线（检索质量掉了 MHS 才会跟着掉）。刻意用 SQL ``json_extract``
    只抽这两个标量而不是整个 ``metrics`` 对象——一条 200 点的曲线背 200 份完整
    指标快照，响应体会膨胀到没法在前端轮询。要看某一天的全量指标，按
    ``snapshot_id`` 单独取。

    注意 JSON path 里那对双引号：``metrics`` 中该键的实际名字是 ``precision@5``
    （见 :meth:`MemoryHealthChecker.check`），``@`` 不是合法的裸字段名，
    写成 ``$.precision@5`` 会静默取回 NULL 而不是报错。
    """
    clauses = ["julianday('now') - julianday(created_at) <= ?"]
    params: list[Any] = [max(1, days)]
    if owner_id is not None:
        clauses.append("owner_id=?")
        params.append(owner_id)
    if soul_id is not None:
        clauses.append("soul_id=?")
        params.append(soul_id)
    rows = get_conn().execute(
        f"SELECT snapshot_id, mhs, level, issues, source, created_at, "
        f"json_extract(metrics,'$.\"precision@5\"') AS precision_at_5, "
        f"json_extract(metrics,'$.precision_source') AS precision_source "
        f"FROM memory_health_snapshots WHERE {' AND '.join(clauses)} "
        "ORDER BY created_at ASC LIMIT ?",
        [*params, max(1, min(limit, 1000))],
    ).fetchall()

    points = []
    for row in rows:
        item = dict(row)
        try:
            item["issues"] = json.loads(item["issues"]) if item["issues"] else []
        except (TypeError, ValueError):
            item["issues"] = []
        points.append(item)

    values = [point["mhs"] for point in points]
    return {
        "days": days,
        "points": points,
        "count": len(points),
        "min_mhs": min(values) if values else None,
        "max_mhs": max(values) if values else None,
        "latest_mhs": values[-1] if values else None,
        "delta": round(values[-1] - values[0], 1) if len(values) >= 2 else None,
        "note": None if points else "尚无健康度快照，调用 POST /memory/health/snapshot 开始采样",
    }


def self_knowledge_panel(
    *,
    limit: int = 20,
    confidence_threshold: float = 0.7,
    owner_id: str | None = None,
    soul_id: str | None = None,
) -> dict[str, Any]:
    """Self-Knowledge Panel（规范 §3.3）：我有哪些记忆、凭据是什么、哪些不确定、怎么纠错。"""
    conn = get_conn()
    scope_sql, scope_params = _scope(owner_id, soul_id)
    scope_clause = f" AND {scope_sql}" if scope_sql else ""

    by_class = {
        row["memory_class"]: row["n"]
        for row in conn.execute(
            f"""
            SELECT memory_class, COUNT(*) AS n FROM memory_capsules_v2
            WHERE COALESCE(json_extract(state,'$.lifecycle'),'active')
                  NOT IN ('forgotten','deleted','rejected')
            {scope_clause}
            GROUP BY memory_class
            """,
            scope_params,
        ).fetchall()
    }
    by_source = {
        (row["source"] or "unknown"): row["n"]
        for row in conn.execute(
            f"""
            SELECT json_extract(provenance,'$.source_type') AS source, COUNT(*) AS n
            FROM memory_capsules_v2
            WHERE COALESCE(json_extract(state,'$.lifecycle'),'active')
                  NOT IN ('forgotten','deleted','rejected')
            {scope_clause}
            GROUP BY 1
            """,
            scope_params,
        ).fetchall()
    }
    uncertain_rows = conn.execute(
        f"""
        SELECT capsule_id, memory_class,
               json_extract(governance,'$.confidence') AS confidence,
               json_extract(governance,'$.sensitivity_level') AS sensitivity_level,
               json_extract(state,'$.lifecycle') AS lifecycle,
               json_extract(provenance,'$.source_type') AS source_type
        FROM memory_capsules_v2
        WHERE COALESCE(json_extract(governance,'$.confidence'), 1.0) < ?
          AND COALESCE(json_extract(state,'$.lifecycle'),'active')
              NOT IN ('forgotten','deleted','rejected')
        {scope_clause}
        ORDER BY json_extract(governance,'$.confidence') ASC
        LIMIT ?
        """,
        [confidence_threshold, *scope_params, max(1, min(limit, 200))],
    ).fetchall()
    unverified = conn.execute(
        f"""
        SELECT COUNT(*) FROM memory_capsules_v2
        WHERE COALESCE(json_extract(provenance,'$.verified'), 0) = 0
          AND COALESCE(json_extract(state,'$.lifecycle'),'active')
              NOT IN ('forgotten','deleted','rejected')
        {scope_clause}
        """,
        scope_params,
    ).fetchone()[0]

    return {
        "generated_at": now(),
        "what_i_remember": {
            "by_memory_class": by_class,
            "by_source": by_source,
            "by_lifecycle": state_counts(owner_id=owner_id, soul_id=soul_id),
            "total": sum(by_class.values()),
        },
        "what_i_am_unsure_about": {
            "confidence_threshold": confidence_threshold,
            "low_confidence": [dict(row) for row in uncertain_rows],
            "unverified_count": unverified,
        },
        "how_to_correct": {
            "inspect_provenance": "GET /memory/governance/provenance/{capsule_id}",
            "inspect_ledger": "GET /memory/ledger/{capsule_id}",
            "confirm_pending": "POST /memory/lifecycle/confirm",
            "archive": "POST /memory/lifecycle/transition (to_state=deprecated)",
            "resolve_conflict": "POST /memory/lifecycle/resolve-conflict",
            "forget": "POST /memory/forget/preview → POST /memory/forget/confirm",
            "verify_deletion": "GET /memory/governance/verify-deletion/{capsule_id}",
        },
    }


__all__ = [
    "DELETION_SAMPLE_SIZE",
    "MEB_REPORT_PATH",
    "UNUSED_DAYS",
    "HealthThresholds",
    "MemoryHealthChecker",
    "MemoryHealthReport",
    "collect_metrics",
    "decay_panel",
    "health_report",
    "health_trend",
    "measured_precision_at_5",
    "record_snapshot",
    "self_knowledge_panel",
]
