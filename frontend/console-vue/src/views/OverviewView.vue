<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api/client'
import { usePlatformModules } from '@/composables/usePlatformModules'
import PageHero from '@/components/gf/PageHero.vue'
import GfStat from '@/components/gf/GfStat.vue'
import GfTag from '@/components/gf/GfTag.vue'
import GfEmpty from '@/components/gf/GfEmpty.vue'

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
  ['docs_reference_governance', '论文引用治理', '卷一'],
  ['git_commit_review', '提交前审查', '卷二'],
  ['poisoning_preference_confirm', '投毒与偏好确认', '卷三'],
  ['self_evolution_loop', '自进化闭环', '卷四'],
  ['prompt_injection_false_positive_echo', '误报回声风险', '卷五'],
]

const FLOW = [
  { icon: '入', name: '多源接入', desc: '石渠校验 source_layer' },
  { icon: '守', name: '策略门', desc: '司契护栏治理' },
  { icon: '存', name: '枢忆生产', desc: 'MemoryCapsule 2.0' },
  { icon: '召', name: '可信调用', desc: '检索证据卡编排' },
  { icon: '鉴', name: 'Arena 鉴证', desc: '复盘演化审计' },
]

function fmt(v: any) {
  if (v === 'pending') return '待测'
  if (typeof v === 'number') return v % 1 !== 0 ? (v * 100).toFixed(1) + '%' : String(v)
  return String(v)
}

onMounted(async () => {
  try { metrics.value = await api.arenaMetrics() } catch { metrics.value = null }
  loading.value = false
})
</script>

<template>
  <div class="overview">

    <!-- 大楷体水印 -->
    <div class="watermark" aria-hidden="true">枢忆</div>

    <PageHero
      seal="览"
      title="总览 · 宛委枢忆"
      en="Overview · MemoryOps Autopilot"
      sub="v0.11.0 Workflow Run 主线 · 端侧记忆治理生产控制面"
    />

    <!-- 舱室统计带 -->
    <div class="stat-band">
      <GfStat label="平台舱室" :value="modules.length || 20" tone="rouge" hint="MemoryOps Studio" />
      <GfStat label="部分实现" :value="statusCounts.partial" tone="gold" hint="partial 标注" />
      <GfStat label="规划标注" :value="statusCounts.planned" tone="dai" hint="planned 标注" />
    </div>

    <!-- 月洞门英雄区 -->
    <section class="moon-hero">
      <div class="moon-gate" aria-hidden="true">
        <svg viewBox="0 0 220 220" width="100%" height="100%">
          <!-- 月洞门圆环 -->
          <circle cx="110" cy="110" r="86" class="mg-ring" fill="none" />
          <circle cx="110" cy="110" r="78" class="mg-ring-soft" fill="none" />
          <!-- 月晕 -->
          <circle cx="110" cy="110" r="60" class="mg-moon" />
          <!-- 梅枝 -->
          <path d="M30 168 Q 78 128 128 138 T 196 96" class="mg-twig" fill="none" />
          <path d="M126 138 Q 148 148 168 142" class="mg-twig" fill="none" />
          <!-- 梅花 -->
          <g class="mg-blossom">
            <circle cx="96" cy="128" r="5" /><circle cx="107" cy="135.4" r="5" />
            <circle cx="102.2" cy="148.6" r="5" /><circle cx="85.8" cy="148.6" r="5" />
            <circle cx="81" cy="135.4" r="5" /><circle cx="94" cy="138.4" r="2.8" class="mg-heart" />
          </g>
          <g class="mg-blossom mg-blossom--soft">
            <circle cx="168" cy="118" r="4.2" /><circle cx="177.2" cy="124.2" r="4.2" />
            <circle cx="173.2" cy="135.2" r="4.2" /><circle cx="159.6" cy="135.2" r="4.2" />
            <circle cx="155.4" cy="124.2" r="4.2" /><circle cx="166.4" cy="126.6" r="2.4" class="mg-heart" />
          </g>
          <circle cx="188" cy="98" r="3.4" class="mg-bud" />
          <circle cx="52" cy="158" r="3" class="mg-bud" />
        </svg>
      </div>
      <div class="moon-body">
        <p class="hero-quote">
          <span class="qm">「</span>不是记忆 demo，而是一台可以自行闭环的精密生产仪器。<span class="qm">」</span>
        </p>
        <p class="hero-flow">
          多源接入 → Policy Gate → MemoryCapsule 2.0 → 检索/证据卡 →
          模型网关 → 指挥闭环 → Workflow Run → 复盘演化 → Arena 评测
        </p>
      </div>
    </section>

    <div v-if="loading" class="state-row">
      <span class="ldot"></span><span class="ldot"></span><span class="ldot"></span>
      <span>研墨中，正在加载指标…</span>
    </div>
    <GfEmpty v-else-if="!metrics" text="无法加载指标 — 运行 ./scripts/run_eval.sh 后刷新" />

    <template v-else>
      <!-- Arena KV 统计带 -->
      <div class="stat-band">
        <GfStat label="MemoryArena Cases" :value="metrics.total_cases" tone="rouge" hint="评测案卷总数" />
        <GfStat label="断言通过" :value="`${metrics.assertions_passed} / ${metrics.total_assertions}`" tone="bamboo" hint="assertions passed" />
        <GfStat label="Workflow Run" value="v0.11.0" tone="dai" hint="当前主线版本" />
      </div>

      <!-- 指标网格 -->
      <section class="section">
        <div class="sec-head">
          <span class="sec-seal">评</span>
          <h2>Arena 评测指标</h2>
          <div class="sec-line"></div>
        </div>
        <div class="metrics-grid">
          <div v-for="(meta, key) in META" :key="key" class="metric-card"
            :class="{ danger: meta.danger && metrics[key] > 0, warn: meta.warn && metrics[key] !== 'pending' && metrics[key] < 0.6 }">
            <span class="mc-bloom" aria-hidden="true"></span>
            <div class="mc-val" :class="{ pending: metrics[key] === 'pending' }">{{ fmt(metrics[key]) }}</div>
            <div class="mc-cn">{{ meta.cn }}</div>
            <div class="mc-en">{{ key }}</div>
          </div>
        </div>
      </section>

      <!-- 五案卷宗 -->
      <section class="section">
        <div class="sec-head">
          <span class="sec-seal">案</span>
          <h2>五案卷宗</h2>
          <div class="sec-line"></div>
        </div>
        <div class="case-grid">
          <article v-for="c in CASES" :key="c[0]" class="case-card">
            <GfTag tone="gold">{{ c[2] }}</GfTag>
            <h3>{{ c[1] }}</h3>
            <code>{{ c[0] }}</code>
            <span class="case-pass">✓</span>
          </article>
        </div>
      </section>

      <!-- 演示路线 -->
      <section class="section">
        <div class="sec-head">
          <span class="sec-seal">流</span>
          <h2>演示路线</h2>
          <div class="sec-line"></div>
        </div>
        <div class="flow">
          <div v-for="(f, i) in FLOW" :key="f.icon" class="flow-step">
            <div class="flow-icon">{{ f.icon }}</div>
            <b>{{ f.name }}</b>
            <em>{{ f.desc }}</em>
            <div v-if="i < FLOW.length - 1" class="flow-arr">→</div>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.overview { max-width: 1200px; position: relative; }

/* ══ 大楷体水印 ══ */
.watermark {
  position: fixed;
  right: 60px;
  top: 50%;
  transform: translateY(-50%);
  font-family: var(--font-kai);
  font-size: 280px;
  font-weight: 900;
  color: color-mix(in srgb, var(--rouge) 6%, transparent);
  pointer-events: none;
  user-select: none;
  line-height: 1;
  letter-spacing: -10px;
  z-index: 0;
}

/* ══ 统计带 ══ */
.stat-band {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
  margin-bottom: 24px;
  position: relative;
  z-index: 1;
}

/* ══ 月洞门英雄区 ══ */
.moon-hero {
  display: flex;
  align-items: center;
  gap: 28px;
  margin-bottom: 28px;
  padding: 26px 30px;
  background: var(--card);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
  position: relative;
  z-index: 1;
  overflow: hidden;
  transition: transform .22s ease, box-shadow .22s ease, border-color .22s ease;
}
.moon-hero:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-lift);
  border-color: var(--gold-line);
}
.moon-gate {
  width: 168px;
  height: 168px;
  flex-shrink: 0;
  filter: drop-shadow(0 0 14px var(--rouge-glow));
}
.mg-ring { stroke: var(--gold-line); stroke-width: 2; }
.mg-ring-soft { stroke: var(--gold-line); stroke-width: 1; opacity: .5; stroke-dasharray: 3 5; }
.mg-moon { fill: var(--rouge-glow); opacity: .22; }
.mg-twig { stroke: var(--gold); stroke-width: 2.4; stroke-linecap: round; opacity: .8; }
.mg-blossom circle { fill: var(--rouge); opacity: .9; }
.mg-blossom--soft circle { fill: var(--rouge); opacity: .55; }
.mg-blossom .mg-heart { fill: var(--gold); opacity: .95; }
.mg-bud { fill: var(--rouge); opacity: .5; }
.hero-quote {
  font-family: var(--font-kai);
  font-size: 20px;
  letter-spacing: 3px;
  line-height: 1.8;
  color: var(--ink);
  margin-bottom: 12px;
}
.qm { color: var(--cinnabar); font-size: 24px; }
.hero-flow { font-size: 12.5px; color: var(--ink-soft); line-height: 1.9; letter-spacing: 1px; }

/* ══ 状态行（研墨中） ══ */
.state-row {
  display: flex; align-items: center; gap: 8px;
  padding: 26px 24px;
  font-family: var(--font-kai);
  letter-spacing: 2px;
  color: var(--ink-muted); font-size: 13px;
  background: var(--card);
  border: 1px dashed var(--gold-line);
  border-radius: var(--radius-card);
  margin-bottom: 20px;
  position: relative; z-index: 1;
}
.ldot {
  width: 6px; height: 6px; border-radius: 50%; background: var(--cinnabar);
  animation: ldot 1.2s ease-in-out infinite;
}
.ldot:nth-child(2) { animation-delay: .2s; }
.ldot:nth-child(3) { animation-delay: .4s; }
@keyframes ldot { 0%,100%{opacity:.2;transform:scale(.7)} 50%{opacity:1;transform:scale(1)} }

/* ══ 章节 ══ */
.section { margin-bottom: 32px; position: relative; z-index: 1; }
.sec-head { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; }
.sec-seal {
  font-family: var(--font-kai); font-size: 13px; font-weight: 700;
  width: 30px; height: 30px; display: grid; place-items: center;
  color: #FDF6E9;
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  border-radius: var(--radius-seal);
  box-shadow: var(--shadow-seal);
  flex-shrink: 0;
}
.sec-head h2 {
  font-size: 21px; font-weight: 700; letter-spacing: 3px;
  font-family: var(--font-kai); color: var(--ink);
}
.sec-line { flex: 1; height: 1px; background: linear-gradient(90deg, var(--gold-line), transparent); }

/* ══ 指标网格 ══ */
.metrics-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
.metric-card {
  background: var(--card);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
  padding: 16px;
  position: relative;
  overflow: hidden;
  transition: transform .22s ease, box-shadow .22s ease, border-color .22s ease;
}
.metric-card:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-lift);
  border-color: var(--gold-line);
}
.mc-bloom {
  position: absolute; top: 0; left: 0; right: 0; height: 4px;
  border-radius: var(--radius-card) var(--radius-card) 0 0;
  background: linear-gradient(90deg, var(--dai), transparent);
}
.metric-card.danger .mc-bloom { background: linear-gradient(90deg, var(--cinnabar), var(--rouge)); }
.metric-card.warn .mc-bloom { background: linear-gradient(90deg, var(--gold), transparent); }
.mc-val {
  font-size: 28px; font-weight: 700; font-family: var(--font-kai);
  color: var(--dai); line-height: 1; margin: 6px 0 8px; letter-spacing: 1px;
}
.mc-val.pending { font-size: 16px; color: var(--gold); }
.metric-card.danger .mc-val { color: var(--cinnabar); }
.mc-cn { font-size: 12.5px; color: var(--ink); letter-spacing: 1px; }
.mc-en { font-size: 10px; color: var(--ink-muted); font-family: var(--font-mono); margin-top: 4px; word-break: break-all; }

/* ══ 五案卷宗 ══ */
.case-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 14px; }
.case-card {
  background: var(--card);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
  padding: 16px 14px;
  min-height: 150px;
  position: relative;
  transition: transform .22s ease, box-shadow .22s ease, border-color .22s ease;
}
.case-card:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-lift);
  border-color: color-mix(in srgb, var(--rouge) 45%, transparent);
}
.case-card h3 {
  font-size: 15px; letter-spacing: 2px; font-family: var(--font-kai);
  color: var(--ink); margin: 10px 0 8px;
}
.case-card code {
  font-size: 9.5px; color: var(--ink-muted); font-family: var(--font-mono);
  word-break: break-all; display: block; line-height: 1.6;
}
.case-pass {
  position: absolute; right: 12px; bottom: 12px;
  color: var(--bamboo); border: 1px solid var(--bamboo);
  padding: 1px 8px; font-size: 11px; border-radius: 999px;
}

/* ══ 演示路线 ══ */
.flow {
  display: flex;
  background: var(--card);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
  overflow: hidden;
}
.flow-step {
  flex: 1; display: flex; flex-direction: column; align-items: center;
  padding: 22px 12px;
  border-right: 1px solid var(--line-soft);
  position: relative; text-align: center;
  transition: background .22s ease;
}
.flow-step:last-child { border-right: 0; }
.flow-step:hover { background: color-mix(in srgb, var(--rouge) 6%, transparent); }
.flow-icon {
  font-family: var(--font-kai); font-size: 20px; font-weight: 700;
  color: var(--cinnabar); width: 46px; height: 46px;
  display: grid; place-items: center;
  border: 1.5px solid color-mix(in srgb, var(--cinnabar) 40%, transparent);
  border-radius: 50%;
  background: color-mix(in srgb, var(--rouge) 10%, transparent);
  box-shadow: 0 0 12px var(--rouge-glow);
  margin-bottom: 10px;
}
.flow-step b {
  display: block; font-size: 13.5px; letter-spacing: 2px;
  font-family: var(--font-kai); color: var(--ink); margin-bottom: 5px;
}
.flow-step em { display: block; font-style: normal; font-size: 11px; color: var(--ink-muted); line-height: 1.6; }
.flow-arr {
  position: absolute; right: -8px; top: 50%; transform: translateY(-50%);
  color: var(--cinnabar); font-size: 14px; z-index: 2;
  background: var(--card-solid); border-radius: 50%; padding: 2px 3px;
}

/* ══ 响应式 ══ */
@media (max-width: 1100px) { .case-grid { grid-template-columns: repeat(3,1fr); } }
@media (max-width: 900px) {
  .metrics-grid { grid-template-columns: repeat(2,1fr); }
  .stat-band { grid-template-columns: 1fr; }
  .moon-hero { flex-direction: column; text-align: center; }
}
@media (max-width: 600px) {
  .case-grid { grid-template-columns: 1fr; }
  .flow { flex-wrap: wrap; }
  .flow-step { min-width: 50%; }
  .flow-arr { display: none; }
}
</style>
