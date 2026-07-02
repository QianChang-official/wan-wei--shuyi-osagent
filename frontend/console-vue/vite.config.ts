import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  base: '/console/',
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: {
      '/health': 'http://127.0.0.1:8010',
      '/memory': 'http://127.0.0.1:8010',
      '/audit':  'http://127.0.0.1:8010',
    },
  },
  build: { outDir: 'dist', emptyOutDir: true },
})
