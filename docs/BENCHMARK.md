# Benchmark

> 现行最新一轮实测为 **2026-09-08 银河麒麟桌面操作系统 V11 虚拟机内连续采集**，四项赛题指标原始数据与逐条复现方法见 [competition/09-vm-evidence.md](../competition/09-vm-evidence.md)，原始文件在 [`reports/kylin-vm-evidence-20260908/`](../reports/kylin-vm-evidence-20260908/)（SHA256SUMS 覆盖 33 个入库文件）。本文同时保留历史宿主机口径以便对照，两者均标注采集日期与环境。

## 偏好提取

多口径如实报告（赛题要求 ≥85%）：

| 口径 | 结果 | 出处 |
|---|---|---|
| MEB full 公开集 4 例粒度，麒麟 SDK 生产路径（native auto） | **3/4 = 75%**，总体 19/20 | `reports/kylin-vm-evidence-20260908/01b-meb-full-native-auto.json` |
| MEB full，回退链（native off，local bge + FTS） | 3/4 = 75%，总体 19/20 | `reports/kylin-vm-evidence-20260908/01-meb-full-native-off.json` |
| MEB full 消融臂 fts_only（词面通道） | **4/4 = 100%** | `reports/kylin-vm-evidence-20260908/02-baseline-compare.json` |
| 历史宽口径（12 偏好用例，公开 + 仓外隐藏集，2026-09-02 宿主机） | 11/12 = **91.67%** | `reports/baseline_compare.json`（`preference_extraction_accuracy=0.9167`） |
| EGPM 算法级消融（72 事件 × 6 场景，代理检测器） | 61.1% | `reports/kylin-vm-evidence-20260908/03-egpm-benchmark.json`——**非系统指标** |
| MEB mini | 2/2 通过 | `reports/meb_score_report.json` |

唯一失败用例 `MEB-PREF-003`（多条偏好并存按查询意图分别召回）：语义通道把句式相近但主题无关的「地铁通勤」偏好胶囊带进「忌口」查询 top-5（must_not_contain 泄漏）。宿主机两次历史运行同错，属确定性行为而非麒麟环境问题；词面通道通过。优化方向：语义候选最低相似度阈值、词面命中加权压制语义-only 候选、偏好类型（`preference_type`）硬过滤。另 4 例公开集上单例失败即 25 个百分点，用例集粒度需要扩容。隐藏集不在仓库内，无法在 VM 复现。

无独立线上 precision 报告的项标为未实跑。

## 知识检索

召回率（赛题要求 ≥85%）：2026-09-08 麒麟 VM 实测 MEB full 双配置（生产路径 + 回退链）**knowledge_recall 用例 4/4，声明相关性标注的检索步 Recall@5 = 1.0**；四臂消融（hybrid / fts_only / vector_only / no_governance）**全部 Recall@5 = 1.0**——召回不依赖任何单一通道，治理开关不影响召回（`01b-*` / `01-*` / `02-baseline-compare.json`）。MEB full 检索 trace（生产路径 28 条，进程内）单条 0.95–19.98ms。

历史宿主机口径：MEB mini 知识召回 3/3。本机 SQLite FTS5 p95 0.8072ms（README 实测表）。

## 冲突处理

赛题要求 ≥88%。2026-09-08 麒麟 VM 实测 MEB full conflict_update 用例 **4/4 = 100%**（生产路径与回退链同分）；**no_governance 消融臂对照 0/4 = 0%**——冲突正确性由治理层（Policy Gate + 生命周期状态机）直接保障，去掉即归零，组件贡献可量化。MEB mini 冲突更新用例 3/3。

## 检索延迟
麒麟原生 SDK 端到端（常驻 bridge，2026-09-08 麒麟 V11 VM 实测，30 次计时 + 1 次预热）：**p50 27.51ms / p95 92.675ms / max 115.393ms**（`reports/kylin-vm-evidence-20260908/06-kylin-sdk-latency.json`）。历史口径对照：2026-07 one-shot 冷启动 p50 195.320ms、p95 246.473ms（`reports/kylin-native-sdk-evidence/latency.json`）；v1.0.0 验收宿主机 HTTP 全链路 p50 29ms、p95 83ms（CHANGELOG 2026-09-05）。常驻 bridge 把模型加载移出请求路径，是 p95 由 246.5ms 降至 92.7ms 的原因。消融报告中 FTS-only p95 1.01ms、hybrid 8.13ms、vector-only 7.37ms（`reports/baseline_compare.json`）。

## 遗忘验证
MEB mini 遗忘 3/3；删除证据链由五处残留验证覆盖。麒麟 V11 VM 实机全链路（含 PDF 删除证书导出）通过记录见 `reports/kylin-vm-evidence-20260908/09c-demo-governance.txt`。未实跑跨部署长期恢复测试。

## 对照实验
MEB full（非官方）历史结果（2026-09-02 宿主机，60 例）：fts_only 60/60，hybrid 59/60，vector_only 58/60，no_governance 46/60（`reports/baseline_compare.json`）；14 例失败中 12 例为冲突更新场景（CONF），另 KNOW 1 例、PREF 1 例。

2026-09-08 麒麟 V11 VM 复测四臂消融（公开集 20 例，每臂独立临时库）：Recall@5 **四臂全部 = 1.0**——召回能力不依赖任何单一通道，治理开关不影响召回；conflict_correctness 三臂 1.0、no_governance 臂 **0.0**；pass_rate fts_only 20/20、hybrid 19/20、vector_only 18/20、no_governance 14/20（`reports/kylin-vm-evidence-20260908/02-baseline-compare.json`）。

EGPM 算法级消融已补测（72 事件 × 6 场景）：preference_accuracy **0.6111**，false_preference_rate 0.9474；+Drift 臂 drift_f1 0.4000（`reports/kylin-vm-evidence-20260908/03-egpm-report.md`）。该口径是代理检测器的**事件级**准确率，用于论证「朴素累计投票不可靠」，**不是**系统偏好提取指标；Emotion / Persona / Safety Consistency 组件未实现，相应指标标记为未验证。Phase-2 Outcome Validation 的真实漂移与统一对照仍未接入。

## 延迟规模曲线
麒麟 V11 VM 实测（1k/10k/50k 条记忆、50 条中文 query、冷热两态），双口径如实分列：

- **纯 FTS 词面通道**（语义通道关闭，与已提交宿主机曲线同口径）：冷态 p95 = **6.0 / 53.2 / 224.6ms**，热态 p95 = 3.8 / 45.7 / 210.0ms（`reports/kylin-vm-evidence-20260908/05b-latency-scale-fts-only.json`）——5 万条记忆下仍满足赛题 ≤500ms。
- **全栈回退链**（语义 brute-force 余弦 + FTS）：50k 档 p95 **2785ms**（`reports/kylin-vm-evidence-20260908/05-latency-scale.json`）——语义回退通道在万条以上明显退化。这正是「麒麟 SDK 为主通道、语义回退仅兜底」的设计依据；赛题未对该回退通道设阈值，HNSW 索引化为既定优化方向。

历史宿主机口径（`reports/latency_scale.json`）：1k cold p95 4.61ms、10k 77.06ms、50k 447.94ms。逐次原始延迟在各 JSON 中均可复现。

## 向量检索度量口径（#235）
麒麟原生通道的向量检索度量使用**官方 SDK 默认 COSINE**：建库侧走快速 `CreateCollection(name, dim, ...)`（`Database.h`），检索侧 `SearchArguments` 构造默认 `MetricType::COSINE`（`types/SearchArguments.h`），双侧一致——官方 `exampleSchema.cpp` 明确「检索度量要与索引一致」（其演示为索引 L2 + `arguments.SetMetricType(L2)`）。选择理由：当前默认 embedding 模型（`ensemble-embd_gte-base_uint8-text`，768 维）为 gte 类归一化文本向量，COSINE 是标准度量，且归一化向量下 COSINE 与 IP 排名等价。`MetricType` 枚举（L2/IP/COSINE/HAMMING/JACCARD）与 `IndexDesc.SetMetricType` 均在官方头文件中开放，后续如需切换度量，建库与检索两侧必须同步修改。COSINE vs IP 对照实验列为可选后续（见 #235），未实测前不写入口径结论。

## 知识演化与时序（TKE Benchmark）
四场景（软件演化 Firefox→Chrome→Edge / 流程演化 v1→v2→v3 / 规范替换 / 延迟导入——transaction_time 与 valid_time 错位场景）全部真实写路径：
- **Active Knowledge Accuracy（as-of/truth 历史回放正确率）：100%**
- **Evolution Chain Accuracy（演化链重建正确率）：100%**

复现：`PYTHONPATH=. python scripts/bench_tke.py`；原始逐采样判定见 `reports/tke_benchmark.json`，报告 `reports/tke_benchmark_report.md`。2026-09-08 麒麟 V11 VM 当日复测同口径双 100%（`reports/kylin-vm-evidence-20260908/04-tke-benchmark.json`）。

## 偏好演化（Preference Graph）
节点/边建模、preference_score 四因子、演化幂等、冲突建议式裁决、级联遗忘与 preference-aware 重排由 45 条测试锁定（`test_preference_graph.py` 等四件套）；消融对照实验未跑，接入统一基准后补充。EGPM 算法级消融已补测（见「对照实验」一节），但其口径是代理检测器的事件级准确率，不构成 Preference Graph 的消融对照。
