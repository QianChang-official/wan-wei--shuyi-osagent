<script setup lang="ts">
import { computed, onMounted, shallowRef } from 'vue'
import { api } from '@/api/client'

const loading = shallowRef(true)
const error = shallowRef('')
const sessionCore = shallowRef<any>({ fields: [], design_rules: [] })
const demoTrace = shallowRef<any>({ flow: [] })
const reasoning = shallowRef<any>({ modes: [] })
const reasoningResult = shallowRef<any>(null)
const redqueen = shallowRef<any>({ criteria: [] })
const redqueenResult = shallowRef<any>(null)
const contracts = shallowRef<any>({ contracts: [] })
const drift = shallowRef<any>({ checks: [] })
const pathways = shallowRef<any>({ items: [] })
const questions = shallowRef<any>({ items: [] })
const answerResult = shallowRef<any>(null)
const visualProtocol = shallowRef<any>({ required_panels: [], fallback_path: [] })
const visualResult = shallowRef<any>(null)

const selectedMode = shallowRef('deep')
const selectedQuestion = shallowRef('chain_design')
const redqueenDraft = shallowRef('v0.9.1 deepening page includes Visual Verification, Contract Truth, and partial/planned boundaries.')

const modeSummary = computed(() => reasoning.value.modes?.map((item: any) => item.mode).join(' / ') || '')
const contractLayers = computed(() => contracts.value.contracts?.map((item: any) => item.layer).join(' / ') || '')
const firstQuestion = computed(() => questions.value.items?.[0]?.id || 'chain_design')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [sessionRes, traceRes, reasoningRes, redqueenRes, contractRes, driftRes, pathwayRes, questionRes, visualRes] = await Promise.all([
      api.deepeningSessionCoreDesign(),
      api.deepeningSessionCoreDemoTrace(),
      api.deepeningReasoningDepthDesign(),
      api.deepeningRedQueenEvaluatorDesign(),
      api.deepeningContractSourceOfTruth(),
      api.deepeningContractDriftCheck(),
      api.deepeningAgiAsiPathways(),
      api.deepeningInterrogationQuestions(),
      api.deepeningVisualVerificationProtocol(),
    ])
    sessionCore.value = sessionRes
    demoTrace.value = traceRes
    reasoning.value = reasoningRes
    redqueen.value = redqueenRes
    contracts.value = contractRes
    drift.value = driftRes
    pathways.value = pathwayRes
    questions.value = questionRes
    visualProtocol.value = visualRes
    selectedQuestion.value = firstQuestion.value
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function runReasoning() {
  reasoningResult.value = await api.deepeningReasoningDepthSimulate({ mode: selectedMode.value, task_type: 'architecture_review', task_risk: selectedMode.value === 'audit' ? 'high' : 'medium' })
}

async function runRedQueen() {
  redqueenResult.value = await api.deepeningRedQueenEvaluateDryRun({ agent_output: redqueenDraft.value, utility_epoch: 'epoch_v091', adversarial_objective: 'find weak assumptions', metrics: { arena_assertions: 16 } })
}

async function runAnswer() {
  answerResult.value = await api.deepeningInterrogationAnswerDryRun({ question_id: selectedQuestion.value, detail_level: 'deep', context: 'v0.9.1 Deep Expansion & Visual Verification' })
}

async function runVisual() {
  visualResult.value = await api.deepeningVisualVerificationChecklistDryRun({ route: '/console/#/deepening', page_name: 'DeepeningView', fallback_mode: true })
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-head">
      <h1>深做追问</h1>
      <p>v0.9.1 深度扩展与可视验证</p>
    </div>

    <section class="hero-board">
      <div><b>会话</b><span>会话核心</span></div>
      <div><b>深度</b><span>{{ modeSummary }}</span></div>
      <div><b>真值</b><span>{{ contractLayers }}</span></div>
      <div><b>可视</b><span>可视验证</span></div>
    </section>

    <div class="boundary">本页只调用项目内 v0.9.1 dry-run / read-only API；不联网，不修改真实记忆，不声明完整复现外部系统。</div>
    <div v-if="loading" class="muted">加载深做追问层...</div>
    <div v-else-if="error" class="muted">{{ error }}</div>

    <template v-else>
      <section class="section-block two-col">
        <article class="panel">
          <div class="section-title">会话核心</div>
          <div class="chips"><span v-for="field in sessionCore.fields" :key="field.name">{{ field.name }} · {{ field.source_layer }}</span></div>
          <div class="trace"><span v-for="step in demoTrace.flow" :key="step.stage">{{ step.stage }} -> {{ step.item }}</span></div>
        </article>
        <article class="panel">
          <div class="section-title">推理深度</div>
          <div class="mode-grid"><div v-for="mode in reasoning.modes" :key="mode.mode"><b>{{ mode.mode }}</b><span>{{ mode.evidence_requirement }}</span><em>{{ mode.estimated_token_multiplier }}x</em></div></div>
          <div class="run-row"><select v-model="selectedMode"><option>shallow</option><option>normal</option><option>deep</option><option>audit</option></select><button @click="runReasoning">模拟运行</button></div>
          <pre>{{ reasoningResult || '等待 reasoning-depth simulate dry-run' }}</pre>
        </article>
      </section>

      <section class="section-block two-col">
        <article class="panel">
          <div class="section-title">红皇后评估器</div>
          <div class="chips"><span v-for="item in redqueen.criteria" :key="item.id">{{ item.id }} · {{ item.weight }}</span></div>
          <textarea v-model="redqueenDraft"></textarea><button @click="runRedQueen">评估 dry-run</button>
          <pre>{{ redqueenResult || '等待 red queen evaluator dry-run' }}</pre>
        </article>
        <article class="panel">
          <div class="section-title">合约真值</div>
          <div class="contract-list"><span v-for="item in contracts.contracts" :key="item.layer">{{ item.layer }} · {{ item.status }}</span></div>
          <div class="contract-list"><span v-for="item in drift.checks" :key="item.id">{{ item.id }} · {{ item.status }}</span></div>
        </article>
      </section>

      <section class="section-block two-col">
        <article class="panel">
          <div class="section-title">AGI 到 ASI 路径</div>
          <div class="path-list"><div v-for="item in pathways.items" :key="item.path"><b>{{ item.path }}</b><span>{{ item.osagent_mapping }}</span><em>{{ item.current_state }} -> {{ item.next_gate }}</em></div></div>
        </article>
        <article class="panel">
          <div class="section-title">连环追问</div>
          <div class="run-row"><select v-model="selectedQuestion"><option v-for="item in questions.items" :key="item.id" :value="item.id">{{ item.title }}</option></select><button @click="runAnswer">回答 dry-run</button></div>
          <div class="question-list"><span v-for="item in questions.items" :key="item.id">{{ item.id }} · {{ item.focus }}</span></div>
          <pre>{{ answerResult || '等待连环追问 dry-run' }}</pre>
        </article>
      </section>

      <section class="section-block two-col">
        <article class="panel">
          <div class="section-title">可视验证</div>
          <div class="chips"><span v-for="item in visualProtocol.required_panels" :key="item">{{ item }}</span></div>
          <div class="contract-list"><span v-for="item in visualProtocol.fallback_path" :key="item">{{ item }}</span></div>
          <button @click="runVisual">清单 dry-run</button>
          <pre>{{ visualResult || '等待 visual checklist dry-run' }}</pre>
        </article>
        <article class="panel">
          <div class="section-title">v0.1-v0.9 加厚边界</div>
          <div class="thickening-grid">
            <div><b>链路怎么设计</b><span>source_layer -> policy -> capsule -> evidence -> export</span></div>
            <div><b>Token 怎么省</b><span>mode routing + top-k + summary + fallback tokens</span></div>
            <div><b>线上挂了怎么办</b><span>/health + smoke + dist fallback + reports</span></div>
            <div><b>数据在哪里</b><span>SQLite / reports / docs / git / runtime_log</span></div>
          </div>
        </article>
      </section>
    </template>
  </div>
</template>

<style scoped>
.page-head { margin-bottom: 22px; }
.page-head h1 { font-size: 28px; letter-spacing: 3px; }
.page-head p, .muted { color: var(--ink-soft); font-size: 13px; margin-top: 5px; }
.hero-board { display: grid; grid-template-columns: repeat(4, 1fr); border: 1px solid var(--line); background: rgba(28,26,23,.04); margin-bottom: 12px; }
.hero-board div { display: grid; place-items: center; min-height: 86px; padding: 12px 8px; border-left: 1px solid var(--line-soft); text-align: center; }
.hero-board div:first-child { border-left: 0; }
.hero-board b { font-size: 26px; font-family: Georgia, serif; color: var(--cinnabar); }
.hero-board span { color: var(--ink-soft); font-size: 11px; line-height: 1.4; }
.boundary { border-left: 4px solid var(--cinnabar); background: rgba(255,255,255,.36); padding: 12px 14px; color: var(--ink-soft); font-size: 13px; margin-bottom: 18px; }
.section-block { margin-top: 24px; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.panel { border: 1px solid var(--line); background: rgba(255,255,255,.34); padding: 15px; min-width: 0; }
.section-title { border-left: 4px solid var(--cinnabar); padding-left: 10px; margin-bottom: 12px; font-size: 16px; font-weight: 700; letter-spacing: 2px; }
.chips, .trace, .contract-list, .question-list { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0; }
.chips span, .trace span, .contract-list span, .question-list span { border: 1px solid var(--line-soft); padding: 3px 7px; color: var(--ink-soft); font-size: 11px; background: rgba(255,255,255,.38); }
.mode-grid, .path-list, .thickening-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
.mode-grid div, .path-list div, .thickening-grid div { border: 1px solid var(--line-soft); background: rgba(255,255,255,.35); padding: 10px; }
.mode-grid b, .path-list b, .thickening-grid b { display: block; color: var(--cinnabar); margin-bottom: 5px; }
.mode-grid span, .path-list span, .thickening-grid span { display: block; color: var(--ink-soft); font-size: 12px; line-height: 1.45; }
.mode-grid em, .path-list em { display: block; color: var(--mineral); font-size: 11px; margin-top: 7px; font-style: normal; }
.run-row { display: flex; gap: 8px; margin: 10px 0; }
select, textarea { width: 100%; border: 1px solid var(--line); background: rgba(255,255,255,.45); padding: 8px; color: var(--ink); }
textarea { min-height: 74px; resize: vertical; }
button { border: 1px solid var(--cinnabar); color: var(--cinnabar); background: rgba(178,58,46,.07); padding: 8px 11px; white-space: nowrap; }
pre { border: 1px solid var(--line); background: rgba(28,26,23,.04); color: var(--ink-soft); padding: 10px; white-space: pre-wrap; word-break: break-word; max-height: 260px; overflow: auto; font-size: 11px; }
@media (max-width: 1050px) { .two-col, .mode-grid, .path-list, .thickening-grid { grid-template-columns: 1fr; } }
@media (max-width: 700px) { .hero-board { grid-template-columns: repeat(2, 1fr); } }
</style>
