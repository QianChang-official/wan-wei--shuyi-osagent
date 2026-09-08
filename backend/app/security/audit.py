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

"""Agent Audit：一键审计当前部署的安全与治理姿态。

设计目标：把「修安全问题」变成「出审计报告」。复用 Security Score 的检查项，
扩展数据隔离、记忆完整性、密钥轮换状态等治理维度，输出结构化审计报告。

与 Security Score 的区别：
- Score 是「当前状态评分」，供日常监控；
- Audit 是「完整检查报告」，供交付前自检、合规留档。
"""
from __future__ import annotations

from typing import Any

from .score import compute_security_score


def _check_localhost_exposure() -> dict[str, Any]:
    """localhost 暴露面：回环免密状态 + Origin/Host 校验。"""
    from .auth import (
        _is_loopback_bound,
        _loopback_exempt_enabled,
        _loopback_exempt_write_allowed,
    )

    bound = _is_loopback_bound()
    read_exempt = _loopback_exempt_enabled()
    write_exempt = _loopback_exempt_write_allowed()

    issues: list[str] = []
    if not bound:
        issues.append("绑定非回环地址，API 暴露到网络")
    if read_exempt:
        issues.append("回环免密开启（裸启动默认）")
    if write_exempt:
        issues.append("回环免密覆盖写操作")

    ok = not issues
    return {
        "id": "localhost_exposure",
        "name": "localhost 暴露面",
        "passed": ok,
        "detail": "回环绑定 + 免密已关闭" if ok else "; ".join(issues),
        "severity": "critical" if not bound else ("warning" if not ok else "info"),
    }


def _check_data_isolation() -> dict[str, Any]:
    """数据隔离：identity 表就绪 + 活跃身份数量。"""
    from .auth import _identity_table_ready

    ready = _identity_table_ready()
    if not ready:
        return {
            "id": "data_isolation",
            "name": "数据隔离",
            "passed": False,
            "detail": "identity 表未建（回退到旧版派生，无多身份隔离）",
            "severity": "warning",
        }

    from ..db import get_conn

    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(DISTINCT identity_id) AS cnt FROM identity WHERE is_active=1"
    ).fetchone()
    count = row["cnt"] if row else 0
    return {
        "id": "data_isolation",
        "name": "数据隔离",
        "passed": count >= 1,
        "detail": f"identity 表就绪，活跃身份 {count} 个",
        "severity": "info" if count >= 1 else "warning",
    }


def _check_key_rotation_status() -> dict[str, Any]:
    """密钥轮换状态：是否存在已轮换/撤销的 key。"""
    from .auth import _identity_table_ready

    if not _identity_table_ready():
        return {
            "id": "key_rotation_status",
            "name": "密钥轮换状态",
            "passed": False,
            "detail": "identity 表未建，无法评估",
            "severity": "warning",
        }

    from ..db import get_conn

    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM identity WHERE is_active=0"
    ).fetchone()
    rotated = row["cnt"] if row else 0
    return {
        "id": "key_rotation_status",
        "name": "密钥轮换状态",
        "passed": True,
        "detail": f"已轮换/撤销 {rotated} 个 key（历史数据保留）",
        "severity": "info",
    }


def _check_memory_integrity() -> dict[str, Any]:
    """记忆完整性：capsule/event 表存在性 + 孤立记录检测。"""
    from ..db import get_conn

    conn = get_conn()
    issues: list[str] = []

    for table in ("memory_capsules_v2", "memory_events", "soul_persona"):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        if not row:
            issues.append(f"{table} 表不存在")

    if not issues:
        # 检测无 soul 关联的孤儿 capsule
        orphan = conn.execute(
            """
            SELECT COUNT(*) FROM memory_capsules_v2 mc
            WHERE NOT EXISTS (
                SELECT 1 FROM soul_persona sp
                WHERE json_extract(mc.provenance, '$.soul_id') = sp.soul_id
            )
            """
        ).fetchone()[0]
        if orphan > 0:
            issues.append(f"发现 {orphan} 条孤儿记忆（无 soul 关联）")

    ok = not issues
    return {
        "id": "memory_integrity",
        "name": "记忆完整性",
        "passed": ok,
        "detail": "核心表齐全，无孤儿记忆" if ok else "; ".join(issues),
        "severity": "warning" if not ok else "info",
    }


def run_agent_audit() -> dict[str, Any]:
    """执行一键审计，返回结构化报告。

    输出::
        {
            "audit_id": "audit_<timestamp>",
            "timestamp": "...",
            "security_score": {...},
            "checks": [...],
            "summary": {"total": n, "passed": n, "warnings": n, "critical": n},
        }
    """
    from ..utils.datetime_utils import utc_now_iso_compact

    score = compute_security_score()
    extra_checks = [
        _check_localhost_exposure(),
        _check_data_isolation(),
        _check_key_rotation_status(),
        _check_memory_integrity(),
    ]

    all_checks = score["checks"] + extra_checks
    critical = sum(1 for c in all_checks if c.get("severity") == "critical")
    warnings = sum(
        1 for c in all_checks if not c.get("passed") and c.get("severity") != "critical"
    )

    return {
        "audit_id": f"audit_{utc_now_iso_compact()}",
        "timestamp": utc_now_iso_compact(),
        "security_score": score,
        "checks": all_checks,
        "summary": {
            "total": len(all_checks),
            "passed": sum(1 for c in all_checks if c.get("passed")),
            "warnings": warnings,
            "critical": critical,
        },
    }
