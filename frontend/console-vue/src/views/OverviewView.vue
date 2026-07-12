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

    <!-- 大楷体水印标题 -->
    <div class="watermark-title" aria-hidden="true">枢忆</div>

    <!-- 页头（回纹边框） -->
    <header class="page-head huiwen-box">
      <div class="huiwen-corner tl"></div>
      <div class="huiwen-corner tr"></div>
      <div class="huiwen-corner bl"></div>
      <div class="huiwen-corner br"></div>
      <div class="head-inner">
        <div class="head-badge">MemoryOps Autopilot</div>
        <h1>总览 · 宛委枢忆</h1>
        <p>v0.9.3 Workflow Run 主线 · 端侧记忆治理生产控制面</p>
      </div>
      <div class="head-stats">
        <div class="hstat"><b>{{ modules.length || 20 }}</b><span>平台舱室</span></div>
        <div class="hstat"><b>{{ statusCounts.partial }}</b><span>部分实现</span></div>
        <div class="hstat muted"><b>{{ statusCounts.planned }}</b><span>规划标注</span></div>
      </div>
    </header>

    <!-- 英雄区 -->
    <section class="hero">
      <div class="hero-quote">
        <span class="qm">「</span>
        不是记忆 demo，而是一台可以自行闭环的精密生产仪器。
        <span class="qm">」</span>
      </div>
      <p class="hero-flow">
        多源接入 → Policy Gate → MemoryCapsule 2.0 → 检索/证据卡 →
        模型网关 → 指挥闭环 → Workflow Run → 复盘演化 → Arena 评测
      </p>
    </section>

    <div v-if="loading" class="state-row">
      <span class="ldot"></span><span class="ldot"></span><span class="ldot"></span>
      <span>加载指标中…</span>
    </div>
    <div v-else-if="!metrics" class="state-row muted">
      ◎ 无法加载指标 — 运行 <code>./scripts/run_eval.sh</code> 后刷新
    </div>

    <template v-else>
      <!-- KV 数字 -->
      <div class="kv-row">
        <div class="kv-card accent">
          <div class="kv-label">MemoryArena Cases</div>
          <div class="kv-val">{{ metrics.total_cases }}</div>
        </div>
        <div class="kv-card accent">
          <div class="kv-label">断言通过</div>
          <div class="kv-val">{{ metrics.assertions_passed }}<span class="kv-of">/{{ metrics.total_assertions }}</span></div>
        </div>
        <div class="kv-card">
          <div class="kv-label">Workflow Run</div>
          <div class="kv-val small">v0.9.3</div>
        </div>
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
            <!-- 回纹角装饰 -->
            <span class="mc-corner tl"></span>
            <span class="mc-corner br"></span>
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
            <div class="case-vol">{{ c[2] }}</div>
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
.watermark-title {
  position: fixed;
  right: 60px;
  top: 50%;
  transform: translateY(-50%);
  font-family: var(--kai);
  font-size: 280px;
  font-weight: 900;
  color: rgba(178,58,46,.045);
  pointer-events: none;
  user-select: none;
  line-height: 1;
  letter-spacing: -10px;
  z-index: 0;
}

/* ══ 回纹边框盒子 ══ */
.huiwen-box {
  position: relative;
  padding: 20px 24px;
  background: rgba(255,255,255,.55);
  backdrop-filter: blur(2px);
  border: 1px solid rgba(200,153,31,.3);
  margin-bottom: 24px;
}
/* 四角回纹 — 用 clip-path 模拟 */
.huiwen-corner {
  position: absolute;
  width: 18px;
  height: 18px;
  border-color: var(--cinnabar);
  border-style: solid;
  opacity: .7;
}
.huiwen-corner.tl { top: 4px; left: 4px; border-width: 2px 0 0 2px; }
.huiwen-corner.tr { top: 4px; right: 4px; border-width: 2px 2px 0 0; }
.huiwen-corner.bl { bottom: 4px; left: 4px; border-width: 0 0 2px 2px; }
.huiwen-corner.br { bottom: 4px; right: 4px; border-width: 0 2px 2px 0; }
/* 内层回纹 */
.huiwen-corner::after {
  content: '';
  position: absolute;
  width: 8px;
  height: 8px;
  border-color: rgba(200,153,31,.5);
  border-style: solid;
}
.huiwen-corner.tl::after { top: 3px; left: 3px; border-width: 1px 0 0 1px; }
.huiwen-corner.tr::after { top: 3px; right: 3px; border-width: 1px 1px 0 0; }
.huiwen-corner.bl::after { bottom: 3px; left: 3px; border-width: 0 0 1px 1px; }
.huiwen-corner.br::after { bottom: 3px; right: 3px; border-width: 0 1px 1px 0; }

/* ── 页头 ── */
.head-inner { position: relative; z-index: 1; }
.head-badge {
  font-family: var(--kai);
  font-size: 10px;
  letter-spacing: 2px;
  color: var(--cinnabar);
  border: 1px solid rgba(178,58,46,.4);
  padding: 2px 8px;
  display: inline-block;
  margin-bottom: 8px;
}
.page-head { display: flex; align-items: center; justify-content: space-between; }
.page-head h1 {
  font-family: var(--kai);
  font-size: 28px;
  font-weight: 700;
  letter-spacing: 4px;
  color: var(--ink);
  line-height: 1.2;
}
.page-head p { font-size: 12px; color: var(--ink-muted); margin-top: 4px; }
.head-stats { display: flex; gap: 0; border: 1px solid rgba(200,153,31,.25); position: relative; z-index: 1; }
.hstat {
  display: flex; flex-direction: column; align-items: center;
  padding: 10px 18px; border-left: 1px solid rgba(200,153,31,.2);
}
.hstat:first-child { border-left: 0; }
.hstat b { font-size: 26px; font-family: Georgia, serif; color: var(--cinnabar); line-height: 1; }
.hstat.muted b { color: var(--ink-muted); }
.hstat span { font-size: 10px; color: var(--ink-muted); margin-top: 3px; }

/* ── 英雄区 ── */
.hero {
  margin-bottom: 24px;
  padding: 18px 22px;
  background: rgba(255,255,255,.42);
  border-left: 4px solid var(--cinnabar);
  border-top: 1px solid rgba(200,153,31,.2);
  border-bottom: 1px solid rgba(200,153,31,.2);
  border-right: 1px solid rgba(200,153,31,.15);
  position: relative; z-index: 1;
}
.hero-quote {
  font-family: var(--kai);
  font-size: 18px;
  letter-spacing: 2px;
  line-height: 1.6;
  margin-bottom: 8px;
}
.qm { color: var(--cinnabar); font-size: 22px; }
.hero-flow { font-size: 12px; color: var(--ink-soft); line-height: 1.8; }

/* ── 状态行 ── */
.state-row {
  display: flex; align-items: center; gap: 8px;
  padding: 24px; color: var(--ink-muted); font-size: 13px;
  border: 1px dashed rgba(200,153,31,.3); margin-bottom: 20px;
  position: relative; z-index: 1;
}
.ldot {
  width: 6px; height: 6px; border-radius: 50%; background: var(--cinnabar);
  animation: ldot 1.2s ease-in-out infinite;
}
.ldot:nth-child(2) { animation-delay: .2s; }
.ldot:nth-child(3) { animation-delay: .4s; }
@keyframes ldot { 0%,100%{opacity:.2;transform:scale(.7)} 50%{opacity:1;transform:scale(1)} }
.state-row code { font-family: var(--mono); font-size: 11px; background: rgba(0,0,0,.06); padding: 1px 5px; }

/* ── KV ── */
.kv-row { display: flex; gap: 12px; margin-bottom: 24px; flex-wrap: wrap; position: relative; z-index: 1; }
.kv-card {
  border: 1px solid rgba(200,153,31,.25);
  background: rgba(255,255,255,.5);
  padding: 14px 20px; min-width: 130px;
}
.kv-card.accent { border-left: 4px solid var(--cinnabar); }
.kv-label { font-size: 10px; color: var(--ink-muted); font-family: var(--mono); margin-bottom: 5px; }
.kv-val { font-size: 42px; font-weight: 700; font-family: Georgia, serif; color: var(--cinnabar); line-height: 1; }
.kv-val.small { font-size: 20px; color: var(--mineral); }
.kv-of { font-size: 18px; color: var(--ink-muted); }

/* ── 章节 ── */
.section { margin-bottom: 32px; position: relative; z-index: 1; }
.sec-head { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
.sec-seal {
  font-family: var(--kai); font-size: 12px; font-weight: 700;
  width: 28px; height: 28px; display: grid; place-items: center;
  background: var(--cinnabar); color: #F8EDD8; border-radius: 2px;
  box-shadow: 0 0 10px rgba(178,58,46,.35); flex-shrink: 0;
}
.sec-head h2 { font-size: 15px; font-weight: 700; letter-spacing: 2px; font-family: var(--kai); }
.sec-line { flex: 1; height: 1px; background: linear-gradient(90deg, rgba(200,153,31,.4), transparent); }

/* ── 指标网格 ── */
.metrics-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.metric-card {
  border: 1px solid rgba(200,153,31,.2);
  border-top: 3px solid var(--mineral);
  background: rgba(255,255,255,.45);
  padding: 13px 14px;
  position: relative;
  transition: transform .18s, box-shadow .18s;
}
.metric-card:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(26,23,20,.1); }
.metric-card.danger { border-top-color: var(--cinnabar); }
.metric-card.warn { border-top-color: var(--gamboge); }
/* 回纹角 */
.mc-corner {
  position: absolute;
  width: 10px; height: 10px;
  border-color: rgba(200,153,31,.4);
  border-style: solid;
}
.mc-corner.tl { top: 3px; left: 3px; border-width: 1px 0 0 1px; }
.mc-corner.br { bottom: 3px; right: 3px; border-width: 0 1px 1px 0; }
.mc-val { font-size: 26px; font-weight: 700; font-family: Georgia, serif; color: var(--mineral); line-height: 1; margin-bottom: 7px; }
.mc-val.pending { font-size: 15px; color: var(--gamboge); }
.metric-card.danger .mc-val { color: var(--cinnabar); }
.mc-cn { font-size: 12px; color: var(--ink); }
.mc-en { font-size: 9.5px; color: var(--ink-muted); font-family: var(--mono); margin-top: 3px; word-break: break-all; }

/* ── 五案卷宗 ── */
.case-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; }
.case-card {
  border: 1px solid rgba(200,153,31,.25);
  background: rgba(255,255,255,.42);
  padding: 14px 12px;
  min-height: 140px;
  position: relative;
  transition: border-color .18s, transform .18s;
}
.case-card:hover { border-color: rgba(178,58,46,.4); transform: translateY(-2px); }
.case-vol {
  font-family: var(--kai); font-size: 11px; color: var(--gamboge);
  border: 1px solid rgba(200,153,31,.4); padding: 1px 6px;
  display: inline-block; margin-bottom: 8px; border-radius: 1px;
}
.case-card h3 { font-size: 13.5px; letter-spacing: 1px; font-family: var(--kai); margin-bottom: 6px; }
.case-card code { font-size: 9px; color: var(--ink-muted); font-family: var(--mono); word-break: break-all; display: block; }
.case-pass {
  position: absolute; right: 8px; bottom: 8px;
  color: var(--jade); border: 1px solid var(--jade);
  padding: 1px 6px; font-size: 10px; border-radius: 1px;
}

/* ── 演示路线 ── */
.flow { display: flex; border: 1px solid rgba(200,153,31,.25); overflow: hidden; }
.flow-step {
  flex: 1; display: flex; flex-direction: column; align-items: center;
  padding: 16px 10px; background: rgba(255,255,255,.38);
  border-right: 1px solid rgba(200,153,31,.2);
  position: relative; text-align: center;
  transition: background .18s;
}
.flow-step:last-child { border-right: 0; }
.flow-step:hover { background: rgba(255,255,255,.6); }
.flow-icon {
  font-family: var(--kai); font-size: 20px; font-weight: 700;
  color: var(--cinnabar); width: 38px; height: 38px;
  display: grid; place-items: center;
  border: 1px solid rgba(178,58,46,.3); border-radius: 2px;
  background: rgba(178,58,46,.07); margin-bottom: 8px;
}
.flow-step b { display: block; font-size: 13px; letter-spacing: 1px; font-family: var(--kai); margin-bottom: 4px; }
.flow-step em { display: block; font-style: normal; font-size: 10.5px; color: var(--ink-muted); line-height: 1.5; }
.flow-arr {
  position: absolute; right: -9px; top: 50%; transform: translateY(-50%);
  color: var(--cinnabar); font-size: 14px; z-index: 2;
  background: var(--xuan); padding: 2px 1px;
}

/* ── 响应式 ── */
@media (max-width: 1100px) { .case-grid { grid-template-columns: repeat(3,1fr); } }
@media (max-width: 900px) { .metrics-grid { grid-template-columns: repeat(2,1fr); } .head-stats { display: none; } }
@media (max-width: 600px) { .case-grid { grid-template-columns: 1fr; } .flow { flex-wrap: wrap; } .flow-step { min-width: 50%; } .flow-arr { display: none; } }
</style>
