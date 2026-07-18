<script setup lang="ts">
/**
 * 万枢织机 · 自动化工作流台
 * 契约（后端 platform_api/automation）：
 *   GET  /automation/flows                      工作流列表
 *   POST /automation/flows                      新建工作流
 *   PUT  /automation/flows/{id}                 更新（启用开关等）
 *   POST /automation/flows/ai-edit              AI 解析修改指令 { flow_id, instruction }
 *   POST /automation/flows/{id}/ai-apply        应用 AI 方案
 *   POST /automation/flows/{id}/run             立即运行
 *   GET  /automation/runs                       运行记录
 *   GET  /automation/flows/schedule/overview    定时总览
 * 全部字段容错（可选链 + 默认值），后端未连通时展示离线示例并诚实标注。
 */
import { computed, onMounted, ref, shallowRef } from 'vue'
import { apiGet, apiPost, apiPut } from '@/api/platform'
import PageHero from '@/components/gf/PageHero.vue'
import GfCard from '@/components/gf/GfCard.vue'
import GfTag from '@/components/gf/GfTag.vue'
import GfButton from '@/components/gf/GfButton.vue'
import GfEmpty from '@/components/gf/GfEmpty.vue'
import InkDivider from '@/components/gf/InkDivider.vue'

type TagTone = 'rouge' | 'dai' | 'bamboo' | 'gold' | 'ink'
type TriggerType = 'manual' | 'schedule' | 'event'

interface FlowStep {
  id: string
  name: string
  type: string
  on_error: string
}

interface Flow {
  id: string
  name: string
  description: string
  triggerType: TriggerType
  triggerDetail: string
  enabled: boolean
  steps: FlowStep[]
}

interface RunRecord {
  id: string
  flowId: string
  flowName: string
  status: string
  startedAt: string
  error: string
}

interface NextRun {
  flowId: string
  flowName: string
  cron: string
  nextAt: string
}

interface AiChange {
  text: string
}

interface AiEditResult {
  understood: string
  changes: AiChange[]
  proposedFlow: unknown
}

interface CreateForm {
  name: string
  description: string
  triggerType: TriggerType
  cron: string
  event: string
}

/* ── 步骤类型图鉴：圆点字 + 色调（禁 emoji，取汉字意象） ── */
const STEP_META: Record<string, { char: string; tone: TagTone; label: string }> = {
  agent: { char: '智', tone: 'dai', label: '智能体' },
  shell: { char: '令', tone: 'ink', label: '命令' },
  http: { char: '网', tone: 'gold', label: '网络' },
  memory: { char: '忆', tone: 'rouge', label: '记忆' },
  condition: { char: '岔', tone: 'bamboo', label: '条件' },
}

function stepMeta(type: string): { char: string; tone: TagTone; label: string } {
  return STEP_META[type] ?? { char: '步', tone: 'ink', label: type || '步骤' }
}

const TRIGGER_LABELS: Record<TriggerType, string> = { manual: '手动', schedule: '定时', event: '事件' }
const TRIGGER_TONES: Record<TriggerType, TagTone> = { manual: 'gold', schedule: 'dai', event: 'rouge' }

const RUN_META: Record<string, { label: string; tone: TagTone }> = {
  success: { label: '成功', tone: 'bamboo' },
  succeeded: { label: '成功', tone: 'bamboo' },
  failed: { label: '失败', tone: 'rouge' },
  error: { label: '失败', tone: 'rouge' },
  running: { label: '运行中', tone: 'dai' },
  queued: { label: '排队中', tone: 'gold' },
  pending: { label: '排队中', tone: 'gold' },
  cancelled: { label: '已取消', tone: 'ink' },
  simulated: { label: '模拟', tone: 'gold' },
}

const ON_ERROR_LABELS: Record<string, string> = {
  stop: '出错即止',
  continue: '出错继续',
  retry: '出错重试',
}

/* ── 离线兜底示例数据 ── */
const SAMPLE_FLOWS: Flow[] = [
  {
    id: 'sample-morning-brief',
    name: '晨间要闻汇编',
    description: '每日 7 点抓取订阅源，AI 汇总成中文简报后沉淀至知识库。',
    triggerType: 'schedule',
    triggerDetail: '0 7 * * *',
    enabled: true,
    steps: [
      { id: 's1', name: '抓取订阅源', type: 'http', on_error: 'continue' },
      { id: 's2', name: 'AI 汇总成稿', type: 'agent', on_error: 'stop' },
      { id: 's3', name: '写入知识库', type: 'memory', on_error: 'retry' },
    ],
  },
  {
    id: 'sample-chat-archive',
    name: '会话归档',
    description: '会话结束时提取要点，打上标签归档，供日后检索。',
    triggerType: 'event',
    triggerDetail: 'chat.finished',
    enabled: true,
    steps: [
      { id: 's1', name: '提取会话要点', type: 'agent', on_error: 'stop' },
      { id: 's2', name: '条件判断是否有新知', type: 'condition', on_error: 'continue' },
      { id: 's3', name: '归档至知识库', type: 'memory', on_error: 'stop' },
    ],
  },
  {
    id: 'sample-disk-cleanup',
    name: '临时文件清扫',
    description: '手动触发，清理下载目录中超过 30 天的临时文件。',
    triggerType: 'manual',
    triggerDetail: '',
    enabled: false,
    steps: [
      { id: 's1', name: '扫描临时目录', type: 'shell', on_error: 'stop' },
      { id: 's2', name: '清理过期文件', type: 'shell', on_error: 'continue' },
    ],
  },
]

const SAMPLE_RUNS: RunRecord[] = [
  { id: 'run-1', flowId: 'sample-morning-brief', flowName: '晨间要闻汇编', status: 'success', startedAt: '今日 07:00', error: '' },
  { id: 'run-2', flowId: 'sample-chat-archive', flowName: '会话归档', status: 'running', startedAt: '今日 09:42', error: '' },
  { id: 'run-3', flowId: 'sample-disk-cleanup', flowName: '临时文件清扫', status: 'failed', startedAt: '昨日 18:20', error: '目标目录不存在（示例）' },
]

const SAMPLE_NEXT_RUNS: NextRun[] = [
  { flowId: 'sample-morning-brief', flowName: '晨间要闻汇编', cron: '0 7 * * *', nextAt: '明日 07:00' },
]

/* ── 规范化（对后端缺字段容错） ── */
function pickArray(res: unknown, keys: string[]): Record<string, unknown>[] {
  if (Array.isArray(res)) return res as Record<string, unknown>[]
  if (res && typeof res === 'object') {
    const obj = res as Record<string, unknown>
    for (const k of keys) {
      if (Array.isArray(obj[k])) return obj[k] as Record<string, unknown>[]
    }
  }
  return []
}

function fmtTime(v: unknown): string {
  if (!v) return ''
  const s = String(v)
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return s
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function normTrigger(raw: unknown): { type: TriggerType; detail: string } {
  let typeStr = ''
  let detail = ''
  if (typeof raw === 'string') {
    typeStr = raw
  } else if (raw && typeof raw === 'object') {
    const t = raw as Record<string, unknown>
    typeStr = String(t.type ?? t.kind ?? '')
    detail = String(t.cron ?? t.event ?? t.expr ?? '')
  }
  const s = typeStr.toLowerCase()
  if (s.includes('sched') || s.includes('cron') || s.includes('定时')) return { type: 'schedule', detail }
  if (s.includes('event') || s.includes('事件')) return { type: 'event', detail }
  return { type: 'manual', detail }
}

function normFlow(raw: Record<string, unknown>): Flow {
  const trig = normTrigger(raw.trigger ?? raw.trigger_type)
  let detail = trig.detail
  if (!detail) detail = String(raw.cron ?? raw.schedule ?? raw.event ?? '')
  const stepsRaw = Array.isArray(raw.steps) ? raw.steps : []
  const steps: FlowStep[] = stepsRaw.map((s, i) => {
    const o = (s && typeof s === 'object' ? s : {}) as Record<string, unknown>
    return {
      id: String(o.id ?? `step-${i + 1}`),
      name: String(o.name ?? o.title ?? `第 ${i + 1} 步`),
      type: String(o.type ?? 'agent'),
      on_error: String(o.on_error ?? ''),
    }
  })
  return {
    id: String(raw.id ?? raw.flow_id ?? ''),
    name: String(raw.name ?? '未命名工作流'),
    description: String(raw.description ?? ''),
    triggerType: trig.type,
    triggerDetail: detail,
    enabled: raw.enabled !== false,
    steps,
  }
}

function normRun(raw: Record<string, unknown>, i: number): RunRecord {
  return {
    id: String(raw.id ?? raw.run_id ?? `run-${i}`),
    flowId: String(raw.flow_id ?? ''),
    flowName: String(raw.flow_name ?? raw.name ?? ''),
    status: String(raw.status ?? 'unknown').toLowerCase(),
    startedAt: fmtTime(raw.started_at ?? raw.created_at ?? raw.time),
    error: String(raw.error ?? ''),
  }
}

function normNextRun(raw: Record<string, unknown>, i: number): NextRun {
  return {
    flowId: String(raw.flow_id ?? raw.id ?? `nr-${i}`),
    flowName: String(raw.flow_name ?? raw.name ?? '未命名工作流'),
    cron: String(raw.cron ?? raw.schedule ?? ''),
    nextAt: fmtTime(raw.next_at ?? raw.next_run_at ?? raw.time),
  }
}

function normAiResult(res: unknown): AiEditResult {
  const o = (res && typeof res === 'object' ? res : {}) as Record<string, unknown>
  const changesRaw = Array.isArray(o.changes) ? o.changes : []
  const changes: AiChange[] = changesRaw.map((c) => {
    if (typeof c === 'string') return { text: c }
    const r = (c && typeof c === 'object' ? c : {}) as Record<string, unknown>
    return { text: String(r.description ?? r.detail ?? r.text ?? r.change ?? JSON.stringify(r)) }
  })
  return {
    understood: String(o.understood ?? o.understanding ?? o.summary ?? ''),
    changes,
    proposedFlow: o.proposed_flow ?? o.proposedFlow ?? o.flow ?? null,
  }
}

/* ── 状态 ── */
const flows = shallowRef<Flow[]>([])
const runs = shallowRef<RunRecord[]>([])
const nextRuns = shallowRef<NextRun[]>([])
const scheduledCount = shallowRef(0)
const loading = shallowRef(true)
const offline = shallowRef(false)
const notice = shallowRef('')
const noticeKind = shallowRef<'error' | 'offline' | 'ok'>('ok')

const selectedId = shallowRef('')
const togglingId = shallowRef('')
const runningFlowId = shallowRef('')

const showCreate = shallowRef(false)
const creating = shallowRef(false)
const createForm = ref<CreateForm>({ name: '', description: '', triggerType: 'manual', cron: '', event: '' })

const aiInstruction = shallowRef('')
const aiResult = shallowRef<AiEditResult | null>(null)
const aiBusy = shallowRef(false)
const applyingAi = shallowRef(false)

const selected = computed<Flow | null>(() => flows.value.find((f) => f.id === selectedId.value) ?? null)

const aiJson = computed(() => JSON.stringify(aiResult.value?.proposedFlow ?? null, null, 2))

function setNotice(text: string, kind: 'error' | 'offline' | 'ok' = 'ok'): void {
  notice.value = text
  noticeKind.value = kind
}

function runMeta(status: string): { label: string; tone: TagTone } {
  return RUN_META[status] ?? { label: status || '未知', tone: 'ink' }
}

function onErrorLabel(v: string): string {
  return ON_ERROR_LABELS[v] ?? v
}

/* ── 加载 ── */
async function load(): Promise<void> {
  loading.value = true
  notice.value = ''
  let flowsFailed = false
  const [flowsRes, runsRes, schedRes] = await Promise.allSettled([
    apiGet<unknown>('/automation/flows'),
    apiGet<unknown>('/automation/runs'),
    apiGet<unknown>('/automation/flows/schedule/overview'),
  ])

  if (flowsRes.status === 'fulfilled') {
    flows.value = pickArray(flowsRes.value, ['items', 'flows', 'data']).map(normFlow).filter((f) => f.id)
  } else {
    flowsFailed = true
    flows.value = SAMPLE_FLOWS
  }

  runs.value = runsRes.status === 'fulfilled'
    ? pickArray(runsRes.value, ['items', 'runs', 'data']).map(normRun)
    : SAMPLE_RUNS

  if (schedRes.status === 'fulfilled') {
    const o = (schedRes.value && typeof schedRes.value === 'object' ? schedRes.value : {}) as Record<string, unknown>
    const upcoming = pickArray(schedRes.value, ['next_runs', 'upcoming', 'items']).map(normNextRun)
    nextRuns.value = upcoming
    scheduledCount.value = Number(o.scheduled_count ?? o.total_scheduled ?? o.count ?? upcoming.length) || upcoming.length
  } else {
    nextRuns.value = SAMPLE_NEXT_RUNS
    scheduledCount.value = SAMPLE_NEXT_RUNS.length
  }

  offline.value = flowsFailed
  if (flowsFailed) {
    setNotice('后端未连通，当前展示离线示例数据；一切变更仅在本地生效，不会持久化。', 'offline')
  }
  if (!selectedId.value && flows.value.length) {
    selectedId.value = flows.value[0]?.id ?? ''
  }
  loading.value = false
}

function selectFlow(flow: Flow): void {
  selectedId.value = flow.id
  aiResult.value = null
  aiInstruction.value = ''
}

/* ── 启用开关 ── */
async function toggleEnabled(flow: Flow): Promise<void> {
  if (togglingId.value) return
  togglingId.value = flow.id
  const next = !flow.enabled
  try {
    if (!offline.value) {
      await apiPut<unknown>(`/automation/flows/${flow.id}`, { enabled: next })
    }
    flows.value = flows.value.map((f) => (f.id === flow.id ? { ...f, enabled: next } : f))
    if (offline.value) setNotice('离线模式：开关状态仅本地生效。', 'offline')
  } catch (e) {
    setNotice(`切换启用状态失败：${e instanceof Error ? e.message : String(e)}`, 'error')
  } finally {
    togglingId.value = ''
  }
}

/* ── 新建 ── */
function openCreate(): void {
  createForm.value = { name: '', description: '', triggerType: 'manual', cron: '', event: '' }
  showCreate.value = true
}

function closeCreate(): void {
  if (creating.value) return
  showCreate.value = false
}

async function createFlow(): Promise<void> {
  if (creating.value) return
  creating.value = true
  const form = createForm.value
  const trigger: Record<string, string> = { type: form.triggerType }
  if (form.triggerType === 'schedule' && form.cron) trigger.cron = form.cron
  if (form.triggerType === 'event' && form.event) trigger.event = form.event
  const payload = {
    name: form.name,
    description: form.description,
    trigger,
    enabled: true,
    steps: [] as unknown[],
  }
  try {
    if (!offline.value) {
      await apiPost<unknown>('/automation/flows', payload)
      await load()
    } else {
      const local: Flow = {
        id: `local-${Date.now()}`,
        name: form.name,
        description: form.description,
        triggerType: form.triggerType,
        triggerDetail: form.triggerType === 'schedule' ? form.cron : form.triggerType === 'event' ? form.event : '',
        enabled: true,
        steps: [],
      }
      flows.value = [...flows.value, local]
      selectedId.value = local.id
      setNotice('离线模式：新工作流仅存在于本页内存。', 'offline')
    }
    showCreate.value = false
  } catch (e) {
    setNotice(`新建工作流失败：${e instanceof Error ? e.message : String(e)}`, 'error')
  } finally {
    creating.value = false
  }
}

/* ── 立即运行 ── */
async function runFlow(flow: Flow): Promise<void> {
  if (runningFlowId.value) return
  runningFlowId.value = flow.id
  try {
    if (!offline.value) {
      await apiPost<unknown>(`/automation/flows/${flow.id}/run`)
      setNotice(`「${flow.name}」已触发运行。`, 'ok')
      const runsRes = await apiGet<unknown>('/automation/runs').catch(() => null)
      if (runsRes) runs.value = pickArray(runsRes, ['items', 'runs', 'data']).map(normRun)
    } else {
      const fake: RunRecord = {
        id: `local-run-${Date.now()}`,
        flowId: flow.id,
        flowName: flow.name,
        status: 'simulated',
        startedAt: fmtTime(new Date().toISOString()),
        error: '',
      }
      runs.value = [fake, ...runs.value]
      setNotice('离线模式：已生成一条模拟运行记录。', 'offline')
    }
  } catch (e) {
    setNotice(`触发运行失败：${e instanceof Error ? e.message : String(e)}`, 'error')
  } finally {
    runningFlowId.value = ''
  }
}

/* ── AI 编辑 ── */
async function aiEdit(): Promise<void> {
  const flow = selected.value
  const instruction = aiInstruction.value.trim()
  if (!flow || !instruction || aiBusy.value) return
  aiBusy.value = true
  try {
    if (!offline.value) {
      const res = await apiPost<unknown>('/automation/flows/ai-edit', { flow_id: flow.id, instruction })
      aiResult.value = normAiResult(res)
    } else {
      aiResult.value = {
        understood: `（离线模拟）已收到修改指令：「${instruction}」。后端连通后，此处将由 AI 给出真实理解。`,
        changes: [
          { text: `（模拟）依据指令「${instruction}」调整步骤编排` },
          { text: '（模拟）保持现有触发方式与启用状态不变' },
        ],
        proposedFlow: {
          id: flow.id,
          name: flow.name,
          trigger: { type: flow.triggerType },
          enabled: flow.enabled,
          steps: flow.steps,
        },
      }
    }
  } catch (e) {
    setNotice(`AI 解析失败：${e instanceof Error ? e.message : String(e)}`, 'error')
  } finally {
    aiBusy.value = false
  }
}

async function applyAi(): Promise<void> {
  const flow = selected.value
  const result = aiResult.value
  if (!flow || !result || applyingAi.value) return
  applyingAi.value = true
  try {
    if (!offline.value) {
      await apiPost<unknown>(`/automation/flows/${flow.id}/ai-apply`, { proposed_flow: result.proposedFlow })
      setNotice('AI 方案已应用，工作流已更新。', 'ok')
      aiResult.value = null
      aiInstruction.value = ''
      await load()
    } else {
      if (result.proposedFlow && typeof result.proposedFlow === 'object') {
        const normed = normFlow({ ...(result.proposedFlow as Record<string, unknown>), id: flow.id })
        flows.value = flows.value.map((f) => (f.id === flow.id ? { ...normed, id: flow.id } : f))
      }
      aiResult.value = null
      setNotice('离线模式：AI 方案仅应用到本页内存。', 'offline')
    }
  } catch (e) {
    setNotice(`应用 AI 方案失败：${e instanceof Error ? e.message : String(e)}`, 'error')
  } finally {
    applyingAi.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <PageHero
      seal="织"
      title="万枢织机"
      en="AUTOMATION LOOM"
      sub="工作流编排 · AI 编辑 · 运行留痕。机杼一启，步步成纹。"
    />

    <div v-if="notice" class="notice" :class="noticeKind" role="status" aria-live="polite">
      <span class="notice-text">{{ notice }}</span>
      <GfButton variant="ghost" small :disabled="loading" @click="load">刷新</GfButton>
    </div>

    <!-- ── 定时总览条 ── -->
    <div class="schedule-strip">
      <span class="ss-seal">辰</span>
      <span class="ss-label">定时总览</span>
      <span class="ss-count">{{ scheduledCount }} 条定时流</span>
      <div class="ss-runs">
        <template v-if="nextRuns.length">
          <span v-for="n in nextRuns.slice(0, 4)" :key="n.flowId + n.nextAt" class="ss-chip">
            <span class="ss-name">{{ n.flowName }}</span>
            <code v-if="n.cron" class="ss-cron">{{ n.cron }}</code>
            <span class="ss-at">{{ n.nextAt || '待排期' }}</span>
          </span>
        </template>
        <span v-else class="ss-empty">暂无定时工作流排期</span>
      </div>
    </div>

    <div class="action-bar">
      <GfButton :disabled="loading" @click="openCreate">新建工作流</GfButton>
    </div>

    <div class="main-grid">
      <!-- ── 工作流列表 ── -->
      <GfCard title="工作流" seal="流" class="flows-card">
        <div v-if="loading" class="muted">研墨中…</div>
        <template v-else>
          <div v-if="flows.length" class="flow-list">
            <article
              v-for="flow in flows"
              :key="flow.id"
              class="flow-row"
              :class="{ active: flow.id === selectedId, disabled: !flow.enabled }"
              tabindex="0"
              role="button"
              :aria-pressed="flow.id === selectedId"
              @click="selectFlow(flow)"
              @keyup.enter="selectFlow(flow)"
            >
              <div class="flow-main">
                <div class="flow-name-row">
                  <h3 class="flow-name">{{ flow.name }}</h3>
                  <GfTag :tone="TRIGGER_TONES[flow.triggerType]">{{ TRIGGER_LABELS[flow.triggerType] }}</GfTag>
                  <code v-if="flow.triggerDetail" class="flow-cron">{{ flow.triggerDetail }}</code>
                </div>
                <p v-if="flow.description" class="flow-desc">{{ flow.description }}</p>
                <span class="flow-steps-count">{{ flow.steps.length }} 个步骤</span>
              </div>
              <button
                class="switch"
                :class="{ on: flow.enabled }"
                type="button"
                role="switch"
                :aria-checked="flow.enabled"
                :aria-label="`启用开关：${flow.name}`"
                :disabled="togglingId === flow.id"
                @click.stop="toggleEnabled(flow)"
              >
                <span class="knob"></span>
              </button>
            </article>
          </div>
          <GfEmpty v-else text="尚无工作流。点上方「新建工作流」织就第一匹。" />
        </template>
      </GfCard>

      <!-- ── 运行记录侧栏 ── -->
      <GfCard title="运行留痕" seal="痕" class="runs-card">
        <div v-if="runs.length" class="run-list">
          <div v-for="run in runs.slice(0, 12)" :key="run.id" class="run-row">
            <GfTag :tone="runMeta(run.status).tone">{{ runMeta(run.status).label }}</GfTag>
            <div class="run-info">
              <span class="run-name">{{ run.flowName || run.flowId || '未知工作流' }}</span>
              <span class="run-time">{{ run.startedAt || '—' }}</span>
              <span v-if="run.error" class="run-error">{{ run.error }}</span>
            </div>
          </div>
        </div>
        <GfEmpty v-else text="尚无运行记录" />
      </GfCard>
    </div>

    <!-- ── 详情：步骤时间线 + AI 编辑 ── -->
    <GfCard v-if="selected" :key="selected.id" title="流详情" seal="详" class="detail-card">
      <div class="detail-head">
        <div class="detail-title">
          <h3>{{ selected.name }}</h3>
          <p v-if="selected.description">{{ selected.description }}</p>
        </div>
        <GfButton :disabled="!!runningFlowId" @click="runFlow(selected)">
          {{ runningFlowId === selected.id ? '触发中…' : '立即运行' }}
        </GfButton>
      </div>

      <InkDivider label="步骤时间线" />

      <ol v-if="selected.steps.length" class="timeline">
        <li v-for="(step, i) in selected.steps" :key="step.id" class="tl-item">
          <span class="step-dot" :data-tone="stepMeta(step.type).tone" :title="stepMeta(step.type).label">
            {{ stepMeta(step.type).char }}
          </span>
          <div class="tl-body">
            <span class="tl-name">{{ i + 1 }}. {{ step.name }}</span>
            <GfTag :tone="stepMeta(step.type).tone">{{ stepMeta(step.type).label }}</GfTag>
            <span v-if="step.on_error" class="tl-err">on_error · {{ onErrorLabel(step.on_error) }}</span>
          </div>
        </li>
      </ol>
      <GfEmpty v-else text="该工作流尚无步骤，可试试下方 AI 编辑。" />

      <InkDivider label="AI 编辑工作流" />

      <div class="ai-edit">
        <textarea
          v-model="aiInstruction"
          class="ai-input"
          rows="2"
          placeholder="用一句话描述想怎样修改此工作流，例如：在抓取后加一步条件判断，失败时重试两次。"
          aria-label="AI 编辑工作流指令"
        ></textarea>
        <div class="ai-actions">
          <GfButton variant="ghost" small :disabled="aiBusy || !aiInstruction.trim()" @click="aiEdit">
            {{ aiBusy ? 'AI 解析中…' : 'AI 解析修改' }}
          </GfButton>
        </div>

        <div v-if="aiResult" class="ai-result">
          <p class="ai-understood">
            <span class="ai-k">AI 理解</span>
            <span>{{ aiResult.understood || '—' }}</span>
          </p>
          <ul v-if="aiResult.changes.length" class="ai-changes">
            <li v-for="(c, i) in aiResult.changes" :key="i">{{ c.text }}</li>
          </ul>
          <details class="ai-json">
            <summary>proposed_flow · 折叠预览</summary>
            <pre>{{ aiJson }}</pre>
          </details>
          <div class="ai-actions">
            <GfButton small :disabled="applyingAi" @click="applyAi">
              {{ applyingAi ? '应用中…' : '应用此方案' }}
            </GfButton>
            <GfButton variant="ghost" small :disabled="applyingAi" @click="aiResult = null">舍弃</GfButton>
          </div>
        </div>
      </div>
    </GfCard>

    <!-- ── 新建弹层 ── -->
    <div v-if="showCreate" class="overlay" @click.self="closeCreate">
      <div class="modal" role="dialog" aria-modal="true" aria-label="新建工作流">
        <header class="modal-hd">
          <span class="modal-seal">新</span>
          <h3>新建工作流</h3>
        </header>
        <form class="modal-form" @submit.prevent="createFlow">
          <label>名称<input v-model.trim="createForm.name" required maxlength="40" placeholder="例如：晨间要闻汇编" autocomplete="off" /></label>
          <label>描述<textarea v-model.trim="createForm.description" rows="2" placeholder="一句话说明这条流程做什么"></textarea></label>
          <div class="field-row">
            <label>触发方式
              <select v-model="createForm.triggerType">
                <option value="manual">手动</option>
                <option value="schedule">定时</option>
                <option value="event">事件</option>
              </select>
            </label>
            <label v-if="createForm.triggerType === 'schedule'">cron 表达式<input v-model.trim="createForm.cron" placeholder="0 7 * * *" autocomplete="off" /></label>
            <label v-if="createForm.triggerType === 'event'">事件名<input v-model.trim="createForm.event" placeholder="例如 chat.finished" autocomplete="off" /></label>
          </div>
          <div class="modal-actions">
            <button class="form-submit" type="submit" :disabled="creating">{{ creating ? '创建中…' : '创建工作流' }}</button>
            <button class="form-cancel" type="button" :disabled="creating" @click="closeCreate">取消</button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<style scoped>
.muted { color: var(--ink-soft); font-size: 13px; padding: 14px 0; font-family: var(--font-kai); letter-spacing: 2px; }

.notice {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 0 0 18px;
  padding: 10px 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  font-size: 12px;
}
.notice.error {
  color: var(--cinnabar-deep);
  border-color: var(--line-cinnabar);
  background: color-mix(in srgb, var(--cinnabar) 7%, transparent);
}
.notice.offline {
  color: color-mix(in srgb, var(--gold) 80%, var(--ink));
  border-color: var(--gold-line);
  background: color-mix(in srgb, var(--gold) 8%, transparent);
}
.notice.ok {
  color: color-mix(in srgb, var(--bamboo) 72%, var(--ink));
  border-color: color-mix(in srgb, var(--bamboo) 40%, transparent);
  background: color-mix(in srgb, var(--bamboo) 9%, transparent);
}
.notice-text { line-height: 1.6; }

/* ── 定时总览条 ── */
.schedule-strip {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding: 12px 16px;
  margin-bottom: 18px;
  border: 1px solid var(--gold-line);
  border-radius: var(--radius-card);
  background: color-mix(in srgb, var(--gold) 7%, var(--card));
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  box-shadow: var(--shadow-card);
}
.ss-seal {
  font-family: var(--font-kai);
  font-size: 13px;
  font-weight: 700;
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  color: #FDF6E9;
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  border-radius: var(--radius-seal);
  box-shadow: 0 0 10px var(--cinnabar-glow);
  flex-shrink: 0;
}
.ss-label { font-family: var(--font-kai); font-size: 15px; letter-spacing: 3px; color: var(--ink); font-weight: 700; }
.ss-count { font-size: 11px; letter-spacing: 1px; color: var(--ink-muted); }
.ss-runs { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-left: auto; }
.ss-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 4px 12px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--card);
  font-size: 12px;
  color: var(--ink-soft);
}
.ss-name { font-family: var(--font-kai); letter-spacing: 1px; color: var(--ink); }
.ss-cron { font-family: var(--font-mono); font-size: 10px; color: var(--dai); }
.ss-at { font-size: 11px; color: var(--ink-muted); }
.ss-empty { font-size: 12px; color: var(--ink-muted); font-family: var(--font-kai); letter-spacing: 2px; }

.action-bar { display: flex; justify-content: flex-end; margin: -8px 0 18px; }

.main-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: 18px;
  align-items: start;
}

/* ── 工作流列表 ── */
.flow-list { display: grid; gap: 12px; }
.flow-row {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  background: var(--card);
  box-shadow: var(--shadow-card);
  cursor: pointer;
  transition: transform .2s ease, box-shadow .2s ease, border-color .2s ease;
}
.flow-row:hover { transform: translateY(-2px); box-shadow: var(--shadow-lift); border-color: var(--gold-line); }
.flow-row.active { border-color: color-mix(in srgb, var(--rouge) 55%, transparent); box-shadow: var(--shadow-glow-rouge); }
.flow-row.disabled { opacity: .72; }
.flow-main { min-width: 0; flex: 1; }
.flow-name-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.flow-name { font-family: var(--font-kai); font-size: 17px; letter-spacing: 2px; color: var(--ink); overflow-wrap: anywhere; }
.flow-cron { font-family: var(--font-mono); font-size: 10px; color: var(--dai); }
.flow-desc {
  margin-top: 6px;
  font-size: 12px;
  color: var(--ink-soft);
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.flow-steps-count { display: inline-block; margin-top: 8px; font-size: 11px; letter-spacing: 1px; color: var(--ink-muted); }

/* ── 启用开关 ── */
.switch {
  width: 42px;
  height: 23px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--line-soft);
  position: relative;
  flex-shrink: 0;
  transition: background .2s ease, border-color .2s ease;
}
.switch .knob {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 17px;
  height: 17px;
  border-radius: 50%;
  background: var(--ink-muted);
  transition: transform .2s ease, background .2s ease;
}
.switch.on { background: color-mix(in srgb, var(--bamboo) 30%, transparent); border-color: color-mix(in srgb, var(--bamboo) 55%, transparent); }
.switch.on .knob { transform: translateX(19px); background: var(--bamboo); }
.switch:disabled { opacity: .55; cursor: not-allowed; }

/* ── 运行记录侧栏 ── */
.run-list { display: grid; gap: 10px; }
.run-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-small);
  background: color-mix(in srgb, var(--card) 82%, transparent);
}
.run-info { min-width: 0; display: grid; gap: 2px; }
.run-name { font-size: 12px; font-family: var(--font-kai); letter-spacing: 1px; color: var(--ink); overflow-wrap: anywhere; }
.run-time { font-size: 11px; color: var(--ink-muted); }
.run-error { font-size: 11px; color: var(--cinnabar); overflow-wrap: anywhere; }

/* ── 详情 ── */
.detail-card { margin-top: 18px; }
.detail-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; flex-wrap: wrap; }
.detail-title h3 { font-family: var(--font-kai); font-size: 20px; letter-spacing: 2px; color: var(--ink); }
.detail-title p { margin-top: 6px; font-size: 12px; color: var(--ink-soft); line-height: 1.6; max-width: 560px; }

/* ── 步骤时间线 ── */
.timeline { list-style: none; }
.tl-item { position: relative; display: flex; gap: 12px; padding: 9px 0 9px 4px; }
.tl-item::before {
  content: '';
  position: absolute;
  left: 19px;
  top: 42px;
  bottom: -4px;
  width: 1px;
  background: linear-gradient(180deg, var(--gold-line), transparent);
}
.tl-item:last-child::before { display: none; }
.step-dot {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-family: var(--font-kai);
  font-size: 14px;
  font-weight: 700;
  border: 1px solid transparent;
  flex-shrink: 0;
}
.step-dot[data-tone='dai'] { background: color-mix(in srgb, var(--dai) 14%, transparent); border-color: color-mix(in srgb, var(--dai) 34%, transparent); color: var(--dai); }
.step-dot[data-tone='ink'] { background: var(--line-soft); border-color: var(--line); color: var(--ink-soft); }
.step-dot[data-tone='gold'] { background: color-mix(in srgb, var(--gold) 15%, transparent); border-color: color-mix(in srgb, var(--gold) 38%, transparent); color: color-mix(in srgb, var(--gold) 72%, var(--ink)); }
.step-dot[data-tone='rouge'] { background: color-mix(in srgb, var(--rouge) 14%, transparent); border-color: color-mix(in srgb, var(--rouge) 34%, transparent); color: color-mix(in srgb, var(--rouge) 74%, var(--ink)); }
.step-dot[data-tone='bamboo'] { background: color-mix(in srgb, var(--bamboo) 15%, transparent); border-color: color-mix(in srgb, var(--bamboo) 36%, transparent); color: color-mix(in srgb, var(--bamboo) 66%, var(--ink)); }
.tl-body { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding-top: 4px; }
.tl-name { font-size: 13px; color: var(--ink); letter-spacing: 1px; }
.tl-err { font-size: 11px; color: var(--ink-muted); font-family: var(--font-mono); letter-spacing: 1px; }

/* ── AI 编辑 ── */
.ai-input {
  display: block;
  width: 100%;
  resize: vertical;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  background: var(--card);
  color: var(--ink);
  padding: 10px 12px;
  font: inherit;
  font-size: 13px;
  transition: border-color .2s ease, box-shadow .2s ease;
}
.ai-input:focus { outline: none; border-color: var(--cinnabar); box-shadow: 0 0 0 3px var(--rouge-glow); }
.ai-actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
.ai-result {
  margin-top: 14px;
  padding: 14px;
  border: 1px solid var(--gold-line);
  border-radius: var(--radius-card);
  background: color-mix(in srgb, var(--gold) 5%, transparent);
}
.ai-understood { display: flex; gap: 10px; font-size: 13px; color: var(--ink-soft); line-height: 1.7; }
.ai-k {
  flex-shrink: 0;
  font-family: var(--font-kai);
  font-size: 12px;
  letter-spacing: 2px;
  color: var(--cinnabar);
  border: 1px solid var(--line-cinnabar);
  border-radius: 999px;
  padding: 1px 10px;
  height: fit-content;
}
.ai-changes { margin: 10px 0 0 18px; display: grid; gap: 5px; font-size: 12px; color: var(--ink-soft); line-height: 1.6; }
.ai-changes li::marker { color: var(--rouge); }
.ai-json { margin-top: 12px; }
.ai-json summary {
  cursor: pointer;
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 1px;
  color: var(--dai);
}
.ai-json pre {
  margin-top: 8px;
  max-height: 260px;
  overflow: auto;
  padding: 12px;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-small);
  background: var(--bg-soft);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  color: var(--ink-soft);
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.6;
}

/* ── 弹层 ── */
.overlay {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: grid;
  place-items: center;
  padding: 20px;
  background: color-mix(in srgb, var(--ink) 34%, transparent);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
}
.modal {
  width: min(560px, 100%);
  background: var(--card-solid);
  border: 1px solid var(--gold-line);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-lift);
  padding: 20px 22px;
}
.modal-hd { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; }
.modal-seal {
  font-family: var(--font-kai);
  font-size: 13px;
  font-weight: 700;
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  color: #FDF6E9;
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  border-radius: var(--radius-seal);
  box-shadow: 0 0 10px var(--cinnabar-glow);
}
.modal-hd h3 { font-family: var(--font-kai); font-size: 20px; letter-spacing: 3px; color: var(--ink); }
.modal-form { display: grid; gap: 12px; }
.modal-form label { display: grid; gap: 6px; color: var(--ink-muted); font-family: var(--font-mono); font-size: 10px; letter-spacing: 1px; }
.modal-form input, .modal-form textarea, .modal-form select {
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  background: var(--card);
  color: var(--ink);
  padding: 8px 12px;
  font: inherit;
  font-size: 12px;
  transition: border-color .2s ease, box-shadow .2s ease;
}
.modal-form textarea { resize: vertical; }
.modal-form input:focus, .modal-form textarea:focus, .modal-form select:focus {
  outline: none;
  border-color: var(--cinnabar);
  box-shadow: 0 0 0 3px var(--rouge-glow);
}
.field-row { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 4px; }

/* 原生提交/取消按钮（GfButton 固定 type=button） */
.form-submit, .form-cancel {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 8px 20px;
  border-radius: 999px;
  border: 1px solid transparent;
  font-size: 13px;
  letter-spacing: 2px;
  font-family: var(--font-kai);
  cursor: pointer;
  transition: transform .18s ease, box-shadow .18s ease, background .18s ease, color .18s ease, border-color .18s ease;
}
.form-submit {
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  color: #FDF6E9;
  box-shadow: 0 2px 12px var(--cinnabar-glow), var(--shadow-card);
}
.form-submit:hover:not(:disabled) { transform: translateY(-2px); box-shadow: 0 4px 18px var(--cinnabar-glow), var(--shadow-glow-rouge); }
.form-cancel { background: var(--card); border-color: var(--gold-line); color: var(--ink-soft); }
.form-cancel:hover:not(:disabled) { transform: translateY(-2px); border-color: var(--rouge); color: var(--cinnabar); box-shadow: var(--shadow-glow-rouge); }
.form-submit:disabled, .form-cancel:disabled { opacity: .55; cursor: not-allowed; transform: none; box-shadow: none; }

@media (max-width: 980px) {
  .main-grid { grid-template-columns: 1fr; }
}
@media (max-width: 620px) {
  .action-bar { justify-content: flex-start; }
  .ss-runs { margin-left: 0; }
  .field-row { grid-template-columns: 1fr; }
}
</style>
