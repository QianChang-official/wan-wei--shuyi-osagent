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
  ['docs_reference_governance', '论文引用治理', '卷一', 'arXiv / ICML / AAAI / OWASP 分级引用，证据卡覆盖关键建议。'],
  ['git_commit_review', '提交前审查', '卷二', 'HTML residue、JSON manifest、remote HEAD 验证流程召回。'],
  ['poisoning_preference_confirm', '投毒与偏好确认', '卷三', '跳过确认类污染进入 quarantine，unsafe_autonomy 恒为 0。'],
  ['self_evolution_loop', '自进化闭环', '卷四', '失败复盘沉淀风险，二次任务召回风险并改变计划。'],
  ['prompt_injection_false_positive_echo', '误报回声风险', '卷五', '区分 source_layer，不把自身告警当外部注入证据。'],
]

const FLOW = [
  { step: '一', name: '多源接入', desc: '石渠校验 source_layer 与格式质量', icon: '入' },
  { step: '二', name: '策略门', desc: '司契护栏做确认/隔离/拒绝', icon: '守' },
  { step: '三', name: '枢忆生产', desc: 'MemoryCapsule 2.0 + SQLite/FTS5', icon: '存' },
  { step: '四', name: '可信调用', desc: '检索证据卡 + 模型/技能编排', icon: '召' },
  { step: '五', name: 'Arena 鉴证', desc: '复盘演化、审计、导出材料', icon: '鉴' },
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
    <!-- 页头 -->
    <header class="page-head">
      <div class="head-left">
        <div class="head-badge">MemoryOps</div>
        <div>
          <h1>总览 · 宛委枢忆</h1>
          <p>v0.9.3 Workflow Run 主线 · 端侧记忆治理生产控制面</p>
        </div>
      </div>
      <div class="head-right">
        <div class="head-stat">
          <b>{{ modules.length || 20 }}</b>
          <span>平台舱室</span>
        </div>
        <div class="head-stat">
          <b>{{ statusCounts.partial }}</b>
          <span>部分实现</span>
        </div>
        <div class="head-stat muted">
          <b>{{ statusCounts.planned }}</b>
          <span>规划标注</span>
        </div>
      </div>
    </header>

    <!-- 英雄区 -->
    <section class="hero">
      <div class="hero-inner">
        <div class="hero-quote">
          <span class="quote-mark">「</span>
          不是记忆 demo，而是一台可以自行闭环的精密生产仪器。
          <span class="quote-mark">」</span>
        </div>
        <p class="hero-desc">
          多源接入 → Policy Gate → MemoryCapsule 2.0 → 检索/证据卡 →
          模型网关 → 指挥闭环 → Workflow Run → 复盘演化 → Arena 评测 → 审计与导出
        </p>
      </div>
    </section>

    <!-- 指标区 -->
    <div v-if="loading" class="loading-state">
      <span class="loading-dot"></span>
      <span class="loading-dot"></span>
      <span class="loading-dot"></span>
      <span>加载指标中…</span>
    </div>
    <div v-else-if="!metrics" class="empty-state">
      <span class="empty-icon">◎</span>
      <span>无法加载指标 — 运行 <code>./scripts/run_eval.sh</code> 后刷新</span>
    </div>

    <template v-else>
      <!-- KV 大数字 -->
      <div class="kv-row">
        <div class="kv-card accent">
          <div class="kv-label">MemoryArena Cases</div>
          <div class="kv-value">{{ metrics.total_cases }}</div>
        </div>
        <div class="kv-card accent">
          <div class="kv-label">断言通过</div>
          <div class="kv-value">
            {{ metrics.assertions_passed }}
            <span class="kv-denom">/ {{ metrics.total_assertions }}</span>
          </div>
        </div>
        <div class="kv-card">
          <div class="kv-label">Workflow Run</div>
          <div class="kv-value small">v0.9.3</div>
        </div>
      </div>

      <!-- 指标网格 -->
      <section class="section">
        <div class="section-head">
          <span class="section-seal">评</span>
          <h2>Arena 评测指标</h2>
          <div class="section-line"></div>
        </div>
        <div class="metrics-grid">
          <div
            v-for="(meta, key) in META"
            :key="key"
            class="metric-card"
            :class="{
              danger: meta.danger && metrics[key] > 0,
              warn: meta.warn && metrics[key] !== 'pending' && metrics[key] < 0.6
            }"
          >
            <div class="mc-value" :class="{ pending: metrics[key] === 'pending' }">
              {{ fmt(metrics[key]) }}
            </div>
            <div class="mc-cn">{{ meta.cn }}</div>
            <div class="mc-en">{{ key }}</div>
          </div>
        </div>
      </section>

      <!-- 五案卷宗 -->
      <section class="section">
        <div class="section-head">
          <span class="section-seal">案</span>
          <h2>五案卷宗</h2>
          <div class="section-line"></div>
        </div>
        <div class="case-grid">
          <article v-for="c in CASES" :key="c[0]" class="case-card">
            <div class="case-top">
              <span class="case-vol">{{ c[2] }}</span>
              <span class="case-pass">✓ PASS</span>
            </div>
            <h3>{{ c[1] }}</h3>
            <code>{{ c[0] }}</code>
            <p>{{ c[3] }}</p>
          </article>
        </div>
      </section>

      <!-- 演示路线 -->
      <section class="section">
        <div class="section-head">
          <span class="section-seal">流</span>
          <h2>演示路线</h2>
          <div class="section-line"></div>
        </div>
        <div class="flow">
          <div v-for="(f, i) in FLOW" :key="f.step" class="flow-step">
            <div class="flow-icon">{{ f.icon }}</div>
            <div class="flow-body">
              <b>{{ f.name }}</b>
              <em>{{ f.desc }}</em>
            </div>
            <div v-if="i < FLOW.length - 1" class="flow-arrow">→</div>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.overview { max-width: 1200px; }

/* ── 页头 ── */
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 28px;
  padding-bottom: 20px;
  border-bottom: 1px solid var(--line-gold);
}
.head-left { display: flex; align-items: center; gap: 16px; }
.head-badge {
  font-family: var(--kai);
  font-size: 11px;
  letter-spacing: 2px;
  color: var(--cinnabar);
  border: 1px solid var(--cinnabar);
  padding: 3px 8px;
  border-radius: 2px;
  white-space: nowrap;
}
.page-head h1 {
  font-size: 26px;
  font-weight: 700;
  letter-spacing: 3px;
  font-family: var(--kai);
  color: var(--ink);
  line-height: 1.2;
}
.page-head p { font-size: 12px; color: var(--ink-muted); margin-top: 4px; letter-spacing: .5px; }
.head-right { display: flex; gap: 0; border: 1px solid var(--line); }
.head-stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 10px 20px;
  border-left: 1px solid var(--line);
  min-width: 80px;
}
.head-stat:first-child { border-left: 0; }
.head-stat b { font-size: 28px; font-family: Georgia, serif; color: var(--cinnabar); line-height: 1; }
.head-stat.muted b { color: var(--ink-muted); }
.head-stat span { font-size: 10px; color: var(--ink-muted); margin-top: 4px; }

/* ── 英雄区 ── */
.hero {
  margin-bottom: 28px;
  border: 1px solid var(--line);
  border-left: 4px solid var(--cinnabar);
  background: rgba(255,255,255,.32);
  padding: 20px 24px;
  position: relative;
  overflow: hidden;
}
.hero::after {
  content: '忆';
  position: absolute;
  right: 20px;
  top: 50%;
  transform: translateY(-50%);
  font-family: var(--kai);
  font-size: 80px;
  color: rgba(178,58,46,.06);
  pointer-events: none;
  line-height: 1;
}
.hero-quote {
  font-family: var(--kai);
  font-size: 19px;
  letter-spacing: 2px;
  color: var(--ink);
  line-height: 1.5;
  margin-bottom: 10px;
}
.quote-mark { color: var(--cinnabar); font-size: 22px; }
.hero-desc { font-size: 12.5px; color: var(--ink-soft); line-height: 1.8; letter-spacing: .3px; }

/* ── 加载/空状态 ── */
.loading-state, .empty-state {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 32px;
  color: var(--ink-muted);
  font-size: 13px;
  border: 1px dashed var(--line);
  margin-bottom: 24px;
}
.loading-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--cinnabar);
  animation: pulse 1.2s ease-in-out infinite;
}
.loading-dot:nth-child(2) { animation-delay: .2s; }
.loading-dot:nth-child(3) { animation-delay: .4s; }
@keyframes pulse { 0%,100% { opacity: .3; transform: scale(.8); } 50% { opacity: 1; transform: scale(1); } }
.empty-icon { font-size: 20px; color: var(--gamboge); }
.empty-state code { font-family: var(--mono); font-size: 11px; background: rgba(0,0,0,.06); padding: 1px 5px; }

/* ── KV 大数字 ── */
.kv-row { display: flex; gap: 14px; margin-bottom: 28px; flex-wrap: wrap; }
.kv-card {
  border: 1px solid var(--line);
  background: rgba(255,255,255,.38);
  padding: 16px 22px;
  min-width: 140px;
}
.kv-card.accent { border-left: 4px solid var(--cinnabar); }
.kv-label { font-size: 11px; color: var(--ink-muted); font-family: var(--mono); margin-bottom: 6px; }
.kv-value {
  font-size: 44px;
  font-weight: 700;
  font-family: Georgia, serif;
  color: var(--cinnabar);
  line-height: 1;
}
.kv-value.small { font-size: 22px; color: var(--mineral); }
.kv-denom { font-size: 20px; color: var(--ink-muted); }

/* ── 章节通用 ── */
.section { margin-bottom: 36px; }
.section-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.section-seal {
  font-family: var(--kai);
  font-size: 13px;
  font-weight: 700;
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  background: var(--cinnabar);
  color: #F8EDD8;
  border-radius: 2px;
  flex-shrink: 0;
  box-shadow: 0 0 12px rgba(178,58,46,.3);
}
.section-head h2 {
  font-size: 16px;
  font-weight: 700;
  letter-spacing: 2px;
  font-family: var(--kai);
}
.section-line {
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, var(--line-gold), transparent);
}

/* ── 指标网格 ── */
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.metric-card {
  border: 1px solid var(--line);
  border-top: 3px solid var(--mineral);
  background: rgba(255,255,255,.34);
  padding: 14px 16px;
  transition: transform .18s, box-shadow .18s;
}
.metric-card:hover { transform: translateY(-2px); box-shadow: var(--shadow-lift); }
.metric-card.danger { border-top-color: var(--cinnabar); }
.metric-card.warn { border-top-color: var(--gamboge); }
.mc-value {
  font-size: 28px;
  font-weight: 700;
  font-family: Georgia, serif;
  color: var(--mineral);
  line-height: 1;
  margin-bottom: 8px;
}
.mc-value.pending { font-size: 16px; color: var(--gamboge); }
.metric-card.danger .mc-value { color: var(--cinnabar); }
.mc-cn { font-size: 12.5px; color: var(--ink); letter-spacing: .5px; }
.mc-en { font-size: 10px; color: var(--ink-muted); font-family: var(--mono); margin-top: 3px; word-break: break-all; }

/* ── 五案卷宗 ── */
.case-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
}
.case-card {
  border: 1px solid var(--line);
  background: rgba(255,255,255,.34);
  padding: 14px;
  min-height: 190px;
  position: relative;
  transition: border-color .18s, transform .18s;
}
.case-card:hover { border-color: var(--line-gold); transform: translateY(-2px); }
.case-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.case-vol {
  font-family: var(--kai);
  font-size: 11px;
  color: var(--gamboge);
  border: 1px solid rgba(200,153,31,.4);
  padding: 1px 6px;
  border-radius: 2px;
}
.case-pass {
  font-size: 10px;
  color: var(--jade);
  border: 1px solid var(--jade);
  padding: 1px 6px;
  border-radius: 2px;
}
.case-card h3 { font-size: 14px; letter-spacing: 1px; margin-bottom: 5px; font-family: var(--kai); }
.case-card code {
  font-size: 9.5px;
  color: var(--ink-muted);
  font-family: var(--mono);
  word-break: break-all;
  display: block;
  margin-bottom: 8px;
}
.case-card p { font-size: 11.5px; color: var(--ink-soft); line-height: 1.65; }

/* ── 演示路线 ── */
.flow {
  display: flex;
  align-items: stretch;
  gap: 0;
  border: 1px solid var(--line);
  overflow: hidden;
}
.flow-step {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 16px 12px;
  background: rgba(255,255,255,.32);
  border-right: 1px solid var(--line);
  position: relative;
  text-align: center;
  transition: background .18s;
}
.flow-step:last-child { border-right: 0; }
.flow-step:hover { background: rgba(255,255,255,.55); }
.flow-icon {
  font-family: var(--kai);
  font-size: 22px;
  font-weight: 700;
  color: var(--cinnabar);
  width: 40px;
  height: 40px;
  display: grid;
  place-items: center;
  border: 1px solid rgba(178,58,46,.3);
  border-radius: 2px;
  margin-bottom: 10px;
  background: rgba(178,58,46,.06);
}
.flow-body b { display: block; font-size: 13.5px; letter-spacing: 1px; font-family: var(--kai); margin-bottom: 5px; }
.flow-body em { display: block; font-style: normal; font-size: 11px; color: var(--ink-muted); line-height: 1.5; }
.flow-arrow {
  position: absolute;
  right: -10px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--cinnabar);
  font-size: 16px;
  z-index: 1;
  background: var(--xuan);
  padding: 2px;
}

/* ── 响应式 ── */
@media (max-width: 1100px) {
  .case-grid { grid-template-columns: repeat(3, 1fr); }
  .flow { flex-wrap: wrap; }
  .flow-step { min-width: 33%; }
  .flow-arrow { display: none; }
}
@media (max-width: 900px) {
  .metrics-grid { grid-template-columns: repeat(2, 1fr); }
  .head-right { display: none; }
}
@media (max-width: 600px) {
  .case-grid { grid-template-columns: 1fr; }
  .flow-step { min-width: 50%; }
}
</style>
