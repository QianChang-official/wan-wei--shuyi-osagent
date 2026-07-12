<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import { usePlatformModules } from '@/composables/usePlatformModules'

const { modules, loading, error, statusCounts, byPillar } = usePlatformModules()
const selected = shallowRef('all')

const filters = computed(() => ['all', ...Object.keys(byPillar.value)])
const visibleModules = computed(() =>
  selected.value === 'all' ? modules.value : byPillar.value[selected.value] ?? [],
)

function statusName(status: string) {
  return status === 'done' ? '已实现' : status === 'partial' ? '部分实现' : '规划中'
}
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>平台舱室总图</h1>
        <p>v0.7 记忆运维自动驾驶平台 · 20 舱生产控制面</p>
      </div>
      <div class="control-strip">
        <span>已完成 {{ statusCounts.done }}</span>
        <span>部分实现 {{ statusCounts.partial }}</span>
        <span>规划中 {{ statusCounts.planned }}</span>
      </div>
    </div>

    <div class="filters">
      <button v-for="filter in filters" :key="filter" :class="{ active: selected === filter }" @click="selected = filter">
        {{ filter === 'all' ? '全部舱室' : filter }}
      </button>
    </div>

    <div v-if="loading" class="muted">加载平台模块中...</div>
    <div v-else-if="error" class="muted">{{ error }}</div>
    <div v-else class="module-grid">
      <article v-for="item in visibleModules" :key="item.id" class="module-card" :class="item.status">
        <div class="module-top">
          <div>
            <h2>{{ item.name_cn }}</h2>
            <p>{{ item.name_en }}</p>
          </div>
          <span class="status">{{ statusName(item.status) }}</span>
        </div>
        <p class="desc">{{ item.description }}</p>
        <div class="refs">
          <div>
            <b>后端实现</b>
            <span v-for="ref in item.backend_refs" :key="ref">{{ ref }}</span>
          </div>
          <div>
            <b>竞品参考</b>
            <span v-for="ref in item.competition_refs" :key="ref">{{ ref }}</span>
          </div>
        </div>
      </article>
    </div>
  </div>
</template>

<style scoped>
.page-head { display: flex; justify-content: space-between; gap: 20px; align-items: flex-end; margin-bottom: 22px; }
.page-head h1 { font-size: 28px; letter-spacing: 3px; }
.page-head p { margin-top: 5px; color: var(--ink-soft); font-size: 13px; }
.control-strip { display: grid; grid-template-columns: repeat(3, minmax(92px, 1fr)); border: 1px solid var(--line); background: rgba(28,26,23,.04); }
.control-strip span { padding: 10px 12px; border-left: 1px solid var(--line-soft); font-family: var(--mono); font-size: 11px; color: var(--ink-soft); }
.control-strip span:first-child { border-left: 0; }
.filters { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 18px; }
.filters button { border: 1px solid var(--line); background: rgba(255,255,255,.38); padding: 8px 11px; color: var(--ink-soft); }
.filters button.active { border-color: var(--cinnabar); color: var(--cinnabar); background: rgba(178,58,46,.08); }
.muted { color: var(--ink-soft); }
.module-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 13px; }
.module-card { border: 1px solid var(--line); background: rgba(255,255,255,.38); padding: 14px; min-height: 244px; border-top: 4px solid var(--mineral); }
.module-card.partial { border-top-color: var(--gamboge); }
.module-card.planned { border-top-color: var(--ink-soft); opacity: .86; }
.module-top { display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; }
.module-top h2 { font-size: 16px; letter-spacing: 1px; }
.module-top p { font-size: 10.5px; color: var(--mineral); font-family: Georgia, serif; margin-top: 3px; }
.status { white-space: nowrap; border: 1px solid currentColor; padding: 2px 6px; font-size: 10.5px; color: var(--cinnabar); }
.desc { margin-top: 10px; color: var(--ink-soft); font-size: 12px; line-height: 1.6; min-height: 58px; }
.refs { margin-top: 12px; display: grid; gap: 9px; }
.refs b { display: block; font-family: var(--mono); font-size: 10px; color: var(--gamboge); margin-bottom: 4px; }
.refs span { display: inline-block; margin: 0 5px 5px 0; padding: 2px 5px; border: 1px solid var(--line-soft); font-size: 10.5px; color: var(--ink-soft); background: rgba(255,255,255,.25); }
@media (max-width: 1200px) { .module-grid { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 900px) { .page-head { display: block; } .control-strip { margin-top: 14px; } .module-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 620px) { .module-grid { grid-template-columns: 1fr; } }
</style>
