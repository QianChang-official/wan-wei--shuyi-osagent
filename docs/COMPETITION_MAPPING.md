# 赛题映射

| 需求 | 功能 | 代码位置 | 测试位置 |
|---|---|---|---|
| 可证明删除 | 五处验证、PDF 证书 | `backend/app/memoryos/governance.py` | `test_memoryos_certificate.py` |
| 防止复活 | 生命周期状态机 | `backend/app/memoryos/lifecycle.py` | `test_memoryos_lifecycle.py` |
| 审计追溯 | append-only 账本、Provenance | `backend/app/memoryos/governance.py` | `test_memoryos_governance.py` |
| 偏好治理 | Policy Gate、EGPM | `backend/app/memory_runtime/` | `test_policy_gate.py`、`test_preference_outcome.py` |
| 知识检索 | FTS5/向量通道 | `backend/app/memory_runtime/` | `test_retrieval.py`、`test_local_embedding.py` |
| 麒麟适配 | 原生 SDK 桥接 | `native/kylin-sdk-bridge/` | `test_kylin_native_sdk.py` |
