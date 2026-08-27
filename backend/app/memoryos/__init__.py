"""MemoryOS —— 记忆治理层（Lifecycle / Governance / Accounting / Health / Benchmark）。

规范来源：仓库根 ``AI优化/`` 下的五份草案 + ``MemoryOS-core参考实现.md``。
每份规范末尾的「集成点（宛委·枢忆）」一节明确要求**扩展现有组件**而非另起体系，
因此本包与 ``app.memory_runtime`` 平级协作，而不是取代它：

- ``lifecycle``   记忆状态机（合法转移裁决 + FTS 同步 + 账本副作用）
- ``governance``  不可变账本 / Provenance Card / 删除验证 / MHG 事故分级
- ``accounting``  逐条记忆的成本-收益-ROI 经济账本
- ``health``      MHS 健康度与三面板（Health / Decay / Self-Knowledge）
- ``harness``     MEB/MHEB 评测 runner

依赖方向（防循环导入）
----------------------
``memoryos.*`` 可以在模块级 import ``memory_runtime.*`` 之外的基础设施
（``..db`` / ``..utils`` / ``..audit``）；对 ``memory_runtime.*`` 的依赖一律放在
**函数内部**局部 import。反向地，``memory_runtime.*`` 只能从
``memoryos.lifecycle`` 的**纯词表段**（枚举、转移表、常量，无 DB 访问）做模块级
import，其余一律局部 import。这与仓库既有做法一致
（``capsule_store`` 局部 import ``vector_index``、``evolution`` 局部 import
``tier_manager``），不引入新范式。
"""

from .lifecycle import (
    IllegalTransitionError,
    LifecycleState,
    RETRIEVABLE_STATES,
    TERMINAL_STATES,
    TRANSITIONS,
    apply_transition,
    can_transition,
    assert_transition,
    legal_next_states,
)

__all__ = [
    "IllegalTransitionError",
    "LifecycleState",
    "RETRIEVABLE_STATES",
    "TERMINAL_STATES",
    "TRANSITIONS",
    "apply_transition",
    "assert_transition",
    "can_transition",
    "legal_next_states",
]
