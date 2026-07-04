> 项目：宛委·枢忆 OSAgent  
> 版本：v0.2（含 SOTA 对标、记忆安全、自演化与评测增强）  

# 完整开发 Plan

## 目标

构建端侧可运行的 OS Agent 记忆优化系统，实现多源接入、偏好捕捉、知识沉淀、冲突融合、高效检索、证据追溯、安全遗忘、记忆自演化与纵向安全评测。

## 阶段

- Phase 0：仓库、Schema、FastAPI、SQLite、适配器。
- Phase 1：事件写入、多源接入、偏好提取、知识入库、关键词检索、审计。
- Phase 2：MemoryCapsule、偏好版本化、知识冲突融合、短中长期记忆流转。
- Phase 3：embedding Adapter、FTS/BM25、向量接口、关系召回、证据卡。
- Phase 4：司契护栏、敏感识别、记忆投毒防御、精准遗忘。
- Phase 5：TTME-style 推理期记忆扩展、SimpleMem-style 语义压缩。
- Phase 6：评测、验收、部署、演示材料。
