<script setup lang="ts">
import { computed, onMounted, shallowRef } from 'vue'
import { api, type AdoptionRoute, type ResearchTechnology, type VersionMapping } from '@/api/client'
import PageHero from '@/components/gf/PageHero.vue'
import GfCard from '@/components/gf/GfCard.vue'
import GfTag from '@/components/gf/GfTag.vue'
import GfStat from '@/components/gf/GfStat.vue'
import GfEmpty from '@/components/gf/GfEmpty.vue'
import InkDivider from '@/components/gf/InkDivider.vue'

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

type GfTone = 'rouge' | 'dai' | 'bamboo' | 'gold' | 'ink'
function statusTone(status: string): GfTone {
  const tones: Record<string, GfTone> = { done: 'bamboo', partial: 'gold', planned: 'dai', pending: 'rouge' }
  return tones[status] ?? 'ink'
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
    <PageHero
      seal="研"
      title="权威吸收"
      en="Research Adoption"
      sub="v0.8 权威技术吸收 · 研究雷达 / 技术吸收仪表盘"
    />

    <div class="stat-row">
      <GfStat label="A 级来源" :value="sourceCounts.A" tone="rouge" />
      <GfStat label="B 级来源" :value="sourceCounts.B" tone="dai" />
      <GfStat label="部分吸收" :value="statusCounts.partial" tone="gold" />
      <GfStat label="规划中" :value="statusCounts.planned" tone="ink" />
    </div>

    <section class="radar-board" aria-hidden="true">
      <div class="radar-core">
        <b>v0.8</b>
        <span>权威技术吸收</span>
      </div>
      <div class="radar-ring ring-a">MemoryArena · MemOS · Reflexion</div>
      <div class="radar-ring ring-b">MemoryBank · HippoRAG · LoCoMo</div>
      <div class="radar-ring ring-c">MemGPT · Generative Agents · AgeMem</div>
    </section>

    <div class="filters">
      <button class="filter-btn" :class="{ active: selectedLevel === 'all' }" @click="selectedLevel = 'all'">全部</button>
      <button
        v-for="level in ['A', 'B', 'C', 'D']"
        :key="level"
        class="filter-btn"
        :class="{ active: selectedLevel === level }"
        @click="selectedLevel = level"
      >
        {{ level }} 级来源
      </button>
    </div>

    <GfEmpty v-if="loading" text="研墨中，正在加载权威技术矩阵…" />
    <p v-else-if="error" class="error-note">{{ error }}</p>
    <GfEmpty v-else-if="!filteredTechnologies.length" text="此级别下暂无技术条目" />
    <template v-else>
      <section class="tech-grid">
        <GfCard v-for="item in filteredTechnologies" :key="item.id">
          <div class="tech-top">
            <div>
              <h2 class="tech-name">{{ item.name }}</h2>
              <p class="tech-pub">{{ item.publication_status }}</p>
            </div>
            <span class="level-seal">{{ item.source_level }}</span>
          </div>
          <div class="ratio"><i :style="{ width: percent(item.adoption_ratio) }"></i><b>{{ percent(item.adoption_ratio) }}</b></div>
          <p class="idea">{{ item.core_idea }}</p>
          <div class="sources">
            <a v-for="(url, index) in item.source_urls" :key="url" :href="url" target="_blank" rel="noreferrer">
              来源 {{ index + 1 }}
            </a>
          </div>
          <div class="chip-list"><GfTag v-for="mod in item.target_modules" :key="mod" tone="dai">{{ mod }}</GfTag></div>
          <div class="status-line"><GfTag :tone="statusTone(item.current_status)">{{ statusName(item.current_status) }}</GfTag></div>
          <div class="action-block">
            <b>v0.8 动作</b>
            <ul><li v-for="action in item.v08_actions" :key="action">{{ action }}</li></ul>
          </div>
          <div class="action-block risk">
            <b>v0.9 收敛</b>
            <ul><li v-for="risk in item.v09_risk_controls" :key="risk">{{ risk }}</li></ul>
          </div>
        </GfCard>
      </section>

      <section class="section">
        <h2 class="sec-title">五大落地路线</h2>
        <div class="route-grid">
          <GfCard v-for="route in routes" :key="route.route_id" :title="route.name_cn">
            <div class="route-meta">
              <code class="code-line">{{ route.route_id }}</code>
              <GfTag :tone="statusTone(route.status)">{{ route.status }}</GfTag>
            </div>
            <p class="route-impact">{{ route.expected_impact }}</p>
            <div class="plan-columns">
              <div><b>后端</b><span v-for="p in route.backend_plan" :key="p">{{ p }}</span></div>
              <div><b>前端</b><span v-for="p in route.frontend_plan" :key="p">{{ p }}</span></div>
              <div><b>竞技场</b><span v-for="p in route.arena_plan" :key="p">{{ p }}</span></div>
            </div>
          </GfCard>
        </div>
      </section>

      <section class="section">
        <InkDivider label="版本依据图" />
        <div class="lineage-rail">
          <article v-for="item in versionMap" :key="item.version" class="lineage-step">
            <span class="lineage-dot" aria-hidden="true"></span>
            <div class="version-card">
              <span class="version-mark">{{ item.version }}</span>
              <h3>{{ item.positioning }}</h3>
              <div class="chip-list"><GfTag v-for="support in item.authoritative_support" :key="support" tone="ink">{{ support }}</GfTag></div>
              <p><b>已完成</b>{{ item.completed.join(' / ') }}</p>
              <p><b>未完成</b>{{ item.unfinished.join(' / ') }}</p>
            </div>
          </article>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.stat-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; }
.section { margin-top: 26px; }
.error-note {
  margin-top: 18px;
  padding: 12px 16px;
  border-radius: var(--radius-small);
  border: 1px solid var(--line-cinnabar);
  background: color-mix(in srgb, var(--cinnabar) 8%, transparent);
  color: var(--cinnabar);
  font-size: 13px;
}
.sec-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-family: var(--font-kai);
  font-size: 22px;
  letter-spacing: 4px;
  color: var(--ink);
  margin-bottom: 14px;
}
.sec-title::before {
  content: '';
  width: 11px;
  height: 11px;
  border-radius: 3px;
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  box-shadow: 0 0 8px var(--rouge-glow);
  flex-shrink: 0;
}

/* 研究雷达：月洞门 + 金环 */
.radar-board {
  position: relative;
  min-height: 250px;
  margin-top: 20px;
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  background:
    radial-gradient(420px 200px at 50% 46%, var(--rouge-glow), transparent 70%),
    var(--card);
  backdrop-filter: blur(8px);
  box-shadow: var(--shadow-card);
  overflow: hidden;
}
.radar-core {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 122px;
  height: 122px;
  border-radius: 50%;
  border: 1px solid var(--gold-line);
  box-shadow: 0 0 0 6px color-mix(in srgb, var(--gold-line) 35%, transparent), var(--shadow-glow-rouge);
  display: grid;
  place-items: center;
  align-content: center;
  gap: 4px;
  background: var(--card-solid);
  text-align: center;
}
.radar-core b { font-family: var(--font-kai); font-size: 26px; color: var(--cinnabar); line-height: 1; letter-spacing: 2px; }
.radar-core span { font-size: 11px; letter-spacing: 2px; color: var(--ink-muted); }
.radar-ring {
  position: absolute;
  border: 1px solid var(--line);
  border-radius: var(--radius-pill);
  background: var(--card);
  color: var(--ink-soft);
  font-family: var(--font-mono);
  font-size: 11.5px;
  padding: 7px 14px;
  box-shadow: var(--shadow-card);
  white-space: nowrap;
}
.ring-a { top: 26px; left: 50%; transform: translateX(-50%); color: var(--cinnabar); border-color: var(--line-cinnabar); }
.ring-b { bottom: 26px; left: 9%; color: var(--dai); }
.ring-c { bottom: 26px; right: 9%; color: var(--gold); }

.filters { display: flex; gap: 10px; flex-wrap: wrap; margin: 20px 0; }
.filter-btn {
  border: 1px solid var(--line);
  background: var(--card);
  color: var(--ink-soft);
  border-radius: var(--radius-pill);
  padding: 6px 16px;
  font-size: 12px;
  letter-spacing: 1px;
  font-family: var(--font-kai);
  transition: border-color .18s ease, color .18s ease, box-shadow .18s ease, background .18s ease;
}
.filter-btn:hover { border-color: var(--rouge); color: var(--cinnabar); }
.filter-btn.active {
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  border-color: transparent;
  color: #FDF6E9;
  box-shadow: 0 2px 10px var(--cinnabar-glow);
}

.tech-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; }
.tech-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.tech-name { font-size: 16px; font-family: var(--font-mono); color: var(--ink); }
.tech-pub { color: var(--dai); font-size: 11px; margin-top: 4px; }
.level-seal {
  width: 36px;
  height: 36px;
  flex-shrink: 0;
  display: grid;
  place-items: center;
  border-radius: var(--radius-seal);
  font-family: var(--font-kai);
  font-weight: 700;
  font-size: 16px;
  color: #FDF6E9;
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  box-shadow: 0 0 12px var(--cinnabar-glow);
}
.ratio {
  position: relative;
  height: 20px;
  border-radius: var(--radius-pill);
  background: var(--line-soft);
  overflow: hidden;
  margin: 14px 0;
}
.ratio i {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  border-radius: var(--radius-pill);
  background: linear-gradient(90deg, var(--rouge), var(--gold));
}
.ratio b {
  position: absolute;
  right: 10px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 11px;
  color: var(--ink);
  font-family: var(--font-mono);
}
.idea { color: var(--ink-soft); font-size: 12.5px; line-height: 1.7; min-height: 58px; }
.sources { display: flex; flex-wrap: wrap; gap: 10px; margin: 10px 0; }
.sources a { color: var(--dai); font-size: 10.5px; border-bottom: 1px solid var(--gold-line); transition: color .18s ease, border-color .18s ease; }
.sources a:hover { color: var(--cinnabar); border-color: var(--cinnabar); }
.chip-list { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; }
.status-line { margin: 6px 0 2px; }
.action-block { border-top: 1px solid var(--line-soft); padding-top: 10px; margin-top: 10px; }
.action-block b { display: block; color: var(--gold); font-size: 11px; letter-spacing: 2px; margin-bottom: 6px; }
.action-block.risk b { color: var(--cinnabar); }
ul { padding-left: 16px; }
li { color: var(--ink-soft); font-size: 11.5px; line-height: 1.55; margin-bottom: 4px; }

.route-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 20px; }
.route-meta { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.code-line { color: var(--dai); font-size: 11px; font-family: var(--font-mono); }
.route-impact { color: var(--ink-soft); font-size: 12.5px; line-height: 1.7; margin: 10px 0; }
.plan-columns { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 12px; }
.plan-columns > div { border: 1px solid var(--line-soft); border-radius: var(--radius-small); background: var(--line-soft); padding: 10px; }
.plan-columns b { display: block; font-size: 11px; letter-spacing: 2px; color: var(--gold); margin-bottom: 6px; font-family: var(--font-kai); }
.plan-columns span { display: block; color: var(--ink-soft); font-size: 10.5px; line-height: 1.5; margin-bottom: 4px; }

/* 版本依据图：朱砂圆点 + 金线 */
.lineage-rail {
  position: relative;
  display: grid;
  grid-template-columns: repeat(4, minmax(200px, 1fr));
  gap: 14px;
  padding-top: 26px;
  overflow-x: auto;
  padding-bottom: 4px;
}
.lineage-rail::before {
  content: '';
  position: absolute;
  top: 8px;
  left: 48px;
  right: 48px;
  height: 2px;
  background: linear-gradient(90deg, transparent, var(--gold-line) 10%, var(--gold-line) 90%, transparent);
}
.lineage-step { position: relative; min-width: 0; }
.lineage-dot {
  position: absolute;
  top: -24px;
  left: 50%;
  transform: translateX(-50%);
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--cinnabar);
  border: 2px solid var(--card-solid);
  box-shadow: 0 0 0 2px var(--gold-line), 0 0 10px var(--rouge-glow);
  z-index: 1;
}
.version-card {
  border: 1px solid var(--line-soft);
  background: var(--card);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
  padding: 14px 16px;
  height: 100%;
}
.version-mark {
  display: inline-block;
  border-radius: var(--radius-pill);
  border: 1px solid var(--line-cinnabar);
  color: var(--cinnabar);
  padding: 2px 12px;
  font-family: var(--font-mono);
  font-size: 11px;
  margin-bottom: 10px;
}
.version-card h3 { font-size: 14px; font-family: var(--font-kai); letter-spacing: 1px; line-height: 1.5; color: var(--ink); margin-bottom: 8px; }
.version-card p { color: var(--ink-soft); font-size: 11.5px; line-height: 1.6; margin-top: 8px; }
.version-card p b { color: var(--gold); margin-right: 6px; font-family: var(--font-kai); letter-spacing: 1px; }

@media (max-width: 1200px) { .tech-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 900px) {
  .route-grid, .tech-grid { grid-template-columns: 1fr; }
  .stat-row { grid-template-columns: repeat(2, 1fr); }
  .plan-columns { grid-template-columns: 1fr; }
  .ring-b { left: 4%; }
  .ring-c { right: 4%; }
}
</style>
