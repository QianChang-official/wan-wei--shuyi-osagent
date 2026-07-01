> 项目：宛委·枢忆 OSAgent  
> 分支：灵犀情感分支 / Affective Memory-aware Management  

# 灵犀情感分支：情感记忆感知管理设计

## 1. 分支定位

灵犀情感分支用于在 OS Agent 记忆系统中引入情绪显著性与交互状态线索，辅助记忆写入、检索、遗忘和交互风格适配。

该分支不做心理诊断，不保存高敏感情绪隐私，不把临时情绪误判为长期人格偏好。

## 2. 核心思想

情绪不是事实本身，而是记忆管理的调制信号。

```text
事实内容回答“发生了什么”；
偏好记忆回答“用户稳定喜欢什么”；
情绪状态回答“当时交互氛围如何”；
情绪显著性回答“这条记忆是否值得更谨慎地处理”。
```

## 3. Schema 扩展

```json
{
  "affective_metadata": {
    "valence": "positive | neutral | negative | mixed | unknown",
    "arousal": 0.0,
    "emotional_salience": 0.0,
    "user_state_hint": "focused | happy | frustrated | stressed | unknown",
    "affective_source": "explicit | inferred | interaction_signal",
    "safety_note": "normal | sensitive | crisis_related | private"
  }
}
```

## 4. 写入策略

- 高情绪显著性、低敏感：提高候选记忆优先级。
- 高情绪显著性、高敏感：不直接长期固化，进入短期/隔离/需确认。
- 临时负面情绪：不得直接转写成长期偏好。
- 显式表达的长期偏好：可进入长期偏好记忆。

## 5. 检索策略

- 任务型场景：事实准确优先，情绪权重低。
- 陪伴/沟通场景：适度参考情绪线索调整语气。
- 安全场景：只触发温和安全边界，不做诊断。

## 6. 与现有模块关系

```text
石渠校验：提取弱情绪线索。
司契护栏：过滤高敏感情绪内容，防止创伤/隐私长期固化。
玄珠偏好：区分长期情感偏好与短期情绪状态。
建木网络：将情绪线索作为关系边/调制信号。
忘机机制：支持删除情绪相关记忆。
兰台鉴证：评测情绪线索是否导致误记、过记或安全风险。
```

## 7. 创新点

本分支引入情感显著性作为 MemoryCapsule 生命周期调制因子，使系统不仅能管理“记住什么”，还能管理“什么内容应该谨慎记、短期记、确认后记或主动遗忘”。

## 8. 灵感来源

- McGaugh：情绪唤醒影响记忆巩固。
- Phelps：杏仁核与海马在情绪记忆中的交互。
- LaBar & Cabeza：情绪记忆的认知神经科学综述。
- Kensinger：情绪对核心细节与外围细节记忆的不同影响。
- Picard：Affective Computing。
- Emotional Chatting Machine：内部/外部情绪记忆用于对话生成。
- EmpatheticDialogues：共情对话数据与情绪感知回应。
- Generative Agents：memory stream 与 importance score。
## 9. Copilot 提到方向的核验结论

- MemEmo: Evaluating Emotion in Memory Systems of Agents：已核验，arXiv:2602.23944。可用于“情感记忆评测”，包括 emotional information extraction、emotional memory updating、emotional memory question answering。
- EmoLLM: Multimodal Emotional Understanding Meets Large Language Models：已核验，arXiv:2406.16442。适合作为未来多模态/截图/OCR 情绪线索适配参考，不作为当前记忆主线。
- MemoryBank：已核验，可支撑长期记忆、遗忘曲线、长期陪伴与用户画像。
- Dynamic Affective Memory Management for Personalized LLM Agents：本轮未能通过 OpenAlex/arXiv/API 搜到确定条目，暂列“待核验技术池”，拿到准确 arXiv ID/DOI 后再纳入正式 SOTA。

推荐表述：本项目不声称模型具有真实情感，而是借鉴 affective memory 相关研究，将用户反馈、态度倾向和情感变化作为记忆元数据，用于偏好演化、检索重排序和个性化交互，并由 trust-aware retrieval 与司契护栏限制其安全边界。
