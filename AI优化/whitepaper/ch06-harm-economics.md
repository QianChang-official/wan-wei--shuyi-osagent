# 第 6 章:Memory Harm × Economics 标准

> **Canonical**:本章是 **MHEB 权重、ROI 公式、MHS 公式、MHG 分级**的唯一权威定义处。第 5 章的 score_report 权重字段只引用本章,不重复定义。
> **来源**:4.docx → `MemoryOS-Accounting经济账本.md` + `MemoryOS-Health规范.md`(2026-08-20)
> **状态**:已合并(Accounting §1-5 + Health §1-4,集成点各自保留)

## 6.1 Memory Harm Framework

### 6.1.1 MHG 事故分级

| MHG | 级别 | 示例 | 动作 |
|---|---|---|---|
| MHG-1 | 轻微 | 过期记忆被召回 | 记录,正常发布 |
| MHG-2 | 一般 | 错误记忆导致回答偏差 | 记录 + 告警 |
| MHG-3 | 严重 | 敏感记忆泄漏到错误 scope | **发布冻结 + 事故响应** |
| MHG-4 | 危险 | 投毒记忆触发高风险工具 | 一票否决 + 回滚 + 红队复盘 |
| MHG-5 | 灾难 | 跨租户泄漏 / 删除残留可被召回 | 一票否决 + 全量审计 |

**Safety 一票否决**:MHG-4/5、跨租户泄漏、删除残留、投毒触发 → 只进 incident report,不进综合分。

### 6.1.2 事故记录格式

见第 5 章 §5.2.3(memory_incident.json)。本章只定义分级与响应协议,记录格式归第 5 章。

## 6.2 Memory Economics:逐条记账(Memory Accounting)

Memory Economics 说了「每 KB 记忆产生多少价值」,但没有定义**怎么算**。Memory Accounting 就是逐条记忆的记账本:

```
每条记忆
├── 存储成本 (Storage Cost)
├── 检索成本 (Retrieval Cost)
├── 维护成本 (Maintenance Cost)
├── 产生收益 (Utility)
└── ROI = (收益 - 成本) / 成本
```

当 ROI < 0 → 进 Decay Panel → 归档/删除候选。

### 6.2.1 成本模型

- **存储成本**(一次性 + 持续):LLM 抽取费用(tokens × 单价)+ 字节数 × 存储单价 × 时长
- **检索成本**(每次召回):注入上下文的 tokens × 单价 + 检索延迟成本
- **维护成本**(定期):状态机扫描/巩固/衰减计算的资源消耗(按次计)

### 6.2.2 收益模型

| 事件 | 含义 | 收益值 |
|---|---|---|
| useful_recall | 召回后回答正确/用户采纳 | +1.0 |
| neutral_recall | 召回但没影响 | +0.1 |
| harmful_recall | 召回导致错误/误导 | -2.0(并记入 Harm) |

### 6.2.3 数据结构

```sql
CREATE TABLE memory_accounts (
    capsule_id      TEXT PRIMARY KEY,
    storage_cost    REAL DEFAULT 0,
    retrieval_cost  REAL DEFAULT 0,
    maintenance_cost REAL DEFAULT 0,
    total_cost      REAL DEFAULT 0,
    useful_recalls  INTEGER DEFAULT 0,
    neutral_recalls INTEGER DEFAULT 0,
    harmful_recalls INTEGER DEFAULT 0,
    utility         REAL DEFAULT 0,
    roi             REAL DEFAULT 0,
    last_accessed   TEXT,
    created_at      TEXT
);
```

### 6.2.4 Python 实现

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
    token_cost: float = 0.000002
    storage_per_kb: float = 0.00001
    maintenance_fixed: float = 0.001


class MemoryAccountant:
    def __init__(self, db_path: str, config: CostConfig | None = None):
        self.conn = sqlite3.connect(db_path)
        self.conn.executescript(SCHEMA)
        self.cfg = config or CostConfig()

    def record_write(self, capsule_id: str, content_size_bytes: int,
                     extraction_tokens: int) -> None:
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
        retrieval = injected_tokens * self.cfg.token_cost
        utility_map = {"useful": 1.0, "neutral": 0.1, "harmful": -2.0}
        utility = utility_map.get(outcome)
        if utility is None:
            raise ValueError(f"unknown outcome: {outcome!r}, must be one of {list(utility_map)}")
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
```

## 6.3 MHEB 综合分(权重唯一定义处)

```
MHEB = 0.40 × UX + 0.25 × Safety_inverse + 0.25 × Product + 0.10 × Academic
```

| 维度 | 权重 | 来源 |
|---|---|---|
| 用户体验(UX) | 0.40 | 第 5 章五类评测通过率 |
| 安全(Safety 反向) | 0.25 | MHG 事故率反向计分;一票否决项不进加权 |
| 产品能力 | 0.25 | 集成完整度、延迟、资源占用 |
| 学术对齐 | 0.10 | 与公开基准的可比性 |

第 5 章 score_report.json 的 `weights` 字段引用本节,不单独定义。

## 6.4 Memory Health:记忆库运行状态仪表盘

现有基准(LongMemEval/BEAM)测「能不能记住」,不是「记忆库健不健康」。Memory Health = 记忆库作为资源的运行状态仪表盘。

### 6.4.1 指标与健康阈值

| 指标 | 含义 | 健康阈值 |
|---|---|---|
| **MHS**(Memory Health Score) | 综合健康分 0-100 | ≥80 健康,60-79 警告,<60 危险 |
| Staleness Rate | 过期记忆占比 | <5% |
| Conflict Rate | 冲突记忆占比 | <2% |
| Noise Ratio | 噪声/无用记忆占比 | <10% |
| Sensitive Coverage | 敏感记忆覆盖率(已识别) | 100% |
| Deletion Residue | 删除残留可召回率 | 0% |
| Unused Memory | 长期未用记忆占比 | <20% |
| Poisoning Incidents | 投毒事故数 | 0 |
| Retrieval Precision@5 | 召回精度 | ≥80% |

### 6.4.2 MHS 计算(公式唯一定义处)

```
MHS = 100
    - 15 × StalenessRate_norm     (staleness > 5% 起扣)
    - 15 × ConflictRate_norm       (conflict > 2% 起扣)
    - 15 × NoiseRatio_norm         (noise > 10% 起扣)
    - 10 × DeletionResidueFlag     (有残留 = 1,直接扣 10)
    - 15 × (1 - SensitiveCoverage)
    - 10 × UnusedRate_norm         (unused > 20% 起扣)
    - 20 × PoisoningFlag           (有投毒 = 1,直接扣 20)
```

各 norm 项 = (实际值 - 阈值) / (上限 - 阈值),超上限封顶。

### 6.4.3 三面板

- **Health Panel**:MHS 总分 + 趋势(7 天)+ 各子指标当前值 vs 阈值 + 最近检查时间
- **Decay Panel**:边际 ROI < 0 的记忆列表(对接 §6.2 Accounting);应归档/应删除/受保护三分类
- **Self-Knowledge Panel**:「我有哪些记忆」/「每条记忆的依据是什么」(provenance)/「哪些我不确定」/「如何纠错」

### 6.4.4 Python 实现

```python
# memory_health.py
"""Memory Health 健康度指标实现"""
from dataclasses import dataclass, field
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


@dataclass
class HealthThresholds:
    staleness_max: float = 0.05
    conflict_max: float = 0.02
    noise_max: float = 0.10
    unused_max: float = 0.20
    precision_min: float = 0.80
    sensitive_cov_min: float = 1.0


@dataclass
class MemoryHealthReport:
    timestamp: str
    mhs: float
    level: str  # healthy / warning / critical
    metrics: dict
    issues: list = field(default_factory=list)


class MemoryHealthChecker:
    def __init__(self, thresholds: HealthThresholds | None = None):
        self.t = thresholds or HealthThresholds()

    def _norm(self, value: float, threshold: float, cap: float = 1.0) -> float:
        if value <= threshold:
            return 0.0
        return min(1.0, (value - threshold) / (cap - threshold))

    def check(self, *, total: int, stale: int, conflicted: int, noisy: int,
              unused: int, sensitive_identified: int, sensitive_total: int,
              deletion_residue: bool, poisoning_incidents: int,
              precision_at_5: float) -> MemoryHealthReport:
        def rate(n: int) -> float:
            return n / total if total else 0.0

        staleness = rate(stale)
        conflict = rate(conflicted)
        noise = rate(noisy)
        unused = rate(unused)
        sensitive_cov = sensitive_identified / sensitive_total if sensitive_total else 1.0

        mhs = 100.0
        mhs -= 15 * self._norm(staleness, self.t.staleness_max, 0.30)
        mhs -= 15 * self._norm(conflict, self.t.conflict_max, 0.15)
        mhs -= 15 * self._norm(noise, self.t.noise_max, 0.50)
        mhs -= 10 * (1.0 if deletion_residue else 0.0)
        mhs -= 15 * (1.0 - min(1.0, sensitive_cov))
        mhs -= 10 * self._norm(unused, self.t.unused_max, 0.60)
        mhs -= 20 * (1.0 if poisoning_incidents > 0 else 0.0)
        if precision_at_5 < self.t.precision_min:
            mhs -= 10 * (self.t.precision_min - precision_at_5) / self.t.precision_min

        mhs = max(0.0, min(100.0, mhs))
        level = "healthy" if mhs >= 80 else ("warning" if mhs >= 60 else "critical")

        issues = []
        if staleness > self.t.staleness_max: issues.append(f"staleness {staleness:.1%}")
        if conflict > self.t.conflict_max: issues.append(f"conflict {conflict:.1%}")
        if noise > self.t.noise_max: issues.append(f"noise {noise:.1%}")
        if deletion_residue: issues.append("deletion residue detected")
        if sensitive_cov < 1.0: issues.append(f"sensitive coverage {sensitive_cov:.0%}")
        if poisoning_incidents > 0: issues.append(f"poisoning incidents: {poisoning_incidents}")
        if precision_at_5 < self.t.precision_min: issues.append(f"precision@5 {precision_at_5:.0%}")

        return MemoryHealthReport(
            timestamp=now_iso(), mhs=round(mhs, 1), level=level,
            metrics={
                "total": total, "staleness": round(staleness, 4),
                "conflict": round(conflict, 4), "noise": round(noise, 4),
                "unused": round(unused, 4), "sensitive_coverage": round(sensitive_cov, 4),
                "deletion_residue": deletion_residue, "poisoning": poisoning_incidents,
                "precision@5": precision_at_5,
            },
            issues=issues,
        )
```

## 6.5 集成点(宛委·枢忆)

| 数据来源 | 接口 |
|---|---|
| total/stale/conflicted | memory_capsules_v2 state 统计(Lifecycle 状态机,见第 8 章) |
| noisy | 检索未命中次数 > N 的记忆标记 |
| unused | last_accessed_at 超 30 天 |
| sensitive | policy_gate 敏感规则命中记录 |
| deletion_residue | verify_deletion 失败数(第 8 章 Governance) |
| poisoning | GuardedMemory 投毒检测命中 |
| precision@5 | 第 5 章 MEB harness 输出 |
| ROI/Decay | §6.2 MemoryAccountant |

## 6.6 验收标准

- [ ] 写入/召回/维护三事件都有记账;ROI 自动重算
- [ ] 有害召回 ROI 转负
- [ ] 健康库 MHS ≥ 80;问题库 MHS < 60 且列出全部 issues
- [ ] Decay Panel 能列出边际 ROI < 0 的记忆
- [ ] MHG-4/5 触发时不进综合分,只进 incident report
