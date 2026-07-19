<script setup lang="ts">
/**
 * 万枢工作台 —— 旗舰 AI 聊天工作台（V1）。
 * 契约（backend/app/platform_api/agents.py、system_svc.py）：
 *   GET  /agents                        智能体列表
 *   GET  /agents/context-size?agent_id= 上下文用量（返回 total_tokens / limit）
 *   PUT  /agents/{id}                   设定当前智能体目标
 *   POST /agents/chat                   对话 {message, agent_id, depth, gear, goal, attachments}
 *   POST /agents/subagent               派生子任务
 *   GET  /agents/workspace/floating     浮动工作区子代理列表
 *   GET  /agents/runs                   运行记录
 *   POST /agents/runs/{id}/approve      批准人工审查中的运行（以后端返回的真实 status 为准）
 *   POST /system/voice                  语音输入上传
 * 降级口径：仅网络异常（isNetworkError）时降级为本地示例 / 离线模拟并在 UI 明确标注；
 * 鉴权失败等其他错误如实提示，不伪装成功、不做本地假放行。
 */
import { computed, nextTick, onMounted, ref, shallowRef, watch } from 'vue'
import { apiGet, apiPost, apiPut, isAuthError, isNetworkError } from '@/api/platform'
import PageHero from '@/components/gf/PageHero.vue'
import GfCard from '@/components/gf/GfCard.vue'
import GfTag from '@/components/gf/GfTag.vue'
import GfButton from '@/components/gf/GfButton.vue'
import GfEmpty from '@/components/gf/GfEmpty.vue'

function platformErrText(e: unknown): string {
  if (isAuthError(e)) return `鉴权失败：${e.message}（请检查左侧 API 密钥）`
  if (isNetworkError(e)) return '网络异常，后端未连通'
  return e instanceof Error ? e.message : String(e)
}

/* ── 类型 ─────────────────────────────────────────────── */
interface AgentInfo {
  id: string
  name: string
  model?: string
  engine?: string
  goal?: string
}

interface AttachmentMeta {
  name: string
  mime: string
  size: number
  dataUrl?: string
}

interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  time: string
  depth?: string
  gear?: string
  engine?: string
  offline?: boolean
  attachments?: AttachmentMeta[]
  contextTokens?: number
}

interface FloatingAgent {
  id: string
  name: string
  task?: string
  status?: string
  simulated?: boolean
}

interface RunRecord {
  id: string
  title: string
  agent?: string
  status?: string
  created_at?: string
  summary?: string
  simulated?: boolean
}

type TagTone = 'rouge' | 'dai' | 'bamboo' | 'gold' | 'ink'
type ToastKind = 'error' | 'info' | 'ok'

/* ── 枚举（与 backend/app/platform_api/deps.py 对齐） ─── */
const DEPTHS: { key: string; label: string; desc: string }[] = [
  { key: 'low', label: '浅思', desc: '快速应答，最省算力，适合闲谈与简单问答' },
  { key: 'medium', label: '常思', desc: '日常任务的均衡档位' },
  { key: 'high', label: '深思', desc: '复杂问题的深入推理与权衡' },
  { key: 'xhigh', label: '极思', desc: '多步规划与深层推理，耗时明显增加' },
  { key: 'max', label: '穷思', desc: '极致思考，穷尽推演，耗时最长' },
  { key: 'ultracode', label: '超码', desc: '面向编程任务的超深思考模式' },
]
const GEARS: { key: string; label: string; desc: string; tone: 'gold' | 'bamboo' | 'rouge' }[] = [
  { key: 'human_review', label: '人工审查', desc: '每一步动作均需人工批准后执行', tone: 'gold' },
  { key: 'sandbox', label: '沙盒工作', desc: '在隔离沙盒中自动执行，不触达真机', tone: 'bamboo' },
  { key: 'device', label: '整台设备', desc: '可触达整台设备，权限最高，谨慎使用', tone: 'rouge' },
]

const FALLBACK_AGENTS: AgentInfo[] = [
  { id: 'shuyan-default', name: '枢言·默认智能体', model: 'shuyan-72b-chat', engine: '枢忆引擎 · 本地示例' },
]
const FALLBACK_FLOATING: FloatingAgent[] = [
  { id: 'demo-sub-1', name: '采风子代理', task: '整理本周模型网关变更摘要', status: 'running', simulated: true },
  { id: 'demo-sub-2', name: '校对子代理', task: '校对说明文档的中文措辞', status: 'done', simulated: true },
]
const FALLBACK_RUNS: RunRecord[] = [
  { id: 'demo-run-1', title: '沙盒内执行后端快速测试集', agent: '枢言·默认智能体', status: 'human_review', created_at: '示例', summary: '等待人工批准后写入工作区', simulated: true },
  { id: 'demo-run-2', title: '整理知识库索引', agent: '枢言·默认智能体', status: 'done', created_at: '示例', summary: '已重建全文索引', simulated: true },
]

/* ── 基础状态 ─────────────────────────────────────────── */
const agents = shallowRef<AgentInfo[]>([])
const agentsOffline = ref(false)
const currentAgentId = ref('')
const currentAgent = computed<AgentInfo | undefined>(() =>
  agents.value.find((a) => a.id === currentAgentId.value) ?? agents.value[0],
)

const savedDepth = localStorage.getItem('wanwei-workbench-depth') ?? ''
const savedGear = localStorage.getItem('wanwei-workbench-gear') ?? ''
const depth = ref(DEPTHS.some((d) => d.key === savedDepth) ? savedDepth : 'medium')
const gear = ref(GEARS.some((g) => g.key === savedGear) ? savedGear : 'human_review')
watch(depth, (v) => localStorage.setItem('wanwei-workbench-depth', v))
watch(gear, (v) => localStorage.setItem('wanwei-workbench-gear', v))

const currentDepth = computed(() => DEPTHS.find((d) => d.key === depth.value) ?? DEPTHS[1]!)
const currentGear = computed(() => GEARS.find((g) => g.key === gear.value) ?? GEARS[0]!)

const goal = ref('')
const goalDraft = ref('')
const goalSaving = ref(false)
const goalLocal = ref(false)

const messages = ref<ChatMessage[]>([])
const draft = ref('')
const sending = ref(false)
const attachments = ref<AttachmentMeta[]>([])
const msgListEl = ref<HTMLElement | null>(null)
const fileInputEl = ref<HTMLInputElement | null>(null)

const panelOpen = ref(true)

/* 上下文 */
const ctxUsed = ref(0)
const ctxLimit = ref(128000)
const ctxEstimated = ref(true)

/* 语音 */
const voiceSupported =
  typeof navigator !== 'undefined' &&
  !!navigator.mediaDevices?.getUserMedia &&
  typeof MediaRecorder !== 'undefined'
const recording = ref(false)
const voiceBusy = ref(false)
let mediaRecorder: MediaRecorder | null = null
let voiceChunks: Blob[] = []

/* 右侧浮动工作区与运行记录 */
const floating = shallowRef<FloatingAgent[]>([])
const floatingLoading = ref(false)
const floatingOffline = ref(false)
const runs = shallowRef<RunRecord[]>([])
const runsLoading = ref(false)
const runsOffline = ref(false)
const subTask = ref('')
const spawning = ref(false)
const approving = ref('')

/* 行内 toast */
const toast = ref<{ msg: string; kind: ToastKind } | null>(null)
let toastTimer: ReturnType<typeof setTimeout> | undefined

/* ── 工具函数 ─────────────────────────────────────────── */
function uid(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

function nowTime(): string {
  return new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function toastMsg(msg: string, kind: ToastKind = 'info'): void {
  toast.value = { msg, kind }
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => {
    toast.value = null
  }, 4200)
}

function pickList(res: unknown): Record<string, any>[] {
  if (Array.isArray(res)) return res as Record<string, any>[]
  if (res && typeof res === 'object') {
    const obj = res as Record<string, unknown>
    for (const k of ['items', 'agents', 'runs', 'workspaces', 'sessions', 'list', 'data']) {
      const v = obj[k]
      if (Array.isArray(v)) return v as Record<string, any>[]
    }
  }
  return []
}

function depthLabel(key?: string): string {
  return DEPTHS.find((d) => d.key === key)?.label ?? (key || '常思')
}

function gearLabel(key?: string): string {
  return GEARS.find((g) => g.key === key)?.label ?? (key || '人工审查')
}

function gearTone(key?: string): TagTone {
  return GEARS.find((g) => g.key === key)?.tone ?? 'ink'
}

function fmtTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1).replace(/\.0$/, '')}k`
  return `${Math.max(0, Math.round(n))}`
}

function fmtSize(n: number): string {
  if (n >= 1048576) return `${(n / 1048576).toFixed(1)} MB`
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${n} B`
}

/* ── 简易 markdown 渲染（粗体 / 行内代码 / 代码块 / 列表） ─ */
function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function renderInline(s: string): string {
  let out = escapeHtml(s)
  out = out.replace(/`([^`\n]+)`/g, '<code>$1</code>')
  out = out.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
  return out
}

function renderMarkdown(src: string): string {
  const lines = src.split('\n')
  const html: string[] = []
  let inCode = false
  let codeBuf: string[] = []
  let listType: 'ul' | 'ol' | null = null
  const closeList = () => {
    if (listType) {
      html.push(`</${listType}>`)
      listType = null
    }
  }
  for (const line of lines) {
    if (/^\s*```/.test(line)) {
      if (inCode) {
        html.push(`<pre><code>${escapeHtml(codeBuf.join('\n'))}</code></pre>`)
        codeBuf = []
        inCode = false
      } else {
        closeList()
        inCode = true
      }
      continue
    }
    if (inCode) {
      codeBuf.push(line)
      continue
    }
    const ul = /^\s*[-*]\s+(.*)$/.exec(line)
    const ol = /^\s*\d+[.、)]\s+(.*)$/.exec(line)
    if (ul) {
      if (listType !== 'ul') {
        closeList()
        html.push('<ul>')
        listType = 'ul'
      }
      html.push(`<li>${renderInline(ul[1] ?? '')}</li>`)
      continue
    }
    if (ol) {
      if (listType !== 'ol') {
        closeList()
        html.push('<ol>')
        listType = 'ol'
      }
      html.push(`<li>${renderInline(ol[1] ?? '')}</li>`)
      continue
    }
    closeList()
    if (line.trim() === '') html.push('<div class="md-gap"></div>')
    else html.push(`<p>${renderInline(line)}</p>`)
  }
  if (inCode) html.push(`<pre><code>${escapeHtml(codeBuf.join('\n'))}</code></pre>`)
  closeList()
  return html.join('')
}

/* ── 上下文 ───────────────────────────────────────────── */
const ctxPct = computed(() => {
  if (ctxLimit.value <= 0) return 0
  return Math.min(100, Math.max(0, Math.round((ctxUsed.value / ctxLimit.value) * 100)))
})
const ctxOffset = computed(() => 2 * Math.PI * 19 * (1 - ctxPct.value / 100))
const ctxColor = computed(() =>
  ctxPct.value >= 85 ? 'var(--cinnabar)' : ctxPct.value >= 60 ? 'var(--gold)' : 'var(--bamboo)',
)

function estimateContext(): void {
  const chars = messages.value.reduce((n, m) => n + m.content.length, 0) + goal.value.length
  ctxUsed.value = Math.round(chars / 2)
  ctxEstimated.value = true
}

async function loadContextSize(): Promise<void> {
  try {
    // 后端 agents.py context_size 接受 ?agent_id=，返回 total_tokens / limit（total_tokens 置候选链首位）
    const qs = currentAgentId.value ? `?agent_id=${encodeURIComponent(currentAgentId.value)}` : ''
    const res = await apiGet<Record<string, any>>(`/agents/context-size${qs}`)
    const used = Number(res?.total_tokens ?? res?.used ?? res?.tokens ?? res?.context_tokens ?? res?.used_tokens ?? NaN)
    const limit = Number(res?.limit ?? res?.max ?? res?.max_tokens ?? res?.window ?? NaN)
    if (Number.isFinite(limit) && limit > 0) ctxLimit.value = limit
    if (Number.isFinite(used) && used >= 0) {
      ctxUsed.value = used
      ctxEstimated.value = false
    } else {
      estimateContext()
    }
  } catch {
    estimateContext()
  }
}

/* ── 智能体与目标 ─────────────────────────────────────── */
function goalKey(): string {
  return `wanwei-workbench-goal-${currentAgentId.value || 'default'}`
}

async function loadAgents(): Promise<void> {
  try {
    const res = await apiGet<unknown>('/agents')
    const list = pickList(res)
    if (list.length) {
      agents.value = list.map((a, i) => ({
        id: String(a.id ?? a.agent_id ?? `agent-${i}`),
        name: String(a.name ?? a.title ?? `智能体 ${i + 1}`),
        model: a.model ?? a.model_name,
        engine: a.engine ?? a.provider,
        goal: a.goal,
      }))
      agentsOffline.value = false
    } else {
      agents.value = FALLBACK_AGENTS
      agentsOffline.value = true
    }
  } catch (e) {
    const network = isNetworkError(e)
    agents.value = network ? FALLBACK_AGENTS : []
    agentsOffline.value = network
  }
  if (!agents.value.some((a) => a.id === currentAgentId.value)) {
    currentAgentId.value = agents.value[0]?.id ?? ''
  }
  const cur = currentAgent.value
  goalDraft.value = cur?.goal ?? localStorage.getItem(goalKey()) ?? ''
  goal.value = cur?.goal ?? localStorage.getItem(goalKey()) ?? ''
  goalLocal.value = !cur?.goal && !!localStorage.getItem(goalKey())
}

function onAgentSelect(e: Event): void {
  currentAgentId.value = (e.target as HTMLSelectElement).value
  const cur = currentAgent.value
  goalDraft.value = cur?.goal ?? localStorage.getItem(goalKey()) ?? ''
  goal.value = cur?.goal ?? localStorage.getItem(goalKey()) ?? ''
  goalLocal.value = !cur?.goal && !!localStorage.getItem(goalKey())
  void loadContextSize()
}

async function saveGoal(): Promise<void> {
  if (goalSaving.value) return
  goalSaving.value = true
  const g = goalDraft.value.trim()
  try {
    await apiPut(`/agents/${encodeURIComponent(currentAgentId.value)}`, { goal: g })
    goalLocal.value = false
    localStorage.removeItem(goalKey())
    toastMsg('目标已落笔，并同步到当前智能体', 'ok')
  } catch (e) {
    localStorage.setItem(goalKey(), g)
    goalLocal.value = true
    if (isAuthError(e)) {
      toastMsg(`鉴权失败：${e.message}（请检查左侧 API 密钥）`, 'error')
    } else {
      toastMsg('后端未连通，目标已暂存本机', 'info')
    }
  } finally {
    goal.value = g
    goalSaving.value = false
  }
}

function onGoalEnter(e: KeyboardEvent): void {
  if (e.key === 'Enter' && !e.isComposing) {
    e.preventDefault()
    void saveGoal()
  }
}

/* ── 附件 ─────────────────────────────────────────────── */
// 前端限制：单次最多 5 个附件、单文件不超过 10 MB。
// 后端契约仅接收附件元数据（name/mime/size），内容本就不上传；
// 限制主要为防止图片 dataURL 预览把内存拖垮，并在超限时刻给出中文提示。
const ATTACH_MAX_COUNT = 5
const ATTACH_MAX_SIZE = 10 * 1024 * 1024

// 长会话防内存无限增长：消息列表硬上限与修剪目标
const MESSAGE_CAP = 200
const MESSAGE_KEEP = 160

function pickFiles(): void {
  fileInputEl.value?.click()
}

function onPickFiles(e: Event): void {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  for (const f of files) {
    if (attachments.value.length >= ATTACH_MAX_COUNT) {
      toastMsg(`附件最多 ${ATTACH_MAX_COUNT} 个，超出部分已忽略`, 'error')
      break
    }
    if (f.size > ATTACH_MAX_SIZE) {
      toastMsg(`「${f.name}」大小 ${fmtSize(f.size)}，超过单文件 ${fmtSize(ATTACH_MAX_SIZE)} 上限，未添加`, 'error')
      continue
    }
    const att: AttachmentMeta = {
      name: f.name,
      mime: f.type || 'application/octet-stream',
      size: f.size,
    }
    attachments.value = [...attachments.value, att]
    if (f.type.startsWith('image/')) {
      const reader = new FileReader()
      reader.onload = () => {
        att.dataUrl = String(reader.result ?? '')
        attachments.value = [...attachments.value]
      }
      reader.readAsDataURL(f)
    }
  }
  input.value = ''
}

function removeAttachment(i: number): void {
  attachments.value = attachments.value.filter((_, idx) => idx !== i)
}

/* ── 语音输入 ─────────────────────────────────────────── */
function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader()
    r.onload = () => resolve(String(r.result ?? ''))
    r.onerror = () => reject(new Error('读取录音失败'))
    r.readAsDataURL(blob)
  })
}

async function toggleVoice(): Promise<void> {
  if (!voiceSupported || voiceBusy.value) return
  if (recording.value) {
    mediaRecorder?.stop()
    return
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    voiceChunks = []
    const rec = new MediaRecorder(stream)
    mediaRecorder = rec
    rec.ondataavailable = (ev: BlobEvent) => {
      if (ev.data.size) voiceChunks.push(ev.data)
    }
    rec.onstop = () => {
      stream.getTracks().forEach((t) => t.stop())
      recording.value = false
      const blob = new Blob(voiceChunks, { type: rec.mimeType || 'audio/webm' })
      void uploadVoice(blob)
    }
    rec.start()
    recording.value = true
    toastMsg('录音中……再次点击语音按钮结束', 'info')
  } catch {
    toastMsg('无法访问麦克风，请检查系统权限', 'error')
  }
}

async function uploadVoice(blob: Blob): Promise<void> {
  if (!blob.size) return
  voiceBusy.value = true
  try {
    const dataUrl = await blobToDataUrl(blob)
    const base64 = dataUrl.split(',')[1] ?? ''
    const res = await apiPost<Record<string, any>>('/system/voice', {
      audio_b64: base64,
      mime: blob.type,
      duration_ms: 0,
    })
    const text = String(res?.transcription ?? '').trim()
    if (text) {
      draft.value = draft.value ? `${draft.value}\n${text}` : text
      toastMsg('语音已转写并填入输入框', 'ok')
    } else {
      toastMsg('语音已上传，后端未返回转写文本', 'info')
    }
  } catch (e) {
    toastMsg(`语音上传失败：${platformErrText(e)}`, 'error')
  } finally {
    voiceBusy.value = false
  }
}

/* ── 发送消息 ─────────────────────────────────────────── */
function trimMessages(): void {
  if (messages.value.length > MESSAGE_CAP) {
    messages.value = messages.value.slice(-MESSAGE_KEEP)
  }
}

function scrollToBottom(): void {
  void nextTick(() => {
    const el = msgListEl.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

async function send(): Promise<void> {
  const text = draft.value.trim()
  const atts = attachments.value
  if (sending.value || (!text && atts.length === 0)) return
  // 发送消息时只保留附件元数据，不持久化图片 dataURL，避免长会话内存膨胀
  const userMsg: ChatMessage = {
    id: uid(),
    role: 'user',
    content: text || '（随信附件）',
    time: nowTime(),
    attachments: atts.map((a) => ({ name: a.name, mime: a.mime, size: a.size })),
  }
  messages.value = [...messages.value, userMsg]
  trimMessages()
  draft.value = ''
  attachments.value = []
  sending.value = true
  scrollToBottom()
  const payload = {
    message: text,
    agent_id: currentAgentId.value || undefined,
    depth: depth.value,
    gear: gear.value,
    goal: goal.value,
    attachments: atts.map((a) => ({ name: a.name, mime: a.mime, size: a.size })),
  }
  try {
    const res = await apiPost<Record<string, any>>('/agents/chat', payload)
    const reply = String(res?.reply ?? res?.message ?? res?.content ?? res?.text ?? '（后端返回为空）')
    const ct = Number(res?.context_tokens ?? res?.used_tokens ?? NaN)
    messages.value = [
      ...messages.value,
      {
        id: uid(),
        role: 'assistant',
        content: reply,
        time: nowTime(),
        depth: String(res?.depth ?? depth.value),
        gear: String(res?.gear ?? gear.value),
        engine: String(
          res?.engine ?? res?.model ?? currentAgent.value?.engine ?? currentAgent.value?.model ?? '枢忆引擎',
        ),
        contextTokens: Number.isFinite(ct) ? ct : undefined,
      },
    ]
    trimMessages()
    if (Number.isFinite(ct)) {
      ctxUsed.value = ct
      ctxEstimated.value = false
    }
  } catch (e) {
    if (isNetworkError(e)) {
      const sim = [
        '（离线模拟回复）未能连通万枢后端，以下为本地模拟应答，并非真实模型输出。',
        '',
        `你刚才说：「${text || '（附件）'}」`,
        '',
        `- 思考深度：${depthLabel(depth.value)}（${currentDepth.value.desc}）`,
        `- 工作档位：${gearLabel(gear.value)}（${currentGear.value.desc}）`,
        goal.value ? `- 当前目标：${goal.value}` : '- 当前目标：未设定',
        '',
        '服务恢复后，将按以上配置真实执行。',
      ].join('\n')
      messages.value = [
        ...messages.value,
        {
          id: uid(),
          role: 'assistant',
          content: sim,
          time: nowTime(),
          depth: depth.value,
          gear: gear.value,
          engine: '本地模拟',
          offline: true,
        },
      ]
      trimMessages()
      toastMsg('后端未连通，已切换为离线模拟回复', 'error')
      if (ctxEstimated.value) estimateContext()
    } else {
      toastMsg(`发送失败：${platformErrText(e)}`, 'error')
    }
  } finally {
    sending.value = false
    scrollToBottom()
  }
}

function onEnterKey(e: KeyboardEvent): void {
  if (e.key === 'Enter' && !e.isComposing && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
    e.preventDefault()
    void send()
  }
}

/* ── 浮动工作区与运行记录 ─────────────────────────────── */
async function loadFloating(): Promise<void> {
  floatingLoading.value = true
  try {
    const res = await apiGet<unknown>('/agents/workspace/floating')
    floating.value = pickList(res).map((w, i) => ({
      id: String(w.id ?? w.session_id ?? `ws-${i}`),
      name: String(w.name ?? w.title ?? w.agent ?? `子代理 ${i + 1}`),
      task: w.task ?? w.goal ?? w.summary,
      status: w.status ? String(w.status) : 'running',
    }))
    floatingOffline.value = false
  } catch (e) {
    const network = isNetworkError(e)
    floating.value = network ? FALLBACK_FLOATING : []
    floatingOffline.value = network
  } finally {
    floatingLoading.value = false
  }
}

async function loadRuns(): Promise<void> {
  runsLoading.value = true
  try {
    const res = await apiGet<unknown>('/agents/runs')
    runs.value = pickList(res).map((r, i) => ({
      id: String(r.id ?? r.run_id ?? `run-${i}`),
      title: String(r.title ?? r.name ?? r.task ?? `运行 ${i + 1}`),
      agent: r.agent ?? r.agent_name,
      status: r.status ? String(r.status) : 'unknown',
      created_at: r.created_at ?? r.time ?? r.started_at,
      summary: r.summary ?? r.note,
    }))
    runsOffline.value = false
  } catch (e) {
    const network = isNetworkError(e)
    runs.value = network ? FALLBACK_RUNS : []
    runsOffline.value = network
  } finally {
    runsLoading.value = false
  }
}

async function spawnSubagent(): Promise<void> {
  const task = subTask.value.trim()
  if (!task || spawning.value) return
  spawning.value = true
  try {
    await apiPost('/agents/subagent', {
      task,
      agent_id: currentAgentId.value || undefined,
      depth: depth.value,
      gear: gear.value,
    })
    subTask.value = ''
    toastMsg('子任务已派发至浮动工作区', 'ok')
    await loadFloating()
  } catch (e) {
    if (isNetworkError(e)) {
      floating.value = [
        ...floating.value,
        { id: `local-${uid()}`, name: '临时子代理', task, status: 'queued', simulated: true },
      ]
      subTask.value = ''
      toastMsg('后端未连通，已本地模拟派生', 'info')
    } else {
      toastMsg(`派发失败：${platformErrText(e)}`, 'error')
    }
  } finally {
    spawning.value = false
  }
}

function onSubEnter(e: KeyboardEvent): void {
  if (e.key === 'Enter' && !e.isComposing) {
    e.preventDefault()
    void spawnSubagent()
  }
}

async function approveRun(run: RunRecord): Promise<void> {
  if (approving.value) return
  approving.value = run.id
  try {
    const res = await apiPost<Record<string, any>>(`/agents/runs/${encodeURIComponent(run.id)}/approve`, {})
    // 以后端返回的真实 status 为准（批准后通常回到 running 继续推进），不再本地假置 approved；
    // 响应缺 status 时回退为整表刷新（与 MobileView decide() 修法对齐）。
    const actual = typeof res?.status === 'string' && res.status ? res.status : ''
    if (actual) {
      runs.value = runs.value.map((r) => (r.id === run.id ? { ...r, status: actual } : r))
    } else {
      await loadRuns()
    }
    toastMsg(actual === 'running' ? '已批阅放行，运行继续推进' : '已批阅放行该运行', 'ok')
  } catch (e) {
    // 含断网在内的任何失败都如实提示，不做本地假放行
    toastMsg(`批准失败：${platformErrText(e)}`, 'error')
  } finally {
    approving.value = ''
  }
}

function subStatusMeta(status?: string): { label: string; tone: TagTone } {
  const s = (status ?? '').toLowerCase()
  if (['running', 'in_progress', 'working'].includes(s)) return { label: '运行中', tone: 'dai' }
  if (['queued', 'pending'].includes(s)) return { label: '排队中', tone: 'gold' }
  if (['done', 'completed', 'success', 'finished'].includes(s)) return { label: '已完成', tone: 'bamboo' }
  if (['failed', 'error'].includes(s)) return { label: '失败', tone: 'rouge' }
  return { label: status || '待命', tone: 'ink' }
}

function runStatusMeta(status?: string): { label: string; tone: TagTone; review: boolean } {
  const s = (status ?? '').toLowerCase()
  // awaiting_review 是后端 agents.py 的真实审查态（与 AgentsView 对齐）；
  // 其余 4 个为历史/兼容别名，保留容错。
  if (['awaiting_review', 'human_review', 'pending_review', 'review', 'awaiting_approval', 'waiting_review'].includes(s)) {
    return { label: '待审查', tone: 'gold', review: true }
  }
  if (['running', 'in_progress', 'processing'].includes(s)) return { label: '运行中', tone: 'dai', review: false }
  if (s === 'approved') return { label: '已批准', tone: 'bamboo', review: false }
  if (s === 'rejected') return { label: '已驳回', tone: 'rouge', review: false }
  if (s === 'cancelled') return { label: '已取消', tone: 'ink', review: false }
  if (['done', 'completed', 'success', 'finished'].includes(s)) return { label: '已完成', tone: 'bamboo', review: false }
  if (['failed', 'error'].includes(s)) return { label: '失败', tone: 'rouge', review: false }
  return { label: status || '未知', tone: 'ink', review: false }
}

/* ── 挂载 ─────────────────────────────────────────────── */
onMounted(async () => {
  await loadAgents()
  await Promise.all([loadContextSize(), loadFloating(), loadRuns()])
})
</script>

<template>
  <div class="wb">
    <PageHero
      seal="枢"
      title="万枢工作台"
      en="WANSHU WORKBENCH"
      sub="择智能体、定思考深度、控执行档位、立当前目标——统筹子代理于浮动工作区，对话即操演。"
    />

    <!-- 行内 toast -->
    <transition name="toast-fade">
      <div v-if="toast" class="toast" :data-kind="toast.kind" role="status" aria-live="polite">
        <span class="toast-text">{{ toast.msg }}</span>
        <button class="toast-x" type="button" aria-label="关闭提示" @click="toast = null">×</button>
      </div>
    </transition>

    <div class="panel-toggle">
      <GfButton variant="ghost" small @click="panelOpen = !panelOpen">
        {{ panelOpen ? '收起侧栏' : '展开侧栏' }}
      </GfButton>
    </div>

    <div class="wb-layout" :class="{ 'panel-hidden': !panelOpen }">
      <div class="wb-main">
        <!-- ── 操演台 ── -->
        <GfCard title="操演台" seal="令">
          <div class="tb-grid">
            <div class="tb-block">
              <span class="tb-label">智能体</span>
              <div class="tb-row">
                <select class="tb-select" :value="currentAgentId" aria-label="选择智能体" @change="onAgentSelect">
                  <option v-for="a in agents" :key="a.id" :value="a.id">{{ a.name }}</option>
                </select>
                <GfTag v-if="agentsOffline" tone="ink">示例</GfTag>
              </div>
              <span class="tb-hint">
                模型 {{ currentAgent?.model ?? '待配置' }}<template v-if="currentAgent?.engine"> · {{ currentAgent.engine }}</template>
              </span>
            </div>

            <div class="tb-block">
              <span class="tb-label">思考深度</span>
              <div class="seg" role="radiogroup" aria-label="思考深度">
                <button
                  v-for="d in DEPTHS"
                  :key="d.key"
                  type="button"
                  class="seg-btn"
                  :class="{ on: depth === d.key }"
                  :title="`${d.label}：${d.desc}`"
                  :aria-pressed="depth === d.key"
                  @click="depth = d.key"
                >
                  {{ d.label }}
                </button>
              </div>
              <span class="tb-hint">{{ currentDepth.label }}：{{ currentDepth.desc }}</span>
            </div>

            <div class="tb-block">
              <span class="tb-label">工作档位</span>
              <div class="seg" role="radiogroup" aria-label="工作档位">
                <button
                  v-for="g in GEARS"
                  :key="g.key"
                  type="button"
                  class="seg-btn gear-btn"
                  :class="{ on: gear === g.key }"
                  :data-tone="g.tone"
                  :title="`${g.label}：${g.desc}`"
                  :aria-pressed="gear === g.key"
                  @click="gear = g.key"
                >
                  <span class="gear-dot" :data-tone="g.tone" aria-hidden="true"></span>{{ g.label }}
                </button>
              </div>
              <span class="tb-hint">{{ currentGear.label }}：{{ currentGear.desc }}</span>
            </div>

            <div class="tb-block tb-ctx" :title="ctxEstimated ? '上下文为本地估算值，上限按 128k 计' : '上下文用量来自后端统计'">
              <span class="tb-label">上下文</span>
              <div class="ctx-wrap">
                <svg class="ctx-ring" viewBox="0 0 48 48" width="54" height="54" role="img" :aria-label="`上下文已用约 ${ctxPct}%`">
                  <circle cx="24" cy="24" r="19" class="ctx-track" />
                  <circle
                    cx="24"
                    cy="24"
                    r="19"
                    class="ctx-fill"
                    :style="{ stroke: ctxColor, strokeDashoffset: `${ctxOffset}px` }"
                  />
                  <text x="24" y="28" class="ctx-pct" text-anchor="middle">{{ ctxPct }}%</text>
                </svg>
                <div class="ctx-nums">
                  <span class="ctx-used">约 {{ fmtTokens(ctxUsed) }} / {{ fmtTokens(ctxLimit) }}</span>
                  <span class="ctx-sub">{{ ctxEstimated ? '本地估算 · 上限 128k' : '后端统计' }}</span>
                </div>
              </div>
            </div>
          </div>
        </GfCard>

        <!-- ── 目标设定 ── -->
        <GfCard title="目标设定" seal="鹄">
          <div class="goal-row">
            <input
              v-model="goalDraft"
              class="goal-input"
              type="text"
              placeholder="为当前智能体立下目标，例如：完成周报初稿并自检一遍"
              :disabled="goalSaving"
              aria-label="目标设定"
              @keydown="onGoalEnter"
            />
            <GfButton small :disabled="goalSaving" @click="saveGoal">{{ goalSaving ? '落笔中…' : '落笔' }}</GfButton>
          </div>
          <p class="goal-state">
            <template v-if="goal">
              当前目标：{{ goal }}
              <GfTag v-if="goalLocal" tone="gold">本机暂存</GfTag>
              <GfTag v-else tone="bamboo">已同步</GfTag>
            </template>
            <template v-else>尚未设定目标，智能体将按默认使命行事。</template>
          </p>
        </GfCard>

        <!-- ── 花笺对话 ── -->
        <GfCard title="花笺对话" seal="笺" :pad="false" class="wb-chat">
          <div ref="msgListEl" class="msg-list">
            <GfEmpty v-if="!messages.length && !sending" text="笺上尚无字迹，写下第一句吧。" />
            <article
              v-for="m in messages"
              :key="m.id"
              class="msg"
              :class="m.role === 'user' ? 'msg-user' : 'msg-ai'"
            >
              <header v-if="m.role === 'assistant'" class="msg-head">
                <span class="msg-who">{{ currentAgent?.name ?? '智能体' }}</span>
                <GfTag v-if="m.depth" tone="dai">{{ depthLabel(m.depth) }}</GfTag>
                <GfTag v-if="m.gear" :tone="gearTone(m.gear)">{{ gearLabel(m.gear) }}</GfTag>
                <GfTag v-if="m.offline" tone="gold">离线模拟</GfTag>
                <span v-if="m.engine" class="msg-engine">{{ m.engine }}</span>
              </header>
              <header v-else class="msg-head msg-head-user">
                <span class="msg-who">我</span>
              </header>
              <div v-if="m.attachments?.length" class="msg-atts">
                <span v-for="(att, i) in m.attachments" :key="i" class="att-chip">
                  <img v-if="att.dataUrl" :src="att.dataUrl" :alt="att.name" class="att-thumb" />
                  <span class="att-name">{{ att.name }}</span>
                </span>
              </div>
              <div class="msg-body" v-html="renderMarkdown(m.content)"></div>
              <footer class="msg-foot">
                <span class="msg-time">{{ m.time }}</span>
                <span v-if="m.contextTokens !== undefined" class="msg-ctx">
                  上下文 {{ fmtTokens(m.contextTokens) }} tokens
                </span>
              </footer>
            </article>
            <div v-if="sending" class="msg msg-ai">
              <div class="msg-body thinking">
                研墨作答中
                <span class="dots" aria-hidden="true"><i></i><i></i><i></i></span>
              </div>
            </div>
          </div>

          <div class="composer">
            <div v-if="attachments.length" class="composer-atts">
              <span v-for="(att, i) in attachments" :key="`${att.name}-${i}`" class="att-chip">
                <img v-if="att.dataUrl" :src="att.dataUrl" :alt="att.name" class="att-thumb" />
                <span class="att-name">{{ att.name }}</span>
                <span class="att-size">{{ fmtSize(att.size) }}</span>
                <button type="button" class="att-x" :aria-label="`移除附件 ${att.name}`" @click="removeAttachment(i)">×</button>
              </span>
            </div>
            <textarea
              v-model="draft"
              class="composer-input"
              rows="3"
              placeholder="写下要交予智能体的事……（Enter 寄出，Shift+Enter 换行）"
              aria-label="消息输入"
              @keydown="onEnterKey"
            ></textarea>
            <div class="composer-bar">
              <input ref="fileInputEl" type="file" multiple hidden aria-hidden="true" @change="onPickFiles" />
              <GfButton variant="ghost" small :title="`最多 ${ATTACH_MAX_COUNT} 个附件，单文件不超过 ${fmtSize(ATTACH_MAX_SIZE)}`" @click="pickFiles">插入文件 / 图片</GfButton>
              <GfButton
                variant="ghost"
                small
                :disabled="!voiceSupported || voiceBusy"
                :title="voiceSupported ? (recording ? '再次点击结束录音' : '语音输入') : '当前环境不支持录音'"
                @click="toggleVoice"
              >
                <svg
                  class="mic-icon"
                  viewBox="0 0 24 24"
                  width="13"
                  height="13"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.8"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  aria-hidden="true"
                >
                  <rect x="9" y="3" width="6" height="11" rx="3" />
                  <path d="M5 11a7 7 0 0 0 14 0" />
                  <line x1="12" y1="18" x2="12" y2="21" />
                </svg>
                <span v-if="recording" class="rec-dot" aria-hidden="true"></span>
                {{ voiceBusy ? '上传中…' : recording ? '停止录音' : '语音输入' }}
              </GfButton>
              <span v-if="!voiceSupported" class="voice-hint">当前环境不支持语音输入</span>
              <span class="composer-spacer"></span>
              <GfButton :disabled="sending || (!draft.trim() && !attachments.length)" @click="send">
                {{ sending ? '寄出中…' : '寄出' }}
              </GfButton>
            </div>
          </div>
        </GfCard>
      </div>

      <!-- ── 右侧可折叠面板 ── -->
      <aside v-show="panelOpen" class="wb-side">
        <GfCard title="浮动工作区" seal="浮">
          <p v-if="floatingOffline" class="offline-line">后端未连通，以下为示例数据</p>
          <div v-if="floatingLoading" class="side-load">研墨中…</div>
          <template v-else>
            <GfEmpty v-if="!floating.length" text="浮动工作区暂无子代理。" />
            <ul v-else class="sub-list">
              <li v-for="s in floating" :key="s.id" class="sub-item">
                <div class="sub-head">
                  <span class="sub-name">{{ s.name }}</span>
                  <GfTag :tone="subStatusMeta(s.status).tone">{{ subStatusMeta(s.status).label }}</GfTag>
                </div>
                <p v-if="s.task" class="sub-task">{{ s.task }}</p>
                <GfTag v-if="s.simulated" tone="ink">示例</GfTag>
              </li>
            </ul>
          </template>
          <div class="sub-spawn">
            <input
              v-model="subTask"
              class="sub-input"
              type="text"
              placeholder="派生子任务，例如：检索最近的报错日志"
              aria-label="派生子任务"
              @keydown="onSubEnter"
            />
            <GfButton small variant="ghost" :disabled="spawning || !subTask.trim()" @click="spawnSubagent">
              {{ spawning ? '派发中…' : '派发' }}
            </GfButton>
          </div>
        </GfCard>

        <GfCard title="运行记录" seal="录">
          <div class="runs-head">
            <p v-if="runsOffline" class="offline-line">后端未连通，以下为示例数据</p>
            <GfButton small variant="ghost" :disabled="runsLoading" @click="loadRuns">
              {{ runsLoading ? '刷新中…' : '刷新' }}
            </GfButton>
          </div>
          <div v-if="runsLoading && !runs.length" class="side-load">研墨中…</div>
          <template v-else>
            <GfEmpty v-if="!runs.length" text="尚无运行记录。" />
            <ul v-else class="run-list">
              <li
                v-for="r in runs"
                :key="r.id"
                class="run-item"
                :class="{ 'run-review': runStatusMeta(r.status).review }"
              >
                <div class="run-head">
                  <span class="run-title">{{ r.title }}</span>
                  <GfTag :tone="runStatusMeta(r.status).tone">{{ runStatusMeta(r.status).label }}</GfTag>
                </div>
                <p v-if="r.summary" class="run-summary">{{ r.summary }}</p>
                <div class="run-foot">
                  <span class="run-meta">
                    {{ r.agent ?? '' }}<template v-if="r.created_at"> · {{ r.created_at }}</template>
                    <GfTag v-if="r.simulated" tone="ink">示例</GfTag>
                  </span>
                  <GfButton
                    v-if="runStatusMeta(r.status).review"
                    small
                    :disabled="approving === r.id"
                    @click="approveRun(r)"
                  >
                    {{ approving === r.id ? '批阅中…' : '批准放行' }}
                  </GfButton>
                </div>
              </li>
            </ul>
          </template>
        </GfCard>
      </aside>
    </div>
  </div>
</template>

<style scoped>
/* ── 布局 ── */
.panel-toggle { display: flex; justify-content: flex-end; margin: -8px 0 14px; }
.wb-layout { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 20px; align-items: start; }
.wb-layout.panel-hidden { grid-template-columns: minmax(0, 1fr); }
.wb-main { display: grid; gap: 20px; min-width: 0; }
.wb-side { display: grid; gap: 20px; min-width: 0; position: sticky; top: 16px; }

/* ── toast ── */
.toast {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 0 0 16px;
  padding: 10px 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  font-size: 12px;
}
.toast[data-kind='error'] {
  color: var(--cinnabar-deep);
  border-color: var(--line-cinnabar);
  background: color-mix(in srgb, var(--cinnabar) 7%, transparent);
}
.toast[data-kind='ok'] {
  color: color-mix(in srgb, var(--bamboo) 70%, var(--ink));
  border-color: color-mix(in srgb, var(--bamboo) 40%, transparent);
  background: color-mix(in srgb, var(--bamboo) 8%, transparent);
}
.toast[data-kind='info'] {
  color: color-mix(in srgb, var(--dai) 78%, var(--ink));
  border-color: color-mix(in srgb, var(--dai) 34%, transparent);
  background: color-mix(in srgb, var(--dai) 7%, transparent);
}
.toast-text { line-height: 1.6; }
.toast-x {
  border: none;
  background: none;
  color: inherit;
  font-size: 15px;
  cursor: pointer;
  padding: 0 4px;
  opacity: .7;
}
.toast-x:hover { opacity: 1; }
.toast-fade-enter-active, .toast-fade-leave-active { transition: opacity .25s ease, transform .25s ease; }
.toast-fade-enter-from, .toast-fade-leave-to { opacity: 0; transform: translateY(-6px); }

/* ── 操演台 ── */
.tb-grid { display: flex; flex-wrap: wrap; gap: 18px 26px; align-items: flex-start; }
.tb-block { display: grid; gap: 8px; align-content: start; }
.tb-label {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 2px;
  color: var(--ink-muted);
}
.tb-row { display: flex; align-items: center; gap: 8px; }
.tb-hint { font-size: 11px; color: var(--ink-muted); letter-spacing: 1px; max-width: 340px; line-height: 1.6; }
.tb-select {
  min-width: 180px;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  background: var(--card);
  color: var(--ink);
  padding: 8px 12px;
  font: inherit;
  font-size: 12px;
  transition: border-color .2s ease, box-shadow .2s ease;
}
.tb-select:focus {
  outline: none;
  border-color: var(--cinnabar);
  box-shadow: 0 0 0 3px var(--rouge-glow);
}

.seg { display: flex; flex-wrap: wrap; gap: 6px; }
.seg-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 13px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--card);
  color: var(--ink-soft);
  font-family: var(--font-kai);
  font-size: 12px;
  letter-spacing: 1px;
  cursor: pointer;
  transition: border-color .18s ease, color .18s ease, background .18s ease, box-shadow .18s ease, transform .18s ease;
}
.seg-btn:hover { transform: translateY(-1px); border-color: var(--gold-line); }
.seg-btn.on {
  border-color: var(--cinnabar);
  color: var(--cinnabar);
  background: color-mix(in srgb, var(--cinnabar) 8%, transparent);
  box-shadow: 0 0 10px var(--cinnabar-glow);
}
.gear-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.gear-dot[data-tone='gold'] { background: var(--gold); box-shadow: 0 0 6px color-mix(in srgb, var(--gold) 60%, transparent); }
.gear-dot[data-tone='bamboo'] { background: var(--bamboo); box-shadow: 0 0 6px color-mix(in srgb, var(--bamboo) 60%, transparent); }
.gear-dot[data-tone='rouge'] { background: var(--rouge); box-shadow: 0 0 6px var(--rouge-glow); }
.gear-btn.on[data-tone='gold'] {
  border-color: var(--gold);
  color: color-mix(in srgb, var(--gold) 72%, var(--ink));
  background: color-mix(in srgb, var(--gold) 10%, transparent);
  box-shadow: 0 0 10px color-mix(in srgb, var(--gold) 30%, transparent);
}
.gear-btn.on[data-tone='bamboo'] {
  border-color: var(--bamboo);
  color: color-mix(in srgb, var(--bamboo) 72%, var(--ink));
  background: color-mix(in srgb, var(--bamboo) 10%, transparent);
  box-shadow: 0 0 10px color-mix(in srgb, var(--bamboo) 30%, transparent);
}
.gear-btn.on[data-tone='rouge'] {
  border-color: var(--rouge);
  color: color-mix(in srgb, var(--rouge) 74%, var(--ink));
  background: color-mix(in srgb, var(--rouge) 10%, transparent);
  box-shadow: 0 0 10px var(--rouge-glow);
}

/* ── 上下文环形指示 ── */
.ctx-wrap { display: flex; align-items: center; gap: 12px; }
.ctx-track { fill: none; stroke: var(--line-soft); stroke-width: 5; }
.ctx-fill {
  fill: none;
  stroke-width: 5;
  stroke-linecap: round;
  stroke-dasharray: 119.4px;
  transform: rotate(-90deg);
  transform-origin: center;
  transition: stroke-dashoffset .5s ease, stroke .5s ease;
}
.ctx-pct { font-family: var(--font-mono); font-size: 10px; fill: var(--ink-soft); }
.ctx-nums { display: grid; gap: 3px; }
.ctx-used { font-family: var(--font-mono); font-size: 13px; color: var(--ink); }
.ctx-sub { font-size: 10px; letter-spacing: 1px; color: var(--ink-muted); }

/* ── 目标设定 ── */
.goal-row { display: flex; gap: 10px; align-items: center; }
.goal-input {
  flex: 1;
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  background: var(--card);
  color: var(--ink);
  padding: 9px 13px;
  font: inherit;
  font-size: 13px;
  transition: border-color .2s ease, box-shadow .2s ease;
}
.goal-input:focus {
  outline: none;
  border-color: var(--cinnabar);
  box-shadow: 0 0 0 3px var(--rouge-glow);
}
.goal-state { margin-top: 10px; font-size: 12px; color: var(--ink-soft); line-height: 1.7; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }

/* ── 消息流 ── */
.wb-chat :deep(.gf-card-bd) { padding: 0; }
.msg-list {
  max-height: 56vh;
  min-height: 320px;
  overflow-y: auto;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.msg {
  max-width: 78%;
  border-radius: var(--radius-card);
  border: 1px solid var(--line);
  padding: 10px 14px;
  box-shadow: var(--shadow-card);
}
.msg-user {
  align-self: flex-end;
  background: color-mix(in srgb, var(--dai) 9%, var(--card-solid));
  border-color: color-mix(in srgb, var(--dai) 26%, transparent);
  border-bottom-right-radius: var(--radius-small);
}
.msg-ai {
  align-self: flex-start;
  background: var(--card-solid);
  border-bottom-left-radius: var(--radius-small);
}
.msg-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 6px; }
.msg-head-user { justify-content: flex-end; }
.msg-who { font-family: var(--font-kai); font-size: 13px; font-weight: 700; letter-spacing: 2px; color: var(--ink); }
.msg-engine { font-family: var(--font-mono); font-size: 10px; letter-spacing: 1px; color: var(--ink-muted); }
.msg-body { font-size: 13px; line-height: 1.75; color: var(--ink-soft); overflow-wrap: anywhere; }
.msg-body :deep(p) { margin: 0 0 6px; }
.msg-body :deep(p:last-child) { margin-bottom: 0; }
.msg-body :deep(.md-gap) { height: 6px; }
.msg-body :deep(pre) {
  background: var(--bg-soft);
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-small);
  padding: 10px 12px;
  overflow-x: auto;
  margin: 8px 0;
}
.msg-body :deep(code) { font-family: var(--font-mono); font-size: 11.5px; color: var(--dai); }
.msg-body :deep(pre code) { color: var(--ink-soft); }
.msg-body :deep(ul), .msg-body :deep(ol) { margin: 4px 0 8px; padding-left: 20px; }
.msg-body :deep(li) { margin: 2px 0; }
.msg-body :deep(strong) { color: var(--ink); font-weight: 700; }
.msg-foot { display: flex; gap: 12px; margin-top: 6px; }
.msg-time { font-family: var(--font-mono); font-size: 10px; color: var(--ink-muted); }
.msg-ctx { font-family: var(--font-mono); font-size: 10px; color: var(--gold); }
.msg-atts { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }

.thinking { display: flex; align-items: center; gap: 6px; font-family: var(--font-kai); letter-spacing: 2px; color: var(--ink-muted); }
.dots { display: inline-flex; gap: 3px; }
.dots i {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--rouge);
  animation: dotPulse 1.1s ease-in-out infinite;
}
.dots i:nth-child(2) { animation-delay: .18s; }
.dots i:nth-child(3) { animation-delay: .36s; }
@keyframes dotPulse {
  0%, 100% { opacity: .25; transform: translateY(0); }
  50% { opacity: 1; transform: translateY(-3px); }
}

/* ── 附件 ── */
.att-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 999px;
  border: 1px solid var(--gold-line);
  background: color-mix(in srgb, var(--gold) 8%, transparent);
  font-size: 11px;
  color: var(--ink-soft);
  max-width: 100%;
}
.att-thumb { width: 22px; height: 22px; object-fit: cover; border-radius: 6px; border: 1px solid var(--line); flex-shrink: 0; }
.att-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 180px; }
.att-size { font-family: var(--font-mono); font-size: 10px; color: var(--ink-muted); }
.att-x { border: none; background: none; color: var(--cinnabar); cursor: pointer; font-size: 13px; padding: 0 2px; line-height: 1; }

/* ── 输入区 ── */
.composer {
  border-top: 1px solid var(--line-soft);
  padding: 12px 18px 14px;
  display: grid;
  gap: 10px;
  background: color-mix(in srgb, var(--bg-soft) 55%, transparent);
}
.composer-atts { display: flex; flex-wrap: wrap; gap: 6px; }
.composer-input {
  display: block;
  width: 100%;
  resize: vertical;
  min-height: 72px;
  max-height: 220px;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  background: var(--card);
  color: var(--ink);
  padding: 10px 12px;
  font: inherit;
  font-size: 13px;
  line-height: 1.7;
  transition: border-color .2s ease, box-shadow .2s ease;
}
.composer-input:focus {
  outline: none;
  border-color: var(--cinnabar);
  box-shadow: 0 0 0 3px var(--rouge-glow);
}
.composer-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.composer-spacer { flex: 1; }
.mic-icon { flex-shrink: 0; }
.voice-hint { font-size: 11px; color: var(--ink-muted); letter-spacing: 1px; }
.rec-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--cinnabar); animation: recPulse 1s ease-in-out infinite; }
@keyframes recPulse {
  0%, 100% { opacity: .35; }
  50% { opacity: 1; }
}

/* ── 右侧面板 ── */
.offline-line { font-size: 11px; color: var(--gold); letter-spacing: 1px; margin-bottom: 10px; }
.side-load { color: var(--ink-soft); font-size: 13px; padding: 14px 0; font-family: var(--font-kai); letter-spacing: 2px; }
.sub-list, .run-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; }
.sub-item, .run-item {
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-small);
  padding: 10px 12px;
  background: var(--card-solid);
  transition: border-color .18s ease, box-shadow .18s ease;
}
.sub-item:hover, .run-item:hover { border-color: var(--gold-line); }
.run-item.run-review {
  border-color: var(--gold-line);
  background: color-mix(in srgb, var(--gold) 7%, var(--card-solid));
  box-shadow: 0 0 14px color-mix(in srgb, var(--gold) 20%, transparent);
}
.sub-head, .run-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.sub-name, .run-title { font-family: var(--font-kai); font-size: 13px; font-weight: 700; letter-spacing: 1px; color: var(--ink); overflow-wrap: anywhere; }
.sub-task, .run-summary { margin-top: 6px; font-size: 12px; color: var(--ink-soft); line-height: 1.7; overflow-wrap: anywhere; }
.sub-item .gf-tag, .run-meta .gf-tag { margin-top: 6px; }
.sub-spawn { display: flex; gap: 8px; margin-top: 12px; }
.sub-input {
  flex: 1;
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
.sub-input:focus {
  outline: none;
  border-color: var(--cinnabar);
  box-shadow: 0 0 0 3px var(--rouge-glow);
}
.runs-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 10px; }
.runs-head .offline-line { margin-bottom: 0; }
.run-foot { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
.run-meta { font-family: var(--font-mono); font-size: 10px; color: var(--ink-muted); display: inline-flex; align-items: center; gap: 6px; flex-wrap: wrap; }

/* ── 响应式 ── */
@media (max-width: 1100px) {
  .wb-layout { grid-template-columns: minmax(0, 1fr); }
  .wb-side { position: static; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }
}
@media (max-width: 640px) {
  .msg { max-width: 94%; }
  .goal-row { flex-direction: column; align-items: stretch; }
  .goal-row :deep(.gf-btn) { align-self: flex-end; }
  .sub-spawn { flex-direction: column; }
  .sub-spawn :deep(.gf-btn) { align-self: flex-end; }
}
</style>
