# Memory Governance & Accounting Specification

> 来源：6.docx P1 最高 ROI 建议（4.docx 扩展）
> 状态：规范草案 + Python/SQLite 实现草案，供浅唱审阅
> 日期：2026-08-20

## 1. 目标

把 Memory OS 从"组件清单"推进到"操作系统规范"。回答六个问题：

1. 每一次 write / update / retrieve / inject / delete 是否都进入账本？
2. 每条记忆的 owner、scope、source、confidence、valid_from、valid_until、supersedes 如何定义？
3. 什么情况下记忆进入 quarantine？
4. 删除如何验证覆盖原文、摘要、向量、图边、缓存？
5. MHG-3/4/5 如何触发发布冻结或事故响应？
6. 谁在什么时候、基于什么证据改了什么？

## 2. 核心概念

### 2.1 Memory Ledger（记忆账本）

类比：金融账本。每条记忆操作 = 一条不可变账目（append-only）。

```
memory_ledger 表（append-only）
├── ledger_id        TEXT PK        -- 账目 ID
├── op_type          TEXT           -- write/update/retrieve/inject/delete/quarantine/release
├── capsule_id       TEXT           -- 操作对象
├── actor            TEXT           -- 谁操作的（agent/human/system/plugin）
├── before_hash      TEXT           -- 操作前内容哈希（SHA-256）
├── after_hash       TEXT           -- 操作后内容哈希
├── reason           TEXT           -- 操作理由（自动抽取/用户指令/冲突解决/合规删除）
├── risk_class       TEXT           -- low/medium/high/critical
├── trace_id         TEXT           -- 关联检索 Trace
├── created_at       TEXT           -- ISO UTC
└── payload          JSON           -- 完整操作详情（旧值+新值+证据）
```

### 2.2 Provenance Card（来源卡）

每条记忆必须携带：

```
provenance:
  owner:           "user_xxx" | "soul_yyy"     # 属主（API principal 派生）
  scope:           "global" | "project" | "soul" # 可见范围
  source:          "user_input" | "tool_result" | "manual_config" | "eval" | "reflection"
  confidence:      0.0 - 1.0                    # 置信度
  valid_from:      ISO UTC                      # 生效时间
  valid_until:     ISO UTC | null               # 失效时间（null=不过期）
  supersedes:      [capsule_id...]              # 取代了哪些旧记忆
  superseded_by:   [capsule_id...]              # 被谁取代
  verification:    "manual" | "llm_checked" | "unverified"
  evidence_ids:    [evidence_card_id...]        # 证据卡引用
```

### 2.3 Quarantine（隔离区）

触发条件：
- Policy Gate 判定 require_confirmation
- 疑似投毒（Poisoning 检测命中）
- 新旧事实冲突且无法自动裁决
- 敏感信息（PII/凭据）未脱敏

隔离区记忆：**不可检索注入**，只可预览、确认、删除。

### 2.4 删除验证（Deletion Completeness）

删除一条记忆必须验证五处：
1. memory_capsules_v2 主记录（软删/硬删）
2. FTS5 全文索引
3. 向量索引（如果启用）
4. relation_edges 图边
5. 检索缓存/上下文快照

验证方式：删除后执行 `SELECT count(*) WHERE capsule_id=?` 确认 0 行 + FTS 查询确认无命中。

### 2.5 MHG 事故分级

| MHG | 级别 | 示例 | 动作 |
|-----|------|------|------|
| MHG-1 | 轻微 | 过期记忆被召回 | 记录，正常发布 |
| MHG-2 | 一般 | 错误记忆导致回答偏差 | 记录 + 告警 |
| MHG-3 | 严重 | 敏感记忆泄漏到错误 scope | **发布冻结 + 事故响应** |
| MHG-4 | 危险 | 投毒记忆触发高风险工具 | 一票否决 + 回滚 + 红队复盘 |
| MHG-5 | 灾难 | 跨租户泄漏 / 删除残留可被召回 | 一票否决 + 全量审计 |

## 3. SQLite 实现草案

```python
# memory_governance.py
"""Memory Governance & Accounting 实现草案"""
import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_ledger (
    ledger_id   TEXT PRIMARY KEY,
    op_type     TEXT NOT NULL,
    capsule_id  TEXT NOT NULL,
    actor       TEXT NOT NULL,
    before_hash TEXT,
    after_hash  TEXT,
    reason      TEXT,
    risk_class  TEXT DEFAULT 'low',
    trace_id    TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ledger_capsule ON memory_ledger(capsule_id);
CREATE INDEX IF NOT EXISTS idx_ledger_op ON memory_ledger(op_type);
"""


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def append_ledger(conn: sqlite3.Connection, *, op_type: str, capsule_id: str,
                  actor: str, content_before: str | None, content_after: str | None,
                  reason: str, risk_class: str = 'low', trace_id: str | None = None) -> str:
    """写入一条不可变账目。返回 ledger_id。"""
    ledger_id = 'led_' + uuid.uuid4().hex[:12]
    conn.execute(
        """INSERT INTO memory_ledger
           (ledger_id, op_type, capsule_id, actor, before_hash, after_hash,
            reason, risk_class, trace_id, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (ledger_id, op_type, capsule_id, actor,
         sha256(content_before) if content_before is not None else None,
         sha256(content_after) if content_after is not None else None,
         reason, risk_class, trace_id, now_iso()),
    )
    conn.commit()
    return ledger_id


def verify_deletion(conn: sqlite3.Connection, capsule_id: str) -> dict:
    """删除验证：主记录 + FTS + 图边 + 账本。返回各项状态。"""
    checks = {
        'capsules': conn.execute(
            "SELECT count(*) FROM memory_capsules_v2 WHERE capsule_id=?", (capsule_id,)).fetchone()[0],
        'fts': conn.execute(
            "SELECT count(*) FROM memory_capsules_fts WHERE capsule_id=?", (capsule_id,)).fetchone()[0],
        'edges': conn.execute(
            "SELECT count(*) FROM relation_edges WHERE from_id=? OR to_id=?", (capsule_id, capsule_id)).fetchone()[0],
    }
    checks['deleted'] = all(v == 0 for v in checks.values())
    return checks


def quarantine(conn: sqlite3.Connection, capsule_id: str, reason: str, actor: str) -> str:
    """将记忆移入隔离区（生命周期状态切到 quarantined）。"""
    append_ledger(conn, op_type='quarantine', capsule_id=capsule_id,
                  actor=actor, content_before=None, content_after=None,
                  reason=reason, risk_class='medium')
    conn.execute(
        "UPDATE memory_capsules_v2 SET state='quarantined' WHERE capsule_id=?",
        (capsule_id,))
    conn.commit()
    return capsule_id


def mhg_response(mhg_level: int, incident: dict) -> dict:
    """MHG 事故响应。"""
    actions = []
    if mhg_level >= 3:
        actions.append('publish_freeze')      # 发布冻结
    if mhg_level >= 4:
        actions.append('rollback')            # 回滚
        actions.append('red_team_review')     # 红队复盘
    if mhg_level >= 5:
        actions.append('full_audit')          # 全量审计
        actions.append('ledger_export')       # 账本导出
    return {
        'mhg_level': mhg_level,
        'incident_id': 'inc_' + uuid.uuid4().hex[:10],
        'actions': actions,
        'detail': incident,
        'created_at': now_iso(),
    }


# --- 使用示例 ---
if __name__ == '__main__':
    conn = sqlite3.connect(':memory:')
    conn.executescript(SCHEMA)
    conn.execute("""CREATE TABLE memory_capsules_v2 (capsule_id TEXT PRIMARY KEY, state TEXT)""")
    conn.execute("""CREATE TABLE memory_capsules_fts (capsule_id TEXT PRIMARY KEY)""")
    conn.execute("""CREATE TABLE relation_edges (from_id TEXT, to_id TEXT)""")

    # 写入 + 入账
    cid = 'cap_test001'
    conn.execute("INSERT INTO memory_capsules_v2 VALUES (?, 'active')", (cid,))
    lid = append_ledger(conn, op_type='write', capsule_id=cid, actor='agent',
                        content_before=None, content_after='{"text": "hello"}',
                        reason='user said remember')
    print(f'ledger: {lid}')

    # 删除验证
    conn.execute("DELETE FROM memory_capsules_v2 WHERE capsule_id=?", (cid,))
    print('deletion check:', verify_deletion(conn, cid))

    # MHG 事故响应
    print(mhg_response(4, {'desc': 'poisoned memory triggered high-risk tool'}))
```

## 4. 集成点（宛委·枢忆）

| 现有组件 | 新增/改动 |
|---------|----------|
| capsule_store.write_capsule | 追加 append_ledger(op_type=write) |
| capsule_store.update_capsule | 追加 append_ledger(op_type=update) + before/after hash |
| capsule_store.forget_capsules | 追加 append_ledger(delete) + verify_deletion |
| policy_gate.evaluate_policy | 结果含 risk_class 写入账本 |
| 检索入口 | append_ledger(op_type=retrieve, trace_id) |
| /memory/forget 系列 | 删除后调 verify_deletion 返回证据 |

## 5. 验收标准

- [ ] 每次写/改/删都有账目（抽查 100 次操作 100% 有 ledger）
- [ ] 删除后 verify_deletion 返回全零（主/FTS/边）
- [ ] quarantine 的记忆不可被检索注入
- [ ] MHG-3+ 触发 publish_freeze 有测试覆盖
