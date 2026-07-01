> 项目：宛委·枢忆 OSAgent  
> 版本：v0.3（Memory OS + 情感感知记忆 + 安全治理 + 自演化评测）  
> 定位：面向麒麟操作系统的端侧 OS Agent 记忆优化系统  

# 系统架构设计 v0.3

## 1. 一句话架构

宛委·枢忆 OSAgent 是一个端侧 Memory OS 原型：它把 OS Agent 的多源交互转化为可治理的 MemoryCapsule，并围绕 MemoryCapsule 实现接入、准入、提炼、压缩、检索、追溯、遗忘、自演化、情感调权与纵向评测。

```text
多源输入
  ↓
宛委入口 / API / Web 控制台 / 未来 UKUI
  ↓
石渠校验：事件标准化 + 质量评分 + 弱情绪线索抽取
  ↓
司契护栏：敏感识别 + 投毒防御 + trust_score + quarantine
  ↓
枢忆核：MemoryCapsule 生命周期调度
  ↓
玄珠偏好 / 琅嬛知识 / 灵犀情感 / 句芒演化 / 建木网络 / 册府融合 / 忘机机制
  ↓
SQLite + FTS5 + 向量引用 + 关系边表 + 审计日志 + 评测结果
  ↓
兰台鉴证：证据卡 + 验收测试 + 纵向安全 + 情感记忆评测
```

---

## 2. 总体分层

```text
L0 展示与接入层
├── Web Console
├── REST API
├── 未来 UKUI / Qt 入口
└── OCR / 文档 / 工具结果 / 用户行为 Adapter

L1 数据校验层
├── 石渠校验：统一事件模型、质量评分、去重、标准化
└── 灵犀预判：弱情绪线索、情感显著性初筛

L2 安全准入层
├── 司契护栏：敏感信息识别、高危命令检测、路径策略
├── Memory Poisoning Defense：注入/投毒识别
├── trust_score 计算
└── quarantine 隔离池

L3 记忆内核层
├── 枢忆核：MemoryCapsule 生命周期管理
├── CheckpointLog：状态快照
└── FlowOrchestratorAdapter：后续可接 LangGraph 类状态图

L4 记忆能力层
├── 玄珠偏好：偏好提取、版本化、场景适配
├── 琅嬛知识：知识沉淀、模板复用、案例库
├── 灵犀情感：情感显著性、态度倾向、情感记忆调权
├── 句芒演化：TTME-style 推理期记忆扩展、自演化反馈
├── 建木网络：短中长期流转、关系边、结构化记忆网络
├── 册府融合：冲突检测、多源归并、证据卡
└── 忘机机制：自然语言遗忘、preview、confirm、级联删除

L5 存储检索层
├── SQLite 结构化表
├── FTS5 / BM25 关键词索引
├── VectorRef / EmbeddingAdapter
├── RelationEdge 图关系表
└── AuditLog / EvalResult

L6 评测交付层
├── 兰台鉴证：审计、证据、报告
├── ATS 验收矩阵
├── Longitudinal Safety 快照评测
├── MemEmo-style 情感记忆评测
└── 部署、兼容性、演示材料
```

---

## 3. 核心数据结构：MemoryCapsule v0.3

MemoryCapsule 是本项目的最小可治理记忆单元。

```json
{
  "capsule_id": "uuid",
  "owner_scope": "user | scene | project | agent | device",
  "memory_type": "event | preference | knowledge | workflow | experience | affective | audit",
  "payload": {},
  "metadata": {
    "source_event_ids": [],
    "version": 1,
    "confidence": 0.0,
    "trust_score": 0.0,
    "quality_score": 0.0,
    "sensitivity_level": "S0 | S1 | S2 | S3",
    "importance_score": 0.0,
    "retention_score": 0.0,
    "usage_count": 0,
    "last_accessed_at": "ISO-8601"
  },
  "affective_metadata": {
    "target": "object | task | tool | project | style | unknown",
    "polarity": "positive | negative | neutral | mixed | unknown",
    "intensity": 0.0,
    "arousal": 0.0,
    "emotional_salience": 0.0,
    "affective_confidence": 0.0,
    "affective_entropy": 0.0,
    "affective_source": "explicit | inferred | interaction_signal",
    "safety_note": "normal | sensitive | crisis_related | private"
  },
  "index_refs": {
    "fts_rowid": "optional",
    "embedding_ref": "optional",
    "relation_refs": []
  },
  "lifecycle": "raw | candidate | active | deprecated | conflicted | quarantined | forgotten"
}
```

### 3.1 为什么增加 affective_metadata

情感不是事实本身，而是记忆管理的调制信号。

```text
事实内容回答：发生了什么。
偏好记忆回答：用户稳定喜欢什么。
情绪状态回答：当时交互氛围如何。
情绪显著性回答：这条记忆是否需要更谨慎地保留、降权、确认或遗忘。
```

安全边界：系统不声称模型具有真实情感，不做心理诊断，不把临时负面情绪直接固化为长期画像。

---

## 4. 核心闭环一：写入闭环

```text
输入事件
  ↓
石渠校验：source_type / scene / content / quality_score
  ↓
灵犀预判：polarity / intensity / emotional_salience
  ↓
司契护栏：sensitivity_level / trust_score / poison_risk
  ↓
枢忆核：生成 MemoryCapsule(candidate)
  ↓
玄珠偏好 / 琅嬛知识 / 灵犀情感 分类提炼
  ↓
建木网络建立关系边
  ↓
兰台鉴证记录审计证据
```

写入原则：

```text
高质量 + 高可信 + 低敏感 → 可进入 active。
高情绪显著性 + 低敏感 → 提高候选优先级。
高情绪显著性 + 高敏感 → quarantine 或短期保存，需确认。
短期情绪表达 → 不直接变成长期偏好。
注入/投毒风险 → 拒绝或隔离。
```

---

## 5. 核心闭环二：检索闭环

```text
用户查询
  ↓
意图识别：事实问答 / 偏好调用 / 情感交互 / 遗忘 / 评测
  ↓
检索规划：FTS / VectorRef / RelationEdge / AffectiveFilter
  ↓
多路召回：关键词 + 语义 + 关系 + 场景 + 情感目标
  ↓
trust-aware rerank
  ↓
证据卡生成
  ↓
回答或行动建议
```

推荐排序函数：

```text
final_score =
  0.35 * relevance_score
+ 0.15 * relation_score
+ 0.15 * confidence
+ 0.15 * trust_score
+ 0.10 * recency_score
+ 0.05 * affective_fit
+ 0.05 * usage_value
- safety_penalty
```

场景差异：

```text
任务型场景：relevance / trust / evidence 优先。
陪伴型场景：affective_fit 可适度提高。
安全场景：safety_penalty 绝对优先。
```

---

## 6. 核心闭环三：遗忘闭环

```text
自然语言遗忘指令
  ↓
目标解析
  ↓
召回候选 MemoryCapsule
  ↓
生成 preview：命中项、派生项、关系边、索引项、风险说明
  ↓
用户确认
  ↓
软删除 / 索引删除 / 关系边处理 / 派生摘要更新
  ↓
审计记录
```

精准遗忘必须覆盖：

```text
原始事件
MemoryCapsule
偏好版本
知识版本
affective metadata
FTS / VectorRef
RelationEdge
证据卡
派生摘要
```

---

## 7. 核心闭环四：自演化闭环

```text
任务执行
  ↓
记录使用了哪些记忆
  ↓
任务结果反馈：成功 / 失败 / 用户纠正 / 用户正反馈
  ↓
更新 confidence / trust_score / retention_score / affective_confidence
  ↓
必要时生成 experience memory
  ↓
进入下一轮检索与写入
```

该闭环吸收：

- SE-GA / TTME：推理期记忆扩展。
- SimpleMem：语义压缩与在线语义合成。
- Memory-R2：记忆贡献归因。
- MemoryBank：遗忘曲线与长期陪伴。
- MemEmo：情感记忆提取、更新、问答评测。

---

## 8. 模块职责表

| 模块 | 职责 | 技术 | 创新点 |
|---|---|---|---|
| 宛委入口 | Web/桌面入口、演示 | HTML/JS、FastAPI、未来 UKUI | 记忆可见、可改、可遗忘 |
| 石渠校验 | 多源事件标准化 | Pydantic、JSON Schema | OS Agent 事件总线 |
| 司契护栏 | 安全准入、防投毒 | 正则、规则、trust_score | 写入期+检索期双安全 |
| 枢忆核 | 生命周期调度 | MemoryCapsule、SQLite | 记忆系统资源化 |
| 玄珠偏好 | 偏好提取和版本化 | 规则/LLM Adapter | 偏好可演化、可回滚 |
| 琅嬛知识 | 知识沉淀、模板复用 | FTS、Markdown、JSON | 知识变成可调用资产 |
| 灵犀情感 | 情感显著性调权 | affective_metadata | 情感作为生命周期调制信号 |
| 建木网络 | 关系边、流转 | RelationEdge、图遍历 | 结构化记忆网络 |
| 册府融合 | 冲突处理、证据卡 | 版本表、证据 JSON | 多源记忆可解释融合 |
| 忘机机制 | 精准遗忘 | preview/confirm、soft delete | 级联遗忘闭环 |
| 句芒演化 | 记忆自演化 | usage feedback、compression | 任务反馈驱动记忆质量更新 |
| 兰台鉴证 | 审计评测 | pytest、JSONL、报告生成 | 纵向安全和情感记忆评测 |

---

## 9. 存储设计 v0.3

```text
memory_events             原始事件
memory_capsules           MemoryCapsule 主表
memory_versions           版本记录
memory_relations          关系边
preference_profiles       偏好画像
knowledge_items           知识条目
experience_items          经验记忆
affective_states          情感目标状态与变化
quarantine_items          隔离记忆
audit_logs                审计日志
forget_records            遗忘记录
eval_results              评测结果
checkpoint_logs           状态快照
sync_packages             可选导入导出包
```

---

## 10. 评测设计 v0.3

基础指标：

```text
偏好提取准确率
知识检索 Recall@K
证据卡准确率
冲突处理正确率
P95 检索延迟
精准遗忘成功率
误删率
敏感识别准确率
投毒拦截率
```

新增指标：

```text
Affective Extraction Accuracy：情绪/态度线索提取准确率
Affective Update Correctness：情感状态更新正确率
Affective QA Accuracy：情感记忆问答准确率
Over-memory Rate：短期情绪被误固化比例
Safety Override Rate：情感权重绕过安全策略次数，应为 0
Memory Contribution Score：记忆对任务成功的贡献
Longitudinal Risk Delta：记忆积累导致的安全风险变化
```

---

## 11. SOTA 与灵感映射

| 来源 | 吸收点 | 项目落点 | 边界 |
|---|---|---|---|
| MemOS / Memory OS | 记忆系统资源化、生命周期 | 枢忆核、MemoryCapsule | 不声称完整复现 MemOS |
| LangGraph | 状态图、Checkpointer、Store | FlowOrchestratorAdapter、CheckpointLog | 可选工程实现 |
| Honcho | 用户建模、peer 隔离 | UserMemoryProfile、PeerScope | 不依赖外部云记忆 |
| SE-GA / TTME | 推理期记忆扩展 | 句芒演化 | 不训练大模型，只做端侧记忆调度 |
| SimpleMem | 语义压缩、在线合成 | 压缩型 Capsule、检索规划 | MVP 先规则化实现 |
| Structural Memory | chunks/triples/facts/summaries | 建木网络 | 先用 SQLite 关系边 |
| Memory Poisoning Defense | 投毒防御、trust-aware retrieval | 司契护栏 | 不做攻击性能力 |
| Longitudinal Safety | 纵向安全评测 | 兰台鉴证 | 评测用途 |
| Memory-R2 | 贡献归因 | usage log、贡献评分 | 先做消融统计 |
| MemEmo | 情感记忆评测 | Affective Evaluation | 不做心理诊断 |
| Emotional Memory Neuroscience | 情绪显著性、巩固、核心细节 | 灵犀情感 | 只作类比，不宣称人脑模拟 |
| Affective Computing | 情绪线索计算 | affective_metadata | 弱情绪线索，不识别真实内心 |
| Generative Agents | memory stream、importance score | retention_score | 本地轻量实现 |
| Cognitive Architectures | 感知-记忆-行动闭环 | 总体分层 | 作为设计灵感 |
| Predictive Processing | 预测误差驱动更新 | conflict/update signal | 未来增强 |

---

## 12. 新增灵感池

### 12.1 认知架构

参考“40 years of cognitive architectures”一类综述，将系统理解为：

```text
感知输入 → 工作记忆 → 长期记忆 → 行动选择 → 反馈学习
```

项目落点：宛委入口、枢忆核、句芒演化形成最小认知闭环。

### 12.2 预测处理 / Predictive Processing

思路：系统维护对用户偏好和任务流程的预测，当新事件和预测不一致时触发更新。

项目落点：

```text
prediction_error 高 → 触发偏好冲突检测或知识版本更新。
prediction_error 低 → 仅增加 usage_count 和 confidence。
```

### 12.3 人类情绪记忆

思路：情绪显著性影响记忆巩固，但也会带来偏差。

项目落点：灵犀情感只做调权，不把情绪当事实。

### 12.4 记忆免疫系统

类比生物免疫：记忆写入前要识别“外来有害指令”。

项目落点：司契护栏 + quarantine + trust-aware retrieval。

### 12.5 数据血缘 / Lineage

任何派生记忆都必须能追溯到原始事件。

项目落点：source_event_ids、RelationEdge、证据卡、级联遗忘。

---

## 13. 答辩用总结

```text
宛委·枢忆 OSAgent 的核心不是把文本塞进向量库，而是把 OS Agent 的记忆作为一种可治理系统资源来管理。系统以 MemoryCapsule 为统一抽象，围绕其构建多源接入、安全准入、偏好提取、知识沉淀、结构化关系、情感显著性调权、混合检索、精准遗忘、自演化反馈与纵向评测闭环。

与普通 RAG 相比，本项目不仅回答“如何记住”，还回答“哪些可以记、为什么记、如何证明、如何更新、何时遗忘、如何避免记忆污染”。
```
