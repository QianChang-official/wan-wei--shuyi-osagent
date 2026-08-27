# Memory Health 规范（MemoryOS-Health）

> 来源：ChatGPT 5.6 缺口 1 + 4.docx "记忆健康度/衰减面板/自我认知面板"
> 定位：Memory Health 未来会像 CPU 使用率、内存占用一样重要——独立成体系
> 状态：规范草案 + Python 实现，供浅唱审阅
> 日期：2026-08-20

## 1. 为什么需要 Memory Health

现有基准（LongMemEval/BEAM）测的是"能不能记住"，不是"记忆库健不健康"。
就像操作系统不看"磁盘满了没"，Memory OS 也要看"记忆库状态"。

**Memory Health = 记忆库作为资源的运行状态仪表盘**，聚合：

| 指标 | 含义 | 健康阈值 |
|------|------|---------|
| **MHS**（Memory Health Score） | 综合健康分 0-100 | ≥80 健康，60-79 警告，<60 危险 |
| **Staleness Rate** | 过期记忆占比 | <5% |
| **Conflict Rate** | 冲突记忆占比 | <2% |
| **Noise Ratio** | 噪声/无用记忆占比 | <10% |
| **Sensitive Coverage** | 敏感记忆覆盖率（已识别） | 100% |
| **Deletion Residue** | 删除残留可召回率 | 0% |
| **Unused Memory** | 长期未用记忆占比 | <20% |
| **Poisoning Incidents** | 投毒事故数 | 0 |
| **Retrieval Precision@5** | 召回精度 | ≥80% |

## 2. MHS 计算

```
MHS = 100
    - 15 × StalenessRate_norm     (staleness > 5% 起扣)
    - 15 × ConflictRate_norm       (conflict > 2% 起扣)
    - 15 × NoiseRatio_norm         (noise > 10% 起扣)
    - 10 × DeletionResidueFlag     (有残留 = 1，直接扣 10)
    - 15 × (1 - SensitiveCoverage)
    - 10 × UnusedRate_norm         (unused > 20% 起扣)
    - 20 × PoisoningFlag           (有投毒 = 1，直接扣 20)
```

各 norm 项 = (实际值 - 阈值) / (上限 - 阈值)，超上限封顶。

## 3. 三面板

### 3.1 Health Panel（健康面板）
- MHS 总分 + 趋势（7 天）
- 各子指标当前值 vs 阈值
- 最近一次 Health Check 时间

### 3.2 Decay Panel（衰减面板）
- 边际 ROI 低于 0 的记忆列表
- 应归档/应删除/受保护（高信任/合规）三分类
- 手动触发归档/清理

### 3.3 Self-Knowledge Panel（自我认知面板）
- "我有哪些记忆"（按类别统计）
- "每条记忆的依据是什么"（provenance）
- "哪些我不确定"（低 confidence）
- "如何纠错"（forget + 重写入口）

## 4. Python 实现

```python
# memory_health.py
"""Memory Health 健康度指标实现"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


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
    """聚合各子指标，计算 MHS，输出报告。"""

    def __init__(self, thresholds: HealthThresholds | None = None):
        self.t = thresholds or HealthThresholds()

    def _norm(self, value: float, threshold: float, cap: float = 1.0) -> float:
        """阈值以上才开始扣分，(value-threshold)/(cap-threshold)，超 cap 封顶 1。"""
        if value <= threshold:
            return 0.0
        return min(1.0, (value - threshold) / (cap - threshold))

    def check(self, *, total: int, stale: int, conflicted: int, noisy: int,
              unused: int, sensitive_identified: int, sensitive_total: int,
              deletion_residue: bool, poisoning_incidents: int,
              precision_at_5: float) -> MemoryHealthReport:
        """输入记忆库统计，输出健康报告。"""
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
        if staleness > self.t.staleness_max: issues.append(f"staleness {staleness:.1%} > {self.t.staleness_max:.0%}")
        if conflict > self.t.conflict_max: issues.append(f"conflict {conflict:.1%} > {self.t.conflict_max:.0%}")
        if noise > self.t.noise_max: issues.append(f"noise {noise:.1%} > {self.t.noise_max:.0%}")
        if deletion_residue: issues.append("deletion residue detected")
        if sensitive_cov < 1.0: issues.append(f"sensitive coverage {sensitive_cov:.0%}")
        if poisoning_incidents > 0: issues.append(f"poisoning incidents: {poisoning_incidents}")
        if precision_at_5 < self.t.precision_min: issues.append(f"precision@5 {precision_at_5:.0%}")

        return MemoryHealthReport(
            timestamp=now_iso(),
            mhs=round(mhs, 1),
            level=level,
            metrics={
                "total": total, "staleness": round(staleness, 4),
                "conflict": round(conflict, 4), "noise": round(noise, 4),
                "unused": round(unused, 4), "sensitive_coverage": round(sensitive_cov, 4),
                "deletion_residue": deletion_residue, "poisoning": poisoning_incidents,
                "precision@5": precision_at_5,
            },
            issues=issues,
        )


# --- 使用示例 ---
if __name__ == '__main__':
    hc = MemoryHealthChecker()
    # 健康库
    r1 = hc.check(total=1000, stale=20, conflicted=5, noisy=40,
                  unused=100, sensitive_identified=8, sensitive_total=8,
                  deletion_residue=False, poisoning_incidents=0, precision_at_5=0.92)
    print(f"MHS={r1.mhs} level={r1.level} issues={r1.issues}")
    # 问题库
    r2 = hc.check(total=1000, stale=200, conflicted=80, noisy=300,
                  unused=400, sensitive_identified=3, sensitive_total=8,
                  deletion_residue=True, poisoning_incidents=1, precision_at_5=0.55)
    print(f"MHS={r2.mhs} level={r2.level} issues={r2.issues}")
```

## 5. 集成点（宛委·枢忆）

| 数据来源 | 接口 |
|---------|------|
| total/stale/conflicted | memory_capsules_v2 state 统计（Lifecycle 状态机） |
| noisy | 检索未命中次数 > N 的记忆标记 |
| unused | last_accessed_at 超 30 天 |
| sensitive | policy_gate 敏感规则命中记录 |
| deletion_residue | verify_deletion 失败数（Governance） |
| poisoning | GuardedMemory 投毒检测命中（安全层） |
| precision@5 | MEB harness 输出 |

## 6. 验收标准

- [ ] 健康库 MHS ≥ 80（示例 r1 应输出 healthy）
- [ ] 问题库 MHS < 60 且列出全部 issues（示例 r2）
- [ ] 趋势：连续 7 天报告可画曲线
- [ ] Decay Panel 能列出边际 ROI < 0 的记忆（对接 Accounting）
