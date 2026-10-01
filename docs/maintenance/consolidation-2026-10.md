# 2026-10 主线整合与拆仓记录

## 基准与范围

- 盘点基准：`main@47c1f0a78a75f9ab7e3a4611c79fca5fa1be61b3`，2026-10-02 本地时间。
- 全量枚举得到 9 个上游分支（含 main）；fork PR 不算上游分支，也不属于本次删除权限范围。
- 原本地 detached checkout 的 staged、unstaged、untracked 三层共 79 个改动路径已分别备份并校验还原。开发在独立整合 clone 中进行，不覆盖原工作区。
- 情感／记忆核心与研究拆入私有 `QianChang-official/wanwei-affect-memory`；其三端 SDK 测试与本项目的 UI／系统集成验证分别记录，不能互相替代。

## 分支内容账本

下列“已包含”描述内容关系，而非 `git branch --merged` 的图关系。Squash 合并后源分支仍可能显示 ahead，不能据此重复合并。

| 分支 | 原 tip | 内容处理 |
|---|---|---|
| `chore/bench-close-conn` | `e8972ffe9d84b2ab67e78a470acdd94f78d1dde9` | #238 → `b180f54`，补丁等价；已包含 |
| `fix/audit-conn-identity` | `d79e30399bb4e22bb7695651e4b05ab388d40dd7` | #239 → `c494ccf`，补丁等价；已包含 |
| `fix/forget-held-conn-identity` | `34a1170a513c19442e465767620c8117cddcf44d` | #240 → `639ae24`，补丁等价；已包含 |
| `fix/rate-limit-shared-bucket` | `2ddaf54c9849dbfdc7889da27f1b42d4fa9fdfe9` | #237 → `b0bcc33`，补丁等价；已包含 |
| `fix/release-sarif-permission` | `a0525b888235422df91e42a9e48cc38c88b41916` | #230 → `76af1e8`，聚合补丁等价；已包含 |
| `fix/image-pcre2-upgrade` | `f4d5f55a50e73efd901cd9354ff0815512782f91` | #232 被 #230 的升级＋fail-closed 版本断言覆盖；不恢复较弱实现 |
| `fix/forget-confirm-nested-conn` | `7d5983e4332199df06edebdcbe061540de0af160` | #233 被后续连接／身份／遗忘／限流修复覆盖；14 个触及文件中 7 个与基准相同，其余为主线加强 |
| `dependabot/npm_and_yarn/desktop/npm_and_yarn-63204e99f0` | `1e2e00d83f94d8ceec17137b29777542404025bb` | #244 Electron 43.2→43.5；有独有有效内容，等待正常审核合并，不提前删除 |

### 恢复与删除条件

以上 8 个非 main 分支的精确 tip 均已发布为：

```text
archive/consolidation-2026-10/<原分支名>
```

归档 tag 已逐一用远端 peeled SHA 校验。离线 `archived-refs.bundle` 已通过 `git bundle verify`，SHA-256：

```text
34bed9043118f1e0e8ef70e73d80a49f486b49fb9fb82335ff7c629de39bdfc7
```

本次批准明确用 tag／SHA 清单／本地 bundle 替代 #232/#233 原“保留分支供追溯”的做法。标签不是密码学意义的不可变对象；不重写标签，并保留离线副本。删除前仍须重查完整 tip、内容落点和未决 PR，新提交出现就停止该分支清理。

恢复示例（在授权且需要恢复时手动执行，不自动运行）：

```sh
git fetch origin --tags
git branch recovered-branch archive/consolidation-2026-10/fix/audit-conn-identity
# 如远端归档不可用，先从保留的 bundle 获取相应引用并校验 SHA。
```

**本文件中的归档记录不代表分支已删除。**实际删除结果以最终交付清单和实时 refs 为准；main、未合并有效分支及 fork 分支保留。

### PR #243 与版本标签

- fork `aAutumnMaples/wan-wei--shuyi-osagent:feat/ky11-deploy-local`，盘点 head `f4e953584b543265f458ff23d2e5f6c90b0fb0f1`：sidecar／adapter、启动器、案例及测试修复有用。
- 已有代码审核与 CI 不替代所要求的 ky11 SDK 编译、health/chat、断连重连实测。本次已知 VM 入口不可连接，未伪造实机通过证据，不删除 fork 分支。
- 保留 `v1.0.0`、`v0.11.0` 原指向。`v0.11.0` 含 main 不可达历史；旧 tag 构建不会自动包含 main 后续 Docker 修复。不移动标签，不以简单重跑冒充修复后的发布。

## UI／新功能能力对照

| 能力 | 入口／行为 |
|---|---|
| 新三栏会话、Agent 编辑、设置 | `/console/#/` |
| 原完整导航 | `/console/#/advanced` |
| 团队、子代理、独立编排 | `/console/#/platform/agents` |
| 会话与模板、知识、记忆中心 | 原 `/platform/sessions`、`/platform/knowledge`、`/platform/memory` 前端路由 |
| 审计、治理、导出 | 原 `/audit`、`/governance`、`/exports` 前端路由 |
| OAuth／辅助模型、系统设置 | 原 `/platform/providers`、`/platform/settings` 前端路由 |
| 手机入口 | `/console/#/mobile`，原页面保留；桌面发布清理仍只修改 staging |

原 32 个页面保留，不以删除功能或测试换取重构通过。流式对话的过程事件、终态、断流、取消与确认分别处理；工作档位、深度和 Agent 模型绑定由后端实际消费。续聊只引用服务端验证过的同身份／同 Agent 成功 run；不把任意浏览器历史提升为系统指令。

新工具默认保守：每次副作用有权限检查和精确操作确认，审批与 actor/run/有效期绑定，拒绝与取消不自动重试。私有工作目录限制文件访问，但不假称是进程沙盒。旧非流式工作台默认只读，避免返回无人能够操作的审批票据。

## 验证记录（整合工作树）

- 干净基准后端：**1925 passed、11 skipped**。第一次额外强制 native=off 导致 3 个原生配置测试失败；撤去该不适用的全局覆盖后通过，未修改测试来掩盖失败。
- 当前公开后端（无私有 SDK／无可选工具包）：**2040 passed、15 skipped**。其中新增 skip 包括可选库、私有包与 Windows 无符号链接权限；不是声称这些路径已执行。
- 实际可选 pydantic/OpenAI 库的离线网络替身／临时目录安全与协议回归：Python 3.10、3.11 各 **142 passed**，不调用真实模型或执行宿主命令。
- 前端：生产构建通过，安全 **3/3**、原契约 **57/57**、真实 Vue/jsdom 交互 **22/22**；干净 npm ci 完成，升级到已修复 Vitest 4.1.11 后 npm audit **0 漏洞**。
- 新 RPM：**45 passed、2 skipped**；实际源码 payload 解包后的 import、ASGI lifespan、health/readiness、静态控制台和研究案例验证通过。未把此结果冒充 Linux RPM 安装或 systemd 实测。
- 原桌面测试入口通过（6 个 Node 测试条目，其中旧脚本包含 25 项内部检查）。发布 staging 清理已适配 `AdvancedLayout.vue`，保留两种 Git 换行配置的回归。
- 浏览器曾实际完成后端 health、鉴权设置、Agent 创建、消息发送与真实“网关未配置”反馈，并查看渲染截图；无真实模型凭据。发现的启动脚本／字体 CSP 问题改为同源脚本与本地字体回退，没有放宽 CSP。
- 私有 SDK 的独立 review、wheel、研究与三系统 CI 结果记录在其仓库；不将公开应用的测试数算入 SDK。

## 合并纪律

按主题拆分，遵守每 PR 50 文件／5000 增删行门禁。main 的一次有效 review 保留；未获审核不 admin bypass、不直接 force-push、不削弱保护。堆叠 PR 在其依赖进入 main 后按顺序复核／重定向；对非 main 基分支用现有 workflow_dispatch 运行完整 CI，而非把“没有自动触发检查”当成通过。

变更回退使用 revert 或关闭可选 SDK 接入；不自动重写主线历史，不自动回滚／迁移真实用户数据库。
