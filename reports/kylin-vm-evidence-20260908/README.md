# Kylin VM 全指标实测证据包（2026-09-08）

本目录是 **2026-09-08 在银河麒麟桌面操作系统 V11 虚拟机内采集的完整原始证据**，
对应赛题《OS Agent 记忆优化及高效应用研究》（XA-202612）四项量化指标 + 麒麟适配验证。
所有数字由脚本当场产出并落盘，原始 JSON / 控制台日志 / 环境快照全部留痕，
`SHA256SUMS` 为入库文件的完整性清单。不含任何密码、密钥与数据库文件。

指标对照与逐条复现方法见 [competition/09-vm-evidence.md](../../competition/09-vm-evidence.md)。

## 采集环境（证据：`00-environment.txt`）

| 项 | 值 |
|---|---|
| 操作系统 | 银河麒麟桌面操作系统 V11（Kylin-Desktop V11，Build 20260212，buildid 83681，KYLIN_RELEASE_ID=2603） |
| 内核 | 6.6.0-63-generic #63-KYLINOS SMP PREEMPT_DYNAMIC x86_64 |
| 虚拟化 | Hyper-V，4 vCPU（AMD Ryzen 9 7845HX）/ 7.8 GiB RAM |
| Python | 3.12.3（V11 系统自带） |
| 麒麟向量引擎 | `kylin-ai-vector-engine` 常驻；SDK bridge `/usr/local/bin/wanwei-kylin-sdk-bridge`（md5 留档于环境快照） |
| 嵌入模型 | 麒麟 SDK `ensemble-embd_gte-base_uint8-text`（768 维，生产路径）；回退通道 bge-small-zh（本地，512 维） |
| 源码基线 | 与本 PR 同源的仓库快照（backend/scripts 无本地改动；仅 #217/#218 增补的木兰版权头注释差异，无行为差异） |
| 依赖 | backend/requirements.txt + pytest 9.1.1 + torch 2.14.0+cpu + sentence-transformers 6.0.1（完整 pip freeze 见环境快照） |

## 赛题指标 → 实测结果（全部为本目录当日原始文件产出）

| 赛题指标 | 要求 | 实测 | 证据文件 |
|---|---|---|---|
| 知识检索响应延迟（麒麟 embedding SDK 端到端） | ≤500ms | **p50 27.51ms / p95 92.675ms / max 115.393ms，30 次全样本 ≤500ms** | `06-kylin-sdk-latency.json` |
| 知识检索召回率（Recall@5） | ≥85% | **1.0**（MEB full 全部 28 条检索 trace；四臂消融均为 1.0） | `01b-*` `01-*` `02-*` |
| 知识冲突处理正确率 | ≥88% | **conflict_update 4/4 = 100%**；TKE 双时态 Active Knowledge Accuracy 100% / Evolution Chain Accuracy 100%；no_governance 消融对照 0/4 | `01b-*` `02-*` `04-*` |
| 偏好提取准确率 | ≥85% | **多口径，见下方专节** —— 生产/回退路径 3/4（`MEB-PREF-003` 已知泄漏），词面通道 4/4，历史 12 例宽口径 91.67% | `01b-*` `01-*` `02-*` `03-*` |

### 偏好提取准确率专节（诚实口径）

| 口径 | 结果 | 说明 |
|---|---|---|
| MEB full 公开集（20 例），麒麟 SDK 生产路径（native auto） | 偏好 3/4 = 75%，总体 19/20 | `MEB-PREF-003`（多偏好并存不串味）泄漏：语义通道把「地铁通勤」胶囊带进「忌口」查询的 top-5 |
| MEB full 公开集，回退链（native off，local bge + FTS） | 偏好 3/4 = 75%，总体 19/20 | 同一用例同因失败——宿主机两次历史运行亦同错，确定性已知行为，非麒麟环境问题 |
| MEB full 消融臂（词面通道 fts_only） | 偏好 4/4 = 100% | `02-baseline-compare.json` |
| 历史宽口径（12 偏好用例，公开+仓外隐藏集，2026-09-02 宿主机） | 11/12 = 91.67% | 出处 `reports/baseline_compare.json`；隐藏集不在仓库内，无法在 VM 复现，如实标注 |
| EGPM 算法级消融（72 事件 × 6 场景） | 61.1% | 朴素累计众数/Beta 置信/窗口漂移代理检测器的事件级准确率——**不是系统指标**，用于论证「朴素投票不可靠」的设计动机 |

**已知问题与优化方向**（赛题允许「未达基础指标需明确优化方向」）：`MEB-PREF-003`
暴露语义通道在极小语料（同会话仅数条偏好）下的精确率问题——语义候选未做区分性
过滤，把句式相近但主题无关的偏好胶囊带进 top-5。优化方向：语义候选最低相似度
阈值 / 词面命中加权压制语义-only 候选 / 偏好类型（preference_type）硬过滤。
在 4 例公开集上，单例失败即掉 25 个百分点，粒度问题同样值得用例集扩容解决。

## 文件清单

- `00-environment.txt`：OS / 内核 / CPU / 内存 / Python / pip freeze / 向量引擎服务 / bridge 校验和。
- `01b-meb-full-native-auto.json`(+`-console.txt`/`-traces.json`)：MEB full 公开集 20 例，**麒麟 SDK 生产路径**（native auto）。
- `01-meb-full-native-off.json`(+`-console.txt`/`-traces.json`)：MEB full，native off（与宿主机基线同口径的回退链）。
- `02-baseline-compare.json`(+`-console.txt`)：四臂消融（hybrid / fts_only / vector_only / no_governance），每臂独立临时库，含三项赛题指标分臂对照。
- `03-egpm-benchmark.json`(+`-console.txt`/`-report.md`)：EGPM 偏好事件级消融。
- `04-tke-benchmark.json`(+`-console.txt`/`-report.md`)：TKE 知识演化双时态基准（四场景全部真实写路径）。
- `05-latency-scale.json`：端侧检索规模曲线（1k/10k/50k × 冷热 × 50 query）——**全栈配置**（语义回退通道 + FTS），逐次原始延迟。
- `05b-latency-scale-fts-only.json`(+`-console.txt`)：同曲线**纯 FTS 配置**（语义通道关闭，与已提交宿主机曲线同口径）。
- `06-kylin-sdk-latency.json`(+`-console.txt`)：麒麟原生 embedding+vector SDK 端到端延迟（30 次 + 1 次预热，逐次原始延迟，常驻 bridge）。
- `07-pytest-backend.txt`：全能力配置（native bridge + 本地模型在场）全量后端回归 —— 1866 passed / 9 failed / 4 skipped。
- `07b-pytest-ci-config.txt`：CI 等价配置（native off + 无本地模型）—— **1870 passed / 2 failed / 7 skipped**。两次的差异即 9 个失败的完整归因：7 例因目标机具备 CI 不具备的能力（真实麒麟 bridge、本地语义模型）而与测试假设不符，2 例（`test_pr215_release_staging`）因证据树是 tarball 解包、无 `.git` 目录（该测试读取 git 提交档案）。**无一是产品在麒麟上的功能回归。**
- `08-arena-console.txt` + `arena/`：生产记忆评测（MemoryArena-Lite 6 场景 20 断言全过，unsafe_autonomy_rate=0.0）。
- `09-demo-governance.txt` / `09-backend.log`：真实场景案例第一次尝试（detached）——后端启动并健康检查 200，但演示进程 urllib `EPERM`（同批 curl 可访问）。
- `09b-demo-governance.txt` / `09b-backend.log`：detached 重试 ×3，同样 `EPERM`——**复现 3 次**；同配置**_attached_ 会话内复测 curl / venv python / 系统 python 三个客户端均 200，未复现**。判定：V11 对无会话（nohup 脱离 SSH 会话）python 进程的回环连接存在环境级拦截，curl 不受影响；attached 执行不受影响（issue #206-E 的 KSAF/网络行为观测记录）。
- `09c-demo-governance.txt` / `09c-backend.log` / `09c-deletion-certificate.pdf`：**真实场景案例成功记录（attached 会话）**，见下。
- `SHA256SUMS`：入库文件完整性清单。

### 真实场景应用案例（赛题要求 ≥1 个，`09c-*`）

在麒麟 VM 内、生产配置（麒麟 SDK native auto，检索后端实测 `kylin_native`）完成全链路：
**明文口令写入被 Policy Gate S3 硬拦截（reject）→ 可治理敏感内部知识入库（allow/active）→
跨会话检索召回（命中，backend=kylin_native）→ 自然语言驱动遗忘（hard_delete）→
主表/FTS/图边/向量引用/遗留表五处残留取证全零 → 导出含审计编号的 PDF 删除证明证书（3,680 bytes）**。
复现：先 `scripts/run_dev.sh`，再 `python scripts/demo_governance.py --api-key <key>`。

> 演示脚本本次同步修复至当前 API（`/memory/v2/search` 已由 POST 改 GET；旧示例明文口令
> 现被 Policy Gate 设计性拦截，改为「先演示拦截、再写可治理内容」双段叙事）。

## 入库处理说明（数据完整性口径）

- traces 与延迟原始数组文件在入库时做了 **JSON 等价紧凑化**（`json.dumps` 无缩进单行，
  数据逐字节语义不变，可用 `python -m json.tool` 展开）；其余文件保持采集时原样。
  `SHA256SUMS` 基于入库后文件计算。
- 采集脚本序列（`run_vm_evidence.sh` / `extras.sh` 的等价命令）见
  [competition/09-vm-evidence.md](../../competition/09-vm-evidence.md) 第四节。
- 功能性基准（01/02/03/04/05b/07b）统一 `WANWEI_KYLIN_NATIVE_MODE=off`：与已提交宿主机
  基线同口径，且避免多个临时库向共享 native collection 交叉写入；06/01b/09b 为
  native auto 生产路径。两配置差异即三级回退链的真实行为，全部如实保留。

## 诚实口径

- MEB 用例集是本仓公开集（`official=False`），不是官方竞赛隐藏集；60 例含隐藏集的历史成绩未纳入本包（隐藏集不在仓库内，无法在 VM 复现）。
- EGPM 消融臂是算法级代理检测器（固定窗口众数 + Beta 置信），**不是**系统偏好提取指标。
- 延迟为单机实测（4 vCPU Hyper-V VM），不构成跨机承诺；逐次原始延迟全部留档可复核。
- 全栈规模曲线（05）中 50k 档 p95 2785ms：语义回退通道为 brute-force 余弦（纯 Python 遍历），万条以上明显退化——这正是「麒麟 SDK 为主通道、语义回退仅兜底」的设计依据；纯 FTS 曲线（05b）与已提交宿主机数据同口径可对照。HNSW 化是既定优化方向。
