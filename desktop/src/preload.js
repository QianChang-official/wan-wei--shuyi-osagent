'use strict';
/**
 * 预加载脚本：以最小受控接口把桌面能力暴露给 Web 控制台。
 * contextIsolation 开启，Web 端业务代码零改动即可运行；
 * 若 Web 端主动调用 window.wanweiDesktop.*，则获得桌面级增强。
 */
const { contextBridge, ipcRenderer } = require('electron');

// 注入桌面运行标识 + API Key（Web 端 client.ts 已有桌面适配钩子：
// 读 localStorage 'wanwei-desktop-api-key'，若存在则跳过登录门）
contextBridge.exposeInMainWorld('wanweiDesktop', {
  isDesktop: true,
  platform: process.platform,

  /** 桌面通知 */
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

  /** 局域网手机控制（配对流程显式触发；开启/关闭均会重启后端切换监听地址） */
  lanEnable: (token) => ipcRenderer.invoke('desktop:lan-enable', { token }),
  lanDisable: () => ipcRenderer.invoke('desktop:lan-disable'),

  /** 浮动工作区小窗：show=true 创建/聚焦，false 销毁 */
  floatingWorkspace: (show) => ipcRenderer.invoke('desktop:floating-workspace', { show }),
});

// DOM 就绪后注入 API Key 与系统深色主题（键名与 Web 端约定一致）
window.addEventListener('DOMContentLoaded', () => {
  try {
    const key = process.env.WANWEI_DESKTOP_API_KEY;
    if (key) localStorage.setItem('wanwei-desktop-api-key', key);
  } catch { /* ignore */ }
});

ipcRenderer.on('desktop:theme-changed', (_e, dark) => {
  try {
    // 键名与 Web 端 gf 组件库约定一致（shared.ts: GF_THEME_KEY = 'gf-theme'）
    localStorage.setItem('gf-theme', dark ? 'night' : 'day');
    document.documentElement.dataset.theme = dark ? 'night' : 'day';
  } catch { /* ignore */ }
});
