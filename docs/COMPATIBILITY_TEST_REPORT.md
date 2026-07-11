> 项目：宛委·枢忆 OSAgent  
> 版本：v0.10.0-delivery-hardening

# 兼容性与适配测试报告

## 范围说明

本报告中的 `vm_verified` 仅表示在本地 QEMU/WHPX 虚拟机中实际观察到的
结果，不构成物理目标硬件、OCR 或生产环境认证。官方 embedding 与向量
数据库开发包已在该 VM 中安装和验证；原始输出位于
`reports/kylin-native-sdk-evidence/`。

## 测试环境

- 测试日期：2026-07-11
- 安装镜像：`Kylin-Desktop-V11-2603-Release-20260228-X86_64.iso`
- 镜像 SHA-256：`9D00C0C605E023AA879D895E3AA430D1DFD3EAFDED6273CF297BC1874F9A29C4`
- 虚拟化：Windows QEMU 11，WHPX 加速，`q35` / `qemu64`
- VM 配置：8 vCPU、16 GiB RAM、120 GiB 动态 qcow2 虚拟磁盘
- 存储边界：仅格式化 `C:\VMs\Kylin-V11\kylin-v11.qcow2`；未修改安装 ISO
- 网络配置：QEMU user-mode NAT，`e1000e` 虚拟网卡；通过麒麟软件源安装官方包
- 客体状态：使用系统维护模式安装包并保存变更，重启后在 `Normal Mode` 复验
- Git 基线：`9f5c9e4f73befe77cd7c078ed689d6445cea7c28`；证据包记录的是审阅前 VM 源码快照，不能替代对最终合并提交的 VM 复验。

## 已验证结果

| 项目 | 结果 | 观测证据 |
| --- | --- | --- |
| 安装镜像启动 | `vm_verified` | Kylin V11 Live Desktop 成功启动，并打开图形安装器。 |
| 全盘安装 | `vm_verified` | 安装器识别专用 VirtIO 磁盘 `/dev/vda`，按全盘安装流程创建系统与 swap 分区，并完成系统写入。 |
| 安装器收尾 | `vm_verified` | 安装进度到达收尾脚本和 initramfs 配置阶段，安装器随后退出并触发重启。 |
| 从虚拟磁盘启动 | `vm_verified` | 以 `scripts/start_kylin_vm.ps1 -Mode boot` 启动后出现 Kylin 首次启动初始化界面，而非 ISO Live Desktop。 |
| 图形登录 | `vm_verified` | 首次启动完成后出现登录界面，并成功进入 Kylin 图形桌面。 |
| 账户保留名处理 | `vm_verified` | 安装器拒绝 `root`，提示其为系统保留用户；最终登录界面显示可用本地账户 `wanwei`。 |
| QMP 输入通道 | `vm_verified` | QMP 限制在 `127.0.0.1:5959`；文本、Tab、回车和退格按键均已用于完成安装器表单和登录验证。 |
| 官方 SDK 包 | `vm_verified` | `libkylin-coreai-embedding-dev=1.2.0.0-0k0.4`、`libkysdk-vector-engine-client-dev=1.2.0.0-0k1.1`，另含官方 runtime、模型与引擎依赖。 |
| Bridge 编译与信任 | `vm_verified` | CMake 配置/构建成功；`/usr/local/bin/wanwei-kylin-sdk-bridge` 在 KYSEC 中为 `verified`。 |
| 普通模式持久化 | `vm_verified` | `mm-cli -s` 为 `Normal Mode`；SDK 包、Bridge、向量服务和 KyTensor 重启后仍可用。 |
| embedding probe | `vm_verified` | 官方模型 `ensemble-embd_gte-base_uint8-text` 返回 768 维向量；Bridge probe 同时连接向量数据库。 |
| `/kylin/sdk/status` | `vm_verified` | `backend=kylin_native`、`available=true`、覆盖率 2/2、failed/pending 均为 0。 |
| Capsule 原生写入 | `vm_verified` | 三条测试 Capsule 均返回 `native_index.backend=kylin_native`。 |
| 非关键词语义检索 | `vm_verified` | 精确 FTS 查询为 0 命中，原生向量检索将预期 Capsule 排在第 1。 |
| 精准遗忘与向量删除 | `vm_verified` | 本地 Capsule/FTS/票据/审计/删除意图原子提交；目标生命周期变为 `forgotten`、FTS 行为 0、原生向量映射为 `deleted`，幂等重放一致且再次语义检索未召回。 |
| 崩溃恢复与并发 fencing | `host_verified` | generation-aware CAS、每代独立 vector ID、持久 tombstone 和有界 sweeper 的写入/遗忘崩溃、stale lease 接管及回放测试已纳入全量回归；真实 SDK 正常链路复验通过。 |
| 历史重建 | `vm_verified` | 关闭原生链路创建的两条历史数据从 0/2、pending=2 重建到 2/2、failed=0。 |
| 热态检索延迟 | `vm_verified` | VM loopback 30 次原生 HTTP 检索：p50 195.320 ms、p95 246.473 ms、最大 278.624 ms；不含 1 次 warmup。 |
| 后端回归 | `snapshot_verified` | 审阅前快照在主机为 207 passed、1 skipped，Kylin VM 为 208 passed、1 个已知依赖弃用 warning；最终合并提交仍需在目标 VM 复验。 |

## 尚未验证

| 项目 | 状态 | 后续证据 |
| --- | --- | --- |
| NAT、DNS、HTTPS 与软件源可达性 | `pending` | 记录接口地址、DNS 查询和 HTTPS 请求结果。 |
| 前端依赖安装与生产构建 | `pending` | 运行 `npm --prefix frontend/console-vue ci` 和生产构建。 |
| MemoryArena-Lite、审计、备份恢复与安全回归 | `pending` | 按 `docs/KYLIN_VM_TEST_PLAN.md` 记录命令、输出和结论。 |
| OCR SDK | `sdk_pending` | 本轮只验证官方 embedding 与向量数据库 SDK，没有安装或测试 OCR SDK。 |
| 目标硬件认证 | `target_hardware_pending` | 需要在指定的物理麒麟目标环境复测。 |

## 证据索引与判定边界

- 证据目录：`reports/kylin-native-sdk-evidence/README.md`
- 正常模式复验：`normal-mode-verification.txt`、`normal-mode-api.txt`、`backend-normal.log`
- 原始功能记录：`write-*.json`、`semantic-search.json`、`forget-delete.json`、`history-*.json`
- 性能原始记录：`latency.json`
- 审阅前源码快照全链路：`final-current-source-acceptance.json`
- 审阅前源码快照回归：`pytest-backend-final-audit-closed-host.txt`、`pytest-backend-final-audit-closed-vm.txt`
- 完整性清单：`SHA256SUMS`

本轮 VM 快照证明的是 x86_64 QEMU/WHPX VM 上的官方 SDK 兼容性，不证明物理硬件、
LoongArch/ARM 架构、大规模数据、长时间稳定性或生产 SLA。向量删除证据来自
实际存在的 collection；代码同时把厂商返回 `deleted=false` 的情况保留为
`delete_pending`，并以 generation fencing 与永久 tombstone 恢复 late upsert，
不会把未确认删除写成成功。VM 运行时为 1.3.0；Bridge 针对
旧 runtime 协议的兼容分支未在旧版运行时上实测，仍需对应版本的 vendor smoke。
最终合并提交的 VM 验收仍须以其精确源码哈希重新构建、重跑 probe 和验收记录。
