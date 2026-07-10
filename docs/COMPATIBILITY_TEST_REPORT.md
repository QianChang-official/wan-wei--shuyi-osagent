> 项目：宛委·枢忆 OSAgent  
> 版本：v0.2（含 SOTA 对标、记忆安全、自演化与评测增强）  

# 兼容性与适配测试报告

## 范围说明

本报告中的 `vm_verified` 仅表示在本地 QEMU/WHPX 虚拟机中实际观察到的
结果，不构成麒麟目标硬件、厂商 SDK、OCR、embedding 或生产环境认证。

## 测试环境

- 测试日期：2026-07-11
- 安装镜像：`Kylin-Desktop-V11-2603-Release-20260228-X86_64.iso`
- 镜像 SHA-256：`9D00C0C605E023AA879D895E3AA430D1DFD3EAFDED6273CF297BC1874F9A29C4`
- 虚拟化：Windows QEMU 11，WHPX 加速，`q35` / `qemu64`
- VM 配置：8 vCPU、16 GiB RAM、120 GiB 动态 qcow2 虚拟磁盘
- 存储边界：仅格式化 `C:\VMs\Kylin-V11\kylin-v11.qcow2`；未修改安装 ISO
- 网络配置：QEMU user-mode NAT，`e1000e` 虚拟网卡；连通性尚未验证

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

## 尚未验证

| 项目 | 状态 | 后续证据 |
| --- | --- | --- |
| 内核、Python、SQLite、Node 和 npm 版本 | `pending` | 在已登录 VM 中执行并记录版本命令。 |
| NAT、DNS、HTTPS 与软件源可达性 | `pending` | 记录接口地址、DNS 查询和 HTTPS 请求结果。 |
| 后端安装、启动、健康检查和 smoke 测试 | `pending` | 运行 `bash scripts/setup.sh`、服务启动、`/health/ready` 与 `bash scripts/smoke.sh`。 |
| 前端依赖安装与生产构建 | `pending` | 运行 `npm --prefix frontend/console-vue ci` 和生产构建。 |
| MemoryArena-Lite、审计、备份恢复与安全回归 | `pending` | 按 `docs/KYLIN_VM_TEST_PLAN.md` 记录命令、输出和结论。 |
| Kylin SDK、embedding SDK 和 OCR SDK | `sdk_pending` | 需要已安装、已授权的对应厂商组件。 |
| Kylin embedding/vector native Bridge | `sdk_pending` | Bridge 源码、默认优先路由与 FTS 后备已进入仓库；尚未在 Kylin VM 安装官方开发包并完成编译和 smoke。 |
| 目标硬件认证 | `target_hardware_pending` | 需要在指定的物理麒麟目标环境复测。 |
