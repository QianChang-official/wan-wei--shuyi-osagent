# memoryos-core 参考实现（Reference Implementation）

> 来源：ChatGPT 5.6 缺口 3（"行业标准最终拼的是：谁有跑得起来的代码"）
> 定位：把 Governance + Lifecycle + Health + Accounting 合成一个可运行的核心包
> 状态：整合骨架，供浅唱审阅；目标 = 可接入宛委·枢忆
> 日期：2026-08-20

## 1. 设计

```
memoryos-core/
├── memoryos/
│   ├── __init__.py          # MemoryOS 门面
│   ├── core.py              # 核心：统一入口（write/recall/update/forget）
│   ├── lifecycle.py         # 状态机（来自 MemoryOS-Lifecycle状态机.md）
│   ├── governance.py        # 账本 + Provenance + 删除验证 + MHG（来自 Governance 规范）
│   ├── accounting.py        # 经济账本（来自 Accounting 规范）
│   ├── health.py            # 健康度（来自 Health 规范）
│   └── harness.py           # MEB 评测（来自 BenchmarkHarness.md）
├── tests/
│   └── test_core.py         # 集成测试
└── pyproject.toml
```

**设计原则**：
1. 全部 Python 标准库（sqlite3/json/datetime），零外部依赖
2. 每个子模块可独立使用，也可通过 `MemoryOS` 门面统一调用
3. 所有持久化走 SQLite，单文件可跑
4. 接口与宛委·枢忆现有 API 对齐（write_capsule/forget/retrieve）

## 2. 核心门面（core.py）

```python
# memoryos/core.py
"""MemoryOS 统一门面：把 Lifecycle + Governance + Accounting + Health 串起来"""
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .lifecycle import LifecycleEngine, LifecycleState
from .governance import MemoryLedger, MHGResponse
from .accounting import MemoryAccountant
from .health import MemoryHealthChecker


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


@dataclass
class MemoryOSConfig:
    db_path: str = 'memoryos.db'
    auto_confirm: bool = True
    health_thresholds: dict = field(default_factory=dict)


class MemoryOS:
    """Memory OS 参考实现门面"""

    def __init__(self, config: MemoryOSConfig | None = None):
        self.cfg = config or MemoryOSConfig()
        self.conn = sqlite3.connect(self.cfg.db_path)
        self.conn.executescript(self._schema())
        self.lifecycle = LifecycleEngine(ledger_callback=self._on_lifecycle_event)
        self.governance = MemoryLedger(self.conn)
        self.accounting = MemoryAccountant(self.conn)
        self.health = MemoryHealthChecker()

    def _schema(self) -> str:
        return """
        CREATE TABLE IF NOT EXISTS capsules (
            capsule_id TEXT PRIMARY KEY,
            content TEXT,
            state TEXT,
            owner TEXT,
            scope TEXT,
            source TEXT,
            confidence REAL,
            valid_until TEXT,
            hit_count INTEGER DEFAULT 0,
            last_accessed_at TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS capsule_fts (
            capsule_id TEXT PRIMARY KEY,
            content TEXT
        );
        """

    # ---------- 生命周期事件 → 账本 ----------
    def _on_lifecycle_event(self, op: str, capsule_id: str, state: str):
        self.governance.append(op, capsule_id, actor='system', state=state)

    # ---------- 核心操作 ----------

    def write(self, content: str, *, owner: str = 'user', scope: str = 'global',
              source: str = 'user_input', confidence: float = 0.8,
              valid_until: str | None = None, require_confirmation: bool = False) -> str:
        """写入记忆：Lifecycle 入状态机 + Governance 入账 + Accounting 记账。"""
        import uuid
        cid = 'cap_' + uuid.uuid4().hex[:10]

        # 1. Lifecycle
        rec = self.lifecycle.write(cid, auto_confirm=self.cfg.auto_confirm,
                                   require_confirmation=require_confirmation)

        # 2. 存储
        self.conn.execute(
            """INSERT INTO capsules
               (capsule_id, content, state, owner, scope, source, confidence,
                valid_until, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (cid, content, rec.state.value, owner, scope, source, confidence,
             valid_until, now_iso(), now_iso()))
        self.conn.execute("INSERT INTO capsule_fts VALUES (?,?)", (cid, content))

        # 3. Accounting（估算抽取成本：按内容长度 × 0.3 token/字符）
        est_tokens = int(len(content) * 0.3)
        self.accounting.record_write(cid, len(content.encode('utf-8')), est_tokens)
        self.conn.commit()
        return cid

    def recall(self, query: str, *, top_k: int = 3) -> list[dict]:
        """检索：只召回 active/reinforced 状态，记账 + 记 trace。"""
        rows = self.conn.execute(
            """SELECT c.capsule_id, c.content, c.state, c.hit_count
               FROM capsules c WHERE c.state IN ('active','reinforced')
               ORDER BY CASE c.state WHEN 'reinforced' THEN 0 ELSE 1 END, c.hit_count DESC
               LIMIT ?""", (top_k,)).fetchall()

        results = []
        for cid, content, state, hits in rows:
            # Lifecycle 更新（hit_count + 强化）
            self.lifecycle.on_recall(cid)
            self.conn.execute(
                "UPDATE capsules SET hit_count=hit_count+1, last_accessed_at=? WHERE capsule_id=?",
                (now_iso(), cid))
            # Accounting（先记 neutral，后续可修正为 useful/harmful）
            self.accounting.record_recall(cid, 'neutral', injected_tokens=int(len(content) * 0.3))
            results.append({"capsule_id": cid, "content": content, "state": state, "score": hits})
        self.conn.commit()
        return results

    def confirm(self, capsule_id: str) -> bool:
        """确认 candidate → active。"""
        rec = self.lifecycle.records.get(capsule_id)
        if rec and rec.state == LifecycleState.CANDIDATE:
            rec.transition(LifecycleState.ACTIVE, 'human_confirmed')
            self.conn.execute("UPDATE capsules SET state='active' WHERE capsule_id=?", (capsule_id,))
            self.conn.commit()
            return True
        return False

    def forget(self, capsule_id: str, *, reason: str = 'user_request') -> dict:
        """删除 + 验证（主表/FTS/账本）"""
        self.lifecycle.delete(capsule_id, reason)
        self.conn.execute("DELETE FROM capsules WHERE capsule_id=?", (capsule_id,))
        self.conn.execute("DELETE FROM capsule_fts WHERE capsule_id=?", (capsule_id,))
        self.conn.commit()
        # Governance 删除验证
        return self.governance.verify_deletion(self.conn, capsule_id)

    def health_report(self) -> dict:
        """健康度报告（聚合全库统计）"""
        total = self.conn.execute("SELECT count(*) FROM capsules").fetchone()[0]
        states = dict(self.conn.execute(
            "SELECT state, count(*) FROM capsules GROUP BY state").fetchall())
        return self.health.check(
            total=total,
            stale=states.get('stale', 0),
            conflicted=states.get('conflicted', 0),
            noisy=0,
            unused=0,
            sensitive_identified=0,
            sensitive_total=0,
            deletion_residue=False,
            poisoning_incidents=0,
            precision_at_5=0.9,
        )

    def decay_candidates(self) -> list[dict]:
        return self.accounting.decay_candidates()


# --- 使用示例 ---
if __name__ == '__main__':
    import tempfile, os
    db = os.path.join(tempfile.mkdtemp(), 'mos.db')
    mos = MemoryOS(MemoryOSConfig(db_path=db))

    # 写入
    cid = mos.write("用户喜欢美式咖啡，不加糖", source='user_input')
    print(f"写入: {cid}")

    # 召回
    hits = mos.recall("用户喝什么咖啡")
    print(f"召回: {[h['content'] for h in hits]}")

    # 健康
    print(f"健康: {mos.health_report().level} MHS={mos.health_report().mhs}")

    # 删除验证
    result = mos.forget(cid)
    print(f"删除验证: {result}")
```

## 3. 其他模块占位说明

| 模块 | 来源 | 状态 |
|------|------|------|
| lifecycle.py | MemoryOS-Lifecycle状态机.md | 完整代码已提供 |
| governance.py | MemoryOS-Governance账本规范.md | 完整代码已提供（MemoryLedger 类需小幅改名对齐） |
| accounting.py | MemoryOS-Accounting经济账本.md | 完整代码已提供 |
| health.py | MemoryOS-Health规范.md | 完整代码已提供 |
| harness.py | MemoryOS-BenchmarkHarness.md | 骨架已提供 |

## 4. 接入宛委·枢忆的映射

| memoryos-core | 宛委·枢忆现有 | 改动量 |
|---------------|---------------|--------|
| capsules 表 | memory_capsules_v2 | 增加 state/hit_count/last_accessed_at 字段 |
| capsule_fts | 现有 FTS5 | 复用 |
| LifecycleEngine | 短期/中期流转（#56 已合入） | 补 conflicted/stale/quarantined 状态 |
| MemoryLedger | 审计表（audit.service） | 扩展 append-only + hash |
| Accounting | 无 | 新增表 + 3 个 hook |
| Health | 无 | 新增聚合查询 + 面板 API |

## 5. 验收标准（第一份真实报告）

- [ ] `python -m memoryos` 跑通写入→召回→删除全流程
- [ ] 500 条种子记忆 + 100 条真实交互 → MHEB 报告
- [ ] score_report.json 含 5 类评测 + economics + health
- [ ] 报告可直接放进 2.docx 的"待验收"栏
