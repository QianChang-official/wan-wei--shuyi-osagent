<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api } from '@/api/client'

const metrics = ref<Record<string,any> | null>(null)
const loading = ref(true)
const err = ref('')

const META: Record<string, { cn: string; danger?: boolean; warn?: boolean }> = {
  assertion_pass_rate:         { cn: '断言通过率' },
  unsafe_autonomy_rate:        { cn: '越权自动化率', danger: true },
  evidence_card_coverage_rate: { cn: '证据卡覆盖率' },
  policy_gate_hit_rate:        { cn: '策略门命中率' },
  lifecycle_correct_rate:      { cn: '生命周期正确率' },
  memory_reuse_success_rate:   { cn: '记忆复用率', warn: true },
  post_reflection_update_rate: { cn: '复盘更新率' },
  misleading_memory_rate:      { cn: '误导记忆率', warn: true },
}

function fmt(v: any) {
  if (v === 'pending') return '待测'
  if (typeof v === 'number') return v % 1 !== 0 ? (v * 100).toFixed(1) + '%' : String(v)
  return String(v)
}

onMounted(async () => {
  try {
    // try loading from static report file first
    const r = await fetch('../../reports/production_memory_eval_metrics.json')
    metrics.value = r.ok ? await r.json() : null
  } catch { metrics.value = null }
  loading.value = false
})
</script>

<template>
  <div>
    <div class="page-head">
      <h1>总览 · 兰台鉴证</h1>
      <p>v0.6 Production MemoryArena-Lite 真实运行指标</p>
    </div>
    <div v-if="loading" class="muted">加载中…</div>
    <div v-else-if="!metrics" class="muted">无法加载指标（运行 ./scripts/run_eval.sh 后刷新）</div>
    <template v-else>
      <div class="kv-row">
        <div class="kv-card accent">
          <div class="kv-v">{{ metrics.total_cases }}</div>
          <div class="kv-k">cases</div>
        </div>
        <div class="kv-card accent">
          <div class="kv-v">{{ metrics.assertions_passed }}<span class="kv-of">/{{ metrics.total_assertions }}</span></div>
          <div class="kv-k">assertions</div>
        </div>
      </div>
      <div class="metrics-grid">
        <div v-for="(meta, key) in META" :key="key"
          class="metric-card"
          :class="{ danger: meta.danger && metrics[key] > 0, warn: meta.warn && metrics[key] !== 'pending' && metrics[key] < 0.6 }">
          <div class="mc-v" :class="{ pending: metrics[key] === 'pending' }">{{ fmt(metrics[key]) }}</div>
          <div class="mc-k-en">{{ key }}</div>
          <div class="mc-k-cn">{{ meta.cn }}</div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.page-head { margin-bottom: 28px; }
.page-head h1 { font-size: 28px; font-weight: 700; letter-spacing: 3px; color: var(--ink); }
.page-head p { font-size: 13px; color: var(--ink-soft); margin-top: 4px; }
.muted { color: var(--ink-soft); font-size: 13px; }
.kv-row { display: flex; gap: 16px; margin-bottom: 22px; }
.kv-card { border: 1px solid var(--line); background: rgba(255,255,255,.4); padding: 14px 22px; }
.kv-card.accent { border-left: 4px solid var(--cinnabar); }
.kv-v { font-size: 42px; font-weight: 700; font-family: Georgia, serif; color: var(--cinnabar); line-height: 1; }
.kv-of { font-size: 20px; color: var(--ink-soft); }
.kv-k { font-size: 12px; color: var(--ink-soft); margin-top: 4px; font-family: var(--mono); }
.metrics-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
.metric-card { border: 1px solid var(--line); border-top: 3px solid var(--mineral); background: rgba(255,255,255,.35); padding: 14px; }
.metric-card.danger { border-top-color: var(--cinnabar); }
.metric-card.warn { border-top-color: var(--gamboge); }
.mc-v { font-size: 26px; font-weight: 700; font-family: Georgia, serif; color: var(--mineral); }
.mc-v.pending { font-size: 16px; color: var(--gamboge); }
.metric-card.danger .mc-v { color: var(--cinnabar); }
.mc-k-en { font-size: 10.5px; color: var(--ink-soft); font-family: var(--mono); margin-top: 6px; word-break: break-all; }
.mc-k-cn { font-size: 12px; color: var(--mineral); margin-top: 2px; }
@media (max-width: 900px) { .metrics-grid { grid-template-columns: repeat(2, 1fr); } }
</style>
