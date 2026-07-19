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
        shell, nativeTheme, nativeImage, net, powerSaveBlocker, clipboard, screen,
        session } = require('electron');
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

const LOG_MAX_BYTES = 5 * 1024 * 1024;   // backend.log 大小上限 5MB
const LOG_KEEP_BYTES = 2 * 1024 * 1024;  // 超限后仅保留尾部 2MB

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

/** 日志截断：超过 LOG_MAX_BYTES 时仅保留尾部 LOG_KEEP_BYTES（托盘长期驻留防无限增长） */
function truncateLogIfNeeded(file = LOG_FILE) {
  try {
    const st = fs.statSync(file);
    if (st.size <= LOG_MAX_BYTES) return false;
    const fd = fs.openSync(file, 'r');
    let tail;
    try {
      tail = Buffer.alloc(LOG_KEEP_BYTES);
      fs.readSync(fd, tail, 0, LOG_KEEP_BYTES, st.size - LOG_KEEP_BYTES);
    } finally {
      fs.closeSync(fd);
    }
    fs.writeFileSync(file,
      `[${new Date().toISOString()}] --- log truncated: kept last ${LOG_KEEP_BYTES} of ${st.size} bytes ---\n`);
    fs.appendFileSync(file, tail);
    return true;
  } catch { /* 文件不存在等情况静默 */ }
  return false;
}

function logLine(msg) {
  const line = `[${new Date().toISOString()}] ${msg}\n`;
  try {
    truncateLogIfNeeded();
    fs.appendFileSync(LOG_FILE, line);
  } catch { /* ignore */ }
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

// 说明：原 findFreePortSync 已删除。其 execSync 子进程未设 ELECTRON_RUN_AS_NODE，
// 会以完整 Electron GUI 启动并撞上单实例锁，stdout 无输出、恒回退 8010；
// whenReady 启动流程本身异步，直接使用上方 findFreePort() 真实绑定探测。
// 取舍：探测后关闭监听再交由 uvicorn 绑定，存在极小的 TOCTOU 竞争窗口；
// 若端口恰好被抢，uvicorn 绑定失败会走既有启动错误提示，可接受。

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

/** marker 校验：内容与 requirements.txt 当前哈希一致才算有效
 * （旧格式写入的是时间戳，一律视为失效，触发一次重装后重写为哈希） */
function depsMarkerMatches(marker, reqHash) {
  try { return fs.readFileSync(marker, 'utf8').trim() === reqHash; }
  catch { return false; }
}

/** 首次运行：创建 venv 并安装后端依赖（带桌面通知反馈）
 *  .deps-ok marker 记录 requirements.txt 的 SHA-256；内容变化即重装，避免应用升级后跑旧依赖 */
async function ensureBackendEnv(notify) {
  const venvPy = path.join(VENV_DIR, 'bin', 'python3');
  const marker = path.join(VENV_DIR, '.deps-ok');
  const req = path.join(BACKEND_DIR, 'requirements.txt');
  const reqHash = crypto.createHash('sha256').update(await fsp.readFile(req)).digest('hex');
  if (fs.existsSync(venvPy) && fs.existsSync(marker) && depsMarkerMatches(marker, reqHash)) {
    return venvPy;   // 依赖指纹未变，跳过重装
  }
  if (fs.existsSync(venvPy)) logLine('requirements.txt 已变化或 marker 失效，重装后端依赖 ...');

  notify('正在初始化运行环境', '首次启动需要创建 Python 虚拟环境并安装依赖，约需 1-3 分钟。');
  const sysPy = findPython();
  if (!fs.existsSync(venvPy)) {
    logLine('creating venv ...');
    const r0 = spawnSync(sysPy, ['-m', 'venv', VENV_DIR], { stdio: 'inherit' });
    if (r0.status !== 0) throw new Error('python3 -m venv 失败，请确认已安装 python3-venv');
  }

  const pip = path.join(VENV_DIR, 'bin', 'pip');
  logLine('pip install -r requirements.txt ...');
  const r = spawnSync(pip, ['install', '--disable-pip-version-check', '-r', req],
    { stdio: 'inherit', env: { ...process.env, PIP_INDEX_URL: process.env.PIP_INDEX_URL || 'https://pypi.tuna.tsinghua.edu.cn/simple' } });
  if (r.status !== 0) throw new Error('后端依赖安装失败，详见 ' + LOG_FILE);
  await fsp.writeFile(marker, reqHash);
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
      WANWEI_PLATFORM_DIR: path.join(USER_DATA, 'platform'),
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

/** 停止后端；返回 Promise，等进程真正退出（5s 不退则 SIGKILL），供 LAN 重启与退出流程复用 */
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

/** LAN token 日志脱敏：只保留前 4 位，其余以省略号代替 */
function maskToken(token) {
  const t = String(token || '');
  return t.length <= 4 ? t : t.slice(0, 4) + '…';
}

/** 导航白名单：仅允许控制台自身（http://127.0.0.1:<port>/），其余一律视为外站 */
function isConsoleUrl(url, port = backendPort) {
  return typeof url === 'string' && url.startsWith(`http://127.0.0.1:${port}/`);
}

/** 为窗口加装 will-navigate 白名单：拦下同窗口跳转外站（防泄桥/泄钥），外站交系统浏览器 */
function guardNavigation(wc) {
  wc.on('will-navigate', (e, url) => {
    if (isConsoleUrl(url)) return;
    e.preventDefault();
    logLine(`navigation blocked: ${url}`);
    if (/^https?:\/\//.test(url)) shell.openExternal(url).catch(() => { /* ignore */ });
  });
}

/** IPC 来源校验：senderFrame 必须是控制台自身页面，否则拒绝 */
function isTrustedFrame(frame) {
  try { return isConsoleUrl(frame && frame.url); } catch { return false; }
}

/** 为指定 session 的出站请求注入 X-API-Key；默认 session 一次注册即可覆盖主窗体和浮动窗 */
function injectApiKeyForSession(sess) {
  sess.webRequest.onBeforeSendHeaders(
    { urls: [`http://127.0.0.1:${backendPort}/*`] },
    (details, cb) => {
      details.requestHeaders['X-API-Key'] = apiKey;
      cb({ requestHeaders: details.requestHeaders });
    },
  );
}

/** 节流工厂：windowMs 内最多放行 limit 次，超出返回 true（被节流） */
function createThrottle(limit, windowMs) {
  const hits = [];
  return () => {
    const now = Date.now();
    while (hits.length && now - hits[0] > windowMs) hits.shift();
    if (hits.length >= limit) return true;
    hits.push(now);
    return false;
  };
}
const notifyThrottled = createThrottle(5, 10000);   // 桌面通知：10s 内最多 5 条，防渲染端轰炸

/** 窗口 bounds 离屏校验：与任一显示器工作区重叠 ≥100×60（标题栏可见可操作）才算可见 */
function isVisibleOnSomeDisplay(b, displays) {
  if (!b || !Number.isFinite(b.x) || !Number.isFinite(b.y)) return false;
  const w = Number.isFinite(b.width) ? b.width : 1440;
  const h = Number.isFinite(b.height) ? b.height : 900;
  return (displays || []).some((d) => {
    const a = d && d.workArea;
    if (!a) return false;
    const overlapX = Math.min(b.x + w, a.x + a.width) - Math.max(b.x, a.x);
    const overlapY = Math.min(b.y + h, a.y + a.height) - Math.max(b.y, a.y);
    return overlapX >= 100 && overlapY >= 60;
  });
}

/** 文件解码容错：含 NUL 字节视为二进制走 base64（避免乱码静默成功）；
 *  去 UTF-8 BOM；非法 UTF-8 序列回退替换字符解码并标注 utf8-lossy */
function decodeFileBuffer(buf) {
  if (buf.includes(0)) return { content: buf.toString('base64'), encoding: 'base64' };
  const body = (buf.length >= 3 && buf[0] === 0xEF && buf[1] === 0xBB && buf[2] === 0xBF)
    ? buf.subarray(3) : buf;
  try {
    return { content: new TextDecoder('utf-8', { fatal: true }).decode(body), encoding: 'utf8' };
  } catch {
    return { content: new TextDecoder('utf-8').decode(body), encoding: 'utf8-lossy' };
  }
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
        // 取舍说明：preload 需读取 process.env.WANWEI_DESKTOP_API_KEY 注入 localStorage，
        // sandbox 下 preload 的 process 为 polyfill（无 env），故保留 sandbox:false；
        // 补偿控制：contextIsolation + nodeIntegration:false + will-navigate 白名单
        // + 全部 IPC handler 校验 senderFrame 来源（见 registerIpc）。
        sandbox: false,
        spellcheck: false,
      },
    });
    floatingWin.setAlwaysOnTop(true, 'floating');
    floatingWin.webContents.setWindowOpenHandler(({ url }) => {
      if (url.startsWith('http')) shell.openExternal(url);
      return { action: 'deny' };
    });
    guardNavigation(floatingWin.webContents);
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
  // 离屏校验：拔掉外接屏后保存的 x/y 可能落在不可见区域；校验不过则不传坐标（系统默认居中）
  const onScreen = isVisibleOnSomeDisplay(state, screen.getAllDisplays());
  mainWindow = new BrowserWindow({
    width: state.width || 1440,
    height: state.height || 900,
    x: onScreen ? state.x : undefined,
    y: onScreen ? state.y : undefined,
    minWidth: 960, minHeight: 640,
    title: APP_NAME,
    icon: path.join(__dirname, '..', 'build', 'icons', '256x256.png'),
    backgroundColor: '#F6F1E7',          // 宣纸色，避免白闪，贴合「花朝」主题
    autoHideMenuBar: true,               // UKUI 风格：默认隐藏菜单栏（Alt 呼出）
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      // 取舍说明：preload 需读取 process.env.WANWEI_DESKTOP_API_KEY 注入 localStorage，
      // sandbox 下 preload 的 process 为 polyfill（无 env），故保留 sandbox:false；
      // 补偿控制：contextIsolation + nodeIntegration:false + will-navigate 白名单
      // + 全部 IPC handler 校验 senderFrame 来源（见 registerIpc）。
      sandbox: false,
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

  // 同窗口导航白名单：仅控制台自身，外站 preventDefault + 系统浏览器打开
  guardNavigation(mainWindow.webContents);

  mainWindow.on('close', (e) => {
    saveWindowState(mainWindow);
    if (!quitting) {                       // 关闭即最小化到托盘（桌面应用惯例）
      e.preventDefault();
      mainWindow.hide();
    }
  });
  mainWindow.on('closed', () => { mainWindow = null; });

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
  // 自启动归一说明（三套机制的关系，避免重复拉起）：
  //  ① 打包内 systemd --user 服务：postinst 仅拷贝到 /etc/systemd/user，不 enable，
  //     属高级用户可选管理方式，默认不激活；
  //  ② 打包内 autostart.desktop：extraFiles 仅随包分发到安装目录，不写入 XDG
  //     autostart，属备件，默认不激活；
  //  ③ 本函数维护的 ~/.config/autostart 条目 + Electron setLoginItemSettings：
  //     唯一运行时生效路径，即「开机自启动」开关的唯一事实来源。
  //  单实例锁兜底：即使 ①② 被用户手动激活与 ③ 并存，也只会有一个实例运行。
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
/** 注册 IPC handler：统一经 handle() 包装，校验 senderFrame 归属控制台页面 */
function registerIpc() {
  const handle = (channel, fn) => {
    ipcMain.handle(channel, (event, ...args) => {
      if (!isTrustedFrame(event.senderFrame)) {
        logLine(`IPC rejected: ${channel} from ${String((event.senderFrame && event.senderFrame.url) || 'unknown')}`);
        throw new Error('IPC 来源不受信任');
      }
      return fn(event, ...args);
    });
  };

  // 桌面通知（10s 内最多 5 条，超出丢弃并返回 false）
  handle('desktop:notify', (_e, { title, body } = {}) => {
    if (notifyThrottled()) { logLine('notification throttled'); return false; }
    notify(String(title || APP_NAME), String(body || ''));
    return true;
  });

  // 本地文件访问：打开对话框并读取（限制 8MB，防误读大文件；编码见 decodeFileBuffer）
  handle('desktop:open-file', async (_e, opts = {}) => {
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
    const buf = await fsp.readFile(file);
    const { content, encoding } = decodeFileBuffer(buf);
    return { path: file, name: path.basename(file), size: stat.size, content, encoding };
  });

  // 保存文件到本地
  handle('desktop:save-file', async (_e, { defaultName, content, filters } = {}) => {
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
  handle('desktop:show-item', (_e, p) => { shell.showItemInFolder(String(p)); return true; });

  // 运行信息（前端"关于"页可用）
  handle('desktop:info', () => ({
    version: app.getVersion(),
    backendPort,
    webUrl: `http://127.0.0.1:${backendPort}/console/`,
    dataDir: USER_DATA,
    platform: process.platform,
  }));

  handle('desktop:set-autostart', (_e, enable) => { setAutostart(!!enable); return getAutostart(); });
  handle('desktop:get-autostart', () => getAutostart());

  // 防睡眠：任务期间阻止系统挂起 / 屏幕常亮
  handle('desktop:set-prevent-sleep', (_e, { enable, mode } = {}) =>
    setPreventSleep(!!enable, mode));
  handle('desktop:get-prevent-sleep', () => getPreventSleep());

  // 局域网手机控制：仅由前端配对流程显式触发；
  // 开启 = 后端以 0.0.0.0 重启（保持端口），关闭 = 恢复 127.0.0.1 重启
  handle('desktop:lan-enable', async (_e, { token } = {}) => {
    const ip = firstLanIPv4();
    if (!ip) throw new Error('未找到可用的局域网 IPv4 地址');
    if (backendHost !== '0.0.0.0' || !backendProc) await restartBackend('0.0.0.0');
    const url = `http://${ip}:${backendPort}/console/#/mobile?token=${String(token || '')}`;
    lanState = { enabled: true, url };
    refreshTray();
    // token 脱敏：只打前 4 位，完整配对 URL 不落日志
    logLine(`LAN enabled: http://${ip}:${backendPort}/console/#/mobile?token=${maskToken(token)}（已脱敏）`);
    return { enabled: true, lan_url: url, host: backendHost, port: backendPort };
  });

  handle('desktop:lan-disable', async () => {
    if (backendHost !== '127.0.0.1' || !backendProc) await restartBackend('127.0.0.1');
    lanState = { enabled: false, url: '' };
    refreshTray();
    logLine('LAN disabled, backend back on 127.0.0.1');
    return { enabled: false, lan_url: null, host: backendHost, port: backendPort };
  });

  // 浮动工作区小窗（420×640 置顶无边框，加载移动端视图）
  handle('desktop:floating-workspace', (_e, { show } = {}) =>
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
    // 真实异步探测空闲端口（原 findFreePortSync 恒回退 8010，已删除，见上方说明）
    backendPort = await findFreePort();
    // 主进程兜底注入：所有窗口（主窗体 / 浮动窗 / LAN 手机视图）共享默认 session
    injectApiKeyForSession(session.defaultSession);
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

  let backendCleaned = false;
  app.on('window-all-closed', () => { /* 托盘常驻，不退出 */ });
  app.on('before-quit', (e) => {
    quitting = true;
    // 等后端真正退出再放行：否则 SIGTERM 后主进程先退，5s SIGKILL 兜底永不执行，
    // 后端卡死即成孤儿进程占用端口。stopBackend 内部有 5s 超时，不会无限阻塞退出。
    if (!backendCleaned && backendProc) {
      e.preventDefault();
      stopBackend().finally(() => { backendCleaned = true; app.quit(); });
    }
  });
}

// ---------------------------------------------------------------- test hook
// 仅供自检脚本使用：设置 WANWEI_DESKTOP_TEST_EXPORTS=1 并以 electron 桩加载时，
// 导出内部函数做单元验证；正常 Electron 运行不设置该变量，无任何导出。
if (process.env.WANWEI_DESKTOP_TEST_EXPORTS === '1') {
  module.exports = {
    findFreePort,
    truncateLogIfNeeded,
    maskToken,
    isConsoleUrl,
    isTrustedFrame,
    isVisibleOnSomeDisplay,
    createThrottle,
    decodeFileBuffer,
    depsMarkerMatches,
  };
}
