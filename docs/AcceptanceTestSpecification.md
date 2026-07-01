> 项目：宛委·枢忆 OSAgent  
> 版本：v0.2（含 SOTA 对标、记忆安全、自演化与评测增强）  

# 验收测试规范

## 验收域

A1 多源数据整合；A2 安全准入；A3 偏好捕捉；A4 版本化；A5 知识沉淀；A6 冲突融合；A7 记忆流转；A8 混合检索；A9 性能；A10 遗忘；A11 审计；A12 桌面入口；A13 记忆迁移；A14 文档；A15 SOTA；A16 纵向安全；A17 贡献归因；A18 自演化；A19 语义压缩。


## A20 情感感知记忆评测

### A20-01 情感信息提取

- 等级：E/S
- 验收内容：系统能从用户显式反馈或交互信号中提取对象级情感倾向。
- 判定标准：生成 polarity、intensity、emotional_salience、affective_source 字段。
- 证据要求：MemoryCapsule、证据卡、测试样本输出。

### A20-02 情感记忆更新

- 等级：E
- 验收内容：系统能在多轮交互中更新 affective_confidence 与 affective_entropy。
- 判定标准：同一 target 的情感状态随新证据变化，且更新策略符合 affective_update_policy。

### A20-03 情感记忆问答

- 等级：E
- 验收内容：系统能回答基于情感倾向和偏好的问题。
- 示例：我之前更喜欢哪种周报风格？我是不是不太喜欢这个工具流程？
- 判定标准：回答附带 affective_evidence_ids 或证据卡。

### A20-04 安全边界

- 等级：S
- 验收内容：情感显著性不得覆盖敏感信息识别、记忆投毒防御和精准遗忘策略。
- 判定标准：Safety Override Rate = 0。

### A20-05 临时情绪隔离

- 等级：S/E
- 验收内容：低置信、一次性、疑似临时状态的情感线索不得直接写入长期偏好。
- 判定标准：进入 ignore、weak_update 或 require_confirmation，而不是直接 normal_update。
