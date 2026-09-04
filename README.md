# 宛委·枢忆

[![Security](https://github.com/QianChang-official/wan-wei--shuyi-osagent/actions/workflows/security.yml/badge.svg)](https://github.com/QianChang-official/wan-wei--shuyi-osagent/actions/workflows/security.yml)
![Version](https://img.shields.io/badge/version-v0.11.0-blue)
![License](https://img.shields.io/badge/license-Mulan%20PSL%20v2-green)

**AI 会记住你。但更重要的是，它能证明自己已经忘记。**

面向信创环境的可审计 Agent 记忆治理平台。

---

## 三分钟证据链

```bash
python scripts/demo_governance.py --api-key <key>
```

上面的脚本会自动完成：

| 步骤 | 动作 | 你看到什么 |
|---|---|---|
| 1 | 写入一条敏感记忆 | 记忆胶囊创建成功，含 Policy Gate 审计标记 |
| 2 | 跨会话检索召回 | 无需重复交代背景，AI 直接命中 |
| 3 | 指定删除该记忆 | 硬删除执行完成 |
| 4 | 验证删除完整性 | 主表/FTS/图边/向量引用/遗留表五处逐项取证，全部为零 |
| 5 | 导出删除证明 | 生成 PDF 证书，含审计编号与证据链说明 |

**第 4 步是全场唯一没人能现场复刻的演示。**

---

## 为什么存在

今天的 AI 存在一个被忽视的问题：AI 会记住很多东西，但没人知道——

- 它到底记住了什么
- 为什么记住
- 什么时候形成
- 是否删除成功
- 会不会重新出现

对于个人用户，这只是烦恼。对于政企单位，这是风险。

当领导问：**"三个月前录入系统的敏感信息真的删除了吗？"**

大多数 AI 平台给不出答案。

---

## 核心能力

| 能力 | 说明 | 端点 |
|---|---|---|
| **删除证明** | 五处逐项取证（主表/FTS/图边/向量/遗留），生成 PDF 证书 | `/memory/governance/verify-deletion/{id}/certificate` |
| **生命周期状态机** | 10 态合法转移裁决，非法转移 422 拒绝；已遗忘的记忆不会复活 | `/memory/lifecycle/*` |
| **不可变账本** | 每次写入/更新/召回/删除留一条账目，append-only 由 SQLite 触发器强制 | `/memory/ledger/{id}` |
| **Provenance Card** | 单条记忆的来源、置信、有效期、版本链 | `/memory/governance/provenance/{id}` |

---

## 真实场景

**政务办公**：用户说"帮我继续上周的项目汇报"，系统自动召回历史文档与工作记录，无需重复说明。

**知识治理**：用户说"删除所有关于项目 A 的内容"，系统执行删除、清理关联索引、验证完整性、输出审计报告。

**长期协作**：AI 逐步了解工作习惯、项目背景、组织流程，形成专属数字助手——且这一切可审计。

## 竞赛交付

竞赛答辩入口：[competition/](competition/)

## 创新点

五项创新及其代码与证据：[docs/INNOVATIONS.md](docs/INNOVATIONS.md)

---

## 完整功能

<details>
<summary>展开查看完整技术栈与功能清单</summary>

### 快速开始

1. **启动服务**：`scripts/run_dev.ps1`（Windows）或 `scripts/run_dev.sh`（Linux/麒麟），控制台将在 http://127.0.0.1:8010/console/ 就绪。
2. **发第一段对话**：打开控制台进入「万枢工作台」，在输入框直接提问即可；未配置模型时走 local_mock 通路。
3. **配置模型接入**：进入「模型接入」视图，从供应商目录中任选一家，填入 API key 保存。OpenAI 兼容云端供应商（含 DeepSeek）与 AWS Bedrock 已接通真实调用；其余供应商在 alpha 阶段诚实标注为 stub。
4. **说「记住」生成记忆指令**：写入前经 Policy Gate 校验敏感内容；可在「记忆中枢」查看与编辑。
5. **治理演示**：运行 `python scripts/demo_governance.py --api-key <key>` 查看完整证据链。

### 部署

前置条件：Python 3.10+、Node.js 22.12+（Electron 源码构建要求；终端用户安装 deb/rpm 不需要 Node）。

```bash
# Windows
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\run_dev.ps1

# Linux / 麒麟 OS
bash scripts/setup.sh
bash scripts/run_dev.sh
```

### 记忆治理层（MemoryOS）

实现位于 `backend/app/memoryos/`（约 3.6k 行，223 个测试函数），设计与偏差说明见 [docs/MemoryOS-记忆治理层.md](docs/MemoryOS-记忆治理层.md)。

| 能力 | 端点 |
|---|---|
| MHG 事故分级（1-5 级，MHG≥3 置起发布冻结） | `/memory/governance/*` |
| 经济账本（逐条记忆的成本/收益/ROI） | `/memory/accounting/*` |
| 健康度 MHS（过期率/冲突率/噪声率聚合） | `/memory/health` |
| MEB 评测（5 类用例 × 4 维加权） | `/memoryos/bench/report` |
| MQ 能力画像（五子能力分项打分） | `/memoryos/mq` |

### 性能实测

| 项目 | 结果 | 范围 |
|---|---|---|
| 本机 SQLite FTS5 检索 | p95 为 0.8072 ms | 100 次、50 个 seed capsules、单机单进程 |
| 麒麟原生 SDK（V11 VM） | p50 195.320 ms、p95 246.473 ms | QEMU/WHPX VM 快照证据 |
| MemoryArena-Lite | 5 cases、16 assertions 全部通过 | unsafe_autonomy_rate=0.0 |

### 诚实边界

- 当前系统是单节点 alpha，不宣称企业生产级、多副本高可用或 SLA。
- 成本金额是估算不是实测（token 数按字符数 × 0.3 粗估）。
- precision@5 无实跑报告时为 `null`，不用占位值填满仪表盘。
- MEB 当前只有公开集，pass_rate 1.0 是本仓自建用例集成绩，不是公开赛题成绩。
- 梦境归档仅支持手动触发，无每夜调度。
- 原生 Kylin 检索在 SDK 不可用时回退 FTS5。

### 安全边界

- 回环免密默认**只读**（GET/HEAD 放行），写操作必须带 key。
- Origin/Host 校验阻断 CSRF 与 DNS-rebinding。
- SSRF 防护与代理共存，pinned-IP 白名单控制出向。
- 自动化工作流按执行档位分级：human_review（默认）/ sandbox / device。

### 许可证

本项目采用**木兰宽松许可证 第2版（Mulan PSL v2）**。

</details>

---

## 文档中心

[根目录文档中心](文档中心_DOCUMENTATION_HUB.md)是历史合集与分类索引；当前竞赛交付见 [competition/](competition/)，技术创新见 [docs/INNOVATIONS.md](docs/INNOVATIONS.md)。

---

*宛委主藏书，枢忆主枢机。记忆可被检索、被治理、被审计。*
