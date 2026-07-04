<script setup lang="ts">
import { computed, onMounted, shallowRef } from 'vue'
import { api } from '@/api/client'

const loading = shallowRef(true)
const running = shallowRef(false)
const error = shallowRef('')
const design = shallowRef<any>({ stages: [], scenarios: [], model_gateway: {} })
const mapping = shallowRef<any>({ items: {} })
const run = shallowRef<any>(null)
const trace = shallowRef<any[]>([])
const artifacts = shallowRef<any>(null)
const selectedScenario = shallowRef('weekly_report_preference_learning')
const userGoal = shallowRef('生成本周项目周报，并记住正式语气和三段式结构偏好。')

const doneCount = computed(() => design.value.stages?.filter((item: any) => item.implemented === 'done').length ?? 0)
const partialCount = computed(() => design.value.stages?.filter((item: any) => item.implemented === 'partial').length ?? 0)
const requirementCount = computed(() => Object.keys(mapping.value.items ?? {}).length)
const runSummary = computed(() => run.value?.summary ?? {})
const controlLatency = computed(() => trace.value.reduce((sum, item) => sum + Number(item.latency_ms || 0), 0))

function statusText(status: string) {
  if (status === 'completed') return '完成'
  if (status === 'skipped') return '跳过'
  if (status === 'failed') return '失败'
  return status || '待运行'
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [designRes, mappingRes] = await Promise.all([
      api.workflowDesign(),
      api.workflowCompetitionMapping(),
    ])
    design.value = designRes
    mapping.value = mappingRes
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function startWorkflowRun() {
  running.value = true
  error.value = ''
  try {
    const created = await api.workflowCreateRun({
      scenario: selectedScenario.value,
      user_goal: userGoal.value,
      include_model_gateway: true,
      include_forgetting: true,
      dry_run: true,
    })
    run.value = created
    const [traceRes, artifactRes] = await Promise.all([
      api.workflowTrace(created.run_id),
      api.workflowArtifacts(created.run_id),
    ])
    trace.value = traceRes.items || []
    artifacts.value = artifactRes.items || null
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    running.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-head">
      <h1>赛题工作流 · Workflow Run</h1>
      <p>v0.9.3 Workflow Run 主线：把平台舱室收束为一条安全 dry-run OSAgent 闭环。</p>
    </div>

    <section class="hero-board">
      <div><b>{{ design.stages?.length || 10 }}</b><span>workflow stages</span></div>
      <div><b>{{ doneCount }}</b><span>done</span></div>
      <div><b>{{ partialCount }}</b><span>partial</span></div>
      <div><b>{{ requirementCount }}</b><span>赛题要求映射</span></div>
      <div><b>{{ runSummary.latency_ms || '待运行' }}</b><span>OSAgent 控制链路 ms</span></div>
    </section>

    <div class="boundary">本页不是新增孤岛页面；它把石渠校验、司契护栏、枢忆核、通玄模型舱、百工技能舱、忘机机制、兰台鉴证和云笈导出串成一次可回放 workflow run。默认安全 dry-run：不执行危险工具，不写生产记忆，不把模型生成延迟混入 OSAgent 控制链路。</div>

    <div v-if="loading" class="muted">加载工作流...</div>
    <div v-else-if="error" class="muted">{{ error }}</div>

    <template v-else>
      <section class="section-block two-col">
        <article class="panel">
          <div class="section-title">启动一次 workflow run</div>
          <div class="run-row">
            <select v-model="selectedScenario">
              <option v-for="item in design.scenarios" :key="item.id" :value="item.id">{{ item.name_cn }}</option>
            </select>
            <button :disabled="running" @click="startWorkflowRun">{{ running ? '运行中…' : '启动 Workflow Run' }}</button>
          </div>
          <textarea v-model="userGoal"></textarea>
          <dl v-if="run" class="run-meta">
            <dt>run_id</dt><dd>{{ run.run_id }}</dd>
            <dt>trace_id</dt><dd>{{ run.trace_id }}</dd>
            <dt>status</dt><dd>{{ run.status }}</dd>
            <dt>dry_run</dt><dd>{{ run.dry_run }}</dd>
            <dt>risk</dt><dd>{{ runSummary.risk_level }}</dd>
            <dt>next</dt><dd>{{ runSummary.next_action }}</dd>
          </dl>
          <p v-else class="muted">等待启动；运行后会生成 run_id、trace_id、10 阶段证据与审计记录。</p>
        </article>
        <article class="panel">
          <div class="section-title">模型接入位置与延迟边界</div>
          <dl>
            <dt>provider</dt><dd>{{ design.model_gateway.provider }}</dd>
            <dt>api_base</dt><dd>{{ design.model_gateway.api_base }}</dd>
            <dt>status</dt><dd>{{ design.model_gateway.status }}</dd>
            <dt>boundary</dt><dd>{{ design.model_gateway.boundary }}</dd>
            <dt>control_ms</dt><dd>{{ controlLatency || '待运行' }}</dd>
          </dl>
        </article>
      </section>

      <section class="section-block">
        <div class="section-title">10 阶段进度条</div>
        <div class="progress-rail">
          <article v-for="(stage, index) in (trace.length ? trace : design.stages)" :key="stage.stage_id || stage.id" class="progress-step" :class="stage.status || stage.implemented">
            <span>{{ index + 1 }}</span>
            <b>{{ stage.stage || stage.name_cn }}</b>
            <em>{{ statusText(stage.status) }}</em>
            <small>{{ stage.latency_ms ? `${stage.latency_ms}ms` : stage.implemented }}</small>
          </article>
        </div>
      </section>

      <section v-if="trace.length" class="section-block">
        <div class="section-title">阶段证据卡</div>
        <div class="evidence-grid">
          <article v-for="item in trace" :key="item.stage_id" class="evidence-card" :class="item.status">
            <div class="evidence-head">
              <h2>{{ item.order }}. {{ item.stage }}</h2>
              <span>{{ item.risk_level }}</span>
            </div>
            <code>{{ item.stage_id }} · {{ item.route }}</code>
            <p>{{ item.output.summary }}</p>
            <div v-if="item.skip_reason" class="skip">跳过原因：{{ item.skip_reason }}</div>
            <div class="chips"><span v-for="ev in item.evidence" :key="ev.kind + ev.ref">{{ ev.kind }} · {{ ev.source_layer }}</span></div>
            <footer>{{ item.next_action }}</footer>
          </article>
        </div>
      </section>

      <section v-if="trace.length" class="section-block two-col">
        <article class="panel">
          <div class="section-title">Trace 回放</div>
          <pre>{{ trace }}</pre>
        </article>
        <article class="panel">
          <div class="section-title">Artifacts / 边界</div>
          <pre>{{ artifacts }}</pre>
        </article>
      </section>

      <section class="section-block">
        <div class="section-title">赛题要求映射</div>
        <div class="mapping-grid">
          <article v-for="(items, requirement) in mapping.items" :key="requirement" class="mapping-card">
            <h3>{{ requirement }}</h3>
            <span v-for="item in items" :key="item.stage_id">{{ item.stage }} · {{ item.implemented }} · {{ item.route }}</span>
          </article>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.page-head { margin-bottom: 22px; }
.page-head h1 { font-size: 28px; letter-spacing: 3px; }
.page-head p, .muted { color: var(--ink-soft); font-size: 13px; margin-top: 5px; }
.hero-board { display: grid; grid-template-columns: repeat(5, 1fr); border: 1px solid var(--line); background: rgba(28,26,23,.04); margin-bottom: 12px; }
.hero-board div { display: grid; place-items: center; padding: 16px 8px; border-left: 1px solid var(--line-soft); text-align: center; }
.hero-board div:first-child { border-left: 0; }
.hero-board b { font-size: 30px; font-family: Georgia, serif; color: var(--cinnabar); }
.hero-board span { color: var(--ink-soft); font-size: 11px; }
.boundary { border-left: 4px solid var(--cinnabar); background: rgba(255,255,255,.36); padding: 12px 14px; color: var(--ink-soft); font-size: 13px; margin-bottom: 18px; }
.section-block { margin-top: 26px; }
.section-title { border-left: 4px solid var(--cinnabar); padding-left: 10px; margin-bottom: 12px; font-size: 16px; font-weight: 700; letter-spacing: 2px; }
.two-col { display: grid; grid-template-columns: 1.15fr .85fr; gap: 14px; }
.panel { border: 1px solid var(--line); background: rgba(255,255,255,.34); padding: 15px; min-width: 0; }
.run-row { display: flex; gap: 8px; margin-bottom: 10px; }
select, textarea { width: 100%; border: 1px solid var(--line); background: rgba(255,255,255,.45); padding: 8px; color: var(--ink); }
textarea { min-height: 66px; resize: vertical; }
button { border: 1px solid var(--cinnabar); color: var(--cinnabar); background: rgba(178,58,46,.07); padding: 8px 11px; white-space: nowrap; }
button:disabled { opacity: .55; cursor: wait; }
dl { display: grid; grid-template-columns: 90px 1fr; gap: 8px; margin-top: 12px; }
dt { color: var(--gamboge); font-family: var(--mono); font-size: 11px; }
dd { color: var(--ink-soft); font-size: 12px; word-break: break-all; }
.progress-rail { display: grid; grid-template-columns: repeat(10, 1fr); gap: 8px; }
.progress-step { border: 1px solid var(--line); border-top: 4px solid var(--ink-soft); background: rgba(255,255,255,.34); padding: 10px; min-height: 118px; }
.progress-step.completed, .progress-step.done { border-top-color: var(--jade); }
.progress-step.skipped { border-top-color: var(--gamboge); }
.progress-step span { display: inline-grid; place-items: center; width: 24px; height: 24px; background: var(--cinnabar); color: #fff; border-radius: 50%; font-size: 12px; }
.progress-step b { display: block; margin-top: 8px; font-size: 12px; line-height: 1.35; }
.progress-step em, .progress-step small { display: block; margin-top: 5px; color: var(--ink-soft); font-style: normal; font-size: 10.5px; }
.evidence-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.evidence-card { border: 1px solid var(--line); border-top: 4px solid var(--jade); background: rgba(255,255,255,.34); padding: 13px; }
.evidence-card.skipped { border-top-color: var(--gamboge); }
.evidence-head { display: flex; justify-content: space-between; gap: 12px; }
.evidence-head h2 { font-size: 15px; }
.evidence-head span { color: var(--cinnabar); font-family: var(--mono); font-size: 11px; }
.evidence-card code { display: block; color: var(--mineral); font-size: 10.5px; margin: 7px 0; }
.evidence-card p, .skip, footer { color: var(--ink-soft); font-size: 12px; line-height: 1.55; }
.chips { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 10px; }
.chips span, .mapping-card span { border: 1px solid var(--line-soft); padding: 2px 6px; color: var(--ink-soft); font-size: 10.5px; background: rgba(255,255,255,.38); }
footer { border-top: 1px solid var(--line-soft); margin-top: 10px; padding-top: 8px; }
pre { border: 1px solid var(--line); background: rgba(28,26,23,.04); color: var(--ink-soft); padding: 10px; white-space: pre-wrap; word-break: break-word; max-height: 360px; overflow: auto; font-size: 11px; }
.mapping-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.mapping-card { border: 1px solid var(--line); background: rgba(255,255,255,.34); padding: 12px; }
.mapping-card h3 { font-size: 14px; margin-bottom: 8px; }
.mapping-card span { display: inline-block; margin: 0 5px 5px 0; }
@media (max-width: 1200px) { .progress-rail { grid-template-columns: repeat(5, 1fr); } .mapping-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 900px) { .hero-board, .two-col, .evidence-grid { grid-template-columns: 1fr; } }
@media (max-width: 760px) { .progress-rail, .mapping-grid { grid-template-columns: 1fr; } }
</style>
