<script setup lang="ts">
import { onMounted, shallowRef } from 'vue'
import { api, type ExportPackage } from '@/api/client'
import PageHero from '@/components/gf/PageHero.vue'
import GfCard from '@/components/gf/GfCard.vue'
import GfTag from '@/components/gf/GfTag.vue'
import GfEmpty from '@/components/gf/GfEmpty.vue'

const packages = shallowRef<ExportPackage[]>([])
const error = shallowRef('')
const loaded = shallowRef(false)

onMounted(async () => {
  try {
    packages.value = (await api.exportPackages()).items
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loaded.value = true
  }
})

function statusName(status: string) {
  return status === 'partial' ? '部分完成' : status === 'pending' ? '待补齐' : '已完成'
}
</script>

<template>
  <div>
    <PageHero
      seal="笈"
      title="云笈导出舱"
      en="EXPORT CENTER"
      sub="PPT / 技术方案 / 测试报告 / 用户手册 / 适配测试报告 / 演示脚本"
    />
    <div v-if="error" class="notice error" role="alert">{{ error }}</div>

    <div v-if="!loaded && !error" class="muted">研墨中…</div>
    <GfEmpty v-else-if="!packages.length && !error" text="暂无导出包" />

    <div class="package-grid">
      <GfCard v-for="pack in packages" :key="pack.id" class="package" :class="pack.status">
        <div class="package-head">
          <h2>{{ pack.name_cn }}</h2>
          <GfTag :tone="pack.status === 'partial' ? 'gold' : pack.status === 'pending' ? 'rouge' : 'bamboo'">{{ statusName(pack.status) }}</GfTag>
        </div>
        <code>{{ pack.id }}</code>
        <div class="evidence">
          <b>证据文件</b>
          <p v-if="pack.evidence_files.length === 0">待补齐：尚无可声明文件</p>
          <p v-for="file in pack.evidence_files" :key="file">{{ file }}</p>
        </div>
        <div class="demo-path">{{ pack.demo_path }}</div>
      </GfCard>
    </div>
  </div>
</template>

<style scoped>
.notice {
  margin: 0 0 18px;
  padding: 10px 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  font-size: 12px;
}
.notice.error {
  color: var(--cinnabar-deep);
  border-color: var(--line-cinnabar);
  background: color-mix(in srgb, var(--cinnabar) 7%, transparent);
}
.muted { color: var(--ink-soft); font-size: 13px; padding: 14px 0; font-family: var(--font-kai); letter-spacing: 2px; }

.package-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 16px; align-items: stretch; }
.package { border-top: 2px solid var(--line); }
.package.pending { border-top-color: color-mix(in srgb, var(--cinnabar) 55%, transparent); }
.package.partial { border-top-color: color-mix(in srgb, var(--gold) 60%, transparent); }

.package-head { display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; }
.package-head h2 { font-family: var(--font-kai); font-size: 16px; letter-spacing: 2px; color: var(--ink); line-height: 1.4; }
code { display: block; margin: 8px 0 12px; font-family: var(--font-mono); color: var(--dai); font-size: 11px; word-break: break-all; }
.evidence b { display: block; font-size: 11px; letter-spacing: 2px; color: var(--gold); margin-bottom: 7px; }
.evidence p { color: var(--ink-soft); font-size: 11.5px; line-height: 1.5; word-break: break-all; margin-bottom: 5px; }
.demo-path {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--gold-line);
  color: var(--cinnabar);
  font-family: var(--font-mono);
  font-size: 11px;
  word-break: break-all;
}

@media (max-width: 1200px) { .package-grid { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 800px) { .package-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 560px) { .package-grid { grid-template-columns: 1fr; } }
</style>
