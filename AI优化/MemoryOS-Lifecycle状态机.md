# Memory Lifecycle 状态机规范

> 来源：6.docx P1 补充 + 2.docx"记忆生命周期不完整"缺口
> 状态：规范草案 + Python 实现草案，供浅唱审阅
> 日期：2026-08-20

## 1. 状态定义

```
candidate → active → reinforced → stale → conflicted → archived → quarantined → deleted
```

| 状态 | 含义 | 触发条件 | 允许操作 | 是否可检索 |
|------|------|---------|---------|-----------|
| candidate | 待确认候选 | 新写入但 require_confirmation | confirm / reject / timeout | ❌ |
| active | 活跃记忆 | 确认通过 / 直接写入 | update / reinforce / delete | ✅ |
| reinforced | 强化记忆 | 重复命中 ≥2 次 | update / archive / delete | ✅（高权重） |
| stale | 过期记忆 | valid_until 到期 / 长期未用 | refresh / archive / delete | ⚠️（低权重或弃权） |
| conflicted | 冲突记忆 | 新事实与旧事实矛盾 | resolve / supersede / archive | ❌（需裁决） |
| archived | 归档记忆 | 主动归档 / 自动降权 | restore / delete | ❌（不进上下文） |
| quarantined | 隔离记忆 | 投毒/敏感/未确认 | preview / confirm / delete | ❌ |
| deleted | 已删除 | 用户/合规删除 | 无（只留账本） | ❌ |

## 2. 状态转移图

```
                ┌──────────────────────────────────────┐
                │                                      │
 write ──► candidate ──confirm──► active ──reinforce──► reinforced
                │                    │  │                  │
             reject                hit≥2 │              stale 到期
                │                    │  │                  │
                ▼                    ▼  ▼                  ▼
             deleted ◄──resolve── conflicted           stale ──refresh──► active
                ▲                    ▲                  │
                │                    │                  ├─archive──► archived
             timeout             conflict             │            │
                │                    │                  ▼            │
             quarantine ◄────────────┴──────────────── deleted ◄────┘
```

关键规则：
1. **candidate 必须显式确认**才能进 active（防止噪声自动进入）
2. **conflicted 必须裁决**：supersede（新压旧）或 resolve（合并）
3. **stale 不直接删除**：refresh 或 archive，留审计
4. **quarantined 不可检索注入**（安全底线）
5. **deleted 只留账本**，物理删除或软删由策略决定

## 3. Python 实现草案

```python
# memory_lifecycle.py
"""Memory Lifecycle 状态机实现草案"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class LifecycleState(str, Enum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    REINFORCED = "reinforced"
    STALE = "stale"
    CONFLICTED = "conflicted"
    ARCHIVED = "archived"
    QUARANTINED = "quarantined"
    DELETED = "deleted"


# 合法转移表
TRANSITIONS = {
    LifecycleState.CANDIDATE: {LifecycleState.ACTIVE, LifecycleState.DELETED, LifecycleState.QUARANTINED},
    LifecycleState.ACTIVE: {LifecycleState.REINFORCED, LifecycleState.STALE, LifecycleState.CONFLICTED,
                            LifecycleState.ARCHIVED, LifecycleState.DELETED},
    LifecycleState.REINFORCED: {LifecycleState.STALE, LifecycleState.CONFLICTED,
                                LifecycleState.ARCHIVED, LifecycleState.DELETED},
    LifecycleState.STALE: {LifecycleState.ACTIVE, LifecycleState.ARCHIVED, LifecycleState.DELETED},
    LifecycleState.CONFLICTED: {LifecycleState.ACTIVE, LifecycleState.DELETED, LifecycleState.QUARANTINED},
    LifecycleState.ARCHIVED: {LifecycleState.ACTIVE, LifecycleState.DELETED},
    LifecycleState.QUARANTINED: {LifecycleState.ACTIVE, LifecycleState.DELETED},
    LifecycleState.DELETED: set(),
}


@dataclass
class MemoryRecord:
    capsule_id: str
    state: LifecycleState
    hit_count: int = 0
    valid_until: Optional[str] = None
    last_accessed_at: Optional[str] = None
    history: list = field(default_factory=list)  # [(from, to, reason, ts)]

    def transition(self, to: LifecycleState, reason: str) -> bool:
        """执行状态转移。非法转移返回 False 并记录。"""
        if to not in TRANSITIONS[self.state]:
            raise ValueError(f"非法转移: {self.state} -> {to}")
        self.history.append((self.state.value, to.value, reason, now_iso()))
        self.state = to
        return True


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


class LifecycleEngine:
    """状态机引擎：裁决转移 + 触发副作用（账本/审计/告警）"""

    def __init__(self, ledger_callback=None):
        self.records: dict[str, MemoryRecord] = {}
        self.ledger_callback = ledger_callback  # 对接 Governance 账本

    def write(self, capsule_id: str, *, auto_confirm: bool = True,
              require_confirmation: bool = False) -> MemoryRecord:
        """写入。默认直接 active；require_confirmation 时进 candidate。"""
        rec = MemoryRecord(capsule_id=capsule_id, state=LifecycleState.CANDIDATE)
        self.records[capsule_id] = rec
        if auto_confirm and not require_confirmation:
            rec.transition(LifecycleState.ACTIVE, 'auto_confirm')
        self._ledger('write', capsule_id, rec.state)
        return rec

    def on_recall(self, capsule_id: str) -> MemoryRecord:
        """召回命中：更新 hit_count，达阈值强化。"""
        rec = self.records[capsule_id]
        rec.hit_count += 1
        rec.last_accessed_at = now_iso()
        if rec.state == LifecycleState.ACTIVE and rec.hit_count >= 2:
            rec.transition(LifecycleState.REINFORCED, f'hit_count={rec.hit_count}')
        if rec.state == LifecycleState.STALE:
            rec.transition(LifecycleState.ACTIVE, 'recalled_after_stale')
        self._ledger('reinforce' if rec.state == LifecycleState.REINFORCED else 'recall',
                     capsule_id, rec.state)
        return rec

    def detect_conflict(self, capsule_id: str, existing_id: str, reason: str) -> None:
        """发现新旧冲突：两边进 conflicted，待裁决。"""
        self.records[capsule_id].transition(LifecycleState.CONFLICTED, reason)
        self.records[existing_id].transition(LifecycleState.CONFLICTED, reason)
        self._ledger('conflict', capsule_id, LifecycleState.CONFLICTED)

    def resolve(self, winner_id: str, loser_id: str, reason: str) -> None:
        """裁决：winner 回 active，loser 进 deleted（账本保留）。"""
        self.records[winner_id].transition(LifecycleState.ACTIVE, f'resolve_win: {reason}')
        self.records[loser_id].transition(LifecycleState.DELETED, f'resolve_lose: {reason}')
        self._ledger('resolve', winner_id, LifecycleState.ACTIVE)

    def mark_stale(self, capsule_id: str, reason: str = 'valid_until_expired') -> None:
        self.records[capsule_id].transition(LifecycleState.STALE, reason)
        self._ledger('stale', capsule_id, LifecycleState.STALE)

    def quarantine(self, capsule_id: str, reason: str) -> None:
        self.records[capsule_id].transition(LifecycleState.QUARANTINED, reason)
        self._ledger('quarantine', capsule_id, LifecycleState.QUARANTINED)

    def delete(self, capsule_id: str, reason: str) -> None:
        self.records[capsule_id].transition(LifecycleState.DELETED, reason)
        self._ledger('delete', capsule_id, LifecycleState.DELETED)

    def _ledger(self, op: str, capsule_id: str, state: LifecycleState):
        if self.ledger_callback:
            self.ledger_callback(op, capsule_id, state.value)


# --- 使用示例 ---
if __name__ == '__main__':
    eng = LifecycleEngine(ledger_callback=lambda op, cid, st: print(f'[ledger] {op} {cid} -> {st}'))

    # 写入（直接 active）
    m1 = eng.write('cap_1')
    print(f'cap_1: {m1.state.value}')  # active

    # 需要确认的写入
    m2 = eng.write('cap_2', require_confirmation=True)
    print(f'cap_2: {m2.state.value}')  # candidate
    m2.transition(LifecycleState.ACTIVE, 'human_confirmed')
    print(f'cap_2 after confirm: {m2.state.value}')

    # 召回强化
    eng.on_recall('cap_1')  # hit 1
    eng.on_recall('cap_1')  # hit 2 -> reinforced
    print(f'cap_1: {eng.records["cap_1"].state.value}')  # reinforced

    # 冲突裁决
    eng.detect_conflict('cap_3', 'cap_1', 'user changed preference')
    print(f'cap_1: {eng.records["cap_1"].state.value}')  # conflicted
    eng.resolve('cap_3', 'cap_1', 'new fact wins')
    print(f'cap_1: {eng.records["cap_1"].state.value}')  # deleted

    # 过期
    eng.mark_stale('cap_2')
    print(f'cap_2: {eng.records["cap_2"].state.value}')  # stale
```

## 4. 集成点（宛委·枢忆）

| 现有机制 | 对接 |
|---------|------|
| policy_gate "require_confirmation" | write 时进 candidate 而非 active |
| 检索命中计数 | on_recall 更新 hit_count + 强化 |
| 冲突检测（新增） | 写入前同类候选召回 + LLM/规则判冲突 → conflicted |
| valid_until 字段 | 定时任务扫描 → mark_stale |
| 梦境归档 | archived 批量 + 巩固 |
| forget_capsules | delete + 账本 + 删除验证 |

## 5. 验收标准

- [ ] 非法转移被拒绝（如 deleted → active 抛错）
- [ ] candidate 未确认不进入检索
- [ ] 冲突必须显式裁决，不自动覆盖
- [ ] stale 刷新回 active 有日志
- [ ] 每次转移写入账本（history 字段可审计）
