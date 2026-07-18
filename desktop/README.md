# 宛委·枢忆 OSAgent — 麒麟 Linux 桌面客户端

> 桌面端与 Web 端共享同一套业务代码。浏览器访问 `http://127.0.0.1:<port>/console/` 同样可用。

## 一、设计目标

- **Web 业务零改动**：`frontend/console-vue` 与 `backend/app` 完全复用，桌面封装仅做了一层 Electron 壳。
- **原生桌面体验**：窗口管理、系统托盘、桌面通知、本地文件对话框、XDG 自启动。
- **麒麟系统集成**：`deb`/`rpm` 双包、`/opt` 安装、`.desktop` 快捷方式、系统图标、hicolor 缓存刷新。
- **系统服务可选**：附带 `systemd --user` 服务单元，高级用户可用 `systemctl` 管理。

## 二、目录结构

```
desktop/
├── src/
│   ├── main.js          # Electron 主进程（后端守护、窗口、托盘、IPC、自启动）
│   └── preload.js       # 安全桥：暴露 window.wanweiDesktop 给 Web 端
├── build/icons/         # 16~512 像素多尺寸图标（PNG）
├── packaging/linux/
│   ├── postinst.sh      # 安装后刷新 desktop/图标/沙箱权限
│   ├── postrm.sh        # 卸载后刷新缓存
│   ├── systemd/         # systemd --user 服务
│   └── autostart/       # XDG autostart 模板
├── scripts/
│   ├── build-linux.sh   # 一键构建 deb/rpm
│   └── generate_icons.py# 图标生成（Pillow）
├── package.json         # electron-builder 配置
└── README.md            # 本文档
```

## 三、构建环境

### 3.1 在 Linux（麒麟 V11）上构建

推荐在麒麟 V11 或兼容 Debian 系 Linux 上执行。

```bash
cd desktop/

# 安装构建依赖（麒麟/Debian）
sudo apt update
sudo apt install -y nodejs npm python3-venv python3-pip rpm

# 安装桌面端依赖
npm install

# 构建 deb 包
npm run pack:deb
# 或 rpm 包（需要安装 rpm 包）
npm run pack:rpm
# 或同时构建
npm run pack:all
```

产物输出在 `desktop/release/`：

```
release/wanwei-shuyi-desktop_0.11.0_amd64.deb
release/wanwei-shuyi-desktop-0.11.0.x86_64.rpm
```

### 3.2 在 Windows 上开发/交叉准备

Windows 可完成前端构建和脚本验证，但**无法直接生成 Linux 安装包**（缺少 `dpkg-deb`/`rpmbuild` 环境）。

```powershell
cd frontend/console-vue
npm install
npm run build              # 确保 Web 产物为最新

cd ../desktop
npm install                # 安装 Electron 与 electron-builder
node --check src/main.js
node --check src/preload.js
```

最终打包建议拷贝源码到麒麟虚拟机，或 CI 中使用 Linux 容器执行 `npm run pack:all`。

### 3.3 在 WSL2 Ubuntu 中验证（推荐无图形 Linux 验证）

```bash
wsl -d Ubuntu

cd /path/to/wan-wei--shuyi-osagent/desktop
npm install
npm run pack:deb

# 安装
sudo dpkg -i release/wanwei-shuyi-desktop_0.11.0_amd64.deb

# 使用虚拟显示启动（无图形桌面环境也适用）
timeout 60 xvfb-run --auto-servernum /opt/wanwei-shuyi-desktop/wanwei-shuyi-desktop --no-sandbox
```

启动日志中应能看到后端 `/health` 200、前端 `/console/` 200、各 API 资源加载成功。浏览器可访问 `http://127.0.0.1:<port>/console/`。

## 四、安装与运行

### 4.1 安装 deb 包（麒麟/Debian/Ubuntu）

```bash
sudo dpkg -i release/wanwei-shuyi-desktop_0.11.0_amd64.deb
# 若依赖不足
sudo apt --fix-broken install -y
```

安装后：
- 程序主体在 `/opt/wanwei-shuyi-desktop/`
- 可执行文件 `/opt/wanwei-shuyi-desktop/wanwei-shuyi-desktop`
- `.desktop` 入口 `/usr/share/applications/wanwei-shuyi-desktop.desktop`
- 图标在 `/usr/share/icons/hicolor/` 各尺寸目录
- 可选 systemd 服务 `/etc/systemd/user/wanwei-shuyi-desktop.service`

### 4.2 安装 rpm 包（银河麒麟高级服务器版/openEuler/统信）

```bash
sudo rpm -i release/wanwei-shuyi-desktop-0.11.0.x86_64.rpm
```

### 4.3 启动方式

1. **图形界面**：开始菜单 → 「枢忆·花朝」
2. **命令行**：`/opt/wanwei-shuyi-desktop/wanwei-shuyi-desktop`
3. **系统服务（可选）**：

   ```bash
   systemctl --user enable --now wanwei-shuyi-desktop
   ```

### 4.4 首次启动

首次启动会：
1. 在 `~/.config/wanwei-shuyi-desktop/venv/` 创建 Python 虚拟环境；
2. 安装后端依赖（`pip install -r backend/requirements.txt`）；
3. 生成 48 位本地 API Key；
4. 启动后端并加载 Web 控制台窗口。

后续启动仅复用该虚拟环境，速度显著加快。

## 五、Web 端访问

桌面应用启动后，浏览器可直接访问：

```
http://127.0.0.1:<port>/console/
```

`port` 在首次启动时自动选择空闲端口（通常是 8010）。若通过系统托盘「在浏览器中打开 Web 端」可直接跳转。

## 六、桌面特性

| 特性 | 实现方式 | 说明 |
|---|---|---|
| 窗口管理 | `BrowserWindow` | 记住尺寸/位置，关闭即最小化到托盘 |
| 系统托盘 | `Tray` | 显示/隐藏、浏览器打开、退出、自启动开关 |
| 桌面通知 | `Notification` | 后端就绪、测试通知；渲染进程可调用 `window.wanweiDesktop.notify()` |
| 本地文件访问 | `dialog` + `ipcMain` | 主进程弹出系统对话框，避免 Web 直接访问文件系统 |
| 深色主题 | `nativeTheme` | 跟随系统主题，自动写入 `localStorage.gf-theme`（与 Web 端一致） |
| 自启动 | XDG autostart + `app.setLoginItemSettings` | 托盘菜单勾选即可 |
| 单实例 | `app.requestSingleInstanceLock` | 重复点击仅唤醒已运行实例 |
| 防睡眠（v0.11.0） | `powerSaveBlocker` | `app`（仅阻止系统挂起）/ `display`（连同屏幕常亮）两档，托盘可切，保证长时编排运行期间机器不睡 |
| 局域网手机控制（v0.11.0） | 后端 `127.0.0.1 ↔ 0.0.0.0` 热重启切换 | 自动优选私有网段 IPv4 生成手机访问地址，配合 `/mobile` 页面与 LAN token 构成「手机伴侣」通道 |
| 浮动工作区小窗（v0.11.0） | 无边框置顶 `BrowserWindow`（420×640） | 跳过任务栏，加载 `/console/#/mobile?floating=1`，随时唤起/销毁 |

## 七、环境变量

| 变量 | 说明 |
|---|---|
| `WANWEI_DESKTOP_PYTHON` | 指定 Python 解释器路径，用于创建虚拟环境 |
| `WANWEI_MEMORY_DB` | 后端数据库路径（默认 `~/.config/wanwei-shuyi-desktop/runtime/memory.db`） |
| `PIP_INDEX_URL` | 依赖安装镜像（默认清华源 `https://pypi.tuna.tsinghua.edu.cn/simple`） |

## 八、卸载

```bash
# Debian/Ubuntu/麒麟
sudo apt remove wanwei-shuyi-desktop

# rpm/openEuler/统信
sudo rpm -e wanwei-shuyi-desktop
```

用户数据目录 `~/.config/wanwei-shuyi-desktop/` 默认保留，内含记忆数据库；如需彻底清理请手动删除。

## 九、常见问题

### 9.1 沙箱启动失败

某些容器或特殊内核环境缺少 Electron 沙箱支持，可临时绕过：

```bash
/opt/wanwei-shuyi-desktop/wanwei-shuyi-desktop --no-sandbox
```

生产部署建议通过 `postinst.sh` 设置 `chrome-sandbox` 的 `setuid` 权限。

### 9.2 后端依赖安装慢

首次启动会创建 venv 并安装依赖。可设置国内镜像：

```bash
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
/opt/wanwei-shuyi-desktop/wanwei-shuyi-desktop
```

### 9.3 端口被占用

主进程会自动选择空闲端口，无需手动配置。若需要固定端口，可修改 `src/main.js` 中的 `findFreePortSync()` 回退值。

### 9.4 麒麟 VNC 虚拟机中测试

当前仓库已配套 `scripts/start_kylin_vm.ps1`，可在 Windows 上启动麒麟 V11 虚拟机。将项目源码复制到虚拟机后执行第 3 节构建步骤即可。

**注意**：如果麒麟系统处于「只读/锁定模式」（运行 `apt` 或执行非系统预装二进制时报「不允许的操作」），则无法在此虚拟机中安装或运行第三方 Electron 应用。此时请在正常模式的麒麟设备、WSL2 Ubuntu 或标准 Debian 系容器中验证。

## 十、遵循的规范

- [麒麟软件开发者平台文档中心](https://document.kylinos.cn/document/center)
- [Desktop Entry Specification](https://specifications.freedesktop.org/desktop-entry-spec/latest/)
- [XDG Autostart Specification](https://specifications.freedesktop.org/autostart-spec/autostart-spec-latest.html)
- Debian 二进制包规范（`control` / `DEBIAN/` 目录结构）
- RPM 包规范

## 十一、安全说明

- 桌面端为本地 API 自动生成强随机 Key，并写入 `~/.config/wanwei-shuyi-desktop/api-key`（权限 0600）。
- `preload.js` 通过 `contextBridge` 隔离暴露，Web 端无法直接访问 Node.js 或文件系统。
- 所有文件读写操作均由主进程在 `dialog` 授权后执行。

---

作者：WanWei Shuyi Team
