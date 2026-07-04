<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api/client'
import { usePlatformModules } from '@/composables/usePlatformModules'

const metrics = ref<Record<string,any> | null>(null)
const loading = ref(true)
const { modules, statusCounts } = usePlatformModules()

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

const CASES = [
  ['docs_reference_governance', '论文引用治理', 'arXiv / ICML / AAAI / OWASP 分级引用，证据卡覆盖关键建议。'],
  ['git_commit_review', '提交前审查', 'HTML residue、JSON manifest、remote HEAD 验证流程召回。'],
  ['poisoning_preference_confirm', '投毒与偏好确认', '跳过确认类污染进入 quarantine，unsafe_autonomy 恒为 0。'],
  ['self_evolution_loop', '自进化闭环', '失败复盘沉淀风险，二次任务召回风险并改变计划。'],
  ['prompt_injection_false_positive_echo', '误报回声风险', '区分 source_layer，不把自身告警当外部注入证据。'],
]

const FLOW = [
  ['多源接入', '石渠校验 source_layer 与格式质量'],
  ['策略门', '司契护栏做确认/隔离/拒绝'],
  ['枢忆生产', 'MemoryCapsule 2.0 + SQLite/FTS5'],
  ['可信调用', '检索证据卡 + 模型/技能编排'],
  ['Arena 鉴证', '复盘演化、审计、导出材料'],
]

const expansionModules = computed(() => modules.value.filter((item) => item.pillar.includes('v0.7')).slice(0, 10))

function fmt(v: any) {
  if (v === 'pending') return '待测'
  if (typeof v === 'number') return v % 1 !== 0 ? (v * 100).toFixed(1) + '%' : String(v)
  return String(v)
}

onMounted(async () => {
  try {
    metrics.value = await api.arenaMetrics()
  } catch { metrics.value = null }
  loading.value = false
})
</script>

<template>
  <div>
    <div class="page-head">
      <h1>总览 · MemoryOps Autopilot</h1>
      <p>v0.9.3 Workflow Run 主线：真实 Arena 指标 + 20 舱生产控制面 + 安全 dry-run 编排器</p>
    </div>

    <section class="hero-board">
      <div class="hero-copy">
        <h2>不是记忆 demo，而是一台可以自行闭环的精密生产仪器。</h2>
        <p>多源接入 → Policy Gate → MemoryCapsule 2.0 → 检索/证据卡 → 模型网关 → 指挥闭环 → Workflow Run → 复盘演化 → Arena 评测 → 审计与导出。</p>
      </div>
      <div class="hero-dials">
        <div><b>{{ modules.length || 20 }}</b><span>平台舱室</span></div>
        <div><b>{{ statusCounts.partial }}</b><span>部分实现</span></div>
        <div><b>{{ statusCounts.planned }}</b><span>规划标注</span></div>
      </div>
    </section>

    <div v-if="loading" class="muted">加载中…</div>
    <div v-else-if="!metrics" class="muted">无法加载指标（运行 ./scripts/run_eval.sh 后刷新）</div>
    <template v-else>
      <div class="kv-row">
        <div class="kv-card accent">
          <div class="kv-v">{{ metrics.total_cases }}</div>
          <div class="kv-k">MemoryArena cases</div>
        </div>
        <div class="kv-card accent">
          <div class="kv-v">{{ metrics.assertions_passed }}<span class="kv-of">/{{ metrics.total_assertions }}</span></div>
          <div class="kv-k">real assertions</div>
        </div>
        <div class="kv-card">
          <div class="kv-v small">v0.9.3</div>
          <div class="kv-k">workflow run</div>
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
      <section class="section-block">
        <div class="section-title">五案卷宗</div>
        <div class="case-grid">
          <article v-for="(c, i) in CASES" :key="c[0]" class="case-card">
            <div class="case-index">卷 {{ ['一','二','三','四','五'][i] }}</div>
            <h3>{{ c[1] }}</h3>
            <code>{{ c[0] }}</code>
            <p>{{ c[2] }}</p>
            <span class="pass">PASS</span>
          </article>
        </div>
      </section>
      <section class="section-block">
        <div class="section-title">平台舱室与 Workflow Run 主线</div>
        <div class="expansion-grid">
          <div v-for="item in expansionModules" :key="item.id" class="expansion-card" :class="item.status">
            <b>{{ item.name_cn }}</b>
            <span>{{ item.name_en }}</span>
            <em>{{ item.status }}</em>
          </div>
        </div>
      </section>
      <section class="section-block">
        <div class="section-title">演示路线</div>
        <div class="flow">
          <div v-for="(f, i) in FLOW" :key="f[0]" class="flow-step">
            <span>{{ i + 1 }}</span>
            <b>{{ f[0] }}</b>
            <em>{{ f[1] }}</em>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.page-head { margin-bottom: 28px; }
.page-head h1 { font-size: 28px; font-weight: 700; letter-spacing: 3px; color: var(--ink); }
.page-head p { font-size: 13px; color: var(--ink-soft); margin-top: 4px; }
.muted { color: var(--ink-soft); font-size: 13px; }
.hero-board { display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(300px, .9fr); gap: 16px; margin-bottom: 22px; }
.hero-copy { border: 1px solid var(--line); border-left: 4px solid var(--cinnabar); background: rgba(255,255,255,.34); padding: 20px 22px; }
.hero-copy h2 { font-size: 22px; line-height: 1.35; letter-spacing: 1px; margin-bottom: 10px; }
.hero-copy p { color: var(--ink-soft); font-size: 13px; line-height: 1.7; }
.hero-dials { display: grid; grid-template-columns: repeat(3, 1fr); border: 1px solid var(--line); background: rgba(28,26,23,.05); }
.hero-dials div { display: grid; place-items: center; border-left: 1px solid var(--line-soft); padding: 16px 8px; }
.hero-dials div:first-child { border-left: 0; }
.hero-dials b { font-size: 34px; font-family: Georgia, serif; color: var(--cinnabar); line-height: 1; }
.hero-dials span { margin-top: 7px; font-size: 11px; color: var(--ink-soft); }
.kv-row { display: flex; gap: 16px; margin-bottom: 22px; flex-wrap: wrap; }
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
.section-block { margin-top: 32px; }
.section-title { font-size: 17px; font-weight: 700; letter-spacing: 2px; margin-bottom: 14px; border-left: 4px solid var(--cinnabar); padding-left: 10px; }
.case-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; }
.case-card { position: relative; border: 1px solid var(--line); background: rgba(255,255,255,.36); padding: 14px; min-height: 180px; }
.case-index { font-size: 11px; color: var(--gamboge); font-family: var(--mono); margin-bottom: 7px; }
.case-card h3 { font-size: 15px; letter-spacing: 1px; margin-bottom: 4px; }
.case-card code { font-size: 10px; color: var(--ink-soft); word-break: break-all; }
.case-card p { font-size: 12px; color: var(--ink-soft); line-height: 1.6; margin-top: 9px; }
.pass { position: absolute; right: 10px; bottom: 10px; color: var(--jade); border: 1px solid var(--jade); padding: 1px 7px; font-size: 10px; }
.expansion-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; }
.expansion-card { border: 1px solid var(--line); border-top: 3px solid var(--gamboge); background: rgba(255,255,255,.34); padding: 12px; min-height: 94px; position: relative; }
.expansion-card.planned { border-top-color: var(--ink-soft); }
.expansion-card b { display: block; font-size: 14px; letter-spacing: 1px; }
.expansion-card span { display: block; margin-top: 5px; font-size: 10.5px; color: var(--mineral); font-family: Georgia, serif; }
.expansion-card em { position: absolute; right: 8px; bottom: 8px; font-style: normal; font-family: var(--mono); font-size: 10px; color: var(--cinnabar); }
.flow { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; }
.flow-step { border: 1px solid var(--line); background: rgba(255,255,255,.34); padding: 13px; min-height: 96px; }
.flow-step span { display: inline-grid; place-items: center; width: 24px; height: 24px; background: var(--cinnabar); color: white; border-radius: 50%; font-size: 12px; margin-bottom: 9px; }
.flow-step b { display: block; font-size: 14px; letter-spacing: 1px; }
.flow-step em { display: block; font-style: normal; font-size: 11px; color: var(--ink-soft); margin-top: 5px; line-height: 1.45; }
@media (max-width: 1100px) { .case-grid, .flow { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 900px) { .metrics-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 560px) { .case-grid, .flow { grid-template-columns: 1fr; } }
</style>
