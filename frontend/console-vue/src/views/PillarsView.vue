<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import { usePlatformModules } from '@/composables/usePlatformModules'

const { modules, loading, error, statusCounts } = usePlatformModules()
const mode = shallowRef<'all' | 'core' | 'v07'>('all')

const visibleModules = computed(() => {
  if (mode.value === 'core') return modules.value.filter((item) => !item.pillar.includes('v0.7'))
  if (mode.value === 'v07') return modules.value.filter((item) => item.pillar.includes('v0.7'))
  return modules.value
})

const PRINCIPLES = [
  'Memory is a control plane. 记忆是 Agent 行为控制平面。',
  'No memory without provenance. 没有来源证明的记忆不得长期化。',
  'No personalization without governance. 没有治理的个性化就是风险。',
  'No retrieval without trust. 检索不能只看相关性，必须看可信度。',
  'No deletion without verification. 遗忘必须可验证。',
  'No automation without status labels. 未实现能力必须标 partial/planned/pending。',
]

function sealOf(name: string) {
  return name.slice(0, 1)
}
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>主线架构</h1>
        <p>祖宗模块不可删，只能加；v0.7 扩展为 20 舱 MemoryOps Studio。</p>
      </div>
      <div class="status-panel">
        <span>done（已完成）{{ statusCounts.done }}</span>
        <span>partial（部分）{{ statusCounts.partial }}</span>
        <span>planned（计划中）{{ statusCounts.planned }}</span>
      </div>
    </div>

    <div class="mode-tabs">
      <button :class="{ active: mode === 'all' }" @click="mode = 'all'">全部 20 舱</button>
      <button :class="{ active: mode === 'core' }" @click="mode = 'core'">祖宗主线</button>
      <button :class="{ active: mode === 'v07' }" @click="mode = 'v07'">v0.7 新增</button>
    </div>

    <div v-if="loading" class="muted">加载舱室...</div>
    <div v-else-if="error" class="muted">{{ error }}</div>
    <div v-else class="grid20">
      <div v-for="p in visibleModules" :key="p.id" class="pillar" :class="p.status">
        <div class="p-stamp">{{ sealOf(p.name_cn) }}</div>
        <div class="p-cn">{{ p.name_cn }}</div>
        <div class="p-fn">{{ p.name_en }}</div>
        <p class="p-desc">{{ p.description }}</p>
        <div class="p-mod">{{ p.status }} · {{ p.backend_refs[0] }}</div>
      </div>
    </div>

    <div class="principle">
      <h3>六条架构原则</h3>
      <ol>
        <li v-for="item in PRINCIPLES" :key="item">{{ item }}</li>
      </ol>
    </div>
  </div>
</template>

<style scoped>
.page-head { display: flex; justify-content: space-between; gap: 20px; align-items: flex-end; margin-bottom: 22px; }
.page-head h1 { font-size: 28px; font-weight: 700; letter-spacing: 3px; }
.page-head p { font-size: 13px; color: var(--ink-soft); margin-top: 4px; }
.status-panel { display: grid; grid-template-columns: repeat(3, 1fr); border: 1px solid var(--line); background: rgba(28,26,23,.04); }
.status-panel span { padding: 10px 12px; border-left: 1px solid var(--line-soft); font-family: var(--mono); font-size: 11px; color: var(--ink-soft); }
.status-panel span:first-child { border-left: 0; }
.mode-tabs { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 18px; }
.mode-tabs button { border: 1px solid var(--line); background: rgba(255,255,255,.38); color: var(--ink-soft); padding: 8px 12px; }
.mode-tabs button.active { border-color: var(--cinnabar); color: var(--cinnabar); background: rgba(178,58,46,.08); }
.muted { color: var(--ink-soft); }
.grid20 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
.pillar { border: 1px solid var(--line); background: rgba(255,255,255,.38); padding: 16px 14px; position: relative; min-height: 216px; border-top: 4px solid var(--mineral); }
.pillar.partial { border-top-color: var(--gamboge); }
.pillar.planned { border-top-color: var(--ink-soft); opacity: .86; }
.p-stamp { position: absolute; top: 12px; right: 12px; width: 34px; height: 34px; border: 2px solid var(--cinnabar); border-radius: 5px; display: grid; place-items: center; font-size: 15px; font-weight: 700; color: var(--cinnabar); }
.p-cn { font-size: 17px; font-weight: 700; letter-spacing: 2px; }
.p-fn { font-size: 11px; color: var(--mineral); margin: 5px 0 8px; font-family: Georgia, serif; letter-spacing: 1px; }
.p-desc { font-size: 12.5px; color: var(--ink-soft); line-height: 1.62; margin-right: 34px; }
.p-mod { position: absolute; left: 14px; right: 14px; bottom: 12px; font-size: 10.5px; color: var(--gamboge); font-family: var(--mono); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.principle { margin-top: 32px; border: 1px solid var(--line); background: rgba(255,255,255,.38); padding: 20px 24px; border-left: 4px solid var(--cinnabar); }
.principle h3 { font-size: 16px; letter-spacing: 2px; margin-bottom: 12px; }
.principle ol { padding-left: 20px; }
.principle li { font-size: 13.5px; color: var(--ink-soft); margin-bottom: 6px; line-height: 1.6; }
.principle li::marker { color: var(--cinnabar); font-weight: 700; }
@media (max-width: 1200px) { .grid20 { grid-template-columns: repeat(3,1fr); } }
@media (max-width: 900px) { .page-head { display: block; } .status-panel { margin-top: 14px; } .grid20 { grid-template-columns: repeat(2,1fr); } }
@media (max-width: 560px) { .grid20 { grid-template-columns: 1fr; } }
</style>
