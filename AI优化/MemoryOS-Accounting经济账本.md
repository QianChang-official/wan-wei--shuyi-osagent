# Memory Accounting 经济账本规范（MemoryOS-Accounting）

> 来源：ChatGPT 5.6 缺口 2（Governance 有 Ledger，但 Economics 没落到账）
> 定位：把 Memory Economics 从"概念"变成"逐条记忆的成本-收益-ROI 账本"
> 状态：规范草案 + Python 实现，供浅唱审阅
> 日期：2026-08-20

## 1. 为什么需要 Memory Accounting

Memory Economics 说了"每 KB 记忆产生多少价值"，但没有定义**怎么算**。
Memory Accounting 就是逐条记忆的记账本：

```
每条记忆
├── 存储成本 (Storage Cost)
├── 检索成本 (Retrieval Cost)
├── 维护成本 (Maintenance Cost)
├── 产生收益 (Utility)
└── ROI = (收益 - 成本) / 成本
```

当 ROI < 0 → 进 Decay Panel → 归档/删除候选。

## 2. 成本模型

### 2.1 存储成本（一次性 + 持续）
- 一次性写入成本：LLM 抽取费用（tokens × 单价）
- 持续存储成本：字节数 × 存储单价 × 存储时长

### 2.2 检索成本（每次召回）
- 每次注入上下文的 tokens × 单价
- 检索延迟成本（时间）

### 2.3 维护成本（定期）
- 状态机扫描/巩固/衰减计算的资源消耗（按次计）

## 3. 收益模型

收益 = 记忆被"有用召回"带来的价值。定义三类事件：

| 事件 | 含义 | 收益值 |
|------|------|--------|
| useful_recall | 召回后回答正确/用户采纳 | +1.0 |
| neutral_recall | 召回但没影响 | +0.1 |
| harmful_recall | 召回导致错误/误导 | -2.0（并记入 Harm） |

## 4. 数据结构

```sql
CREATE TABLE memory_accounts (
    capsule_id      TEXT PRIMARY KEY,
    storage_cost    REAL DEFAULT 0,      -- 累计存储成本
    retrieval_cost  REAL DEFAULT 0,      -- 累计检索成本
    maintenance_cost REAL DEFAULT 0,     -- 累计维护成本
    total_cost      REAL DEFAULT 0,
    useful_recalls  INTEGER DEFAULT 0,   -- 有用召回次数
    neutral_recalls INTEGER DEFAULT 0,
    harmful_recalls INTEGER DEFAULT 0,
    utility         REAL DEFAULT 0,      -- 累计收益
    roi             REAL DEFAULT 0,      -- (utility - total_cost)/total_cost
    last_accessed   TEXT,
    created_at      TEXT
);
```

## 5. Python 实现

```python
# memory_accounting.py
"""Memory Accounting 逐条记忆经济账本"""
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_accounts (
    capsule_id TEXT PRIMARY KEY,
    storage_cost REAL DEFAULT 0,
    retrieval_cost REAL DEFAULT 0,
    maintenance_cost REAL DEFAULT 0,
    total_cost REAL DEFAULT 0,
    useful_recalls INTEGER DEFAULT 0,
    neutral_recalls INTEGER DEFAULT 0,
    harmful_recalls INTEGER DEFAULT 0,
    utility REAL DEFAULT 0,
    roi REAL DEFAULT 0,
    last_accessed TEXT,
    created_at TEXT
);
"""


@dataclass
class CostConfig:
    """成本单价配置"""
    token_cost: float = 0.000002    # 每 token 成本（示例：deepseek flash 级别）
    storage_per_kb: float = 0.00001  # 每 KB 每月的存储成本
    maintenance_fixed: float = 0.001  # 每次维护扫描固定成本


class MemoryAccountant:
    def __init__(self, db_path: str, config: CostConfig | None = None):
        self.conn = sqlite3.connect(db_path)
        self.conn.executescript(SCHEMA)
        self.cfg = config or CostConfig()

    def record_write(self, capsule_id: str, content_size_bytes: int,
                     extraction_tokens: int) -> None:
        """写入时记账：一次性抽取成本 + 初始存储。"""
        storage = content_size_bytes / 1024 * self.cfg.storage_per_kb
        cost = extraction_tokens * self.cfg.token_cost + storage
        self.conn.execute(
            """INSERT INTO memory_accounts
               (capsule_id, storage_cost, total_cost, created_at)
               VALUES (?,?,?,?)""",
            (capsule_id, storage, cost, now_iso()))
        self.conn.commit()

    def record_recall(self, capsule_id: str, outcome: str,
                      injected_tokens: int) -> None:
        """召回记账：成本 + 收益。outcome: useful/neutral/harmful"""
        retrieval = injected_tokens * self.cfg.token_cost
        utility = {"useful": 1.0, "neutral": 0.1, "harmful": -2.0}[outcome]

        self.conn.execute(
            """UPDATE memory_accounts SET
               retrieval_cost = retrieval_cost + ?,
               total_cost = total_cost + ?,
               useful_recalls = useful_recalls + ?,
               neutral_recalls = neutral_recalls + ?,
               harmful_recalls = harmful_recalls + ?,
               utility = utility + ?,
               last_accessed = ?
               WHERE capsule_id = ?""",
            (retrieval, retrieval,
             1 if outcome == 'useful' else 0,
             1 if outcome == 'neutral' else 0,
             1 if outcome == 'harmful' else 0,
             utility, now_iso(), capsule_id))
        self._recompute_roi(capsule_id)
        self.conn.commit()

    def record_maintenance(self, capsule_id: str) -> None:
        self.conn.execute(
            """UPDATE memory_accounts SET
               maintenance_cost = maintenance_cost + ?,
               total_cost = total_cost + ?
               WHERE capsule_id = ?""",
            (self.cfg.maintenance_fixed, self.cfg.maintenance_fixed, capsule_id))
        self._recompute_roi(capsule_id)
        self.conn.commit()

    def _recompute_roi(self, capsule_id: str) -> None:
        row = self.conn.execute(
            "SELECT total_cost, utility FROM memory_accounts WHERE capsule_id=?",
            (capsule_id,)).fetchone()
        if row:
            cost, util = row
            roi = (util - cost) / cost if cost > 0 else 0.0
            self.conn.execute(
                "UPDATE memory_accounts SET roi=? WHERE capsule_id=?",
                (round(roi, 4), capsule_id))

    def decay_candidates(self, min_roi: float = 0.0, limit: int = 50) -> list[dict]:
        """边际 ROI < min_roi 的记忆 = 衰减候选（进 Decay Panel）。"""
        rows = self.conn.execute(
            """SELECT capsule_id, total_cost, utility, roi, useful_recalls, harmful_recalls
               FROM memory_accounts WHERE roi < ? ORDER BY roi ASC LIMIT ?""",
            (min_roi, limit)).fetchall()
        return [{"capsule_id": r[0], "total_cost": r[1], "utility": r[2],
                 "roi": r[3], "useful": r[4], "harmful": r[5]} for r in rows]

    def summary(self) -> dict:
        row = self.conn.execute(
            """SELECT count(*), sum(total_cost), sum(utility),
                      sum(useful_recalls), sum(harmful_recalls)
               FROM memory_accounts""").fetchone()
        n, cost, util, useful, harmful = row
        return {
            "memories": n or 0,
            "total_cost": round(cost or 0, 4),
            "total_utility": round(util or 0, 4),
            "useful_recalls": useful or 0,
            "harmful_recalls": harmful or 0,
            "avg_roi": round((util - cost) / cost, 4) if cost else 0,
        }


# --- 使用示例 ---
if __name__ == '__main__':
    import tempfile, os
    db = os.path.join(tempfile.mkdtemp(), 'accounts.db')
    acct = MemoryAccountant(db)

    # 写入两条记忆
    acct.record_write('cap_1', content_size_bytes=2048, extraction_tokens=300)
    acct.record_write('cap_2', content_size_bytes=4096, extraction_tokens=800)

    # cap_1 被有用召回 3 次（每次注入 100 token），cap_2 有害召回 1 次
    for _ in range(3):
        acct.record_recall('cap_1', 'useful', injected_tokens=100)
    acct.record_recall('cap_2', 'harmful', injected_tokens=200)

    print("summary:", acct.summary())
    print("decay candidates:", acct.decay_candidates())
    # 期望：cap_2 ROI 为负，进衰减候选；cap_1 ROI 为正
```

## 6. 集成点（宛委·枢忆）

| 事件 | 记账调用 |
|------|---------|
| write_capsule | record_write（需要 LLM 抽取 token 数——从调用方传入） |
| 检索注入 | record_recall（outcome 由后续回答质量回填，或先记 neutral 后修正） |
| 定时维护 | record_maintenance（状态机扫描时批量） |
| Decay Panel | decay_candidates 直接喂数据 |
| 删除 | 删除时导出账目到 ledger（Governance 已覆盖） |

## 7. 验收标准

- [ ] 写入/召回/维护三事件都有记账
- [ ] ROI 自动重算（写入后、召回后）
- [ ] 有害召回 ROI 转负（示例 cap_2）
- [ ] Decay Panel 数据来源 = decay_candidates()
