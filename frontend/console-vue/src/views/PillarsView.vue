<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import { usePlatformModules } from '@/composables/usePlatformModules'
import PageHero from '@/components/gf/PageHero.vue'
import GfStat from '@/components/gf/GfStat.vue'
import GfTag from '@/components/gf/GfTag.vue'
import GfCard from '@/components/gf/GfCard.vue'
import GfEmpty from '@/components/gf/GfEmpty.vue'

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

function statusTone(status: string): 'bamboo' | 'gold' | 'dai' {
  return status === 'done' ? 'bamboo' : status === 'partial' ? 'gold' : 'dai'
}
</script>

<template>
  <div class="pillars">
    <PageHero
      seal="枢"
      title="主线架构"
      en="Pillars · Ancestral Mainline"
      sub="祖宗模块不可删，只能加；v0.7 扩展为 20 舱 MemoryOps Studio。"
    />

    <!-- 状态统计带 -->
    <div class="stat-band">
      <GfStat label="done · 已完成" :value="statusCounts.done" tone="bamboo" hint="祖宗主线舱室" />
      <GfStat label="partial · 部分" :value="statusCounts.partial" tone="gold" hint="部分实现" />
      <GfStat label="planned · 计划" :value="statusCounts.planned" tone="dai" hint="规划标注" />
    </div>

    <!-- 模式签 -->
    <div class="mode-tabs">
      <button :class="{ active: mode === 'all' }" @click="mode = 'all'">全部 20 舱</button>
      <button :class="{ active: mode === 'core' }" @click="mode = 'core'">祖宗主线</button>
      <button :class="{ active: mode === 'v07' }" @click="mode = 'v07'">v0.7 新增</button>
    </div>

    <div v-if="loading" class="state-row">
      <span class="ldot"></span><span class="ldot"></span><span class="ldot"></span>
      <span>研墨中，正在加载舱室…</span>
    </div>
    <GfEmpty v-else-if="error" :text="error" />
    <GfEmpty v-else-if="!visibleModules.length" text="此签下暂无舱室" />
    <div v-else class="grid20">
      <div v-for="p in visibleModules" :key="p.id" class="pillar" :class="p.status">
        <span class="p-bloom" aria-hidden="true"></span>
        <div class="p-stamp">{{ sealOf(p.name_cn) }}</div>
        <div class="p-cn">{{ p.name_cn }}</div>
        <div class="p-fn">{{ p.name_en }}</div>
        <p class="p-desc">{{ p.description }}</p>
        <div class="p-foot">
          <GfTag :tone="statusTone(p.status)">{{ p.status }}</GfTag>
          <span class="p-mod">{{ p.backend_refs[0] }}</span>
        </div>
      </div>
    </div>

    <GfCard class="principle" title="六条架构原则" seal="训">
      <ol>
        <li v-for="item in PRINCIPLES" :key="item">{{ item }}</li>
      </ol>
    </GfCard>
  </div>
</template>

<style scoped>
.pillars { max-width: 1200px; position: relative; }

/* ══ 统计带 ══ */
.stat-band {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
  margin-bottom: 24px;
}

/* ══ 模式签（全圆角） ══ */
.mode-tabs { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 22px; }
.mode-tabs button {
  border: 1px solid var(--line);
  background: var(--card);
  color: var(--ink-soft);
  padding: 8px 18px;
  border-radius: 999px;
  font-size: 12.5px;
  letter-spacing: 2px;
  font-family: var(--font-kai);
  transition: all .22s ease;
}
.mode-tabs button:hover { border-color: var(--gold-line); transform: translateY(-2px); }
.mode-tabs button.active {
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

/* ══ 二十舱栅格 ══ */
.grid20 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 28px; }
.pillar {
  background: var(--card);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
  padding: 18px 16px;
  position: relative;
  overflow: hidden;
  min-height: 226px;
  display: flex;
  flex-direction: column;
  transition: transform .22s ease, box-shadow .22s ease, border-color .22s ease;
}
.pillar:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-lift);
  border-color: var(--gold-line);
}
.p-bloom {
  position: absolute; top: 0; left: 0; right: 0; height: 4px;
  border-radius: var(--radius-card) var(--radius-card) 0 0;
  background: linear-gradient(90deg, var(--bamboo), transparent);
}
.pillar.partial .p-bloom { background: linear-gradient(90deg, var(--gold), transparent); }
.pillar.planned .p-bloom { background: linear-gradient(90deg, var(--dai), transparent); }
.pillar.planned { opacity: .88; }
.p-stamp {
  position: absolute; top: 14px; right: 14px;
  width: 36px; height: 36px;
  display: grid; place-items: center;
  font-family: var(--font-kai); font-size: 16px; font-weight: 700;
  color: var(--cinnabar);
  border: 1.5px solid var(--cinnabar);
  border-radius: var(--radius-seal);
  box-shadow: 0 0 10px var(--rouge-glow);
}
.p-cn {
  font-size: 18px; font-weight: 700; letter-spacing: 3px;
  font-family: var(--font-kai); color: var(--ink);
}
.p-fn {
  font-size: 11px; color: var(--dai);
  margin: 6px 0 10px; font-family: var(--font-mono); letter-spacing: 1px;
}
.p-desc { font-size: 12.5px; color: var(--ink-soft); line-height: 1.7; margin-right: 36px; flex: 1; }
.p-foot {
  display: flex; align-items: center; gap: 8px;
  margin-top: 12px;
}
.p-mod {
  font-size: 10px; color: var(--gold); font-family: var(--font-mono);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}

/* ══ 六条架构原则 ══ */
.principle ol { padding-left: 22px; }
.principle li {
  font-size: 13.5px; color: var(--ink-soft);
  margin-bottom: 8px; line-height: 1.8; letter-spacing: .5px;
}
.principle li::marker { color: var(--cinnabar); font-weight: 700; font-family: var(--font-kai); }

/* ══ 响应式 ══ */
@media (max-width: 1200px) { .grid20 { grid-template-columns: repeat(3,1fr); } }
@media (max-width: 900px) {
  .grid20 { grid-template-columns: repeat(2,1fr); }
  .stat-band { grid-template-columns: 1fr; }
}
@media (max-width: 560px) { .grid20 { grid-template-columns: 1fr; } }
</style>
