# 情感／记忆 SDK 的独立维护与显式接入

核心 SDK 与研究工具维护于私有仓库 **QianChang-official/wanwei-affect-memory**。本公开项目仍可独立安装、构建、测试和发布：默认不导入、不下载该私有包，也不要求私有 GitHub 凭据。

## 三个边界，不自动合并

| 路径 | 存储／职责 | 本次行为 |
|---|---|---|
| 现有 `/memory/v2`、情感与 MemoryOS 接口 | OSAgent 的 SQLite 胶囊引擎及原应用 schema | 保留公共实现和兼容行为 |
| 控制台的 `/platform/memory` 相关能力 | platform JSON 记忆中心 | 保留原行为，不暗中接入 SDK |
| 可选 `/memory/sdk` | 独立 SDK schema、独立 SQLite 文件、显式 owner/soul | 安装且显式启用后才可用 |

SDK 不是旧数据库的就地升级器。**不得把 `WANWEI_MEMORY_SDK_DB` 指向已有 OSAgent 数据库**，也不要复制旧表、双写两边或靠安装包自动切换引擎。数据迁移需要单独的备份、映射和迁移验证；本次没有执行用户数据迁移。

## 接入条件

1. 在运行后端的虚拟环境安装经过审核的本地 SDK wheel。例如：
   ```sh
   python -m pip install /absolute/path/wanwei_affect_memory-0.1.0-py3-none-any.whl
   ```
   wheel 由有权限访问私有仓库的维护者构建；本项目不会从私有地址自动下载。
2. 显式配置：
   ```sh
   export WANWEI_MEMORY_SDK_ENABLED=1
   export WANWEI_MEMORY_SDK_DB=/absolute/path/isolated-sdk-memory.db
   ```
   Windows 使用同名进程环境变量和本机绝对路径。不要把示例路径原样用于生产。
3. 当前适配器要求 SDK `API_VERSION="1"`、`SCHEMA_VERSION=1`，并提供 `MemoryEngine`。版本不符、缺包或配置错误会明确失败，不会在失败的写入之后回退至旧引擎。
4. 关闭时设置 `WANWEI_MEMORY_SDK_ENABLED=0` 或不设置。已存在的 SDK 数据文件保留；关闭不删除数据。

启用检查发生在后端启动工作线程之前；每个 SDK 操作创建独立的作用域实例并关闭连接，不缓存跨身份引擎。SDK 数据目录的 ACL、备份和磁盘加密由部署者管理；Windows 的 POSIX mode 位不等于完整 ACL 防护。

## 公开适配接口

所有接口仍经过现有应用鉴权。除状态接口外，必须明确给出当前身份拥有的 `soul_id`；客户端不能传入或覆盖 `owner_id`。

- `GET /memory/sdk/status`：启用状态、SDK/API/schema 版本；不返回数据库路径、密钥或其他身份信息。
- `POST /memory/sdk/capsules`：使用原胶囊写入字段，额外要求 `soul_id`，拒绝未知字段。写入策略、账本和事务由 SDK 执行。
- `GET /memory/sdk/capsules?soul_id=...&limit=50`：当前作用域的可见胶囊。
- `GET /memory/sdk/capsules/{id}?soul_id=...`：不存在或跨作用域均返回 404。
- `GET /memory/sdk/search?q=...&soul_id=...&top_k=5&high_risk=false`：返回 `query`、`retrieval`、`results` 与明确的 SDK namespace。

未启用时状态返回 `enabled:false`，SDK 数据接口返回 `memory_sdk_disabled`。显式启用却无法使用时返回配置错误／503，不伪装正常空结果。响应复用应用的胶囊脱敏，移除内部 owner 标识。

**未新增一步式 HTTP 遗忘入口。** 原应用继续使用既有预览／确认遗忘流程；独立 SDK 的 `forget`、生命周期、偏好／知识演化和情感 API 供明确授权的 Python 宿主调用。不能把 SDK 的底层事务接口当成不可信插件的安全沙盒。

## 维护与验证

- 公共算法基线来自主线 `47c1f0a78a75f9ab7e3a4611c79fca5fa1be61b3`；后续 SDK 算法演进在私有仓库进行。公共基线继续必要的兼容和安全维护。
- 私有到公开的代码同步须单独审核；不自动把私有研究、数据或新增实现推回公开仓库。
- `backend/app/tests/test_memory_sdk_adapter.py` 在未安装私有包时验证禁用、缺依赖、版本、路径、HTTP 鉴权、作用域和关闭连接契约。共享记忆契约对公共基线运行；安装 SDK 时还对真实 SDK 运行，未安装时该分支明确 skip。
- SDK 自身负责三系统、安装后 wheel、算法／生命周期／研究工具的测试；公开应用的 UI、权限和原数据库回归仍在本仓验证。
- SQLite capsule 引擎、JSON 记忆中心和 SDK 的评分／ID／schema 不是可以无条件互换的数据格式。研究结果也不能直接证明控制台聊天或麒麟 native 后端已经完成验证。

原代码保持 Mulan PSL v2 许可。私有仓库的可见性不会撤销已经公开代码的许可；源文件映射、原 revision、第三方来源和实验限制随抽取材料保留。
