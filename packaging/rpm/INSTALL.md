# 宛委·枢忆 控制台 RPM 安装教程

适用包名：`wanwei-shuyi-1.0.0-1.noarch.rpm`。版本未变更，本文不代表已发布或已通过目标系统安装验证。

## 1. 边界与前置条件

- 这是 **source-only noarch** 包：Python 源码、公共研究用例、构建后的 Vue 静态资源、启动脚本和桌面入口。
  不含 venv、Python wheels、原生 SDK、模型、数据库、密钥或原始评测证据。
- `noarch` 只描述本 RPM 的内容；**不保证 x86_64 / ARM64 / LoongArch 等平台均有可用二进制依赖**。
  wheels 必须匹配目标 CPU、Python ABI 和 Linux/glibc。原生 SDK 未随包提供，相应能力不可据此宣称可用。
- 需要可写的标准 RPM 系统布局、systemd（支持 `StateDirectory`，通常 235+）、Python **3.10+**、
  `venv`、`ensurepip`、curl 和 runuser。请通过系统供应商渠道先行配置；**不假定麒麟 V10 预装了适配的 Python**。
- 服务使用无登录权限的 `wanwei-shuyi:wanwei-shuyi` 系统账户，不是 root，也不是当前桌面用户。
  `ProtectSystem=strict`、`ProtectHome=true`、`PrivateDevices=true`、空 capability 集及设备操作关闭是有意的边界。
  **不能控制登录用户桌面、访问其 home、进行系统管理或执行真实设备档动作**。
  RPM 不提供桌面会话代理；不要以 root 运行后端来绕过这些限制。

## 2. 安装源码，然后显式配置依赖

```bash
sudo rpm -ivh wanwei-shuyi-1.0.0-1.noarch.rpm
```

安装只放置文件、创建专用系统账户并刷新 systemd/桌面缓存，**不会自动联网、运行 pip、启用或启动服务**。
配置文件 `/etc/wanwei-shuyi/environment` 是 root-only 0600、RPM `%config(noreplace)` 文件，不放凭据。
若旧部署在 `/etc/systemd/system/wanwei-shuyi.service` 或 drop-in 留有 unit 覆盖，先用 `systemctl cat wanwei-shuyi` 检查。
这些覆盖优先于本包 `/usr/lib/systemd/system` 的安全 unit；管理员须备份并显式迁移，确认 `User=wanwei-shuyi` 和 wrapper 生效后再启动。
包不会删除管理员的 unit 覆盖，也不会自动修正旧 root 服务。

依赖安装二选一，由管理员显式运行（脚本内部把 Python/venv/pip 降权至专用账户）：

```bash
# 联网：只用 PyPI 一个索引，无镜像回退
sudo /opt/apps/wanwei-shuyi/bin/install-deps.sh --online
# 或由管理员批准的一个 HTTPS 索引（不允许 URL 内嵌账号密码）
sudo /opt/apps/wanwei-shuyi/bin/install-deps.sh --online --index-url=https://approved.example/simple

# 离线：预先准备目标平台完整 wheels；目录及文件须允许专用账户遍历和读取
sudo /opt/apps/wanwei-shuyi/bin/install-deps.sh --wheelhouse=/srv/wanwei-wheelhouse
```

脚本使用 `--only-binary=:all:`，不现场编译源码包。离线模式使用 `--no-index`，禁用继承的 pip 配置和额外索引；
`requirements.txt` 仅允许精确包版本，不允许直接 URL 或嵌套索引选项。
缺 Python/ensurepip/匹配 wheel、网络或 pip 失败均返回非零，**不会下载 bootstrap、不删除失败的 venv、不启动服务**。
虚拟环境位于 `/opt/apps/wanwei-shuyi/venv`。失败后保留现场，管理员检查、显式修复后重试；不要忽略失败继续启动。
依赖配置不是锁定供应链证明：上线前仍应审查索引、wheel 来源和依赖版本。

## 3. 显式启用及验证

```bash
sudo systemctl enable --now wanwei-shuyi.service
systemctl status wanwei-shuyi.service
curl --noproxy '*' --fail http://127.0.0.1:8010/health/ready
journalctl -u wanwei-shuyi.service -e
```

服务始终绑定 `127.0.0.1`，默认端口 8010。浏览器打开 `http://127.0.0.1:8010/console/`，
或使用应用菜单入口。启动器仅检查 readiness，**失败时明确报错，不会调用 sudo、拉起服务或打开假成功页面**。
终端可直接执行 `/opt/apps/wanwei-shuyi/bin/wanwei-shuyi` 查看错误信息。

自定义端口：管理员修改 `/etc/wanwei-shuyi/environment` 的 `WANWEI_PORT=8011`，再显式重启服务。
端口必须为无前导零的十进制 1–65535；非特权服务通常不能绑定 1024 以下端口。
桌面用户不可读取该保护文件，启动器需显式传入相同值：

```bash
WANWEI_PORT=8011 /opt/apps/wanwei-shuyi/bin/wanwei-shuyi
```

自定义端口的菜单入口可复制系统 `.desktop` 到用户的 `~/.local/share/applications/`，
把 `Exec` 改为 `/usr/bin/env WANWEI_PORT=8011 /opt/apps/wanwei-shuyi/bin/wanwei-shuyi`。
不要把配置文件当 shell 脚本 source；更改服务端口不会自动更改桌面会话环境。

## 4. 状态、身份与首次访问

`StateDirectory=wanwei-shuyi` 由 systemd 创建 `/var/lib/wanwei-shuyi`（0700），同时作为 `HOME` 和 `WANWEI_DATA_DIR`。
SQLite 默认在该目录下；`WANWEI_PLATFORM_DIR=/var/lib/wanwei-shuyi/platform` 保存 JSON 配置，
`WANWEI_API_KEY_FILE=/var/lib/wanwei-shuyi/api-key` 保存身份密钥，统一落在同一受保护状态树。
启动 wrapper 首次排他创建 0600 密钥，后续重启不重建；已有空文件/符号链接会报错，不静默覆盖。

管理员读取密钥并通过可信本地途径交给授权控制台用户：

```bash
sudo cat /var/lib/wanwei-shuyi/api-key
```

在控制台设置中保存访问密钥，然后配置模型服务商。不要把 API key 粘贴到日志、工单、构建输入或环境示例文件。
此服务账户的身份与原先 root/桌面个人部署不同；若迁移已有数据，应先停止两端服务并备份，
由管理员将数据库、平台 JSON、API key 和相关加密材料作为整体迁移，校验专用账户权限。包不会自动猜测或迁移旧路径。

## 5. 升级与卸载

升级前显式停止服务并备份 `/var/lib/wanwei-shuyi`，安装更新、检查 `.rpmnew` 配置并重新运行依赖步骤，
验证成功后再显式启动。脚本不自动重启正在运行的服务；不要在运行中更新 venv。
卸载使用 `sudo rpm -e wanwei-shuyi`，会停止并禁用服务。
**状态、API key、系统账户/组和管理员创建的 venv 均保留**，避免数据或身份丢失；需要清理时单独备份并人工处理。
修改过的配置由 RPM 按 noreplace/rpmsave 语义处理，不是业务数据备份。

## 6. 构建与验证范围

先在仓库中完成正常的 Vue dist 构建（本脚本不自动安装 npm 依赖），再执行：

```bash
python3 packaging/rpm/assemble_payload.py --output /tmp/wanwei-shuyi-1.0.0.tar.gz
bash packaging/rpm/build-rpm.sh /tmp/wanwei-shuyi-1.0.0.tar.gz
# 或省略参数，自动从当前检出装配 payload
bash packaging/rpm/build-rpm.sh
```

装配器使用路径 allowlist，要求非空 dist/index.html 和 JS，拒绝符号链接/路径逃逸。
压缩时间、tar 顺序/权限/属主固定，`MANIFEST.json` 记录每个载荷文件的 SHA-256、大小、模式；已有输出不覆盖。
构建器验证提供的 payload，在新的 mktemp 目录中使用系统原生 rpmbuild，成功/失败都保留该目录；不删除旧构建、不发布产物。
manifest 仅用于内容核对，不是签名或来源认证。

麒麟 V11 ostree/不可变系统应先确认系统供应商支持的安装方式；不要导入外来发行版 rpmbuild/共享库强行安装。
**解包不等于 RPM 安装**，不会验证账户、权限、脚本、systemd 或桌面集成；不提供“等价安装”的解包捷径。
开发调试若从应用 `backend` 目录使用同级虚拟环境，路径是 `../venv/bin/python`，不是 `../../venv/bin/python`。
Windows 上通过 Python 合约测试和 `bash -n` 只证明这些检查通过，不能据此声称 Linux RPM 安装或 smoke 验证通过。
