<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import { usePlatformModules } from '@/composables/usePlatformModules'
import PageHero from '@/components/gf/PageHero.vue'
import GfStat from '@/components/gf/GfStat.vue'
import GfTag from '@/components/gf/GfTag.vue'
import GfEmpty from '@/components/gf/GfEmpty.vue'

const { modules, loading, error, statusCounts, byPillar } = usePlatformModules()
const selected = shallowRef('all')

const filters = computed(() => ['all', ...Object.keys(byPillar.value)])
const visibleModules = computed(() =>
  selected.value === 'all' ? modules.value : byPillar.value[selected.value] ?? [],
)

function statusName(status: string) {
  return status === 'done' ? '已实现' : status === 'partial' ? '部分实现' : '规划中'
}

function statusTone(status: string): 'bamboo' | 'gold' | 'dai' {
  return status === 'done' ? 'bamboo' : status === 'partial' ? 'gold' : 'dai'
}
</script>

<template>
  <div class="platform">
    <PageHero
      seal="舱"
      title="平台舱室总图"
      en="Platform · Twenty Cabins"
      sub="v0.7 记忆运维自动驾驶平台 · 20 舱生产控制面"
    />

    <!-- 状态统计带 -->
    <div class="stat-band">
      <GfStat label="已完成" :value="statusCounts.done" tone="bamboo" hint="done" />
      <GfStat label="部分实现" :value="statusCounts.partial" tone="gold" hint="partial" />
      <GfStat label="规划中" :value="statusCounts.planned" tone="dai" hint="planned" />
    </div>

    <!-- 舱群签 -->
    <div class="filters">
      <button v-for="filter in filters" :key="filter" :class="{ active: selected === filter }" @click="selected = filter">
        {{ filter === 'all' ? '全部舱室' : filter }}
      </button>
    </div>

    <div v-if="loading" class="state-row">
      <span class="ldot"></span><span class="ldot"></span><span class="ldot"></span>
      <span>研墨中，正在加载平台模块…</span>
    </div>
    <GfEmpty v-else-if="error" :text="error" />
    <GfEmpty v-else-if="!visibleModules.length" text="此舱群暂无舱室" />
    <div v-else class="module-grid">
      <article v-for="item in visibleModules" :key="item.id" class="module-card" :class="item.status">
        <span class="m-bloom" aria-hidden="true"></span>
        <div class="module-top">
          <div>
            <h2>{{ item.name_cn }}</h2>
            <p>{{ item.name_en }}</p>
          </div>
          <GfTag :tone="statusTone(item.status)">{{ statusName(item.status) }}</GfTag>
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
.platform { max-width: 1200px; position: relative; }

/* ══ 统计带 ══ */
.stat-band {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
  margin-bottom: 24px;
}

/* ══ 舱群签（全圆角） ══ */
.filters { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 22px; }
.filters button {
  border: 1px solid var(--line);
  background: var(--card);
  color: var(--ink-soft);
  padding: 8px 16px;
  border-radius: 999px;
  font-size: 12px;
  letter-spacing: 1px;
  font-family: var(--font-kai);
  transition: all .22s ease;
}
.filters button:hover { border-color: var(--gold-line); transform: translateY(-2px); }
.filters button.active {
  border-color: transparent;
  color: #FDF6E9;
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  box-shadow: var(--shadow-glow-rouge);
}

/* ══ 状态行 ══ */
.state-row {
  display: flex; align-items: center; gap: 8px;
  padding: 26px 24px;
  font-family: var(--font-kai); letter-spacing: 2px;
  color: var(--ink-muted); font-size: 13px;
  background: var(--card);
  border: 1px dashed var(--gold-line);
  border-radius: var(--radius-card);
  margin-bottom: 20px;
}
.ldot {
  width: 6px; height: 6px; border-radius: 50%; background: var(--cinnabar);
  animation: ldot 1.2s ease-in-out infinite;
}
.ldot:nth-child(2) { animation-delay: .2s; }
.ldot:nth-child(3) { animation-delay: .4s; }
@keyframes ldot { 0%,100%{opacity:.2;transform:scale(.7)} 50%{opacity:1;transform:scale(1)} }

/* ══ 舱室栅格 ══ */
.module-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
.module-card {
  background: var(--card);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
  padding: 18px 16px;
  min-height: 250px;
  position: relative;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  transition: transform .22s ease, box-shadow .22s ease, border-color .22s ease;
}
.module-card:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-lift);
  border-color: var(--gold-line);
}
.m-bloom {
  position: absolute; top: 0; left: 0; right: 0; height: 4px;
  border-radius: var(--radius-card) var(--radius-card) 0 0;
  background: linear-gradient(90deg, var(--bamboo), transparent);
}
.module-card.partial .m-bloom { background: linear-gradient(90deg, var(--gold), transparent); }
.module-card.planned .m-bloom { background: linear-gradient(90deg, var(--dai), transparent); }
.module-card.planned { opacity: .88; }
.module-top { display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; }
.module-top h2 {
  font-size: 17px; letter-spacing: 2px;
  font-family: var(--font-kai); color: var(--ink); font-weight: 700;
}
.module-top p {
  font-size: 10.5px; color: var(--dai);
  font-family: var(--font-mono); margin-top: 4px; letter-spacing: 1px;
}
.desc { margin-top: 12px; color: var(--ink-soft); font-size: 12.5px; line-height: 1.7; flex: 1; }
.refs { margin-top: 14px; display: grid; gap: 10px; }
.refs b {
  display: block; font-size: 10px; color: var(--gold);
  font-family: var(--font-kai); letter-spacing: 2px; margin-bottom: 5px;
}
.refs span {
  display: inline-block; margin: 0 6px 6px 0; padding: 2px 9px;
  border: 1px solid var(--line); border-radius: 999px;
  font-size: 10.5px; color: var(--ink-soft);
  background: var(--line-soft);
}

/* ══ 响应式 ══ */
@media (max-width: 1200px) { .module-grid { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 900px) {
  .module-grid { grid-template-columns: repeat(2, 1fr); }
  .stat-band { grid-template-columns: 1fr; }
}
@media (max-width: 620px) { .module-grid { grid-template-columns: 1fr; } }
</style>
