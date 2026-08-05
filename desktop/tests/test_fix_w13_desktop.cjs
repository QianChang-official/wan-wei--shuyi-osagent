'use strict';
/**
 * W13 桌面端修复自检（node 直跑，不依赖 Electron 运行时）：
 *   npm test
 * 以 electron 桩加载 main.js / preload.js，验证各项修复逻辑。
 * 覆盖：10-#4/#5/#7(源码级)/#8/#9/#10/#11/#12/#13/#14、10-#3(桥暴露)。
 */
process.env.WANWEI_DESKTOP_TEST_EXPORTS = '1';
// API Key 不再经 process.env 传入 preload；改由 electron 桩的 IPC 通道返回。
const TEST_API_KEY = 'test-api-key-0123456789abcdef0123456789abcdef';

const assert = require('node:assert');
const { EventEmitter } = require('node:events');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const Module = require('node:module');
const SRC_DIR = path.join(__dirname, '..', 'src');
const { recoverBackendEnvBackup, swapBackendEnv } = require('../src/backend_env');

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'wanwei-w13-'));

let exposedApi = null;
const browserWindows = [];

class BrowserWindowStub extends EventEmitter {
  constructor(options) {
    super();
    this.options = options;
    this.destroyed = false;
    this.visible = true;
    this.minimized = false;
    this.restoreCalls = 0;
    this.webContents = {
      on: () => {},
      setWindowOpenHandler: () => {},
    };
    browserWindows.push(this);
  }

  isDestroyed() { return this.destroyed; }
  isVisible() { return this.visible; }
  isMinimized() { return this.minimized; }
  setAlwaysOnTop() {}
  loadURL(url) { this.url = url; }
  focus() {}
  show() { this.visible = true; this.emit('show'); }
  hide() { this.visible = false; this.emit('hide'); }
  minimize() { this.minimized = true; this.emit('minimize'); }
  restore() { this.minimized = false; this.restoreCalls += 1; this.emit('restore'); }
  destroy() {
    this.destroyed = true;
    this.visible = false;
    this.emit('closed');
  }
}

const electronStub = {
  app: {
    isPackaged: false,
    getPath: () => tmp,
    getAppPath: () => tmp,
    getVersion: () => '0.0.0-test',
    requestSingleInstanceLock: () => false,   // 走 app.quit() 分支：模块加载即返回，不启动任何服务
    quit: () => {},
    on: () => {},
    whenReady: () => ({ then: () => {} }),
    setLoginItemSettings: () => {},
  },
  BrowserWindow: BrowserWindowStub,
  Tray: class {},
  Menu: { buildFromTemplate: () => ({}) },
  Notification: class { static isSupported() { return false; } },
  ipcMain: { handle: () => {}, on: () => {} },
  dialog: {},
  shell: {},
  nativeTheme: { on: () => {} },
  nativeImage: { createFromPath: () => ({}), createEmpty: () => ({}) },
  net: {},
  powerSaveBlocker: {},
  clipboard: {},
  screen: { getAllDisplays: () => [{ workArea: { x: 0, y: 0, width: 1920, height: 1080 } }] },
  contextBridge: { exposeInMainWorld: (name, api) => { if (name === 'wanweiDesktop') exposedApi = api; } },
  ipcRenderer: {
    invoke: (ch) => Promise.resolve(ch === 'desktop:api-key' ? TEST_API_KEY : true),
    sendSync: (ch) => (ch === 'desktop:api-key-sync' ? TEST_API_KEY : ''),
    on: () => {},
  },
};

const origLoad = Module._load;
Module._load = function (request, ...rest) {
  if (request === 'electron') return electronStub;
  return origLoad.call(this, request, ...rest);
};

// preload 依赖渲染进程全局：window / document / localStorage
const store = new Map();
let domReadyCb = null;
global.window = {
  location: new URL('http://127.0.0.1:8010/console/'),
  addEventListener: (ev, cb) => { if (ev === 'DOMContentLoaded') domReadyCb = cb; },
};
global.localStorage = {
  setItem: (k, v) => store.set(k, String(v)),
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  removeItem: (k) => store.delete(k),
};
global.document = { documentElement: { dataset: {} } };

const results = [];
async function t(name, fn) {
  try {
    await fn();
    results.push(['PASS', name]);
  } catch (err) {
    results.push(['FAIL', `${name} :: ${err && err.message}`]);
  }
}

(async () => {
  const main = require(path.join(SRC_DIR, 'main.js'));
  const preload = require(path.join(SRC_DIR, 'preload.js'));

  await t('10-#4 findFreePort 真实探测可用端口', async () => {
    const port = await main.findFreePort();
    assert.ok(Number.isInteger(port) && port > 0 && port < 65536, `端口应在合法范围，实际 ${port}`);
    const net = require('node:net');
    await new Promise((resolve, reject) => {
      const srv = net.createServer();
      srv.once('error', reject);
      srv.listen(port, '127.0.0.1', () => srv.close(() => resolve()));
    });
    const src = fs.readFileSync(path.join(SRC_DIR, 'main.js'), 'utf8');
    assert.ok(!src.includes('findFreePortSync() {'), 'findFreePortSync 应已删除');
    assert.ok(!/return 8010/.test(src), '不应再恒回退 8010');
  });

  await t('10-#5 主进程注册 will-navigate 白名单（源码级）', () => {
    const src = fs.readFileSync(path.join(SRC_DIR, 'main.js'), 'utf8');
    assert.ok(src.includes("will-navigate"), '应注册 will-navigate');
    assert.ok(src.includes('guardNavigation(mainWindow.webContents)'), '主窗口应加装导航守卫');
    assert.ok(src.includes('guardNavigation(floatingWin.webContents)'), '浮动窗应加装导航守卫');
    assert.strictEqual(main.isConsoleUrl('http://127.0.0.1:8010/console/', 8010), true);
    assert.strictEqual(main.isConsoleUrl('http://127.0.0.1:8010/console/#/mobile?token=x', 8010), true);
    assert.strictEqual(main.isConsoleUrl('https://evil.example.com/', 8010), false);
    assert.strictEqual(main.isConsoleUrl('http://127.0.0.1:9999/console/', 8010), false);
    assert.strictEqual(main.isConsoleUrl('file:///etc/passwd', 8010), false);
  });

  await t('10-#5 preload 仅控制台来源写 localStorage（同步注入 + 异步兜底）', async () => {
    // preload 加载时（控制台 origin，document_start）应已同步注入
    assert.strictEqual(store.get('wanwei-desktop-api-key'), TEST_API_KEY, '控制台 origin 加载时即同步注入');
    // 外站 origin：同步与异步路径都不得写入
    for (const evil of ['http://evil.example.com/', 'https://evil.example.com/']) {
      global.window.location = new URL(evil);
      store.clear();
      preload.injectDesktopApiKey();
      assert.strictEqual(store.get('wanwei-desktop-api-key'), undefined, `外站 ${evil} 同步路径不得写入`);
      await preload.injectDesktopApiKeyAsync();
      assert.strictEqual(store.get('wanwei-desktop-api-key'), undefined, `外站 ${evil} 异步路径不得写入`);
    }
    // 控制台 origin：两条路径都可注入
    global.window.location = new URL('http://127.0.0.1:8010/console/');
    store.clear();
    preload.injectDesktopApiKey();
    assert.strictEqual(store.get('wanwei-desktop-api-key'), TEST_API_KEY, '控制台 origin 同步注入');
    store.clear();
    await preload.injectDesktopApiKeyAsync();
    assert.strictEqual(store.get('wanwei-desktop-api-key'), TEST_API_KEY, '控制台 origin 异步兜底注入');
    // DOMContentLoaded 兜底钩子仍应注册
    assert.strictEqual(typeof domReadyCb, 'function', 'DOMContentLoaded 回调应已注册');
    global.window.location = new URL('file:///etc/passwd');
    assert.strictEqual(preload.isConsoleOrigin(), false);
    assert.strictEqual(typeof preload.isConsoleOrigin, 'function');
  });

  await t('10-#3 preload 桥暴露 lanEnable/lanDisable（LAN 端到端桌面半环）', () => {
    assert.ok(exposedApi, 'wanweiDesktop 应已暴露');
    for (const k of ['lanEnable', 'lanDisable', 'notify', 'setPreventSleep', 'getPreventSleep',
      'getAutostart', 'setAutostart', 'openFile', 'saveFile', 'showItemInFolder', 'info', 'floatingWorkspace']) {
      assert.strictEqual(typeof exposedApi[k], 'function', `${k} 应为函数`);
    }
  });

  await t('浮动工作区托盘状态跟随真实窗口生命周期', () => {
    const src = fs.readFileSync(path.join(SRC_DIR, 'main.js'), 'utf8');
    assert.match(src, /label: '显示浮动工作区'/, '托盘缺少浮动工作区入口');
    assert.strictEqual(main.isFloatingWorkspaceVisible(), false);

    assert.strictEqual(main.setFloatingWorkspace(true), true);
    const win = browserWindows.at(-1);
    assert.ok(win, '应创建浮动窗口');
    assert.strictEqual(main.isFloatingWorkspaceVisible(), true);

    win.minimize();
    assert.strictEqual(main.isFloatingWorkspaceVisible(), false, '最小化后托盘应显示未勾选');
    assert.strictEqual(main.setFloatingWorkspace(true), true);
    assert.strictEqual(win.restoreCalls, 1, '重新显示时应先恢复最小化窗口');
    assert.strictEqual(main.isFloatingWorkspaceVisible(), true);

    win.hide();
    assert.strictEqual(main.isFloatingWorkspaceVisible(), false, '隐藏后托盘应显示未勾选');
    main.setFloatingWorkspace(true);
    assert.strictEqual(main.isFloatingWorkspaceVisible(), true, '托盘应恢复既有隐藏窗口');

    assert.strictEqual(main.setFloatingWorkspace(false), false);
    assert.strictEqual(win.isDestroyed(), true);
    assert.strictEqual(main.isFloatingWorkspaceVisible(), false);
  });

  await t('10-#6 sandbox=true 显式开启，密钥改经受信 IPC 同步通道', () => {
    const src = fs.readFileSync(path.join(SRC_DIR, 'main.js'), 'utf8');
    assert.ok(!src.includes('读不到'), '乱码注释「以读不到」应已清除');
    const sandboxOn = (src.match(/sandbox: true/g) || []).length;
    assert.ok(sandboxOn >= 2, '两个窗口应显式 sandbox: true');
    assert.ok(!src.includes('sandbox: false'), '不应再保留 sandbox: false');
    assert.ok(src.includes("ipcMain.on('desktop:api-key-sync'"), '主进程应注册同步取钥通道');
    assert.ok(!src.includes('WANWEI_DESKTOP_API_KEY'), '不应再经 process.env 向 preload 传钥');
    const pre = fs.readFileSync(path.join(SRC_DIR, 'preload.js'), 'utf8');
    assert.ok(pre.includes("sendSync('desktop:api-key-sync')"), 'preload 应经同步通道取钥');
  });

  await t('10-#7 before-quit 阻止默认退出并等待 stopBackend（源码级）', () => {
    const src = fs.readFileSync(path.join(SRC_DIR, 'main.js'), 'utf8');
    const m = src.match(/app\.on\('before-quit'[\s\S]{0,500}?\}\);/);
    assert.ok(m, 'before-quit 处理器应存在');
    assert.ok(m[0].includes('preventDefault()'), '应先阻止默认退出以等待后端');
    assert.ok(m[0].includes('stopBackend()'), '应调用 stopBackend 并挂接完成回调');
  });

  await t('10-#8 backend.log 超 5MB 截断保留尾部', () => {
    const f = path.join(tmp, 'big.log');
    const tailMarker = 'TAIL-MARKER-最近日志';
    fs.writeFileSync(f, 'A'.repeat(5 * 1024 * 1024) + '\n' + tailMarker.repeat(2000));
    assert.ok(fs.statSync(f).size > 5 * 1024 * 1024);
    assert.strictEqual(main.truncateLogIfNeeded(f), true);
    const st = fs.statSync(f);
    assert.ok(st.size <= 2 * 1024 * 1024 + 1024, `截断后应 ≤ 约 2MB，实际 ${st.size}`);
    const content = fs.readFileSync(f, 'utf8');
    assert.ok(content.includes(tailMarker), '应保留尾部最近日志');
    assert.ok(content.includes('log truncated'), '应有截断标记行');
    assert.ok(!content.startsWith('AAAA'), '头部旧内容应被丢弃');
    const small = path.join(tmp, 'small.log');
    fs.writeFileSync(small, 'hello');
    assert.strictEqual(main.truncateLogIfNeeded(small), false, '小文件不应截断');
    assert.strictEqual(fs.readFileSync(small, 'utf8'), 'hello');
    assert.strictEqual(main.truncateLogIfNeeded(path.join(tmp, 'missing.log')), false, '文件不存在应静默');
  });

  await t('10-#9 窗口位置离屏校验', () => {
    const displays = [{ workArea: { x: 0, y: 0, width: 1920, height: 1080 } }];
    assert.strictEqual(main.isVisibleOnSomeDisplay({ x: 100, y: 100, width: 1440, height: 900 }, displays), true);
    assert.strictEqual(main.isVisibleOnSomeDisplay({ x: -5000, y: -5000, width: 1440, height: 900 }, displays), false, '完全离屏应判不可见');
    assert.strictEqual(main.isVisibleOnSomeDisplay({ x: 1820, y: 100, width: 1440, height: 900 }, displays), true, '重叠 ≥100×60 仍可见');
    assert.strictEqual(main.isVisibleOnSomeDisplay({ x: 1900, y: 1000, width: 1440, height: 900 }, displays), false, '仅剩 20px 细条应判离屏回退');
    assert.strictEqual(main.isVisibleOnSomeDisplay({ x: 5000, y: 100, width: 1440, height: 900 }, displays), false);
    assert.strictEqual(main.isVisibleOnSomeDisplay({ width: 1440, height: 900 }, displays), false, '无坐标应回退默认');
    assert.strictEqual(main.isVisibleOnSomeDisplay(null, displays), false);
    // 多显示器：第二块屏在右侧
    const dual = [displays[0], { workArea: { x: 1920, y: 0, width: 1920, height: 1080 } }];
    assert.strictEqual(main.isVisibleOnSomeDisplay({ x: 2000, y: 100, width: 1440, height: 900 }, dual), true);
  });

  await t('10-#10 LAN token 日志脱敏（只留前 4 位）', () => {
    assert.strictEqual(main.maskToken('abcdef1234567890'), 'abcd…');
    assert.strictEqual(main.maskToken('abc'), 'abc');
    assert.strictEqual(main.maskToken(''), '');
    assert.strictEqual(main.maskToken(undefined), '');
    const src = fs.readFileSync(path.join(SRC_DIR, 'main.js'), 'utf8');
    assert.ok(!src.includes("logLine('LAN enabled: ' + url)"), '完整配对 URL 不应再落日志');
  });

  await t('10-#11 IPC 来源校验 + 通知节流', () => {
    assert.strictEqual(main.isTrustedFrame({ url: 'http://127.0.0.1:0/console/' }), true, '控制台 frame 应可信（测试桩端口 0）');
    assert.strictEqual(main.isTrustedFrame({ url: 'https://evil.example.com/' }), false);
    assert.strictEqual(main.isTrustedFrame(null), false);
    assert.strictEqual(main.isTrustedFrame({}), false);
    const src = fs.readFileSync(path.join(SRC_DIR, 'main.js'), 'utf8');
    assert.ok(!/ipcMain\.handle\('/.test(src), '不应再直接注册未包装 handler');
    const th = main.createThrottle(3, 1000);
    assert.strictEqual(th(), false);
    assert.strictEqual(th(), false);
    assert.strictEqual(th(), false);
    assert.strictEqual(th(), true, '窗口内第 4 次应被节流');
    assert.strictEqual(th(), true);
  });

  await t('10-#12 .deps-ok marker 按 requirements 哈希校验', () => {
    const m = path.join(tmp, '.deps-ok');
    fs.writeFileSync(m, 'a'.repeat(64));
    assert.strictEqual(main.depsMarkerMatches(m, 'a'.repeat(64)), true);
    assert.strictEqual(main.depsMarkerMatches(m, 'b'.repeat(64)), false, 'requirements 变化应触发重装');
    fs.writeFileSync(m, '2025-01-01T00:00:00.000Z');
    assert.strictEqual(main.depsMarkerMatches(m, 'a'.repeat(64)), false, '旧时间戳格式应判失效');
    assert.strictEqual(main.depsMarkerMatches(path.join(tmp, 'nope'), 'x'), false, 'marker 缺失应判失效');
  });

  await t('麒麟缓存 venv 原生扩展导入探针', () => {
    const python = process.platform === 'win32' ? 'python' : 'python3';
    assert.strictEqual(main.isBackendEnvHealthy(python, 'pass'), true, '可用解释器应通过探针');
    assert.strictEqual(
      main.isBackendEnvHealthy(python, 'raise SystemExit(7)'),
      false,
      '导入失败必须使缓存 venv 失效',
    );
    const src = fs.readFileSync(path.join(SRC_DIR, 'main.js'), 'utf8');
    assert.ok(src.includes('import pydantic_core') && src.includes('import uvicorn'),
      '探针应覆盖原生扩展与实际启动所需的 uvicorn 依赖');
    assert.ok(src.includes('"-m", "uvicorn", "app.main:app"'),
      '探针应使用与正式后端相同的模块入口');
    assert.ok(src.includes('socket.create_connection(("127.0.0.1", port)'),
      '探针应确认 uvicorn 已真实绑定 loopback 端口');
    assert.ok(src.includes('"--lifespan", "off"'),
      '探针不得在预检阶段触碰用户数据库生命周期');
    assert.ok(src.includes('.staging-${process.pid}-${Date.now()}'),
      '重建应先写入独立 staging venv');
    assert.ok(src.includes('await swapBackendEnv(VENV_DIR, stagingDir, logLine)'),
      '新环境通过健康检查后才应替换当前 venv');
    assert.ok(src.includes('await recoverBackendEnvBackup(VENV_DIR, logLine)'),
      '交换中断后应在下一次启动恢复最后一个可用 venv');
    assert.ok(!src.includes('await fsp.rm(VENV_DIR, { recursive: true, force: true })'),
      '重建失败时不得先删除最后一个可用 venv');
  });

  await t('麒麟缓存 venv staging 交换与失败恢复', async () => {
    const successRoot = fs.mkdtempSync(path.join(tmp, 'venv-success-'));
    const successVenv = path.join(successRoot, 'venv');
    const successStaging = path.join(successRoot, 'staging');
    fs.mkdirSync(successVenv);
    fs.mkdirSync(successStaging);
    fs.writeFileSync(path.join(successVenv, 'state'), 'old');
    fs.writeFileSync(path.join(successStaging, 'state'), 'new');

    await swapBackendEnv(successVenv, successStaging);
    assert.strictEqual(fs.readFileSync(path.join(successVenv, 'state'), 'utf8'), 'new');
    assert.strictEqual(fs.existsSync(`${successVenv}.previous`), false);

    const failureRoot = fs.mkdtempSync(path.join(tmp, 'venv-failure-'));
    const failureVenv = path.join(failureRoot, 'venv');
    fs.mkdirSync(failureVenv);
    fs.writeFileSync(path.join(failureVenv, 'state'), 'last-known-good');

    await assert.rejects(() => swapBackendEnv(failureVenv, path.join(failureRoot, 'missing')));
    assert.strictEqual(
      fs.readFileSync(path.join(failureVenv, 'state'), 'utf8'),
      'last-known-good',
      'staging 激活失败后应恢复旧 venv',
    );

    const recoveryRoot = fs.mkdtempSync(path.join(tmp, 'venv-recovery-'));
    const recoveryVenv = path.join(recoveryRoot, 'venv');
    fs.mkdirSync(`${recoveryVenv}.previous`);
    fs.writeFileSync(path.join(`${recoveryVenv}.previous`, 'state'), 'interrupted-swap');

    await recoverBackendEnvBackup(recoveryVenv);
    assert.strictEqual(fs.readFileSync(path.join(recoveryVenv, 'state'), 'utf8'), 'interrupted-swap');
    assert.strictEqual(fs.existsSync(`${recoveryVenv}.previous`), false);
  });

  await t('10-#13 maintainer 非占位邮箱', () => {
    const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf8'));
    assert.ok(!/example\.(cn|com|org|net)/.test(pkg.build.linux.maintainer),
      `maintainer 不得使用 example 占位域，实际：${pkg.build.linux.maintainer}`);
  });

  await t('10-#14 open-file 编码容错（BOM/二进制/非法序列）', () => {
    const plain = main.decodeFileBuffer(Buffer.from('你好 wanwei', 'utf8'));
    assert.strictEqual(plain.encoding, 'utf8');
    assert.strictEqual(plain.content, '你好 wanwei');
    const bom = main.decodeFileBuffer(Buffer.concat([Buffer.from([0xEF, 0xBB, 0xBF]), Buffer.from('你好', 'utf8')]));
    assert.strictEqual(bom.encoding, 'utf8');
    assert.strictEqual(bom.content, '你好', 'BOM 应被剥离');
    const bin = main.decodeFileBuffer(Buffer.from([0x89, 0x50, 0x4E, 0x47, 0x00, 0x01]));
    assert.strictEqual(bin.encoding, 'base64', '含 NUL 的二进制应走 base64');
    assert.strictEqual(Buffer.from(bin.content, 'base64')[4], 0x00);
    const lossy = main.decodeFileBuffer(Buffer.from([0xFF, 0xFE, 0x41]));
    assert.strictEqual(lossy.encoding, 'utf8-lossy', '非法 UTF-8 应回退并标注');
  });

  let failed = 0;
  for (const [status, name] of results) {
    if (status === 'FAIL') failed += 1;
    console.log(`${status === 'PASS' ? '✅' : '❌'} ${name}`);
  }
  try { fs.rmSync(tmp, { recursive: true, force: true }); } catch { /* ignore */ }
  console.log(failed === 0 ? `\n全部 ${results.length} 项通过` : `\n${failed}/${results.length} 项失败`);
  process.exit(failed === 0 ? 0 : 1);
})();
