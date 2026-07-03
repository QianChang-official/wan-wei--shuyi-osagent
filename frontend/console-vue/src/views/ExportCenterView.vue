<script setup lang="ts">
import { onMounted, shallowRef } from 'vue'
import { api, type ExportPackage } from '@/api/client'

const packages = shallowRef<ExportPackage[]>([])
const error = shallowRef('')

onMounted(async () => {
  try {
    packages.value = (await api.exportPackages()).items
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
})

function statusName(status: string) {
  return status === 'partial' ? '部分完成' : status === 'pending' ? '待补齐' : '已完成'
}
</script>

<template>
  <div>
    <div class="page-head">
      <h1>云笈导出舱</h1>
      <p>PPT / 技术方案 / 测试报告 / 用户手册 / 适配测试报告 / 演示脚本</p>
    </div>
    <div v-if="error" class="muted">{{ error }}</div>

    <div class="package-grid">
      <article v-for="pack in packages" :key="pack.id" class="package" :class="pack.status">
        <div class="package-head">
          <h2>{{ pack.name_cn }}</h2>
          <span>{{ statusName(pack.status) }}</span>
        </div>
        <code>{{ pack.id }}</code>
        <div class="evidence">
          <b>证据文件</b>
          <p v-if="pack.evidence_files.length === 0">pending：尚无可声明文件</p>
          <p v-for="file in pack.evidence_files" :key="file">{{ file }}</p>
        </div>
        <div class="demo-path">{{ pack.demo_path }}</div>
      </article>
    </div>
  </div>
</template>

<style scoped>
.page-head { margin-bottom: 24px; }
.page-head h1 { font-size: 28px; letter-spacing: 3px; }
.page-head p, .muted { color: var(--ink-soft); font-size: 13px; margin-top: 5px; }
.package-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 13px; }
.package { border: 1px solid var(--line); border-top: 4px solid var(--mineral); background: rgba(255,255,255,.36); padding: 14px; min-height: 238px; }
.package.pending { border-top-color: var(--cinnabar); }
.package-head { display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; }
.package-head h2 { font-size: 15px; letter-spacing: 1px; }
.package-head span { white-space: nowrap; border: 1px solid currentColor; color: var(--cinnabar); font-size: 10px; padding: 2px 6px; }
code { display: block; margin: 8px 0 12px; color: var(--mineral); font-size: 11px; }
.evidence b { display: block; font-size: 11px; color: var(--gamboge); margin-bottom: 7px; }
.evidence p { color: var(--ink-soft); font-size: 11.5px; line-height: 1.45; word-break: break-all; margin-bottom: 5px; }
.demo-path { margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--line-soft); color: var(--cinnabar); font-family: var(--mono); font-size: 11px; word-break: break-all; }
@media (max-width: 1200px) { .package-grid { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 800px) { .package-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 560px) { .package-grid { grid-template-columns: 1fr; } }
</style>
