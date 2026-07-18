<script setup lang="ts">
import { computed, onMounted, shallowRef } from 'vue'
import { api } from '@/api/client'
import PageHero from '@/components/gf/PageHero.vue'
import GfCard from '@/components/gf/GfCard.vue'
import GfTag from '@/components/gf/GfTag.vue'
import GfButton from '@/components/gf/GfButton.vue'
import GfStat from '@/components/gf/GfStat.vue'
import GfEmpty from '@/components/gf/GfEmpty.vue'
import InkDivider from '@/components/gf/InkDivider.vue'

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

type GfTone = 'rouge' | 'dai' | 'bamboo' | 'gold' | 'ink'
function stageTone(status: string): GfTone {
  if (status === 'completed' || status === 'done') return 'bamboo'
  if (status === 'skipped' || status === 'partial') return 'gold'
  if (status === 'failed') return 'rouge'
  if (status === 'running') return 'dai'
  return 'ink'
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
    <PageHero
      seal="流"
      title="赛题工作流"
      en="Workflow Closed Loop"
      sub="v0.11.0 工作流运行主线：把平台舱室收束为一条安全 dry-run OSAgent 闭环。"
    />

    <div class="stat-row">
      <GfStat label="工作流阶段" :value="design.stages?.length || 10" tone="rouge" />
      <GfStat label="已完成" :value="doneCount" tone="bamboo" />
      <GfStat label="部分完成" :value="partialCount" tone="gold" />
      <GfStat label="赛题要求映射" :value="requirementCount" tone="dai" />
      <GfStat label="OSAgent 控制链路" :value="runSummary.latency_ms || '待运行'" hint="毫秒" />
    </div>

    <p class="note-boundary">本页不是新增孤岛页面；它把石渠校验、司契护栏、枢忆核、通玄模型舱、百工技能舱、忘机机制、兰台鉴证和云笈导出串成一次可回放 workflow run。默认安全 dry-run：不执行危险工具，不写生产记忆，不把模型生成延迟混入 OSAgent 控制链路。</p>

    <GfEmpty v-if="loading" text="研墨中，正在加载工作流…" />
    <p v-else-if="error" class="error-note">{{ error }}</p>

    <template v-else>
      <div class="grid-two section">
        <GfCard title="启动一次工作流运行" seal="启">
          <div class="run-row">
            <select v-model="selectedScenario" class="gf-input">
              <option v-for="item in design.scenarios" :key="item.id" :value="item.id">{{ item.name_cn }}</option>
            </select>
            <GfButton :disabled="running" @click="startWorkflowRun">{{ running ? '运行中…' : '启动运行' }}</GfButton>
          </div>
          <textarea v-model="userGoal" class="gf-input gf-textarea"></textarea>
          <div v-if="running" class="run-live"><GfTag tone="dai" class="pulse-tag">运行中</GfTag></div>
          <dl v-if="run" class="meta-list">
            <dt>run_id</dt><dd>{{ run.run_id }}</dd>
            <dt>trace_id</dt><dd>{{ run.trace_id }}</dd>
            <dt>status</dt>
            <dd><GfTag :tone="stageTone(run.status || '')" :class="{ 'pulse-tag': run.status === 'running' }">{{ statusText(run.status) }}</GfTag></dd>
            <dt>dry_run</dt><dd>{{ run.dry_run }}</dd>
            <dt>risk</dt><dd><GfTag tone="gold">{{ runSummary.risk_level }}</GfTag></dd>
            <dt>next</dt><dd>{{ runSummary.next_action }}</dd>
          </dl>
          <p v-else class="muted">等待启动；运行后会生成 run_id、trace_id、10 阶段证据与审计记录。</p>
        </GfCard>
        <GfCard title="模型接入位置与延迟边界" seal="玄">
          <dl class="meta-list meta-list--flat">
            <dt>provider</dt><dd>{{ design.model_gateway.provider }}</dd>
            <dt>api_base</dt><dd>{{ design.model_gateway.api_base }}</dd>
            <dt>status</dt><dd><GfTag tone="dai">{{ design.model_gateway.status }}</GfTag></dd>
            <dt>boundary</dt><dd>{{ design.model_gateway.boundary }}</dd>
            <dt>control_ms</dt><dd>{{ controlLatency || '待运行' }}</dd>
          </dl>
        </GfCard>
      </div>

      <section class="section">
        <h2 class="sec-title">十阶进度 · 金线串联</h2>
        <div class="rail">
          <article
            v-for="(stage, index) in (trace.length ? trace : design.stages)"
            :key="stage.stage_id || stage.id"
            class="rail-step"
          >
            <span class="rail-dot" :data-tone="stageTone(stage.status || stage.implemented)" aria-hidden="true"></span>
            <div class="rail-card">
              <b>{{ index + 1 }} · {{ stage.stage || stage.name_cn }}</b>
              <GfTag :tone="stageTone(stage.status || stage.implemented)">{{ statusText(stage.status) }}</GfTag>
              <small>{{ stage.latency_ms ? `${stage.latency_ms}ms` : stage.implemented }}</small>
            </div>
          </article>
        </div>
      </section>

      <template v-if="trace.length">
        <section class="section">
          <h2 class="sec-title">阶段证据卡</h2>
          <div class="grid-2">
            <GfCard v-for="item in trace" :key="item.stage_id">
              <div class="ev-head">
                <h3>{{ item.order }}. {{ item.stage }}</h3>
                <GfTag :tone="stageTone(item.status)">{{ item.risk_level }}</GfTag>
              </div>
              <code class="code-line">{{ item.stage_id }} · {{ item.route }}</code>
              <p class="ev-summary">{{ item.output.summary }}</p>
              <p v-if="item.skip_reason" class="skip-note">跳过原因：{{ item.skip_reason }}</p>
              <div class="chip-list">
                <GfTag v-for="ev in item.evidence" :key="ev.kind + ev.ref" tone="ink">{{ ev.kind }} · {{ ev.source_layer }}</GfTag>
              </div>
              <template #footer><span class="ev-next">{{ item.next_action }}</span></template>
            </GfCard>
          </div>
        </section>

        <div class="grid-two section">
          <GfCard title="追踪回放" seal="迹">
            <pre class="pre-scroll">{{ trace }}</pre>
          </GfCard>
          <GfCard title="运行产物 / 边界" seal="物">
            <pre class="pre-scroll">{{ artifacts }}</pre>
          </GfCard>
        </div>
      </template>

      <section class="section">
        <InkDivider label="赛题要求映射" />
        <div class="mapping-grid">
          <GfCard v-for="(items, requirement) in mapping.items" :key="requirement" :title="String(requirement)">
            <div class="chip-list">
              <GfTag v-for="item in items" :key="item.stage_id" :tone="stageTone(item.implemented)">{{ item.stage }} · {{ item.implemented }} · {{ item.route }}</GfTag>
            </div>
          </GfCard>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.stat-row { display: grid; grid-template-columns: repeat(5, 1fr); gap: 20px; }
.section { margin-top: 22px; }
.note-boundary {
  margin-top: 18px;
  padding: 12px 16px;
  border-radius: var(--radius-small);
  border: 1px solid var(--gold-line);
  border-left: 3px solid var(--cinnabar);
  background: var(--card);
  color: var(--ink-soft);
  font-size: 13px;
  line-height: 1.7;
}
.error-note {
  margin-top: 18px;
  padding: 12px 16px;
  border-radius: var(--radius-small);
  border: 1px solid var(--line-cinnabar);
  background: color-mix(in srgb, var(--cinnabar) 8%, transparent);
  color: var(--cinnabar);
  font-size: 13px;
}
.muted { color: var(--ink-muted); font-size: 13px; line-height: 1.7; }
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
.grid-two { display: grid; grid-template-columns: 1.15fr .85fr; gap: 20px; }
.grid-2 { display: grid; grid-template-columns: repeat(2, 1fr); gap: 20px; }
.run-row { display: flex; gap: 10px; margin-bottom: 10px; }
.gf-input {
  width: 100%;
  border: 1px solid var(--line);
  background: var(--card);
  border-radius: var(--radius-small);
  padding: 9px 12px;
  color: var(--ink);
  font-size: 13px;
  transition: border-color .18s ease, box-shadow .18s ease;
}
.gf-input:focus { outline: none; border-color: var(--cinnabar); box-shadow: 0 0 0 3px var(--rouge-glow); }
.gf-textarea { min-height: 72px; resize: vertical; line-height: 1.6; }
.run-live { margin: 4px 0 8px; }
.meta-list { display: grid; grid-template-columns: 88px 1fr; gap: 9px 12px; margin-top: 14px; align-items: center; }
.meta-list--flat { margin-top: 2px; }
.meta-list dt { color: var(--gold); font-family: var(--font-mono); font-size: 11px; letter-spacing: 1px; }
.meta-list dd { color: var(--ink-soft); font-size: 12px; word-break: break-all; line-height: 1.6; }

/* 十阶时间线：朱砂圆点 + 金线 */
.rail {
  position: relative;
  display: grid;
  grid-template-columns: repeat(10, minmax(132px, 1fr));
  gap: 12px;
  padding-top: 26px;
  overflow-x: auto;
  padding-bottom: 4px;
}
.rail::before {
  content: '';
  position: absolute;
  top: 8px;
  left: 40px;
  right: 40px;
  height: 2px;
  background: linear-gradient(90deg, transparent, var(--gold-line) 10%, var(--gold-line) 90%, transparent);
}
.rail-step { position: relative; min-width: 0; }
.rail-dot {
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
.rail-dot[data-tone='bamboo'] { background: var(--bamboo); }
.rail-dot[data-tone='gold'] { background: var(--gold); }
.rail-dot[data-tone='dai'] { background: var(--dai); }
.rail-dot[data-tone='ink'] { background: var(--ink-muted); box-shadow: 0 0 0 2px var(--line); }
.rail-card {
  border: 1px solid var(--line-soft);
  background: var(--card);
  border-radius: var(--radius-small);
  box-shadow: var(--shadow-card);
  padding: 12px;
  display: grid;
  gap: 6px;
  justify-items: start;
  min-height: 118px;
}
.rail-card b { font-size: 12.5px; line-height: 1.5; color: var(--ink); font-family: var(--font-kai); letter-spacing: 1px; }
.rail-card small { color: var(--ink-muted); font-size: 10.5px; font-family: var(--font-mono); }

.ev-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.ev-head h3 { font-size: 15px; font-family: var(--font-kai); letter-spacing: 2px; color: var(--ink); }
.code-line { display: block; color: var(--dai); font-size: 10.5px; margin: 8px 0; font-family: var(--font-mono); word-break: break-all; }
.ev-summary { color: var(--ink-soft); font-size: 12.5px; line-height: 1.7; }
.skip-note { margin-top: 8px; color: var(--gold); font-size: 12px; line-height: 1.6; }
.chip-list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.ev-next { color: var(--ink-muted); font-size: 12px; line-height: 1.6; }

.pre-scroll {
  border: 1px solid var(--line-soft);
  background: var(--bg-soft);
  border-radius: var(--radius-small);
  color: var(--ink-soft);
  padding: 12px 14px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 360px;
  overflow: auto;
  font-size: 11px;
  font-family: var(--font-mono);
  line-height: 1.6;
}
.mapping-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; }

.pulse-tag { animation: gf-pulse 1.8s ease-out infinite; }
@keyframes gf-pulse {
  0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--dai) 45%, transparent); }
  70% { box-shadow: 0 0 0 7px transparent; }
  100% { box-shadow: 0 0 0 0 transparent; }
}
@media (prefers-reduced-motion: reduce) { .pulse-tag { animation: none; } }

@media (max-width: 1200px) { .mapping-grid { grid-template-columns: repeat(2, 1fr); } .stat-row { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 900px) { .grid-two, .grid-2, .mapping-grid { grid-template-columns: 1fr; } }
@media (max-width: 700px) { .stat-row { grid-template-columns: repeat(2, 1fr); } }
</style>
