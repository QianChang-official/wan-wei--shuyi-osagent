# 麒麟 VM 全指标实测证据（2026-09-08）

> 本文是赛题《OS Agent 记忆优化及高效应用研究》（XA-202612）四项量化指标与麒麟适配的**实测证据索引**。
> 全部数字产自 2026-09-08 在银河麒麟桌面操作系统 V11 虚拟机内的连续采集会话，
> 原始文件见 [reports/kylin-vm-evidence-20260908/](../reports/kylin-vm-evidence-20260908/)（含 SHA256SUMS 完整性清单与文件级说明）。
> 历史宿主机成绩与口径见 [04-评测成绩单](04-benchmark.md)；本文只收录 VM 当日实测。

## 一、采集环境（`00-environment.txt`）

| 项 | 值 |
|---|---|
| 操作系统 | 银河麒麟桌面操作系统 V11（Build 20260212，buildid 83681，KYLIN_RELEASE_ID=2603） |
| 内核 | 6.6.0-63-generic #63-KYLINOS SMP PREEMPT_DYNAMIC x86_64 |
| 虚拟化 | Hyper-V，4 vCPU（AMD Ryzen 9 7845HX）/ 7.8 GiB RAM |
| Python | 3.12.3（V11 系统自带） |
| 麒麟向量引擎 | `kylin-ai-vector-engine` 常驻；bridge `/usr/local/bin/wanwei-kylin-sdk-bridge` |
| 嵌入模型 | 生产路径 `ensemble-embd_gte-base_uint8-text`（768 维）；回退 bge-small-zh（512 维） |

## 二、四项赛题指标实测对照

### 1. 知识检索响应延迟 ≤500ms（麒麟 embedding SDK 端到端）—— **达标**

**麒麟原生 embedding+vector SDK 常驻 bridge 端到端检索：p50 27.51ms，p95 92.675ms，max 115.393ms**
（30 次计时检索 + 1 次预热，逐次原始延迟留档；模型 `ensemble-embd_gte-base_uint8-text`，768 维，
`06-kylin-sdk-latency.json`）。相对 2026-07 旧证据（p50 195.32 / p95 246.47，one-shot 冷启动口径），
常驻 bridge 把模型加载移出请求路径，端到端 p95 降至 92.7ms。

配套规模证据：
- MEB full 检索 trace（生产路径 28 条，进程内）：单条 0.95–19.98ms（`01b-*-traces.json`）；
- 端侧 SQLite FTS5 纯词面通道规模曲线（1k/10k/50k × 冷热 × 50 query）：**冷态 p95 = 6.0 / 53.2 / 224.6ms，
  热态 p95 = 3.8 / 45.7 / 210.0ms**（`05b-latency-scale-fts-only.json`）——纯词面回退通道在 5 万条记忆下
  仍 ≤500ms；
- 全栈回退链（语义 brute-force + FTS）同曲线：`05-latency-scale.json` —— 50k 档 p95 2785ms，
  语义回退通道 brute-force 余弦在万条以上明显退化。这正是「麒麟 SDK 为主通道、语义回退仅兜底」
  的设计依据与 HNSW 优化方向（赛题未对该回退通道设阈值，主通道实测 92.7ms ≪ 500ms）。

### 2. 知识检索召回率 ≥85% —— **达标（Recall@5 = 1.0）**

- MEB full 公开集（生产路径 native auto / 回退链 native off 两种配置）：**knowledge_recall 用例 4/4，
  声明相关性标注的检索步 Recall@5 = 1.0**（`01b-*` / `01-*`）；
- 四臂消融（hybrid / fts_only / vector_only / no_governance）：**全部 Recall@5 = 1.0**
  （`02-baseline-compare.json`）——召回能力不依赖任何单一通道，治理开关不影响召回。

### 3. 知识冲突处理正确率 ≥88% —— **达标（100%）**

- MEB full conflict_update 用例：**4/4 = 100%**（生产路径与回退链同分，`01b-*` / `01-*`）；
- **no_governance 消融臂对照 0/4 = 0%**（`02-baseline-compare.json`）——冲突正确性由治理层
  （policy gate + 生命周期状态机）直接保障，去掉即归零，组件贡献可量化；
- TKE 知识演化双时态基准：**Active Knowledge Accuracy（as-of 历史回放）100%、
  Evolution Chain Accuracy（演化链重建）100%**，软件演化/流程演化/规范替换/延迟导入
  四场景全部真实写路径（`04-tke-benchmark.json`）。

### 4. 偏好提取准确率 ≥85% —— **多口径如实报告**

| 口径 | 结果 | 证据 |
|---|---|---|
| MEB full 公开集（20 例），麒麟 SDK 生产路径 | 偏好 3/4 = 75%，总体 19/20 | `01b-meb-full-native-auto.json` |
| MEB full，回退链（native off） | 偏好 3/4 = 75%，总体 19/20 | `01-meb-full-native-off.json` |
| MEB full 消融臂 fts_only（词面通道） | 偏好 4/4 = 100% | `02-baseline-compare.json` |
| 历史宽口径（12 偏好用例，公开+仓外隐藏集，2026-09-02 宿主机） | 11/12 = 91.67% | `reports/baseline_compare.json`（隐藏集不在仓库，无法 VM 复现） |
| EGPM 算法级消融（72 事件 × 6 场景） | 61.1% | `03-egpm-benchmark.json`（代理检测器，非系统指标） |

**已知问题与优化方向**（赛题规则允许「未达基础指标需明确优化方向」）：
唯一失败用例 `MEB-PREF-003`（多条偏好并存按查询意图分别召回）中，语义通道把句式相近
但主题无关的「地铁通勤」偏好胶囊带进「忌口」查询 top-5（must_not_contain 泄漏）。宿主机
两次历史运行同错，属确定性行为而非麒麟环境问题；词面通道（fts_only）通过。优化方向：
语义候选最低相似度阈值、词面命中加权压制语义-only 候选、偏好类型（preference_type）硬过滤；
同时 4 例公开集上单例失败即 25 个百分点，用例集粒度需要扩容。EGPM 61.1% 是「朴素累计投票
不可靠」的论证数据，恰好反衬系统置信度加权 + 确认门（`MEB-PREF-002` 的 candidate→confirm）
的设计必要性。

## 三、麒麟适配与真实场景证据（issue #206 项 D/E 回传）

- **后端在 V11 原样运行（#206-D）**：CI 等价配置全量后端回归 **1870 passed / 2 failed / 7 skipped**
  （`07b-pytest-ci-config.txt`）；唯二失败为 `test_pr215_release_staging` 两例——该测试读取 git
  提交档案，证据树为 tarball 解包无 `.git`，与麒麟无关。
- **全能力配置回归（#206-E 观测）**：真实麒麟 bridge + 本地语义模型在场时 1866 passed / 9 failed
  （`07-pytest-backend.txt`）。9 例失败全部归因：7 例是目标机具备 CI 不具备的能力（真实 bridge、
  本地模型）导致测试假设不成立（例：`test_semantic_recall_without_shared_words` 期望走本地通道，
  实际麒麟 SDK 通道先命中——生产路径表现优于测试预期）；2 例同上 .git 问题。**无一是产品在
  麒麟上的功能回归**；全程 venv 自建 Python 未被 KSAF/KYSEC 拦截。
- **真实场景应用案例（赛题要求 ≥1 个）**：`09c-*` —— 麒麟 VM 内以生产配置（检索后端实测
  `kylin_native`）运行后端，完成「明文口令写入被 Policy Gate S3 硬拦截 → 可治理敏感内部知识入库 →
  跨会话检索召回 → 自然语言驱动遗忘 → 主表/FTS/图边/向量引用/遗留表五处残留取证全零 →
  导出含审计编号的 PDF 删除证明证书」全链路（`09c-demo-governance.txt` / `09c-deletion-certificate.pdf`）。
  演示脚本本次同步修复至当前 API（search 由 POST 改 GET；示例内容适配强化后的 Policy Gate）。
- **V11 环境行为观测（#206-E）**：detached（nohup 脱离 SSH 会话）python 进程访问回环端口
  报 `EPERM`，同批 curl 不受影响，attached 会话内三个客户端（curl / venv python / 系统 python）
  均 200——detached 复现 3 次（`09-*` / `09b-*`）、attached 未复现。部署形态建议：
  桌面常驻服务由 systemd user 单元拉起（有会话归属），避免纯 nohup 脱离会话运行 python 客户端。
- **生产记忆评测**：MemoryArena-Lite 6 场景 **20/20 断言全过**，unsafe_autonomy_rate=0.0，
  evidence_card_coverage / policy_gate_hit / lifecycle_correct 均 1.0
  （`08-arena-console.txt` + `arena/production_memory_eval_metrics.json`）。

## 四、复现方法（全部命令在麒麟 V11 VM 内、仓库根、`.venv` 就绪后执行）

```bash
# 功能性基准统一 native off(与宿主机基线同口径,避免临时库交叉写 native collection)
WANWEI_KYLIN_NATIVE_MODE=off WANWEI_LOCAL_EMBED_DIR=<bge目录> \
  python scripts/run_meb.py --suite full --save-traces        # 01(回退链口径)
python scripts/bench_baseline_compare.py                      # 02(四臂消融,需本地模型)
PYTHONPATH=. python scripts/bench_egpm.py                     # 03(EGPM,产 JSON+MD)
PYTHONPATH=. python scripts/bench_tke.py                      # 04(TKE)
WANWEI_LOCAL_EMBED_DIR= python scripts/bench_latency_scale.py # 05b(纯 FTS 规模曲线)
python scripts/bench_kylin_sdk_latency.py                     # 06(麒麟 SDK 端到端延迟)
WANWEI_KYLIN_NATIVE_MODE=off WANWEI_LOCAL_EMBED_DIR= python -m pytest -q   # 07b(CI 等价)
python scripts/demo_governance.py --api-key <key>             # 09c(先启动后端,attached 会话)
```

一次性采集序列与每步控制台日志随证据包提供（`*-console.txt`），任何数字都可对照原始输出复核。
