# 宛委·枢忆 控制台 RPM 安装教程

适用包：`wanwei-shuyi-1.0.0-1.noarch.rpm`（noarch，x86_64 / arm64 / loongarch64 通用）

---

## 1. 前置条件

| 项 | 要求 | 说明 |
|---|---|---|
| 系统 | 银河麒麟 V10（RPM 系）或其他 RPM 系 Linux | 麒麟 V11 桌面 ostree 版见文末「附注」 |
| Python | 3.10+（`python3 --version`） | 麒麟 V10 自带，无需另装 |
| 网络 | 能访问 pip 镜像站 | 安装时自动下载依赖；离线/内网见第 3 节换源 |
| 权限 | root 或 sudo | rpm 安装与 %post 脚本均以 root 执行 |

## 2. 安装（一条命令）

```bash
sudo rpm -ivh wanwei-shuyi-1.0.0-1.noarch.rpm
```

安装过程会自动完成以下事情（无需人工干预）：

1. 把后端源码与「花朝台」控制台放到 `/opt/apps/wanwei-shuyi/`；
2. 创建 Python 虚拟环境 `/opt/apps/wanwei-shuyi/venv`，**自动联网**从镜像站下载全部依赖
   （默认顺序：清华镜像 → 阿里云镜像 → PyPI 官方源）；
3. 注册并启动 systemd 服务 `wanwei-shuyi.service`；
4. 安装桌面入口与图标（应用菜单出现「宛委·枢忆 控制台」）。

> 依赖下载通常 1–3 分钟。若某个镜像站不可达会自动换下一个，全部不可达才会报错中止——
> 此时软件本体已落盘，修好网络后执行 `sudo bash /opt/apps/wanwei-shuyi/bin/install-deps.sh` 即可续装。

## 3. 换源（内网 / 指定镜像）

```bash
sudo WANWEI_PIP_INDEX=https://你的内网镜像/simple rpm -ivh wanwei-shuyi-1.0.0-1.noarch.rpm
```

## 4. 验证安装

```bash
systemctl status wanwei-shuyi          # 应为 active (running)
curl http://127.0.0.1:8010/health      # {"status":"ok",...,"version":"v1.0.0"}
```

然后二选一打开控制台：

- 浏览器访问 **http://127.0.0.1:8010/console/**
- 或在应用菜单点「宛委·枢忆 控制台」（会自动拉起服务并打开页面）

## 5. 首次使用（两步）

**① 填入访问密钥**（后端安全策略：本机读免密、写操作需密钥）：

```bash
sudo cat /root/.config/wanwei-shuyi-desktop/api-key
```

把输出的密钥粘贴到控制台左下角「设置 → 通用 → 控制台访问密钥」，保存。
（密钥是首次启动自动生成的 0600 文件；只存在本机。）

**② 配置模型服务商**：「设置 → 模型接入」任选一个服务商（如 DeepSeek），
填入端点、模型名、密钥，保存后点「测试」显示 `✓ 连通正常` 即完成。
回到主界面点「＋ 新智能体」，创建后就能对话了。

## 6. 升级与卸载

```bash
sudo rpm -Uvh wanwei-shuyi-1.0.0-1.noarch.rpm   # 升级
sudo rpm -e wanwei-shuyi                        # 卸载
```

卸载会停止服务、移除程序与虚拟环境；**业务数据保留**在 `/var/lib/wanwei-shuyi/`，
需要彻底删除时再手动 `sudo rm -rf /var/lib/wanwei-shuyi`。

## 7. 故障排查

| 现象 | 处理 |
|---|---|
| `error: Failed dependencies: python3` | 先装 python3：`sudo yum install python3 curl`（或麒麟软件商店） |
| %post 依赖下载失败 | 修网络后 `sudo bash /opt/apps/wanwei-shuyi/bin/install-deps.sh` |
| 服务起不来 | 看日志：`journalctl -u wanwei-shuyi -e` |
| 8010 被占用 | 改端口：`sudo systemctl edit wanwei-shuyi`，加 `Environment=WANWEI_PORT=8011`，重启服务 |
| 控制台创建智能体报 401 | 第 5 节①：密钥未填或填错 |
| 对话报「模型网关未就绪」 | 第 5 节②：服务商未配置或测试未通过 |

## 附注：麒麟 V11 桌面（ostree）的特殊说明

V11 桌面版 `/usr` 为只读 overlay，标准布局中的 `/usr/share/applications` 与图标无法写入，
**不建议直接 `rpm -i`**。可先解包体验（等价于安装）：

```bash
# 若系统没有 rpm2cpio：apt-get download rpm rpm2cpio && dpkg-deb -x rpm*.deb /tmp/rpm-tools
# 然后用 /tmp/rpm-tools/usr/bin/rpm2cpio 替换下面命令中的 rpm2cpio
mkdir -p ~/wanwei && cd ~/wanwei
rpm2cpio ~/wanwei-shuyi-1.0.0-1.noarch.rpm | cpio -idm
WW_PREFIX=$HOME/wanwei bash opt/apps/wanwei-shuyi/bin/install-deps.sh
cd opt/apps/wanwei-shuyi/backend
../../venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
# 浏览器打开 http://127.0.0.1:8010/console/
```
