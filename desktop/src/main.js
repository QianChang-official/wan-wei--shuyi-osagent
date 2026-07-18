'use strict';
/**
 * 枢忆·花朝 — 麒麟 Linux 桌面客户端主进程
 *
 * 职责：
 *  1. 拉起并守护 FastAPI 后端子进程（复用仓库内 backend/，业务代码零改动）
 *  2. 原生窗口管理（记住尺寸、最小化到托盘）
 *  3. 系统托盘 / 桌面通知 / 本地文件访问（IPC，contextIsolation 隔离）
 *  4. 单实例锁、XDG 自启动、UKUI 深色主题跟随
 *  5. 首次运行自动创建 Python venv 并安装后端依赖
 *
 * Web 端访问方式完全不变：浏览器打开 http://127.0.0.1:<port>/console/ 即可。
 */
const { app, BrowserWindow, Tray, Menu, Notification, ipcMain, dialog,
        shell, nativeTheme, nativeImage, net, powerSaveBlocker, clipboard } = require('electron');
const { spawn, spawnSync } = require('node:child_process');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');
const netNode = require('node:net');
const os = require('node:os');

// ---------------------------------------------------------------- constants
const APP_NAME = '枢忆·花朝';
const APP_ID = 'wanwei-shuyi-desktop';

// 资源根：打包后为 resources/，开发时为仓库根（desktop/ 的上一级）
const RES_ROOT = app.isPackaged
  ? process.resourcesPath
  : path.resolve(__dirname, '..', '..');
const BACKEND_DIR = path.join(RES_ROOT, 'backend');
const FRONTEND_DIST = path.join(RES_ROOT, 'frontend', 'console-vue', 'dist');

const USER_DATA = app.getPath('userData');          // ~/.config/wanwei-shuyi-desktop
const RUNTIME_DIR = path.join(USER_DATA, 'runtime');
const VENV_DIR = path.join(USER_DATA, 'venv');
const KEY_FILE = path.join(USER_DATA, 'api-key');
const STATE_FILE = path.join(USER_DATA, 'window-state.json');
const LOG_FILE = path.join(RUNTIME_DIR, 'backend.log');

// ------------------------------------------------------------------ globals
let backendProc = null;
let backendPort = 0;
let backendPython = '';              // 启动后端所用解释器（LAN 重启复用）
let backendHost = '127.0.0.1';       // 当前后端监听地址（LAN 模式为 0.0.0.0）
let restarting = false;              // 主动重启后端时抑制"异常退出"弹窗
let apiKey = '';
let mainWindow = null;
let tray = null;
let quitting = false;

// 防睡眠状态（powerSaveBlocker）
let powerSaveBlockerId = null;       // 当前 blocker id，null 表示未启用
let preventSleepMode = 'app';        // 'app' 阻止系统挂起 | 'display' 连同屏幕常亮

// 局域网手机控制状态
let lanState = { enabled: false, url: '' };

// 浮动工作区小窗
let floatingWin = null;

// ------------------------------------------------------------- small helpers
function logLine(msg) {
  const line = `[${new Date().toISOString()}] ${msg}\n`;
  try { fs.appendFileSync(LOG_FILE, line); } catch { /* ignore */ }
  console.log(line.trim());
}

function findFreePort() {
  return new Promise((resolve, reject) => {
    const srv = netNode.createServer();
    srv.unref();
    srv.on('error', reject);
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

/** 同步取一个空闲端口（启动阶段使用） */
function findFreePortSync() {
  const { execSync } = require('node:child_process');
  // 优先用 Node 自身，避免依赖 python 尚未就绪
  try {
    const out = execSync(
      `"${process.execPath}" -e "const s=require('net').createServer();s.listen(0,'127.0.0.1',()=>{console.log(s.address().port);s.close()})"`,
      { encoding: 'utf8', timeout: 8000 }).trim();
    const p = parseInt(out, 10);
    if (p > 0) return p;
  } catch { /* fall through */ }
  return 8010;
}

/** 生成/读取本机 API Key（0600，仅当前用户可读） */
async function ensureApiKey() {
  try {
    const existing = (await fsp.readFile(KEY_FILE, 'utf8')).trim();
    if (existing.length >= 32) return existing;
  } catch { /* first run */ }
  const key = crypto.randomBytes(24).toString('hex'); // 48 chars
  await fsp.writeFile(KEY_FILE, key + '\n', { mode: 0o600 });
  return key;
}

function findPython() {
  if (process.env.WANWEI_DESKTOP_PYTHON) return process.env.WANWEI_DESKTOP_PYTHON;
  const venvPy = path.join(VENV_DIR, 'bin', 'python3');
  if (fs.existsSync(venvPy)) return venvPy;
  for (const cand of ['python3', 'python3.12', 'python3.11', 'python3.10']) {
    const r = spawnSync(cand, ['--version'], { stdio: 'ignore' });
    if (r.status === 0) return cand;
  }
  return 'python3';
}

/** 首次运行：创建 venv 并安装后端依赖（带桌面通知反馈） */
async function ensureBackendEnv(notify) {
  const venvPy = path.join(VENV_DIR, 'bin', 'python3');
  const marker = path.join(VENV_DIR, '.deps-ok');
  if (fs.existsSync(venvPy) && fs.existsSync(marker)) return venvPy;

  notify('正在初始化运行环境', '首次启动需要创建 Python 虚拟环境并安装依赖，约需 1-3 分钟。');
  logLine('creating venv ...');
  const sysPy = findPython();
  let r = spawnSync(sysPy, ['-m', 'venv', VENV_DIR], { stdio: 'inherit' });
  if (r.status !== 0) throw new Error('python3 -m venv 失败，请确认已安装 python3-venv');

  const pip = path.join(VENV_DIR, 'bin', 'pip');
  const req = path.join(BACKEND_DIR, 'requirements.txt');
  logLine('pip install -r requirements.txt ...');
  r = spawnSync(pip, ['install', '--disable-pip-version-check', '-r', req],
    { stdio: 'inherit', env: { ...process.env, PIP_INDEX_URL: process.env.PIP_INDEX_URL || 'https://pypi.tuna.tsinghua.edu.cn/simple' } });
  if (r.status !== 0) throw new Error('后端依赖安装失败，详见 ' + LOG_FILE);
  await fsp.writeFile(marker, new Date().toISOString());
  return venvPy;
}

function startBackend(python, host = '127.0.0.1') {
  return new Promise((resolve, reject) => {
    backendHost = host;
    const env = {
      ...process.env,
      WANWEI_HOST: host,
      WANWEI_PORT: String(backendPort),
      WANWEI_API_KEY: apiKey,
      WANWEI_MEMORY_DB: path.join(RUNTIME_DIR, 'memory.db'),
      PYTHONUNBUFFERED: '1',
    };
    // 让 preload 能拿到 API Key 注入 localStorage（渲染进程只读这一把钥匙）
    process.env.WANWEI_DESKTOP_API_KEY = apiKey;
    logLine(`starting backend on ${host}:${backendPort}`);
    backendProc = spawn(python, [
      '-m', 'uvicorn', 'app.main:app',
      '--app-dir', BACKEND_DIR,
      '--host', host,
      '--port', String(backendPort),
      '--no-proxy-headers',
    ], { env, stdio: ['ignore', 'pipe', 'pipe'] });

    backendProc.stdout.on('data', (d) => logLine('[backend] ' + d.toString().trim()));
    backendProc.stderr.on('data', (d) => logLine('[backend] ' + d.toString().trim()));
    backendProc.on('exit', (code) => {
      logLine(`backend exited with code ${code}`);
      backendProc = null;
      if (!quitting && !restarting && mainWindow) {
        dialog.showErrorBox(APP_NAME, '后端服务异常退出，请查看日志：' + LOG_FILE);
      }
    });

    // 等待 /health 就绪（最多 60s）
    const deadline = Date.now() + 60000;
    const probe = () => {
      const req = net.request(`http://127.0.0.1:${backendPort}/health`);
      req.on('response', (res) => {
        if (res.statusCode === 200) { logLine('backend ready'); resolve(); }
        else retry();
      });
      req.on('error', retry);
      req.end();
    };
    const retry = () => {
      if (Date.now() > deadline) return reject(new Error('后端启动超时（60s），详见 ' + LOG_FILE));
      if (!backendProc) return reject(new Error('后端进程已退出，详见 ' + LOG_FILE));
      setTimeout(probe, 500);
    };
    probe();
  });
}

/** 停止后端；返回 Promise，等进程真正退出（5s 不退则 SIGKILL），供 LAN 重启复用 */
function stopBackend() {
  const proc = backendProc;
  if (!proc) return Promise.resolve();
  logLine('stopping backend ...');
  backendProc = null;
  try { proc.kill('SIGTERM'); } catch { /* already gone */ }
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      try { proc.kill('SIGKILL'); } catch { /* ignore */ }
      resolve();
    }, 5000);
    proc.once('exit', () => { clearTimeout(timer); resolve(); });
  });
}

/** 以指定监听地址重启后端（LAN 开关的核心步骤），期间抑制异常退出弹窗 */
async function restartBackend(host) {
  if (!backendPython) throw new Error('后端尚未就绪，无法切换监听地址');
  restarting = true;
  try {
    await stopBackend();
    await startBackend(backendPython, host);
  } finally {
    restarting = false;
  }
}

/** 取本机局域网 IPv4（优先私有网段 10./192.168./172.16-31.） */
function firstLanIPv4() {
  const candidates = [];
  for (const list of Object.values(os.networkInterfaces())) {
    for (const it of list || []) {
      if (it && it.family === 'IPv4' && !it.internal) candidates.push(it.address);
    }
  }
  const priv = candidates.find((a) => /^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(a));
  return priv || candidates[0] || '';
}

// --------------------------------------------------------- prevent sleep
function getPreventSleep() {
  return {
    enabled: powerSaveBlockerId !== null && powerSaveBlocker.isStarted(powerSaveBlockerId),
    mode: preventSleepMode,
  };
}

function setPreventSleep(enable, mode) {
  preventSleepMode = mode === 'display' ? 'display' : 'app';
  if (enable) {
    if (powerSaveBlockerId !== null && powerSaveBlocker.isStarted(powerSaveBlockerId)) {
      powerSaveBlocker.stop(powerSaveBlockerId);
    }
    powerSaveBlockerId = powerSaveBlocker.start(
      preventSleepMode === 'display' ? 'prevent-display-sleep' : 'prevent-app-suspension');
    logLine(`powerSaveBlocker started (${preventSleepMode}), id=${powerSaveBlockerId}`);
  } else if (powerSaveBlockerId !== null) {
    if (powerSaveBlocker.isStarted(powerSaveBlockerId)) powerSaveBlocker.stop(powerSaveBlockerId);
    logLine(`powerSaveBlocker stopped, id=${powerSaveBlockerId}`);
    powerSaveBlockerId = null;
  }
  refreshTray();
  return getPreventSleep();
}

// ------------------------------------------------------ floating workspace
function setFloatingWorkspace(show) {
  if (show) {
    if (floatingWin && !floatingWin.isDestroyed()) {
      floatingWin.show();
      floatingWin.focus();
      return true;
    }
    floatingWin = new BrowserWindow({
      width: 420, height: 640,
      alwaysOnTop: true,
      frame: false,
      skipTaskbar: true,
      resizable: true,
      title: APP_NAME + ' · 浮动工作区',
      icon: path.join(__dirname, '..', 'build', 'icons', '256x256.png'),
      backgroundColor: '#F6F1E7',
      autoHideMenuBar: true,
      webPreferences: {
        preload: path.join(__dirname, 'preload.js'),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: false,
        spellcheck: false,
      },
    });
    floatingWin.setAlwaysOnTop(true, 'floating');
    floatingWin.webContents.setWindowOpenHandler(({ url }) => {
      if (url.startsWith('http')) shell.openExternal(url);
      return { action: 'deny' };
    });
    floatingWin.on('closed', () => { floatingWin = null; });
    floatingWin.loadURL(`http://127.0.0.1:${backendPort}/console/#/mobile?floating=1`);
    logLine('floating workspace shown');
    return true;
  }
  if (floatingWin && !floatingWin.isDestroyed()) floatingWin.destroy();
  floatingWin = null;
  logLine('floating workspace hidden');
  return false;
}

// --------------------------------------------------------- window state
function loadWindowState() {
  try { return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8')); }
  catch { return { width: 1440, height: 900 }; }
}
function saveWindowState(win) {
  if (!win || win.isDestroyed()) return;
  try {
    const b = win.getBounds();
    fs.writeFileSync(STATE_FILE, JSON.stringify({ ...b, maximized: win.isMaximized() }));
  } catch { /* ignore */ }
}

// ------------------------------------------------------------------ window
function createWindow() {
  const state = loadWindowState();
  mainWindow = new BrowserWindow({
    width: state.width || 1440,
    height: state.height || 900,
    x: state.x, y: state.y,
    minWidth: 960, minHeight: 640,
    title: APP_NAME,
    icon: path.join(__dirname, '..', 'build', 'icons', '256x256.png'),
    backgroundColor: '#F6F1E7',          // 宣纸色，避免白闪，贴合「花朝」主题
    autoHideMenuBar: true,               // UKUI 风格：默认隐藏菜单栏（Alt 呼出）
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,                    // preload 需要 fs 以读不到，仅 ipcRenderer
      spellcheck: false,
    },
  });
  if (state.maximized) mainWindow.maximize();

  // UKUI/麒麟深色主题跟随：同步到 Web 端「靛夜」主题（localStorage 键与 Web 端一致）
  nativeTheme.on('updated', () => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('desktop:theme-changed', nativeTheme.shouldUseDarkColors);
    }
  });

  // 外部链接交给系统浏览器，窗口内只跑控制台
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('http')) shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.on('close', (e) => {
    saveWindowState(mainWindow);
    if (!quitting) {                       // 关闭即最小化到托盘（桌面应用惯例）
      e.preventDefault();
      mainWindow.hide();
    }
  });
  mainWindow.on('closed', () => { mainWindow = null; });

  // 兜底：为所有 API 请求注入 X-API-Key（preload 的 localStorage 注入为主）
  mainWindow.webContents.session.webRequest.onBeforeSendHeaders(
    { urls: [`http://127.0.0.1:${backendPort}/*`] },
    (details, cb) => {
      details.requestHeaders['X-API-Key'] = apiKey;
      cb({ requestHeaders: details.requestHeaders });
    },
  );

  mainWindow.loadURL(`http://127.0.0.1:${backendPort}/console/`);
}

// -------------------------------------------------------------------- tray
function trayIcon() {
  const p = path.join(__dirname, '..', 'build', 'icons', '48x48.png');
  return fs.existsSync(p) ? p : undefined;
}

function createTray() {
  const icon = trayIcon();
  tray = new Tray(icon ? nativeImage.createFromPath(icon) : nativeImage.createEmpty());
  tray.setToolTip(APP_NAME);
  refreshTray();
  tray.on('click', () => {
    if (mainWindow) { mainWindow.isVisible() ? mainWindow.hide() : mainWindow.show(); }
  });
}

/** 重建托盘菜单（防睡眠勾选 / LAN 状态变化后联动刷新） */
function refreshTray() {
  if (!tray || tray.isDestroyed()) return;
  const openInBrowser = `http://127.0.0.1:${backendPort}/console/`;
  const items = [
    { label: '显示主窗口', click: () => { if (mainWindow) { mainWindow.show(); mainWindow.focus(); } else createWindow(); } },
    { label: '在浏览器中打开 Web 端', click: () => shell.openExternal(openInBrowser) },
    { type: 'separator' },
    { label: '任务期间阻止睡眠', type: 'checkbox', checked: getPreventSleep().enabled,
      sublabel: preventSleepMode === 'display' ? '含屏幕常亮' : '仅阻止系统挂起',
      click: (item) => setPreventSleep(item.checked, preventSleepMode) },
    { label: lanState.enabled ? '局域网手机控制：已开启' : '局域网手机控制：已关闭', enabled: false },
  ];
  if (lanState.enabled && lanState.url) {
    items.push({ label: '复制手机端地址', click: () => { clipboard.writeText(lanState.url); notify('已复制', '手机端局域网地址已复制到剪贴板。'); } });
  }
  items.push(
    { type: 'separator' },
    { label: '开机自启动', type: 'checkbox', checked: getAutostart(),
      click: (item) => setAutostart(item.checked) },
    { label: '发送测试通知', click: () => notify('测试通知', '桌面通知通道正常。') },
    { type: 'separator' },
    { label: '退出', click: () => { quitting = true; app.quit(); } },
  );
  tray.setContextMenu(Menu.buildFromTemplate(items));
}

function notify(title, body) {
  if (Notification.isSupported()) new Notification({ title, body, icon: trayIcon() }).show();
}

// -------------------------------------------------------------- autostart
function autostartFile() {
  return path.join(os.homedir(), '.config', 'autostart', APP_ID + '.desktop');
}
function getAutostart() {
  try { return fs.existsSync(autostartFile()); } catch { return false; }
}
function setAutostart(enable) {
  // 同时走 Electron 标准接口与 XDG autostart 文件（麒麟 V10/V11 均兼容）
  try { app.setLoginItemSettings({ openAtLogin: enable }); } catch { /* ignore */ }
  const file = autostartFile();
  try {
    if (enable) {
      const exec = app.isPackaged ? process.execPath : `${process.execPath} ${app.getAppPath()}`;
      fs.mkdirSync(path.dirname(file), { recursive: true });
      fs.writeFileSync(file, [
        '[Desktop Entry]',
        'Type=Application',
        `Name=${APP_NAME}`,
        `Exec="${exec}"`,
        'X-GNOME-Autostart-enabled=true',
        'X-KDE-autostart-after=panel',
        'Comment=宛委·枢忆 OSAgent 秘府控制台',
        '',
      ].join('\n'));
    } else if (fs.existsSync(file)) {
      fs.unlinkSync(file);
    }
  } catch (err) { logLine('autostart toggle failed: ' + err.message); }
}

// ------------------------------------------------------------------- IPC
function registerIpc() {
  // 桌面通知
  ipcMain.handle('desktop:notify', (_e, { title, body }) => {
    notify(String(title || APP_NAME), String(body || ''));
    return true;
  });

  // 本地文件访问：打开对话框并读取（限制 8MB，防误读大文件）
  ipcMain.handle('desktop:open-file', async (_e, opts = {}) => {
    const win = BrowserWindow.getFocusedWindow() || mainWindow;
    const r = await dialog.showOpenDialog(win, {
      title: opts.title || '选择文件',
      properties: ['openFile'],
      filters: opts.filters || [{ name: '所有文件', extensions: ['*'] }],
    });
    if (r.canceled || !r.filePaths.length) return null;
    const file = r.filePaths[0];
    const stat = await fsp.stat(file);
    if (stat.size > 8 * 1024 * 1024) throw new Error('文件超过 8MB 限制');
    const content = await fsp.readFile(file, 'utf8');
    return { path: file, name: path.basename(file), size: stat.size, content };
  });

  // 保存文件到本地
  ipcMain.handle('desktop:save-file', async (_e, { defaultName, content, filters }) => {
    const win = BrowserWindow.getFocusedWindow() || mainWindow;
    const r = await dialog.showSaveDialog(win, {
      title: '保存文件',
      defaultPath: defaultName || 'export.txt',
      filters: filters || [{ name: '所有文件', extensions: ['*'] }],
    });
    if (r.canceled || !r.filePath) return null;
    await fsp.writeFile(r.filePath, content, 'utf8');
    return { path: r.filePath };
  });

  // 在文件管理器中显示
  ipcMain.handle('desktop:show-item', (_e, p) => { shell.showItemInFolder(String(p)); return true; });

  // 运行信息（前端"关于"页可用）
  ipcMain.handle('desktop:info', () => ({
    version: app.getVersion(),
    backendPort,
    webUrl: `http://127.0.0.1:${backendPort}/console/`,
    dataDir: USER_DATA,
    platform: process.platform,
  }));

  ipcMain.handle('desktop:set-autostart', (_e, enable) => { setAutostart(!!enable); return getAutostart(); });
  ipcMain.handle('desktop:get-autostart', () => getAutostart());

  // 防睡眠：任务期间阻止系统挂起 / 屏幕常亮
  ipcMain.handle('desktop:set-prevent-sleep', (_e, { enable, mode } = {}) =>
    setPreventSleep(!!enable, mode));
  ipcMain.handle('desktop:get-prevent-sleep', () => getPreventSleep());

  // 局域网手机控制：仅由前端配对流程显式触发；
  // 开启 = 后端以 0.0.0.0 重启（保持端口），关闭 = 恢复 127.0.0.1 重启
  ipcMain.handle('desktop:lan-enable', async (_e, { token } = {}) => {
    const ip = firstLanIPv4();
    if (!ip) throw new Error('未找到可用的局域网 IPv4 地址');
    if (backendHost !== '0.0.0.0' || !backendProc) await restartBackend('0.0.0.0');
    const url = `http://${ip}:${backendPort}/mobile?token=${String(token || '')}`;
    lanState = { enabled: true, url };
    refreshTray();
    logLine('LAN enabled: ' + url);
    return { enabled: true, lan_url: url, host: backendHost, port: backendPort };
  });

  ipcMain.handle('desktop:lan-disable', async () => {
    if (backendHost !== '127.0.0.1' || !backendProc) await restartBackend('127.0.0.1');
    lanState = { enabled: false, url: '' };
    refreshTray();
    logLine('LAN disabled, backend back on 127.0.0.1');
    return { enabled: false, lan_url: null, host: backendHost, port: backendPort };
  });

  // 浮动工作区小窗（420×640 置顶无边框，加载移动端视图）
  ipcMain.handle('desktop:floating-workspace', (_e, { show } = {}) =>
    setFloatingWorkspace(!!show));
}

// ------------------------------------------------------------------- boot
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) { mainWindow.show(); mainWindow.focus(); }
  });

  app.whenReady().then(async () => {
    fs.mkdirSync(RUNTIME_DIR, { recursive: true });
    apiKey = await ensureApiKey();
    backendPort = findFreePortSync();
    registerIpc();

    try {
      const py = await ensureBackendEnv((t, b) => notify(t, b));
      backendPython = py;
      await startBackend(py);
    } catch (err) {
      logLine('boot failed: ' + err.message);
      dialog.showErrorBox(APP_NAME + ' 启动失败', err.message);
      app.exit(1);
      return;
    }

    createWindow();
    createTray();
    notify(APP_NAME + ' 已启动', `Web 端地址：http://127.0.0.1:${backendPort}/console/`);
  });

  app.on('window-all-closed', () => { /* 托盘常驻，不退出 */ });
  app.on('before-quit', () => { quitting = true; stopBackend(); });
}

