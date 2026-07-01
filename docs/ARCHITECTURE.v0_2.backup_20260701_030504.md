> 项目：宛委·枢忆 OSAgent  
> 版本：v0.2（含 SOTA 对标、记忆安全、自演化与评测增强）  

# 系统架构设计

```text
宛委入口 → 枢忆核 → 司契护栏 / 石渠校验 / 玄珠偏好 / 句芒演化 / 建木网络 / 琅嬛库 / 册府融合 / 忘机机制 / 兰台鉴证 → SQLite + FTS + 向量引用 + 关系边表
```

## MemoryCapsule

```json
{
  "capsule_id": "uuid",
  "owner_scope": "user | scene | project | agent",
  "memory_type": "preference | knowledge | event | audit | workflow | experience",
  "payload": {},
  "metadata": {
    "source_event_ids": [],
    "version": 1,
    "confidence": 0.0,
    "trust_score": 0.0,
    "sensitivity_level": "S0 | S1 | S2 | S3"
  },
  "lifecycle": "candidate | active | deprecated | quarantined | forgotten"
}
```

## SOTA 映射

- LangGraph → FlowOrchestratorAdapter、CheckpointLog。
- MemOS → MemoryCapsule、生命周期治理。
- Honcho → UserMemoryProfile、PeerScope。
- SE-GA/TTME → 句芒演化 2.0。
- SimpleMem → 语义结构化压缩、在线语义合成、意图感知检索规划。
- Memory Poisoning / Longitudinal Safety → 司契护栏 2.0 与兰台鉴证 2.0。
- Memory-R2 → 记忆贡献归因与消融实验。
