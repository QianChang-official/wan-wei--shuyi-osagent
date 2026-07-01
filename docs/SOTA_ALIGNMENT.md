> 项目：宛委·枢忆 OSAgent  
> 版本：v0.3.1（情感感知记忆调权与安全边界校正版）  

# SOTA 技术对标与吸收说明

## 已纳入

- LangGraph：状态图编排、Checkpointer、Store；映射为 FlowOrchestratorAdapter、CheckpointLog。
- MemOS / Memory OS：记忆作为系统资源、MemCube、生命周期管理；映射为 MemoryCapsule 与枢忆核。
- Honcho：跨会话用户建模、多 Agent 画像隔离；映射为 UserMemoryProfile、PeerScope。
- SE-GA / TTME：推理期记忆扩展、自演化反馈；映射为句芒演化。
- SimpleMem：语义无损压缩、在线语义合成、意图感知检索规划。
- Memory Poisoning Defense：信任评分、记忆净化、trust-aware retrieval；映射为司契护栏。
- Longitudinal Safety：纵向记忆安全评测、NullMemory 对照、快照测试；映射为兰台鉴证。
- Memory-R2：记忆贡献归因、消融评测。
- Dynamic Affective Memory Management for Personalized LLM Agents：已确认，arXiv:2510.27418；吸收 Bayesian-inspired memory update、memory entropy、DABench；映射为 affective_confidence、affective_entropy、affective_update_policy、情感显著性驱动的 retention_score 调制。
- MemEmo：情感记忆提取、更新、问答评测；映射为灵犀情感与兰台鉴证 Affective Evaluation。
- Affective Computing / Emotional Memory：情绪显著性、情感线索、情绪对记忆巩固的调制作用；映射为 affective_metadata。
- Generative Agents / MemoryBank：memory stream、importance score、长期记忆与遗忘曲线；映射为 retention_score 与自演化闭环。
- Engram / MoE：查算分离、条件激活、模型侧未来扩展。

## 暂缓 / 待核验

- SAG、异步稀疏调制、MEMO：暂留待核验技术池。

## 安全表述

本项目不声称模型具备真实情感，也不进行心理诊断；仅将用户反馈、态度倾向和情绪显著性作为记忆元数据，用于偏好演化、检索重排序和交互风格适配，并由司契护栏和 trust-aware retrieval 约束其安全边界。emotional_salience 只能影响记忆保留和排序，不得覆盖安全判定。
