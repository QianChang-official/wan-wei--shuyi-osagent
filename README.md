# 宛委·枢忆 MemoryOps Autopilot Platform

面向麒麟 OS Agent 的端侧记忆治理、检索、评测和安全工作流研究原型。

> 当前版本：v0.10.0-delivery-hardening。这是可运行的单节点 alpha 与参赛研发底座，不是高可用生产平台；所有 partial、planned 和仅在特定环境验证的能力均保留明确边界。

## 文档中心

[文档中心](文档中心_DOCUMENTATION_HUB.md)收录项目全文文档，并按项目与版本、架构与运行时、记忆与 Schema、治理与安全、API 与工作流、评测与合规、麒麟适配、部署与运维、研究资料和历史备份分类。它是根目录唯一的文档入口；每份收录内容都保留来源路径、状态、哈希和稳定锚点，便于审阅和追溯。

## 可运行能力

| 能力 | 当前实现 | 运行边界 |
| --- | --- | --- |
| 记忆运行时 | FastAPI、SQLite、FTS5、MemoryCapsule 2.0、Policy Gate、Evidence Cards、审计和 Vue 同源控制台 | 单节点本地运行时 |
| 记忆操作 | Capsule 写入、列表、检索、命令、复盘，以及 preview/confirm 的精准遗忘 | 受策略门和审计约束 |
| 检索 | 官方 Kylin embedding/vector SDK 可用时原生向量检索优先；不可用或失败时显式回退 SQLite FTS5 | 原生 SDK 是可选能力，不是所有环境的前提 |
| 工作流 | SQLite 持久化的安全 dry-run：run、trace、artifacts 和 audit | 不执行危险工具动作；模型生成延迟单独报告 |
| 模型接入 | local_mock 离线可用；显式配置的本地 OpenAI-compatible endpoint 可做真实 smoke | Anthropic/Gemini 是 catalog/configuration stub，不宣称已接入生产调用 |
| 交付与防护 | 非 root 容器、只读根文件系统、默认 localhost 绑定、生产密钥约束、health/readiness、受保护 metrics、Windows/Linux CI 与容器 smoke | 单节点，不提供多副本高可用或生产 SLA |

## 已验证证据

| 项目 | 结果 | 范围 |
| --- | --- | --- |
| MemoryArena-Lite | 5 cases、16 assertions 全部通过；unsafe_autonomy_rate=0.0 | misleading_memory_rate 与 production_task_success_rate 仍为 pending |
| 本机 SQLite 检索 | capsule_search_zh p95 为 0.8072 ms | 100 次、50 个 seed capsules、单机单进程、排除模型生成延迟 |
| Kylin SDK 快照 | Kylin V11 2603 x86_64 QEMU/WHPX VM 的捕获源码快照中，官方 embedding/vector Bridge、原生写入、语义检索、遗忘、重建和延迟采样均有原始证据 | 30 次 loopback HTTP 搜索 p50 195.320 ms、p95 246.473 ms；不覆盖最终合并提交、物理目标硬件、LoongArch/ARM、OCR、大规模数据、长期稳定性或 SLA |

详见[兼容性测试报告](文档中心_DOCUMENTATION_HUB.md#doc-compatibility-test-report-b002acd2)、[Kylin SDK 集成说明](文档中心_DOCUMENTATION_HUB.md#doc-kylin-native-sdk-integration-29604159)、[评测说明](文档中心_DOCUMENTATION_HUB.md#doc-evaluation-52ba5bd9)和[生产记忆评测](文档中心_DOCUMENTATION_HUB.md#doc-production-memory-eval-fae4873e)。该 VM 快照不覆盖其后的源码提交；待交付的最终提交仍须在目标 VM 按精确源码哈希重新构建并重跑证据。

## 赛题映射

| 赛题方向 | 项目支撑 | 状态 |
| --- | --- | --- |
| 多源数据接入 | 输入校验、source layer、JSON/Markdown/PDF/日志入口设计 | partial |
| 偏好与知识记忆 | MemoryCapsule、偏好/知识双轨、provenance 与关系边 | partial |
| 安全过滤与遗忘 | Policy Gate、确认门、quarantine/reject、遗忘预览与审计 | 可运行链路 |
| 关联检索 | 原生向量优先、FTS5 后备、Evidence Cards | 可运行链路，SDK 依环境可选 |
| 量化评测 | MemoryArena-Lite、报告和指标接口 | 可运行基线；正式赛题硬指标待补齐 |
| 麒麟适配 | Kylin VM SDK 证据、Bridge、兼容性报告 | VM 快照已验证；物理硬件/其他架构/OCR 待验证 |

完整映射见[竞赛要求覆盖矩阵](文档中心_DOCUMENTATION_HUB.md#doc-competition-requirement-coverage-beaccf0d)。

## 快速开始

前置条件：Python 3.10+、Node.js 20+、npm 10+。

### Windows

    powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
    powershell -ExecutionPolicy Bypass -File .\scripts\run_dev.ps1

控制台：http://127.0.0.1:8010/console/

### Linux / 麒麟 OS

    bash scripts/setup.sh
    bash scripts/run_dev.sh

### 容器

    Copy-Item .env.example .env
    .\scripts\init_secret.ps1
    docker compose build
    docker compose up -d

Compose 默认以生产模式运行，要求通过 secret 文件提供 API key，并仅将端口绑定到 127.0.0.1，除非显式修改配置。

## 验证

    .\scripts\smoke.ps1
    .\backend\.venv\Scripts\python.exe -m pytest
    .\scripts\run_eval.ps1
    .\scripts\verify.ps1 -SkipInstall -IncludeArena

smoke.ps1 覆盖 health/readiness、鉴权、Memory v2、workflow 和 metrics；verify.ps1 执行 Python 编译、后端测试、两次确定性前端生产构建，并可选运行 MemoryArena。

## 关键入口

| 接口或页面 | 用途 |
| --- | --- |
| /console/ | Vue MemoryOps Studio |
| /health/live、/health/ready | 存活与就绪探针 |
| /memory/v2/capsules、/memory/v2/search | Capsule 写入、读取和检索 |
| /memory/forget/preview、/memory/forget/confirm | 受确认的精准遗忘 |
| /workflow/runs | 持久化安全 dry-run、trace 和 artifacts |
| /kylin/sdk/status | 原生 SDK/索引状态，需正常 API 鉴权 |
| /metrics | 受保护的 Prometheus 文本指标 |

## 真实边界

- 当前系统是 alpha research prototype，不宣称企业生产级、多副本高可用或 SLA。
- 正式偏好提取准确率、知识检索召回率和冲突处理正确率尚未形成赛题级实测报告。
- 研究复现与 Deepening 接口提供 catalog、schema、读取或 dry-run，不等同于外部系统的完整官方复现或模型训练。
- 原生 Kylin 检索在 SDK 不可用时回退 FTS5；OCR、物理目标硬件和其他目标架构仍需独立验收。
- 公开 Release 仍等待项目所有者选择许可证；自动化不会擅自决定法律条款。
