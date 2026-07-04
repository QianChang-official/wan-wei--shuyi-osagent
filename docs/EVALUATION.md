> 项目：宛委·枢忆 OSAgent  
> 版本：v0.3.1（情感感知记忆调权与安全边界校正版）  

# 评测方案

## 1. 基础指标

- 偏好提取准确率
- 知识检索 Recall@K
- 冲突处理正确率
- P95 检索延迟
- 精准遗忘成功率
- 误删率
- 敏感识别准确率
- 记忆投毒拦截率

## 2. 增强评测

- 语义压缩收益
- 自演化收益
- 记忆投毒防御
- 纵向安全
- 记忆贡献归因

## 3. A20 情感感知记忆评测

A20 对齐 MemEmo 的三个核心维度：情感信息提取、情感记忆更新、情感记忆问答，同时加入安全边界约束。

### A20-01 情感信息提取

系统能从用户显式反馈或交互信号中提取对象级情感倾向。

判定字段：`polarity`、`intensity`、`emotional_salience`、`affective_source`。

### A20-02 情感记忆更新

系统能在多轮交互中更新 `affective_confidence` 与 `affective_entropy`，并根据 `affective_update_policy` 决定忽略、弱更新、正常更新或要求确认。

### A20-03 情感记忆问答

系统能回答“我之前更喜欢哪种周报风格”“我好像不太喜欢哪个工具流程”这类基于情感倾向和偏好的问题，并给出证据卡。

### A20-04 安全边界

情感显著性不得覆盖敏感信息识别、记忆投毒防御和精准遗忘策略。`Safety Override Rate` 应为 0。

### A20-05 临时情绪隔离

低置信、一次性、疑似临时状态的情感线索不得直接写入长期偏好，应采用 `ignore`、`weak_update` 或 `require_confirmation`。

## 4. 推荐新增指标

```text
Affective Extraction Accuracy：情绪/态度线索提取准确率
Affective Update Correctness：情感状态更新正确率
Affective QA Accuracy：情感记忆问答准确率
Over-memory Rate：短期情绪被误固化比例
Safety Override Rate：情感权重绕过安全策略次数，应为 0
Memory Contribution Score：记忆对任务成功的贡献
Longitudinal Risk Delta：记忆积累导致的安全风险变化
```
