// Copyright (c) 2026 QianChang-official
//
// 宛委·枢忆 is licensed under Mulan PSL v2.
// You can use this software according to the terms of the Mulan PSL v2.
// You may obtain a copy of Mulan PSL v2 at:
// http://license.coscl.org.cn/MulanPSL2
//
// THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
// EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
// MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
// See the Mulan PSL v2 for more details.

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'
import { readFileSync } from 'node:fs'

const backend = 'http://127.0.0.1:8010'

// 同时服务默认工作台与保留的高级工具。
const apiPrefixes = [
  '/health', '/arena', '/memory', '/audit', '/platform', '/security',
  '/model-gateway', '/tool-registry', '/tuning', '/exports',
  '/research-adoption', '/workflow', '/reproduction', '/deepening', '/soul',
]

const { version } = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf-8'))

export default defineConfig(({ command }) => ({
  plugins: [vue()],
  base: '/console/',
  define: {
    'import.meta.env.VITE_WANWEI_DEV_API_KEY': JSON.stringify(
      command === 'serve' ? 'wanwei-dev-key' : '',
    ),
    __APP_VERSION__: JSON.stringify(version),
  },
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: Object.fromEntries(apiPrefixes.map((prefix) => [prefix, backend])),
  },
  build: { outDir: 'dist', emptyOutDir: true },
}))
