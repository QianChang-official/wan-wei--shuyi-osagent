/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}

declare module '*.css'

/** 构建期由 vite.config.ts 注入：控制台版本号（与 package.json 同源） */
declare const __APP_VERSION__: string
