# 项目探索与本机复现报告

> 调研快照：2026-07-10（Asia/Singapore）
> 上游：[QianChang-official/wan-wei--shuyi-osagent](https://github.com/QianChang-official/wan-wei--shuyi-osagent)

## 1. 项目结论

宛委·枢忆是一个以 Agent 长期记忆为主题的 alpha research prototype。它把 FastAPI、SQLite/FTS5、MemoryCapsule、策略门、证据卡、命令闭环、反思演化、轻量评测和 Vue 控制台组合为单节点 MemoryOps 演示平台。

项目的优势是概念覆盖完整、边界声明相对诚实、已有可运行主线；主要风险是平台命名与页面规模明显领先于真实实现深度，许多舱室仍是 catalog、stub、template 或 dry-run。它适合比赛演示、研究原型和架构讨论，不应直接表述为生产级自主 Agent 平台。

## 2. 上游成熟度快照

通过 GitHub 官方接口核验：

- 仓库创建于 2026-07-04，默认分支为 `main`，2026-07-10 仍有提交。
- 快照时无 Release、无 tag、无开放 Issue、无许可证文件。
- 构建后的 Vue `dist` 被纳入版本控制，因此克隆后可展示静态控制台，但源码构建仍必须安装 Node 依赖。
- CI 只覆盖 Python 3.9 的编译和少量安全测试，未覆盖 Windows、前端生产构建和完整 HTTP 闭环。

上述状态会随上游变化；发布或再分发前应重新核验许可证、Release 和 CI。

## 3. 真实架构

```text
Vue 3 / Vite 控制台
        |
        | 同源 HTTP + X-API-Key
        v
FastAPI 中间件与路由
  |- API Key / body limit / headers / rate limit
  |- MemoryCapsule + Policy Gate + Evidence + Retrieval
  |- Command Loop + Reflection + Workflow dry-run
  |- Research adoption / reproduction / deepening catalogs
        |
        v
SQLite + FTS5 + audit/workflow persistence
```

已具备可运行逻辑的核心是：记忆写入与检索、策略门、审计、工作流持久化、指挥风险分级、反思基础动作和 5-case MemoryArena-Lite。模型供应商、MCP/Skills、多设备同步、图谱召回、生产观测等多项能力仍是部分实现或设计入口。

## 4. 网络研究核验

本项目不是下列系统的源码集成或完整复现，而是把思想映射到自身 schema/API/UI：

| 参考系统 | 已核验来源 | 本项目实际吸收 |
| --- | --- | --- |
| MemoryArena | [arXiv 2602.16313](https://arxiv.org/abs/2602.16313)、[官方仓库](https://github.com/ZexueHe/MemoryArena) | 本地 5-case/16-assertion Lite runner，不是官方 benchmark 环境 |
| Reflexion | [arXiv 2303.11366](https://arxiv.org/abs/2303.11366)、[官方仓库](https://github.com/noahshinn/reflexion) | 反思/evolution 数据流与 dry-run evaluator |
| MemoryBank | [arXiv 2305.10250](https://arxiv.org/abs/2305.10250)，AAAI 2024 | retention/forgetting 概念映射，未复现完整模型 |
| HippoRAG | [arXiv 2405.14831](https://arxiv.org/abs/2405.14831)、[官方仓库](https://github.com/OSU-NLP-Group/HippoRAG)，NeurIPS 2024 | Hippo-Lite schema/route，未实现完整 PPR 检索栈 |
| MemGPT / Letta | [arXiv 2310.08560](https://arxiv.org/abs/2310.08560)、[Letta](https://github.com/letta-ai/letta) | working/active/archival tier 模板 |
| LoCoMo | [官方仓库](https://github.com/snap-research/locomo)，ACL 2024 | long-session template，未运行官方数据集评测 |
| Generative Agents | [arXiv 2304.03442](https://arxiv.org/abs/2304.03442)、[官方仓库](https://github.com/joonspk-research/generative_agents) | memory stream/reflection/planning 模板 |
| AgeMem | [官方仓库](https://github.com/y1y5/AgeMem) | memory tool dry-run 接口；未包含强化微调训练栈 |
| MemOS | [arXiv 2507.03724](https://arxiv.org/abs/2507.03724) | MemCube-like 生命周期与治理概念 |

## 5. 本机复现结果

验证环境：Windows、Python 3.14.3、Node.js 24.14.1、npm 11.16.0。

初始全量测试为 118 通过、7 失败、5 teardown 错误。失败集中在 Windows 可移植性而非核心算法：默认数据库写到用户目录、线程缓存连接未被统一关闭、POSIX `0600` 权限断言用于 Windows、测试按系统默认 GBK 读取 UTF-8 源码。

本轮完成：

- 增加 Windows 一键 setup/run/eval/smoke 脚本。
- 统一服务端口为 `8010`，补齐全部 Vite API 代理。
- 修复控制台不发送 `X-API-Key` 导致写入、审计和 workflow 401 的问题。
- 数据库使用平台数据目录，并可统一关闭所有 FastAPI 工作线程的 SQLite 连接。
- 应用启动不再吞掉数据库初始化异常。
- 移除原作者私有 WSL/模型路径默认值；真实模型必须显式配置。
- 校正 MemoryBank、HippoRAG、LoCoMo 的发表状态，并在控制台提供来源链接。

最终验证命令和结果以当前工作区的 `git diff`、pytest 输出、前端构建和 `scripts/smoke.ps1` 为准。

最终实测结果：

- `scripts/setup.ps1` 完整执行成功。
- pytest：130 passed，1 skipped；跳过项是 Windows 不具备 POSIX `0600` mode bit 语义。
- Vue/Vite：84 modules transformed，生产构建成功；`npm audit` 为 0 vulnerabilities。
- MemoryArena-Lite：5 cases、16/16 assertions，通过率 1.0，unsafe autonomy rate 0.0。
- HTTP smoke：控制台、401 防护、鉴权、记忆写入、连字符检索和 workflow run 全部通过。

## 6. 后续优先级

1. 补许可证、Release/tag、SBOM 与 GitHub/Gitee CI 矩阵。
2. 为 API 增加版本化路由、统一错误模型和 OpenAPI 契约测试。
3. 把内存限流替换为共享存储实现，补多进程/并发/断电恢复测试。
4. 选择一个研究方向做真实基线对照；优先 FTS5 vs HippoRAG-like recall，而不是继续增加页面。
5. 用官方 LoCoMo/MemoryArena 子集建立可复现实验，分开报告 synthetic assertion 与生产任务成功率。
6. 若进入真实部署，迁移密钥管理、日志脱敏、备份恢复和数据删除证明流程。
