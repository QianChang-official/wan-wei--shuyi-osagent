# 第 8 章:Governance / Accounting / Lifecycle 规范

> **Canonical**:本章是 **Ledger、Provenance Card、Lifecycle 状态机、Quarantine、删除验证**的唯一权威定义处。第 3 章只定义分层结构,第 6 章只提出指标需求。
> **来源**:新增 + 4.docx 扩展 → `MemoryOS-Governance账本规范.md` + `MemoryOS-Lifecycle状态机.md` + `MemoryOS-core参考实现.md`(2026-08-20)
> **状态**:已合并。这是全书的规范核心。

## 8.1 目标

把 Memory OS 从「组件清单」推进到「操作系统规范」。回答六个问题:

1. 每一次 write / update / retrieve / inject / delete 是否都进入账本?
2. 每条记忆的 owner、scope、source、confidence、valid_from、valid_until、supersedes 如何定义?
3. 什么情况下记忆进入 quarantine?
4. 删除如何验证覆盖原文、摘要、向量、图边、缓存?
5. MHG-3/4/5 如何触发发布冻结或事故响应?
6. 谁在什么时候、基于什么证据改了什么?

## 8.2 Memory Ledger(记忆账本)

类比:金融账本。每条记忆操作 = 一条不可变账目(append-only)。

```
memory_ledger 表(append-only)
├── ledger_id        TEXT PK        -- 账目 ID
├── op_type          TEXT           -- write/update/retrieve/inject/delete/quarantine/release
├── capsule_id       TEXT           -- 操作对象
├── actor            TEXT           -- 谁操作的(agent/human/system/plugin)
├── before_hash      TEXT           -- 操作前内容哈希(SHA-256)
├── after_hash       TEXT           -- 操作后内容哈希
├── reason           TEXT           -- 操作理由
├── risk_class       TEXT           -- low/medium/high/critical
├── trace_id         TEXT           -- 关联检索 Trace
├── created_at       TEXT           -- ISO UTC
└── payload          JSON           -- 完整操作详情(旧值+新值+证据)
```

## 8.3 Provenance Card(来源卡)

每条记忆必须携带:

```
provenance:
  owner:           "user_xxx" | "soul_yyy"
  scope:           "global" | "project" | "soul"
  source:          "user_input" | "tool_result" | "manual_config" | "eval" | "reflection"
  confidence:      0.0 - 1.0
  valid_from:      ISO UTC
  valid_until:     ISO UTC | null
  supersedes:      [capsule_id...]
  superseded_by:   [capsule_id...]
  verification:    "manual" | "llm_checked" | "unverified"
  evidence_ids:    [evidence_card_id...]
```

## 8.4 Quarantine(隔离区)

触发条件:

- Policy Gate 判定 require_confirmation
- 疑似投毒(Poisoning 检测命中)
- 新旧事实冲突且无法自动裁决
- 敏感信息(PII/凭据)未脱敏

隔离区记忆:**不可检索注入**,只可预览、确认、删除。

## 8.5 删除验证(Deletion Completeness)

删除一条记忆必须验证五处:

1. memory_capsules_v2 主记录(软删/硬删)
2. FTS5 全文索引
3. 向量索引(如果启用)
4. relation_edges 图边
5. 检索缓存/上下文快照

验证方式:删除后执行 `SELECT count(*) WHERE capsule_id=?` 确认 0 行 + FTS 查询确认无命中。

**向量索引与检索缓存的覆盖说明**:当前草案的 `verify_deletion` 实现只覆盖前 3 处(主记录 + FTS + 图边)。向量索引与检索缓存的验证依赖具体部署形态:

- 向量索引:若启用,删除时同步调 `vector_index.delete(capsule_id)`,由向量层自身保证删除;`verify_deletion` 扩展为可选参数 `check_vector: bool = False`,启用时追加向量层计数检查。
- 检索缓存/上下文快照:属于会话级瞬态,在下次会话重建时自然过期;不进入持久化验证范围,但必须在文档中声明此边界。

## 8.6 MHG 事故响应

分级定义见第 6 章 §6.1.1(Canonical)。本节定义响应协议:

```python
def mhg_response(mhg_level: int, incident: dict) -> dict:
    actions = []
    if mhg_level >= 3:
        actions.append('publish_freeze')
    if mhg_level >= 4:
        actions.append('rollback')
        actions.append('red_team_review')
    if mhg_level >= 5:
        actions.append('full_audit')
        actions.append('ledger_export')
    return {
        'mhg_level': mhg_level,
        'incident_id': incident.get('incident_id', 'inc_' + uuid.uuid4().hex[:10]),
        'actions': actions,
        'detail': incident,
        'created_at': now_iso(),
    }
```

## 8.7 SQLite 实现草案(Governance)

```python
# memory_governance.py
import hashlib
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
    """删除验证:主记录 + FTS + 图边。返回各项状态。"""
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
```

## 8.8 Lifecycle 状态机

### 8.8.1 状态定义

```
candidate → active → reinforced → stale → conflicted → archived → quarantined → deleted
```

| 状态 | 含义 | 触发条件 | 允许操作 | 是否可检索 |
|---|---|---|---|---|
| candidate | 待确认候选 | 新写入但 require_confirmation | confirm / reject / timeout | ❌ |
| active | 活跃记忆 | 确认通过 / 直接写入 | update / reinforce / archive / quarantine / delete | ✅ |
| reinforced | 强化记忆 | 重复命中 ≥2 次 | update / archive / quarantine / delete | ✅(高权重) |
| stale | 过期记忆 | valid_until 到期 / 长期未用 | refresh / archive / delete | ⚠️(低权重或弃权) |
| conflicted | 冲突记忆 | 新事实与旧事实矛盾 | resolve / supersede / archive / quarantine | ❌(需裁决) |
| archived | 归档记忆 | 主动归档 / 自动降权 | restore / delete | ❌(不进上下文) |
| quarantined | 隔离记忆 | 投毒/敏感/未确认 | preview / confirm / delete | ❌ |
| deleted | 已删除 | 用户/合规删除 | 无(只留账本) | ❌ |

### 8.8.2 关键规则

1. **candidate 必须显式确认**才能进 active(防止噪声自动进入)
2. **conflicted 必须裁决**:supersede(新压旧)或 resolve(合并);无法自动裁决时可 archive 或 quarantine
3. **stale 不直接删除**:refresh 或 archive,留审计
4. **quarantined 不可检索注入**(安全底线);active/reinforced 状态发现投毒或 PII 未脱敏时可随时转 quarantined(安全优先于状态机纯度)
5. **deleted 只留账本**,物理删除或软删由策略决定

### 8.8.3 合法转移表与实现

```python
class LifecycleState(str, Enum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    REINFORCED = "reinforced"
    STALE = "stale"
    CONFLICTED = "conflicted"
    ARCHIVED = "archived"
    QUARANTINED = "quarantined"
    DELETED = "deleted"


TRANSITIONS = {
    LifecycleState.CANDIDATE: {LifecycleState.ACTIVE, LifecycleState.DELETED, LifecycleState.QUARANTINED},
    LifecycleState.ACTIVE: {LifecycleState.REINFORCED, LifecycleState.STALE, LifecycleState.CONFLICTED,
                            LifecycleState.ARCHIVED, LifecycleState.QUARANTINED, LifecycleState.DELETED},
    LifecycleState.REINFORCED: {LifecycleState.STALE, LifecycleState.CONFLICTED,
                                LifecycleState.ARCHIVED, LifecycleState.QUARANTINED, LifecycleState.DELETED},
    LifecycleState.STALE: {LifecycleState.ACTIVE, LifecycleState.ARCHIVED, LifecycleState.DELETED},
    LifecycleState.CONFLICTED: {LifecycleState.ACTIVE, LifecycleState.ARCHIVED,
                                LifecycleState.QUARANTINED, LifecycleState.DELETED},
    LifecycleState.ARCHIVED: {LifecycleState.ACTIVE, LifecycleState.DELETED},
    LifecycleState.QUARANTINED: {LifecycleState.ACTIVE, LifecycleState.DELETED},
    LifecycleState.DELETED: set(),
}
```

非法转移抛错;每次转移写账本(history 字段可审计)。

## 8.9 memoryos-core 参考实现(门面整合)

把 Governance + Lifecycle + Accounting + Health 合成一个可运行的核心包:

```
memoryos-core/
├── memoryos/
│   ├── __init__.py          # MemoryOS 门面
│   ├── core.py              # 统一入口(write/recall/update/forget)
│   ├── lifecycle.py         # 状态机(§8.8)
│   ├── governance.py        # 账本 + Provenance + 删除验证 + MHG(§8.2-8.7)
│   ├── accounting.py        # 经济账本(第 6 章 §6.2)
│   ├── health.py            # 健康度(第 6 章 §6.4)
│   └── harness.py           # MEB 评测(第 5 章)
├── tests/
│   └── test_core.py
└── pyproject.toml
```

设计原则:

1. 全部 Python 标准库(sqlite3/json/datetime),零外部依赖
2. 每个子模块可独立使用,也可通过 `MemoryOS` 门面统一调用
3. 所有持久化走 SQLite,单文件可跑
4. 接口与宛委·枢忆现有 API 对齐(write_capsule/forget/retrieve)

核心门面(core.py)串联逻辑:write → Lifecycle 入状态机 + Governance 入账 + Accounting 记账;recall → 只召回 active/reinforced + 记账 + 记 trace;forget → 删除 + 五处验证。

## 8.10 集成点(宛委·枢忆)

| 现有组件 | 新增/改动 |
|---|---|
| capsule_store.write_capsule | 追加 append_ledger(op_type=write) |
| capsule_store.update_capsule | 追加 append_ledger(op_type=update) + before/after hash |
| capsule_store.forget_capsules | 追加 append_ledger(delete) + verify_deletion |
| policy_gate.evaluate_policy | 结果含 risk_class 写入账本 |
| 检索入口 | append_ledger(op_type=retrieve, trace_id) |
| /memory/forget 系列 | 删除后调 verify_deletion 返回证据 |
| policy_gate "require_confirmation" | write 时进 candidate 而非 active |
| 检索命中计数 | on_recall 更新 hit_count + 强化 |
| 冲突检测 | 写入前同类候选召回 + LLM/规则判冲突 → conflicted |
| valid_until 字段 | 定时任务扫描 → mark_stale |
| 梦境归档 | archived 批量 + 巩固 |

## 8.11 验收标准

- [ ] 每次写/改/删都有账目(抽查 100 次操作 100% 有 ledger)
- [ ] 删除后 verify_deletion 返回全零(主/FTS/边)
- [ ] quarantine 的记忆不可被检索注入
- [ ] MHG-3+ 触发 publish_freeze 有测试覆盖
- [ ] 非法转移被拒绝(deleted → active 抛错)
- [ ] candidate 未确认不进入检索
- [ ] 冲突必须显式裁决,不自动覆盖
- [ ] `python -m memoryos` 跑通写入→召回→删除全流程
