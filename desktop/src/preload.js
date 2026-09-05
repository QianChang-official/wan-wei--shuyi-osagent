'use strict';

let _apiKey = '';
/**
 * 预加载脚本：以最小受控接口把桌面能力暴露给 Web 控制台。
 * contextIsolation 开启，Web 端业务代码零改动即可运行；
 * 若 Web 端主动调用 window.wanweiDesktop.*，则获得桌面级增强。
 */
const { contextBridge, ipcRenderer } = require('electron');

/** 来源校验：仅控制台自身（本机回环 http 页面）允许写 localStorage，
 *  防止窗口被导航到外站后把 API Key 写进外站 origin 的存储 */
function isConsoleOrigin() {
  try {
    const u = new URL(window.location.href);
    return u.protocol === 'http:' && ['127.0.0.1', 'localhost', '[::1]'].includes(u.hostname);
  } catch { return false; }
}

// 注入桌面运行标识；API Key 通过受信 IPC 拉取后写入本机控制台 origin 的 localStorage。
contextBridge.exposeInMainWorld('wanweiDesktop', {
  isDesktop: true,
  platform: process.platform,
  getApiKey: () => _apiKey,

  /** 桌面通知（主进程侧有节流：10s 内最多 5 条，被丢弃时 resolve false） */
  notify: (title, body) => ipcRenderer.invoke('desktop:notify', { title, body }),

  /** 本地文件访问（主进程弹出系统对话框） */
  openFile: (options) => ipcRenderer.invoke('desktop:open-file', options || {}),
  saveFile: (options) => ipcRenderer.invoke('desktop:save-file', options || {}),
  showItemInFolder: (p) => ipcRenderer.invoke('desktop:show-item', p),

  /** 运行信息：版本/端口/Web 地址/数据目录 */
  info: () => ipcRenderer.invoke('desktop:info'),

  /** 开机自启动 */
  getAutostart: () => ipcRenderer.invoke('desktop:get-autostart'),
  setAutostart: (enable) => ipcRenderer.invoke('desktop:set-autostart', enable),

  /** 防睡眠：enable 开关，mode 'app'（阻止挂起，默认）| 'display'（含屏幕常亮） */
  setPreventSleep: (enable, mode) => ipcRenderer.invoke('desktop:set-prevent-sleep', { enable, mode }),
  getPreventSleep: () => ipcRenderer.invoke('desktop:get-prevent-sleep'),


  /** 浮动工作区小窗：show=true 创建/聚焦，false 销毁 */
});

// API Key 注入（键名与 Web 端约定一致：localStorage 'wanwei-desktop-api-key'，
// client.ts / platform.ts 的模块级 _loadApiKey() 在页面脚本执行时同步读取）。
// 仅控制台自身 origin 允许写入（外站页面即使意外加载本 preload 也拿不到钥匙）。
function injectDesktopApiKey() {
  if (!isConsoleOrigin()) return;
  try {
    // 同步通道：preload 运行于 document_start，先于页面模块脚本执行，
    // 保证写入早于 Web 端首次读取，消除首启登录门读到空 key 的时序竞争。
    const key = ipcRenderer.sendSync('desktop:api-key-sync');
    if (key) _apiKey = key;
  } catch { /* ignore */ }
}

// 异步兜底：同步通道不可用（异常/旧主进程）时 DOM 就绪后再尝试一次；
// 已成功注入时为同值幂等覆盖，无副作用。
function injectDesktopApiKeyAsync() {
  if (!isConsoleOrigin()) return Promise.resolve();
  return ipcRenderer.invoke('desktop:api-key')
    .then((key) => {
      if (key) _apiKey = key;
    })
    .catch(() => { /* ignore */ });
}

injectDesktopApiKey();

// DOM 就绪后做 API Key 异步兜底注入与系统深色主题同步
window.addEventListener('DOMContentLoaded', () => {
  injectDesktopApiKeyAsync();
});

ipcRenderer.on('desktop:theme-changed', (_e, dark) => {
  if (!isConsoleOrigin()) return;
  try {
    // 键名与 Web 端 gf 组件库约定一致（shared.ts: GF_THEME_KEY = 'gf-theme'）
    localStorage.setItem('gf-theme', dark ? 'night' : 'day');
    document.documentElement.dataset.theme = dark ? 'night' : 'day';
  } catch { /* ignore */ }
});

// 仅供自检脚本使用（WANWEI_DESKTOP_TEST_EXPORTS=1），正常 Electron 运行无任何导出
if (process.env.WANWEI_DESKTOP_TEST_EXPORTS === '1') {
  module.exports = { isConsoleOrigin, injectDesktopApiKey, injectDesktopApiKeyAsync };
}
