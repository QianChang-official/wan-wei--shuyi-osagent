"""
Workflow Run 持久化层

将 workflow runs 从内存字典迁移到 SQLite 持久化存储。

解决的问题：
1. 进程重启后数据丢失
2. 多进程部署时状态不同步
3. 无 TTL 清理导致内存泄漏
4. 无法水平扩展

设计：
- workflow_runs 表存储 run 元数据和完整 JSON
- 支持 TTL 自动清理（默认 7 天）
- 读优先从数据库，fallback 到内存（迁移期）
- 写同时更新数据库和内存（最终可移除内存部分）
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from ..db import get_conn
from ..utils.datetime_utils import utc_now, utc_now_iso


# 默认 TTL: 7 天
DEFAULT_TTL_DAYS = 7


def init_workflow_persistence() -> None:
    """
    初始化 workflow_runs 表。

    在应用启动时调用，确保表结构存在。
    """
    conn = get_conn()
    cursor = conn.cursor()

    # 创建 workflow_runs 表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS workflow_runs (
            run_id TEXT PRIMARY KEY,
            trace_id TEXT NOT NULL,
            scenario TEXT NOT NULL,
            user_goal TEXT NOT NULL,
            status TEXT NOT NULL,
            dry_run INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            -- 完整的 run 数据存储为 JSON
            run_data TEXT NOT NULL,
            -- 索引字段
            version TEXT NOT NULL,
            total_stages INTEGER,
            completed_stages INTEGER,
            skipped_stages INTEGER,
            latency_ms INTEGER,
            risk_level TEXT
        )
    ''')

    # 创建索引以加速查询
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_workflow_runs_created_at
        ON workflow_runs(created_at)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_workflow_runs_status
        ON workflow_runs(status)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_workflow_runs_scenario
        ON workflow_runs(scenario)
    ''')

    conn.commit()
    conn.close()


def save_run(run_id: str, run_data: dict[str, Any]) -> None:
    """
    保存 workflow run 到数据库。

    参数:
        run_id: 运行 ID
        run_data: 完整的 run 数据字典
    """
    conn = get_conn()
    cursor = conn.cursor()

    summary = run_data.get('summary', {})

    cursor.execute('''
        INSERT OR REPLACE INTO workflow_runs (
            run_id, trace_id, scenario, user_goal, status, dry_run,
            created_at, completed_at, run_data, version,
            total_stages, completed_stages, skipped_stages,
            latency_ms, risk_level
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        run_id,
        run_data.get('trace_id', ''),
        run_data.get('scenario', ''),
        run_data.get('user_goal', ''),
        run_data.get('status', 'unknown'),
        1 if run_data.get('dry_run', True) else 0,
        run_data.get('created_at', utc_now_iso()),
        run_data.get('completed_at'),
        json.dumps(run_data, ensure_ascii=False),
        run_data.get('version', ''),
        summary.get('total_stages', 0),
        summary.get('completed_stages', 0),
        summary.get('skipped_stages', 0),
        summary.get('latency_ms', 0),
        summary.get('risk_level', 'unknown'),
    ))

    conn.commit()
    conn.close()


def get_run(run_id: str) -> dict[str, Any] | None:
    """
    从数据库读取 workflow run。

    参数:
        run_id: 运行 ID

    返回:
        完整的 run 数据字典，如果不存在返回 None
    """
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT run_data FROM workflow_runs WHERE run_id = ?
    ''', (run_id,))

    row = cursor.fetchone()
    conn.close()

    if row:
        return json.loads(row[0])
    return None


def list_runs(
    limit: int = 100,
    offset: int = 0,
    scenario: str | None = None,
    status: str | None = None
) -> list[dict[str, Any]]:
    """
    列出 workflow runs（支持分页和过滤）。

    参数:
        limit: 返回数量限制
        offset: 偏移量（分页）
        scenario: 场景过滤（可选）
        status: 状态过滤（可选）

    返回:
        run 数据列表
    """
    conn = get_conn()
    cursor = conn.cursor()

    query = 'SELECT run_data FROM workflow_runs WHERE 1=1'
    params: list[Any] = []

    if scenario:
        query += ' AND scenario = ?'
        params.append(scenario)

    if status:
        query += ' AND status = ?'
        params.append(status)

    query += ' ORDER BY created_at DESC LIMIT ? OFFSET ?'
    params.extend([limit, offset])

    cursor.execute(query, params)

    runs = [json.loads(row[0]) for row in cursor.fetchall()]
    conn.close()

    return runs


def cleanup_old_runs(ttl_days: int = DEFAULT_TTL_DAYS) -> int:
    """
    清理过期的 workflow runs。

    参数:
        ttl_days: TTL 天数（默认 7 天）

    返回:
        删除的记录数
    """
    conn = get_conn()
    cursor = conn.cursor()

    # 计算过期时间阈值
    cutoff = utc_now() - timedelta(days=ttl_days)
    cutoff_iso = cutoff.isoformat()

    # 删除过期记录
    cursor.execute('''
        DELETE FROM workflow_runs
        WHERE created_at < ?
    ''', (cutoff_iso,))

    deleted_count = cursor.rowcount
    conn.commit()
    conn.close()

    return deleted_count


def get_run_count() -> int:
    """
    获取当前存储的 run 总数。

    返回:
        run 记录数
    """
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute('SELECT COUNT(*) FROM workflow_runs')
    count = cursor.fetchone()[0]

    conn.close()
    return count


def get_storage_stats() -> dict[str, Any]:
    """
    获取存储统计信息。

    返回:
        包含总数、状态分布、最旧记录时间等的统计字典
    """
    conn = get_conn()
    cursor = conn.cursor()

    # 总数
    cursor.execute('SELECT COUNT(*) FROM workflow_runs')
    total = cursor.fetchone()[0]

    # 状态分布
    cursor.execute('''
        SELECT status, COUNT(*)
        FROM workflow_runs
        GROUP BY status
    ''')
    status_distribution = dict(cursor.fetchall())

    # 最旧和最新记录
    cursor.execute('''
        SELECT MIN(created_at), MAX(created_at)
        FROM workflow_runs
    ''')
    oldest, newest = cursor.fetchone()

    # 场景分布
    cursor.execute('''
        SELECT scenario, COUNT(*)
        FROM workflow_runs
        GROUP BY scenario
    ''')
    scenario_distribution = dict(cursor.fetchall())

    conn.close()

    return {
        'total_runs': total,
        'status_distribution': status_distribution,
        'scenario_distribution': scenario_distribution,
        'oldest_run': oldest,
        'newest_run': newest,
    }
