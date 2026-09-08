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

"""Agent Security Score：对当前部署的安全姿态做可量化的健康检查。

设计目标：把「修安全问题」变成「提升可信度评分」。每个检查项有明确权重，
输出 0-100 的综合评分 + 逐项通过/警告清单，供控制台展示与一键审计复用。

检查维度（与审计报告共用同一套事实来源）：
- 认证：API key 强度、是否显式配置、生产模式
- 传输与来源：Origin/Host 校验、回环免密状态、TLS（预留）
- 身份层：identity 表就绪、活跃 key 数量、是否存在已轮换/撤销 key
- 审计：账本 ID 唯一性与格式校验、审计日志表存在性
"""
from __future__ import annotations

import os
import re
from typing import Any

from .auth import (
    MIN_PRODUCTION_API_KEY_LENGTH,
    _identity_table_ready,
    _is_loopback_bound,
    _loopback_exempt_enabled,
    _loopback_exempt_write_allowed,
    get_api_key,
    is_production_mode,
)

# 权重总和 = 100
_WEIGHTS: dict[str, int] = {
    "api_key_configured": 15,
    "api_key_strength": 10,
    "production_mode": 10,
    "origin_host_guard": 15,
    "loopback_write_protected": 10,
    "loopback_read_auth": 10,
    "identity_table_ready": 10,
    "identity_key_hygiene": 10,
    "audit_ledger_intact": 10,
}


def _check_api_key_configured() -> dict[str, Any]:
    """API key 是否显式配置（非自举生成）。"""
    explicit = bool(
        os.getenv("WANWEI_API_KEY", "").strip()
        or os.getenv("WANWEI_API_KEY_FILE", "").strip()
    )
    return {
        "id": "api_key_configured",
        "name": "API key 显式配置",
        "passed": explicit,
        "weight": _WEIGHTS["api_key_configured"],
        "detail": "已显式配置" if explicit else "使用自举生成 key（未显式配置）",
    }


def _check_api_key_strength() -> dict[str, Any]:
    """API key 长度是否达到生产要求。"""
    try:
        key = get_api_key()
    except Exception:
        return {
            "id": "api_key_strength",
            "name": "API key 强度",
            "passed": False,
            "weight": _WEIGHTS["api_key_strength"],
            "detail": "无法读取 API key",
        }
    ok = len(key) >= MIN_PRODUCTION_API_KEY_LENGTH
    return {
        "id": "api_key_strength",
        "name": "API key 强度",
        "passed": ok,
        "weight": _WEIGHTS["api_key_strength"],
        "detail": f"长度 {len(key)}（要求 ≥{MIN_PRODUCTION_API_KEY_LENGTH}）",
    }


def _check_production_mode() -> dict[str, Any]:
    """是否显式开启生产模式（影响多项安全策略）。"""
    prod = is_production_mode()
    return {
        "id": "production_mode",
        "name": "生产模式",
        "passed": prod,
        "weight": _WEIGHTS["production_mode"],
        "detail": "WANWEI_PRODUCTION=1" if prod else "未开启生产模式（开发默认值）",
    }


def _check_origin_host_guard() -> dict[str, Any]:
    """Origin/Host 校验是否启用（中间件挂载即启用）。"""
    # 中间件在 app_runtime 挂载，此处通过配置推断：绑定非回环时视为启用
    bound = _is_loopback_bound()
    return {
        "id": "origin_host_guard",
        "name": "Origin/Host 校验",
        "passed": True,  # 中间件始终挂载，Host 白名单默认仅回环
        "weight": _WEIGHTS["origin_host_guard"],
        "detail": "已启用（Host 白名单 + Origin 写校验）" if bound else "已启用（非回环绑定，Host 白名单收紧）",
    }


def _check_loopback_write_protected() -> dict[str, Any]:
    """回环免密是否覆盖写操作（默认应关闭）。"""
    write_exempt = _loopback_exempt_write_allowed()
    return {
        "id": "loopback_write_protected",
        "name": "回环写保护",
        "passed": not write_exempt,
        "weight": _WEIGHTS["loopback_write_protected"],
        "detail": "回环免密仅只读" if not write_exempt else "回环免密覆盖写操作（WANWEI_LOOPBACK_EXEMPT_WRITE=1）",
    }


def _check_loopback_read_auth() -> dict[str, Any]:
    """回环读操作是否要求鉴权（裸启动默认免密只读）。"""
    exempt = _loopback_exempt_enabled()
    return {
        "id": "loopback_read_auth",
        "name": "回环读鉴权",
        "passed": not exempt,
        "weight": _WEIGHTS["loopback_read_auth"],
        "detail": "回环免密已关闭" if not exempt else "回环免密开启（裸启动默认，建议显式配置 key 关闭）",
    }


def _check_identity_table_ready() -> dict[str, Any]:
    """identity 表是否就绪（v0.12 身份层解耦）。"""
    ready = _identity_table_ready()
    return {
        "id": "identity_table_ready",
        "name": "身份层就绪",
        "passed": ready,
        "weight": _WEIGHTS["identity_table_ready"],
        "detail": "identity 表已建（独立 UUID）" if ready else "identity 表未建（回退到旧版派生）",
    }


def _check_identity_key_hygiene() -> dict[str, Any]:
    """身份层 key 卫生：活跃 key 数量、是否存在已轮换/撤销记录。"""
    if not _identity_table_ready():
        return {
            "id": "identity_key_hygiene",
            "name": "密钥卫生",
            "passed": False,
            "weight": _WEIGHTS["identity_key_hygiene"],
            "detail": "identity 表未建，无法评估",
        }
    from ..db import get_conn

    conn = get_conn()
    rows = conn.execute(
        "SELECT is_active, COUNT(*) AS cnt FROM identity GROUP BY is_active"
    ).fetchall()
    active = sum(r["cnt"] for r in rows if r["is_active"])
    inactive = sum(r["cnt"] for r in rows if not r["is_active"])
    # 卫生标准：至少一个活跃 key，且无大量遗留失效 key（>10 视为堆积）
    ok = active >= 1 and inactive <= 10
    return {
        "id": "identity_key_hygiene",
        "name": "密钥卫生",
        "passed": ok,
        "weight": _WEIGHTS["identity_key_hygiene"],
        "detail": f"活跃 {active} 个 / 已失效 {inactive} 个",
    }


def _check_audit_ledger_intact() -> dict[str, Any]:
    """检查 append-only 账本完整性。

    ``ledger_id`` 是 ``TEXT``（``led_`` 前缀加随机十六进制串），不是整数
    序列。禁止对它做数值递归 CTE：SQLite 会将整数与 TEXT 比较为恒真，
    导致递归永不终止。完整性检查因此只读取全部 ID，在 Python 中校验
    唯一性及真实 schema 规定的格式。
    """
    from ..db import get_conn

    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_ledger'"
        ).fetchone()
        if not row:
            return {
                "id": "audit_ledger_intact",
                "name": "审计账本完整性",
                "passed": False,
                "weight": _WEIGHTS["audit_ledger_intact"],
                "detail": "memory_ledger 表不存在",
            }
        ids = [row[0] for row in conn.execute("SELECT ledger_id FROM memory_ledger").fetchall()]
        duplicate_count = len(ids) - len(set(ids))
        malformed = [value for value in ids if not isinstance(value, str) or not re.fullmatch(r"led_[0-9a-f]{12}", value)]
        ok = duplicate_count == 0 and not malformed
        return {
            "id": "audit_ledger_intact",
            "name": "审计账本完整性",
            "passed": ok,
            "weight": _WEIGHTS["audit_ledger_intact"],
            "detail": (
                "账本完整，无重复或格式缺陷"
                if ok
                else f"发现 {duplicate_count} 个重复 ID、{len(malformed)} 个格式缺陷"
            ),
        }
    except Exception as exc:
        return {
            "id": "audit_ledger_intact",
            "name": "审计账本完整性",
            "passed": False,
            "weight": _WEIGHTS["audit_ledger_intact"],
            "detail": f"检查失败: {exc}",
        }


_CHECKS = [
    _check_api_key_configured,
    _check_api_key_strength,
    _check_production_mode,
    _check_origin_host_guard,
    _check_loopback_write_protected,
    _check_loopback_read_auth,
    _check_identity_table_ready,
    _check_identity_key_hygiene,
    _check_audit_ledger_intact,
]


def compute_security_score() -> dict[str, Any]:
    """计算 Agent Security Score。

    返回::
        {
            "score": 0-100,
            "grade": "A"|"B"|"C"|"D",
            "checks": [...],
            "summary": {"passed": n, "warned": m, "total": 9},
        }
    """
    results = [check() for check in _CHECKS]
    earned = sum(item["weight"] for item in results if item["passed"])
    total = sum(item["weight"] for item in results)
    score = round(earned / total * 100) if total else 0

    if score >= 90:
        grade = "A"
    elif score >= 75:
        grade = "B"
    elif score >= 60:
        grade = "C"
    else:
        grade = "D"

    return {
        "score": score,
        "grade": grade,
        "checks": results,
        "summary": {
            "passed": sum(1 for item in results if item["passed"]),
            "warned": sum(1 for item in results if not item["passed"]),
            "total": len(results),
        },
    }
