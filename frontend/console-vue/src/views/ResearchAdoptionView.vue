<script setup lang="ts">
import { computed, onMounted, shallowRef } from 'vue'
import { api, type AdoptionRoute, type ResearchTechnology, type VersionMapping } from '@/api/client'

const technologies = shallowRef<ResearchTechnology[]>([])
const routes = shallowRef<AdoptionRoute[]>([])
const versionMap = shallowRef<VersionMapping[]>([])
const loading = shallowRef(true)
const error = shallowRef('')
const selectedLevel = shallowRef('all')

const filteredTechnologies = computed(() =>
  selectedLevel.value === 'all'
    ? technologies.value
    : technologies.value.filter((item) => item.source_level === selectedLevel.value),
)

const sourceCounts = computed(() => {
  const counts: Record<string, number> = { A: 0, B: 0, C: 0, D: 0 }
  for (const item of technologies.value) counts[item.source_level] = (counts[item.source_level] ?? 0) + 1
  return counts
})

const statusCounts = computed(() => {
  const counts: Record<string, number> = { done: 0, partial: 0, planned: 0, pending: 0 }
  for (const item of technologies.value) counts[item.current_status] = (counts[item.current_status] ?? 0) + 1
  return counts
})

function statusName(status: string) {
  const names: Record<string, string> = { done: '已实现', partial: '部分吸收', planned: '规划中', pending: '待核验' }
  return names[status] ?? status
}

function percent(value: number) {
  return `${Math.round(value * 100)}%`
}

onMounted(async () => {
  loading.value = true
  error.value = ''
  try {
    const [techRes, routeRes, versionRes] = await Promise.all([
      api.researchTechnologies(),
      api.researchRoutes(),
      api.researchVersionMap(),
    ])
    technologies.value = techRes.items
    routes.value = routeRes.items
    versionMap.value = versionRes.items
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>权威吸收舱</h1>
        <p>v0.8 Authoritative Technology Adoption · 研究雷达 / 技术吸收仪表盘</p>
      </div>
      <div class="radar-summary">
        <span>A {{ sourceCounts.A }}</span>
        <span>B {{ sourceCounts.B }}</span>
        <span>partial {{ statusCounts.partial }}</span>
        <span>planned {{ statusCounts.planned }}</span>
      </div>
    </div>

    <section class="radar-board">
      <div class="radar-core">
        <b>v0.8</b>
        <span>权威技术吸收</span>
      </div>
      <div class="radar-ring ring-a">MemoryArena · MemOS · Reflexion</div>
      <div class="radar-ring ring-b">MemoryBank · HippoRAG · LoCoMo</div>
      <div class="radar-ring ring-c">MemGPT · Generative Agents · AgeMem</div>
    </section>

    <div class="filters">
      <button :class="{ active: selectedLevel === 'all' }" @click="selectedLevel = 'all'">全部</button>
      <button v-for="level in ['A', 'B', 'C', 'D']" :key="level" :class="{ active: selectedLevel === level }" @click="selectedLevel = level">
        {{ level }} 级来源
      </button>
    </div>

    <div v-if="loading" class="muted">加载权威技术矩阵...</div>
    <div v-else-if="error" class="muted">{{ error }}</div>
    <template v-else>
      <section class="tech-grid">
        <article v-for="item in filteredTechnologies" :key="item.id" class="tech-card" :class="item.current_status">
          <div class="tech-top">
            <div>
              <h2>{{ item.name }}</h2>
              <p>{{ item.publication_status }}</p>
            </div>
            <span class="level">{{ item.source_level }}</span>
          </div>
          <div class="ratio"><i :style="{ width: percent(item.adoption_ratio) }"></i><b>{{ percent(item.adoption_ratio) }}</b></div>
          <p class="idea">{{ item.core_idea }}</p>
          <div class="sources">
            <a v-for="(url, index) in item.source_urls" :key="url" :href="url" target="_blank" rel="noreferrer">
              来源 {{ index + 1 }}
            </a>
          </div>
          <div class="chips"><span v-for="mod in item.target_modules" :key="mod">{{ mod }}</span></div>
          <div class="status-line">{{ statusName(item.current_status) }}</div>
          <div class="action-block">
            <b>v0.8 动作</b>
            <ul><li v-for="action in item.v08_actions" :key="action">{{ action }}</li></ul>
          </div>
          <div class="action-block risk">
            <b>v0.9 收敛</b>
            <ul><li v-for="risk in item.v09_risk_controls" :key="risk">{{ risk }}</li></ul>
          </div>
        </article>
      </section>

      <section class="section-block">
        <div class="section-title">五大落地路线</div>
        <div class="route-grid">
          <article v-for="route in routes" :key="route.route_id" class="route-card" :class="route.status">
            <h2>{{ route.name_cn }}</h2>
            <code>{{ route.route_id }} · {{ route.status }}</code>
            <p>{{ route.expected_impact }}</p>
            <div class="plan-columns">
              <div><b>Backend</b><span v-for="p in route.backend_plan" :key="p">{{ p }}</span></div>
              <div><b>Frontend</b><span v-for="p in route.frontend_plan" :key="p">{{ p }}</span></div>
              <div><b>Arena</b><span v-for="p in route.arena_plan" :key="p">{{ p }}</span></div>
            </div>
          </article>
        </div>
      </section>

      <section class="section-block">
        <div class="section-title">版本依据图</div>
        <div class="lineage">
          <article v-for="item in versionMap" :key="item.version" class="version-card">
            <div class="version-mark">{{ item.version }}</div>
            <h2>{{ item.positioning }}</h2>
            <div class="support"><span v-for="support in item.authoritative_support" :key="support">{{ support }}</span></div>
            <p><b>已完成</b>{{ item.completed.join(' / ') }}</p>
            <p><b>未完成</b>{{ item.unfinished.join(' / ') }}</p>
          </article>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.page-head { display: flex; justify-content: space-between; align-items: flex-end; gap: 20px; margin-bottom: 22px; }
.page-head h1 { font-size: 28px; letter-spacing: 3px; }
.page-head p { color: var(--ink-soft); font-size: 13px; margin-top: 5px; }
.radar-summary { display: grid; grid-template-columns: repeat(4, minmax(78px, 1fr)); border: 1px solid var(--line); background: rgba(28,26,23,.04); }
.radar-summary span { padding: 10px 12px; border-left: 1px solid var(--line-soft); font-family: var(--mono); font-size: 11px; color: var(--ink-soft); }
.radar-summary span:first-child { border-left: 0; }
.radar-board { position: relative; min-height: 230px; border: 1px solid var(--line); background: radial-gradient(circle at center, rgba(178,58,46,.10), rgba(255,255,255,.28) 42%, rgba(46,90,108,.08)); margin-bottom: 18px; overflow: hidden; }
.radar-core { position: absolute; inset: 74px auto auto 50%; transform: translateX(-50%); width: 118px; height: 82px; border: 2px solid var(--cinnabar); display: grid; place-items: center; background: rgba(255,255,255,.5); }
.radar-core b { font-family: Georgia, serif; font-size: 26px; color: var(--cinnabar); line-height: 1; }
.radar-core span { font-size: 11px; color: var(--ink-soft); }
.radar-ring { position: absolute; left: 50%; transform: translateX(-50%); border: 1px solid var(--line); background: rgba(255,255,255,.42); color: var(--ink-soft); font-family: var(--mono); font-size: 12px; padding: 7px 12px; }
.ring-a { top: 22px; color: var(--cinnabar); }
.ring-b { top: 162px; color: var(--mineral); }
.ring-c { top: 112px; left: 72%; color: var(--gamboge); }
.filters { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 18px; }
.filters button { border: 1px solid var(--line); background: rgba(255,255,255,.38); color: var(--ink-soft); padding: 8px 12px; }
.filters button.active { border-color: var(--cinnabar); color: var(--cinnabar); background: rgba(178,58,46,.08); }
.muted { color: var(--ink-soft); }
.tech-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.tech-card { border: 1px solid var(--line); border-top: 4px solid var(--gamboge); background: rgba(255,255,255,.36); padding: 15px; min-height: 430px; }
.tech-card.planned { border-top-color: var(--ink-soft); }
.tech-card.pending { border-top-color: var(--cinnabar); }
.tech-top { display: flex; justify-content: space-between; gap: 12px; }
.tech-top h2 { font-size: 17px; font-family: var(--mono); }
.tech-top p { color: var(--mineral); font-size: 11px; margin-top: 4px; }
.level { width: 34px; height: 34px; border: 2px solid var(--cinnabar); color: var(--cinnabar); display: grid; place-items: center; font-weight: 700; }
.ratio { position: relative; height: 24px; border: 1px solid var(--line); margin: 14px 0; background: rgba(28,26,23,.04); }
.ratio i { position: absolute; left: 0; top: 0; bottom: 0; background: linear-gradient(90deg, var(--mineral), var(--gamboge)); }
.ratio b { position: absolute; right: 8px; top: 4px; font-size: 11px; color: var(--ink); }
.idea { color: var(--ink-soft); font-size: 12.5px; line-height: 1.58; min-height: 58px; }
.sources { display: flex; flex-wrap: wrap; gap: 6px; margin: 9px 0; }
.sources a { color: var(--mineral); font-size: 10.5px; text-decoration: none; border-bottom: 1px solid currentColor; }
.sources a:hover { color: var(--cinnabar); }
.chips { display: flex; flex-wrap: wrap; gap: 5px; margin: 10px 0; }
.chips span, .support span { border: 1px solid var(--line-soft); background: rgba(255,255,255,.35); color: var(--mineral); padding: 2px 6px; font-size: 10.5px; }
.status-line { color: var(--cinnabar); font-family: var(--mono); font-size: 11px; margin-bottom: 8px; }
.action-block { border-top: 1px solid var(--line-soft); padding-top: 9px; margin-top: 9px; }
.action-block b { display: block; color: var(--gamboge); font-size: 11px; margin-bottom: 5px; }
ul { padding-left: 16px; }
li { color: var(--ink-soft); font-size: 11.5px; line-height: 1.45; margin-bottom: 4px; }
.risk b { color: var(--cinnabar); }
.section-block { margin-top: 30px; }
.section-title { border-left: 4px solid var(--cinnabar); padding-left: 10px; margin-bottom: 12px; font-size: 16px; font-weight: 700; letter-spacing: 2px; }
.route-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; }
.route-card { border: 1px solid var(--line); border-top: 4px solid var(--mineral); background: rgba(255,255,255,.34); padding: 15px; }
.route-card.planned { border-top-color: var(--ink-soft); }
.route-card h2 { font-size: 16px; letter-spacing: 1px; }
.route-card code { display: block; margin: 6px 0 9px; color: var(--mineral); font-size: 11px; }
.route-card p { color: var(--ink-soft); font-size: 12.5px; line-height: 1.55; }
.plan-columns { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 12px; }
.plan-columns b { display: block; font-size: 10px; color: var(--gamboge); margin-bottom: 5px; }
.plan-columns span { display: block; color: var(--ink-soft); font-size: 10.5px; line-height: 1.35; margin-bottom: 4px; }
.lineage { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.version-card { border: 1px solid var(--line); background: rgba(255,255,255,.34); padding: 14px; min-height: 230px; }
.version-mark { display: inline-block; border: 1px solid var(--cinnabar); color: var(--cinnabar); padding: 3px 8px; font-family: var(--mono); font-size: 11px; margin-bottom: 8px; }
.version-card h2 { font-size: 14px; line-height: 1.45; margin-bottom: 8px; }
.support { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 9px; }
.version-card p { color: var(--ink-soft); font-size: 11.5px; line-height: 1.48; margin-bottom: 6px; }
.version-card p b { color: var(--gamboge); margin-right: 6px; }
@media (max-width: 1200px) { .tech-grid { grid-template-columns: repeat(2, 1fr); } .lineage { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 900px) { .page-head { display: block; } .radar-summary { margin-top: 14px; } .route-grid, .tech-grid, .lineage { grid-template-columns: 1fr; } .plan-columns { grid-template-columns: 1fr; } }
</style>
