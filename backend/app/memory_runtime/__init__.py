"""MemoryOps Runtime v0.6（老轨）。

双轨现状（审计 W02-越界#3 诚实标注，不做合并重构）：
- ``app.memory_runtime`` 是legacy MemoryOps 体系：sqlite 胶囊/FTS 检索/evolution；
- ``app.platform_api.memory_center`` 是平台版记忆体系（JSON 影子存储）；
- 两条轨道数据零互通、零合并。唯一复用点是 ``policy_gate.evaluate_policy``
  安全闸门（platform 写入前调用）。

本包内各模块仅维护老轨自身的 capsule/vector/retrieval/evolution 链路，
不消费也不写入 platform 的 JsonStore；反之亦然。新增功能请优先评估应归属
哪条轨道，避免在双轨之间隐式搭桥。
"""
