<script setup lang="ts">
/**
 * 手机伴侣 — 局域网手机控制页（路由 /mobile）。
 * 窄屏优先：max-width 560px 居中、大圆角卡片、底部固定对话操作栏。
 * 契约（与后端 platform_api 子模块钉死）：
 *   POST /system/lan/verify        { token }            配对校验
 *   GET  /agents/runs              运行列表（5s 轮询）
 *   POST /agents/runs/{id}/approve { approved:boolean } 批准/拒绝
 *   POST /agents/chat              { message }          快捷对话
 *   POST /memory/dreams/archive-now                     整理梦境
 *   GET/PUT /system/power          { prevent_sleep }    防睡眠开关
 *   GET  /agents/context-size                           上下文体量（弹层）
 * 所有响应均做可选链容错；接口不可达时运行列表回退为「离线示例数据」。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiGet, apiPost, apiPut, isAuthError, isNetworkError } from '@/api/platform'
import { runStatusGroup, runStatusLabel } from '@/utils/platformEnums'
import GfCard from '@/components/gf/GfCard.vue'
import GfTag from '@/components/gf/GfTag.vue'
import GfButton from '@/components/gf/GfButton.vue'
import GfEmpty from '@/components/gf/GfEmpty.vue'

function platformErrText(e: unknown): string {
  if (isAuthError(e)) return `鉴权失败：${e.message}（请检查左侧 API 密钥）`
  if (isNetworkError(e)) return '网络异常，后端未连通'
  return e instanceof Error ? e.message : String(e)
}

/* ── 类型 ── */
type Phase = 'verifying' | 'paired' | 'failed'

interface RunItem {
  id: string
  title: string
  agent: string
  status: string
  updatedAt: string
  summary: string
  sample?: boolean
}

interface ChatMsg {
  id: number
  role: 'me' | 'agent' | 'sys'
  text: string
  time: string
}

interface CtxInfo {
  used: number
  max: number
  percent: number
  model: string
  note: string
}

/* ── 配对态 ── */
const TOKEN_KEY = 'wanwei-mobile-token'
const PAIRED_KEY = 'wanwei-mobile-paired'
const route = useRoute()
const router = useRouter()
const phase = ref<Phase>('verifying')
const failReason = ref('')
const deviceName = ref('')
const verifying = ref(false)
const manualToken = ref('')

/** 浮动小窗模式：桌面端浮动工作区以 /console/#/mobile?floating=1 加载（08-#37）。
 *  现状：桌面 main.js 加载该 URL 时未附带 token，小窗首启必落在配对门禁；
 *  前端侧不改后端 URL 契约，提供手动粘贴令牌入口作为诚实补救。 */
const isFloating = computed(() => {
  const f = route.query.floating
  const v = Array.isArray(f) ? f[0] : f
  return v === '1' || v === 'true'
})

/* ── 任务监视 ── */
const runs = ref<RunItem[]>([])
const runsOffline = ref(false)
const runsLoading = ref(true)
const deciding = ref('')

/* ── 快捷对话 ── */
const messages = ref<ChatMsg[]>([])
const draft = ref('')
const sending = ref(false)
const chatEnd = ref<HTMLElement | null>(null)
let msgSeq = 0

/* ── 快捷操作 ── */
const archiving = ref(false)
const powerKnown = ref(false)
const preventSleep = ref(false)
const powerBusy = ref(false)
const ctxOpen = ref(false)
const ctxLoading = ref(false)
const ctxInfo = ref<CtxInfo | null>(null)
const ctxError = ref('')

/* ── 轻提示 ── */
const toast = ref('')
let toastTimer: ReturnType<typeof setTimeout> | undefined
function showToast(text: string) {
  toast.value = text
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = '' }, 3200)
}

/* ── 容错解析工具 ── */
function asRecord(v: unknown): Record<string, unknown> | null {
  return v !== null && typeof v === 'object' ? (v as Record<string, unknown>) : null
}
function pickStr(obj: Record<string, unknown>, keys: string[]): string {
  for (const k of keys) {
    const v = obj[k]
    if (typeof v === 'string' && v.trim()) return v
    if (typeof v === 'number' && Number.isFinite(v)) return String(v)
  }
  return ''
}
function pickNum(obj: Record<string, unknown>, keys: string[]): number {
  for (const k of keys) {
    const v = obj[k]
    if (typeof v === 'number' && Number.isFinite(v)) return v
  }
  return NaN
}

/* ── 配对 ── */
/** 令牌脱敏：任何进入页面可见区域的文本都不得携带原始 token（08-#37） */
function maskToken(text: string, token: string): string {
  return token && text.includes(token) ? text.split(token).join('····') : text
}

/** 配对成功后抹掉地址栏 hash 中的 token，避免滞留可见 URL 与浏览历史 */
function stripTokenFromUrl(): void {
  if (route.query.token === undefined) return
  const rest = { ...route.query }
  delete rest.token
  void router.replace({ query: rest })
}

async function verify(candidate: string, fromCache: boolean) {
  if (verifying.value || phase.value === 'paired') return
  verifying.value = true
  phase.value = 'verifying'
  failReason.value = ''
  try {
    const res = await apiPost<unknown>('/system/lan/verify', { token: candidate })
    const r = asRecord(res)
    const rejected = r !== null && (r.ok === false || r.paired === false || r.verified === false || r.success === false)
    if (rejected) throw new Error(pickStr(r, ['message', 'detail', 'error']) || '令牌未通过校验')
    deviceName.value = r ? pickStr(r, ['device_name', 'device', 'name']) : ''
    localStorage.setItem(TOKEN_KEY, candidate)
    localStorage.setItem(PAIRED_KEY, '1')
    phase.value = 'paired'
    if (!fromCache) stripTokenFromUrl()
    startMain()
  } catch (e) {
    if (fromCache) localStorage.removeItem(TOKEN_KEY)
    phase.value = 'failed'
    failReason.value = maskToken(platformErrText(e), candidate)
  } finally {
    verifying.value = false
  }
}

function submitManualToken() {
  const candidate = manualToken.value.trim()
  if (!candidate || verifying.value) return
  manualToken.value = ''
  void verify(candidate, false)
}

function retryPair() {
  const raw = route.query.token
  const fromQuery = Array.isArray(raw) ? raw[0] : raw
  const queryToken = typeof fromQuery === 'string' ? fromQuery.trim() : ''
  const cached = localStorage.getItem(TOKEN_KEY) ?? ''
  const candidate = queryToken || cached
  if (!candidate) {
    failReason.value = '链接中未携带配对令牌（token），请从桌面端重新获取配对链接或二维码。'
    return
  }
  void verify(candidate, !queryToken)
}

function unpair() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(PAIRED_KEY)
  stopPolling()
  phase.value = 'failed'
  failReason.value = '已解除本机配对。请从桌面端重新获取配对链接。'
}

/* ── 任务监视 ── */
/* 状态标签/分组统一取自共享枚举模块 @/utils/platformEnums（09-#11/#12），
   本地不再维护私有映射，避免跨视图漂移。 */
function fmtTime(s: string): string {
  if (!s) return ''
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return s
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return `${hh}:${mm}`
}

const SAMPLE_RUNS: RunItem[] = [
  { id: 'sample-1', title: '整理今日会议纪要', agent: '书僮', status: 'running', updatedAt: '', summary: '正在归纳第 3 节要点', sample: true },
  { id: 'sample-2', title: '部署脚本变更', agent: '账房', status: 'awaiting_review', updatedAt: '', summary: '等待人工审查后放行', sample: true },
  { id: 'sample-3', title: '夜间梦境归档', agent: '梦吏', status: 'completed', updatedAt: '', summary: '已归档 12 段梦境', sample: true },
]

function normalizeRuns(payload: unknown): RunItem[] {
  const root = asRecord(payload)
  const list: unknown = Array.isArray(payload) ? payload : (root?.items ?? root?.runs ?? root?.list ?? [])
  if (!Array.isArray(list)) return []
  return list.map((entry, i): RunItem => {
    const r = asRecord(entry) ?? {}
    return {
      id: pickStr(r, ['id', 'run_id', 'runId', 'uid']) || `run-${i}`,
      title: pickStr(r, ['title', 'name', 'task', 'goal']) || '未命名任务',
      agent: pickStr(r, ['agent', 'agent_name', 'agentName', 'owner']),
      status: pickStr(r, ['status', 'state']).toLowerCase() || 'unknown',
      updatedAt: pickStr(r, ['updated_at', 'updatedAt', 'created_at', 'createdAt', 'time']),
      summary: pickStr(r, ['summary', 'last_message', 'message', 'note', 'description']),
    }
  })
}

async function loadRuns() {
  try {
    const res = await apiGet<unknown>('/agents/runs')
    runs.value = normalizeRuns(res)
    runsOffline.value = false
  } catch (e) {
    const network = isNetworkError(e)
    runs.value = network ? SAMPLE_RUNS : []
    runsOffline.value = network
  } finally {
    runsLoading.value = false
  }
}

async function decide(run: RunItem, approved: boolean) {
  if (deciding.value) return
  if (run.sample) {
    showToast('示例数据不可操作，待后端接入后再试。')
    return
  }
  deciding.value = run.id
  try {
    const result = await apiPost<{ status?: string }>(`/agents/runs/${run.id}/approve`, { approved })
    const actual = result.status
    if (actual === 'rejected') {
      showToast(`已拒绝「${run.title}」`)
    } else if (actual === 'cancelled') {
      showToast(`已取消「${run.title}」`)
    } else {
      showToast(approved ? `已批准「${run.title}」` : `已拒绝「${run.title}」`)
    }
    await loadRuns()
  } catch (e) {
    showToast(`操作失败：${platformErrText(e)}`)
  } finally {
    deciding.value = ''
  }
}

/* ── 快捷对话 ── */
function nowTime(): string {
  const d = new Date()
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
function pushMsg(role: ChatMsg['role'], text: string) {
  messages.value.push({ id: ++msgSeq, role, text, time: nowTime() })
  if (messages.value.length > 60) messages.value.splice(0, messages.value.length - 60)
  void nextTick(() => chatEnd.value?.scrollIntoView({ block: 'end', behavior: 'smooth' }))
}
function extractReply(payload: unknown): string {
  const r = asRecord(payload)
  if (!r) return ''
  const direct = pickStr(r, ['reply', 'message', 'content', 'text', 'answer'])
  if (direct) return direct
  const data = asRecord(r.data)
  if (data) {
    const nested = pickStr(data, ['reply', 'message', 'content', 'text'])
    if (nested) return nested
  }
  return ''
}
async function sendChat() {
  const text = draft.value.trim()
  if (!text || sending.value) return
  sending.value = true
  draft.value = ''
  pushMsg('me', text)
  try {
    const res = await apiPost<unknown>('/agents/chat', { message: text })
    const reply = extractReply(res)
    pushMsg('agent', reply || '口信已送达，智能体思索中，进展见上方任务列表。')
  } catch (e) {
    pushMsg('sys', `发送失败：${platformErrText(e)}`)
  } finally {
    sending.value = false
  }
}

/* ── 快捷操作 ── */
async function archiveDreams() {
  if (archiving.value) return
  archiving.value = true
  try {
    const res = await apiPost<unknown>('/memory/dreams/archive-now')
    const r = asRecord(res)
    const n = r ? pickNum(r, ['archived', 'archived_count', 'count', 'total']) : NaN
    const simulated = r !== null && (r.simulated === true || r.stub === true)
    const base = Number.isFinite(n) ? `已归档 ${n} 段梦境` : '梦境整理请求已送达'
    showToast(simulated ? `${base}（模拟）` : base)
  } catch (e) {
    showToast(`整理失败：${platformErrText(e)}`)
  } finally {
    archiving.value = false
  }
}

function normalizePower(payload: unknown): boolean | null {
  const r = asRecord(payload)
  if (!r) return null
  for (const k of ['prevent_sleep', 'preventSleep', 'keep_awake', 'keepAwake', 'enabled', 'on']) {
    const v = r[k]
    if (typeof v === 'boolean') return v
  }
  return null
}
async function loadPower() {
  try {
    const res = await apiGet<unknown>('/system/power')
    const v = normalizePower(res)
    if (v === null) {
      powerKnown.value = false
    } else {
      preventSleep.value = v
      powerKnown.value = true
    }
  } catch {
    powerKnown.value = false
  }
}
async function togglePower() {
  if (powerBusy.value) return
  powerBusy.value = true
  const next = powerKnown.value ? !preventSleep.value : true
  try {
    const res = await apiPut<unknown>('/system/power', { prevent_sleep: next })
    const v = normalizePower(res)
    preventSleep.value = v ?? next
    powerKnown.value = true
    showToast(preventSleep.value ? '防睡眠已开启，设备将保持清醒' : '防睡眠已关闭')
  } catch (e) {
    showToast(`切换失败：${platformErrText(e)}`)
    await loadPower()
  } finally {
    powerBusy.value = false
  }
}

function normalizeCtx(payload: unknown): CtxInfo | null {
  const r = asRecord(payload)
  if (!r) return null
  const used = pickNum(r, ['tokens', 'used_tokens', 'used', 'context_tokens', 'current_tokens'])
  const max = pickNum(r, ['max_tokens', 'limit', 'max', 'capacity', 'context_window'])
  let percent = pickNum(r, ['percent', 'percentage', 'usage'])
  const ratio = pickNum(r, ['ratio'])
  if (!Number.isFinite(percent) && Number.isFinite(ratio)) percent = ratio <= 1 ? ratio * 100 : ratio
  if (!Number.isFinite(percent) && Number.isFinite(used) && Number.isFinite(max) && max > 0) percent = (used / max) * 100
  const model = pickStr(r, ['model', 'agent', 'name'])
  const note = pickStr(r, ['note', 'message', 'detail'])
  if (!Number.isFinite(used) && !Number.isFinite(percent) && !note) return null
  return {
    used: Number.isFinite(used) ? used : -1,
    max: Number.isFinite(max) ? max : -1,
    percent: Number.isFinite(percent) ? Math.min(100, Math.max(0, percent)) : -1,
    model,
    note,
  }
}
async function openContext() {
  ctxOpen.value = true
  ctxLoading.value = true
  ctxInfo.value = null
  ctxError.value = ''
  try {
    const res = await apiGet<unknown>('/agents/context-size')
    ctxInfo.value = normalizeCtx(res)
    if (!ctxInfo.value) ctxError.value = '后端已响应，但未返回可识别的上下文体量字段。'
  } catch (e) {
    ctxError.value = platformErrText(e)
  } finally {
    ctxLoading.value = false
  }
}
function fmtNum(n: number): string {
  return n >= 0 ? n.toLocaleString('zh-CN') : '—'
}

/* ── 轮询生命周期 ── */
let pollTimer: ReturnType<typeof setInterval> | undefined
function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = undefined
  }
}
function startMain() {
  stopPolling()
  void loadRuns()
  void loadPower()
  pollTimer = setInterval(() => { void loadRuns() }, 5000)
  if (!messages.value.length) {
    pushMsg('agent', '配对成功。我在这儿守着，有要审查的任务会立刻提醒你。')
  }
}

onMounted(() => {
  // 已配对状态作为终态：避免一次性 token 被重复 verify 触发「已使用」
  if (localStorage.getItem(PAIRED_KEY) === '1') {
    phase.value = 'paired'
    startMain()
    return
  }
  const raw = route.query.token
  const fromQuery = Array.isArray(raw) ? raw[0] : raw
  const queryToken = typeof fromQuery === 'string' ? fromQuery.trim() : ''
  const cached = (localStorage.getItem(TOKEN_KEY) ?? '').trim()
  const candidate = queryToken || cached
  if (!candidate) {
    phase.value = 'failed'
    failReason.value = '链接中未携带配对令牌（token），请从桌面端重新获取配对链接或二维码。'
    return
  }
  void verify(candidate, !queryToken)
})

onBeforeUnmount(() => {
  stopPolling()
  if (toastTimer) clearTimeout(toastTimer)
})
</script>

<template>
  <div class="mobile-view">
    <!-- ══ 配对门禁：校验中 / 失败整页 ══ -->
    <div v-if="phase !== 'paired'" class="gate">
      <div class="gate-card">
        <span class="gate-seal">伴</span>
        <template v-if="phase === 'verifying'">
          <h1 class="gate-title">验印中…</h1>
          <p class="gate-sub">正在与桌面端核对配对令牌，请稍候。</p>
        </template>
        <template v-else>
          <h1 class="gate-title">配对失败</h1>
          <p class="gate-sub">{{ failReason || '令牌校验未通过。' }}</p>
          <div class="gate-actions">
            <GfButton :disabled="verifying" @click="retryPair">{{ verifying ? '验印中…' : '重新验印' }}</GfButton>
          </div>
          <form class="gate-manual" @submit.prevent="submitManualToken">
            <input
              v-model="manualToken"
              class="gate-manual-input"
              type="password"
              autocomplete="off"
              placeholder="或手动粘贴配对令牌…"
              :disabled="verifying"
            />
            <GfButton small :disabled="verifying || !manualToken.trim()" @click="submitManualToken">验印</GfButton>
          </form>
          <p v-if="isFloating" class="gate-hint">
            浮动小窗当前不自动携带配对令牌（桌面端注入尚未接入）：请从桌面端「手机伴侣」面板复制令牌后在此粘贴，配对成功后小窗即可使用。
          </p>
          <p class="gate-hint">配对链接形如 <code>/console/#/mobile?token=····</code>，由桌面端「手机伴侣」面板生成。</p>
        </template>
      </div>
    </div>

    <!-- ══ 主界面 ══ -->
    <template v-else>
      <!-- 顶部小页眉 -->
      <header class="m-hero">
        <span class="m-seal">伴</span>
        <div class="m-hero-main">
          <h1 class="m-title">手机伴侣</h1>
          <div class="m-en">MOBILE COMPANION</div>
        </div>
        <div class="m-hero-side">
          <GfTag tone="bamboo">已配对</GfTag>
          <GfTag v-if="deviceName" tone="dai">{{ deviceName }}</GfTag>
          <button class="m-unpair" type="button" @click="unpair">解除</button>
        </div>
      </header>

      <!-- 任务监视 -->
      <GfCard title="任务监视" seal="视" class="m-section">
        <div v-if="runsOffline" class="m-notice">离线示例数据 · 后端未接入，每 5 秒重试</div>
        <div v-if="runsLoading" class="m-muted">研墨中…</div>
        <GfEmpty v-else-if="!runs.length" text="暂无运行中的任务" />
        <ul v-else class="run-list">
          <li v-for="run in runs" :key="run.id" class="run-card" :class="{ 'run-card--review': run.status === 'awaiting_review' || run.status === 'review' }">
            <div class="run-row">
              <span class="run-status" :data-st="runStatusGroup(run.status)">{{ runStatusLabel(run.status) }}</span>
              <div class="run-main">
                <div class="run-title">{{ run.title }}</div>
                <div class="run-meta">
                  <GfTag v-if="run.agent" tone="dai">{{ run.agent }}</GfTag>
                  <span v-if="run.updatedAt" class="run-time">{{ fmtTime(run.updatedAt) }}</span>
                  <GfTag v-if="run.sample" tone="ink">示例</GfTag>
                </div>
                <p v-if="run.summary" class="run-summary">{{ run.summary }}</p>
              </div>
            </div>
            <div v-if="run.status === 'awaiting_review' || run.status === 'review'" class="run-decide">
              <button class="big-btn big-btn--approve" type="button" :disabled="deciding === run.id" @click="decide(run, true)">
                {{ deciding === run.id ? '落印中…' : '批准' }}
              </button>
              <button class="big-btn big-btn--reject" type="button" :disabled="deciding === run.id" @click="decide(run, false)">拒绝</button>
            </div>
          </li>
        </ul>
      </GfCard>

      <!-- 快捷操作 -->
      <GfCard title="快捷操作" seal="捷" class="m-section">
        <div class="action-grid">
          <button class="big-btn big-btn--ghost" type="button" :disabled="archiving" @click="archiveDreams">
            <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M17.5 4.5A8.5 8.5 0 1 0 17.5 19.5 7 7 0 1 1 17.5 4.5Z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>
            <span>{{ archiving ? '整理中…' : '整理梦境' }}</span>
          </button>
          <button class="big-btn big-btn--ghost" :class="{ 'big-btn--on': powerKnown && preventSleep }" type="button" :disabled="powerBusy" @click="togglePower">
            <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M12 3v8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><path d="M6.3 6.5a8 8 0 1 0 11.4 0" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
            <span>{{ powerBusy ? '切换中…' : powerKnown ? (preventSleep ? '防睡眠 · 开' : '防睡眠 · 关') : '防睡眠' }}</span>
          </button>
          <button class="big-btn big-btn--ghost" type="button" @click="openContext">
            <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="3" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M8 9.5h8M8 13h8M8 16.5h5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>
            <span>查看上下文</span>
          </button>
        </div>
      </GfCard>

      <!-- 快捷对话 -->
      <GfCard title="快捷对话" seal="话" class="m-section m-chat">
        <div class="msg-flow">
          <div v-for="m in messages" :key="m.id" class="msg" :data-role="m.role">
            <div class="msg-bubble">{{ m.text }}</div>
            <div class="msg-time">{{ m.time }}</div>
          </div>
          <div ref="chatEnd" class="msg-end" aria-hidden="true"></div>
        </div>
      </GfCard>

      <!-- 上下文弹层 -->
      <Teleport to="body">
        <div v-if="ctxOpen" class="ctx-mask" @click.self="ctxOpen = false">
          <div class="ctx-panel" role="dialog" aria-modal="true" aria-label="上下文体量">
            <div class="ctx-head">
              <span class="ctx-seal">境</span>
              <h2 class="ctx-title">上下文体量</h2>
            </div>
            <div v-if="ctxLoading" class="m-muted">研墨中…</div>
            <div v-else-if="ctxError" class="ctx-error">{{ ctxError }}</div>
            <template v-else-if="ctxInfo">
              <div v-if="ctxInfo.percent >= 0" class="ctx-bar">
                <div class="ctx-bar-fill" :style="{ width: ctxInfo.percent + '%' }"></div>
              </div>
              <div class="ctx-nums">
                <div class="ctx-num"><span class="ctx-num-v">{{ ctxInfo.percent >= 0 ? ctxInfo.percent.toFixed(1) + '%' : '—' }}</span><span class="ctx-num-l">占用</span></div>
                <div class="ctx-num"><span class="ctx-num-v">{{ fmtNum(ctxInfo.used) }}</span><span class="ctx-num-l">已用 tokens</span></div>
                <div class="ctx-num"><span class="ctx-num-v">{{ fmtNum(ctxInfo.max) }}</span><span class="ctx-num-l">上限</span></div>
              </div>
              <p v-if="ctxInfo.model" class="ctx-note">模型：{{ ctxInfo.model }}</p>
              <p v-if="ctxInfo.note" class="ctx-note">{{ ctxInfo.note }}</p>
            </template>
            <div class="ctx-actions">
              <GfButton variant="ghost" small @click="openContext">刷新</GfButton>
              <GfButton variant="ghost" small @click="ctxOpen = false">合上</GfButton>
            </div>
          </div>
        </div>
      </Teleport>

      <!-- 轻提示 -->
      <Transition name="toast">
        <div v-if="toast" class="m-toast" role="status">{{ toast }}</div>
      </Transition>

      <!-- 底部固定操作栏：快捷对话输入 -->
      <form class="composer" @submit.prevent="sendChat">
        <input
          v-model="draft"
          class="composer-input"
          type="text"
          placeholder="捎句话给智能体…"
          :disabled="sending"
          autocomplete="off"
          enterkeyhint="send"
          @keyup.enter.prevent="sendChat"
        />
        <button class="composer-send" type="submit" :disabled="sending || !draft.trim()">
          {{ sending ? '寄出中…' : '发送' }}
        </button>
      </form>
    </template>
  </div>
</template>

<style scoped>
/* ── 窄屏优先布局 ── */
.mobile-view {
  max-width: 560px;
  margin: 0 auto;
  padding: 4px 10px 108px; /* 底部留白给固定操作栏 */
}

/* ── 配对门禁（整页） ── */
.gate {
  min-height: 72vh;
  display: grid;
  place-items: center;
}
.gate-card {
  width: 100%;
  max-width: 420px;
  display: grid;
  justify-items: center;
  gap: 14px;
  padding: 40px 28px;
  background: var(--card);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1px solid var(--line);
  border-radius: 24px;
  box-shadow: var(--shadow-card);
  text-align: center;
}
.gate-seal {
  font-family: var(--font-kai);
  font-size: 26px;
  font-weight: 700;
  width: 64px;
  height: 64px;
  display: grid;
  place-items: center;
  color: #FDF6E9;
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  border-radius: var(--radius-seal);
  box-shadow: var(--shadow-seal);
}
.gate-title {
  font-family: var(--font-kai);
  font-size: 28px;
  letter-spacing: 6px;
  color: var(--ink);
}
.gate-sub {
  font-size: 13px;
  line-height: 1.8;
  color: var(--ink-soft);
  overflow-wrap: anywhere;
}
.gate-actions { margin-top: 4px; }
.gate-manual {
  display: flex;
  gap: 8px;
  align-items: center;
  width: 100%;
  max-width: 320px;
}
.gate-manual-input {
  flex: 1;
  min-width: 0;
  height: 36px;
  padding: 0 14px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--card-solid);
  color: var(--ink);
  font-size: 12px;
  font-family: var(--font-mono);
  transition: border-color .2s ease, box-shadow .2s ease;
}
.gate-manual-input:focus {
  outline: none;
  border-color: var(--cinnabar);
  box-shadow: 0 0 0 3px var(--rouge-glow);
}
.gate-manual-input:disabled { opacity: .55; }
.gate-hint {
  font-size: 11px;
  line-height: 1.8;
  color: var(--ink-muted);
}
.gate-hint code {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--dai);
}

/* ── 顶部小页眉 ── */
.m-hero {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 2px 16px;
}
.m-seal {
  font-family: var(--font-kai);
  font-size: 20px;
  font-weight: 700;
  width: 46px;
  height: 46px;
  display: grid;
  place-items: center;
  color: #FDF6E9;
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  border-radius: var(--radius-seal);
  box-shadow: var(--shadow-seal);
  flex-shrink: 0;
}
.m-hero-main { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.m-title {
  font-family: var(--font-kai);
  font-size: 26px;
  font-weight: 700;
  letter-spacing: 5px;
  color: var(--ink);
  line-height: 1.15;
}
.m-en {
  font-size: 10px;
  letter-spacing: 3px;
  color: var(--ink-muted);
  font-family: var(--font-mono);
}
.m-hero-side {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.m-unpair {
  border: 1px solid var(--gold-line);
  background: var(--card);
  color: var(--ink-muted);
  border-radius: 999px;
  padding: 3px 12px;
  font-size: 11px;
  letter-spacing: 1px;
  font-family: var(--font-kai);
  transition: color .18s ease, border-color .18s ease;
}
.m-unpair:hover { color: var(--cinnabar); border-color: var(--rouge); }

/* ── 区块 ── */
.m-section { margin-bottom: 16px; border-radius: 20px; }
.m-muted {
  color: var(--ink-soft);
  font-size: 13px;
  padding: 14px 0;
  font-family: var(--font-kai);
  letter-spacing: 2px;
}
.m-notice {
  margin-bottom: 12px;
  padding: 8px 12px;
  border: 1px solid var(--gold-line);
  border-radius: var(--radius-small);
  background: color-mix(in srgb, var(--gold) 8%, transparent);
  color: color-mix(in srgb, var(--gold) 70%, var(--ink));
  font-size: 11px;
  letter-spacing: 1px;
}

/* ── 任务卡片：大色块状态徽标 ── */
.run-list { list-style: none; display: grid; gap: 12px; }
.run-card {
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  background: var(--card);
  padding: 12px;
  transition: border-color .2s ease, box-shadow .2s ease;
}
.run-card--review {
  border-color: color-mix(in srgb, var(--gold) 55%, transparent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--gold) 12%, transparent);
}
.run-row { display: flex; gap: 12px; align-items: stretch; }
.run-status {
  flex-shrink: 0;
  width: 64px;
  min-height: 64px;
  display: grid;
  place-items: center;
  border-radius: 14px;
  font-family: var(--font-kai);
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 2px;
  writing-mode: vertical-lr;
  color: #FDF6E9;
  background: var(--ink-muted);
}
.run-status[data-st='run'] {
  background: linear-gradient(160deg, var(--dai), var(--dai-deep));
  animation: st-pulse 1.8s ease-in-out infinite;
}
.run-status[data-st='review'] { background: linear-gradient(160deg, var(--gold), color-mix(in srgb, var(--gold) 70%, var(--cinnabar-deep))); }
.run-status[data-st='ok'] { background: linear-gradient(160deg, var(--bamboo), color-mix(in srgb, var(--bamboo) 72%, var(--ink))); }
.run-status[data-st='bad'] { background: linear-gradient(160deg, var(--cinnabar), var(--cinnabar-deep)); }
.run-status[data-st='idle'] { background: var(--ink-muted); }
@keyframes st-pulse {
  0%, 100% { box-shadow: 0 0 0 0 var(--rouge-glow); }
  50% { box-shadow: 0 0 0 6px transparent; }
}
.run-main { min-width: 0; flex: 1; display: grid; gap: 5px; align-content: start; }
.run-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--ink);
  overflow-wrap: anywhere;
}
.run-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.run-time { font-family: var(--font-mono); font-size: 10px; color: var(--ink-muted); }
.run-summary {
  font-size: 12px;
  line-height: 1.7;
  color: var(--ink-soft);
  overflow-wrap: anywhere;
}
.run-decide {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-top: 12px;
}

/* ── 触屏大按钮 ── */
.big-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 56px;
  padding: 12px 16px;
  border-radius: 16px;
  border: 1px solid transparent;
  font-family: var(--font-kai);
  font-size: 16px;
  letter-spacing: 3px;
  transition: transform .18s ease, box-shadow .18s ease, background .18s ease, border-color .18s ease, color .18s ease;
}
.big-btn:active { transform: translateY(1px) scale(.98); }
.big-btn:disabled { opacity: .55; cursor: not-allowed; transform: none; box-shadow: none; }
.big-btn--approve {
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  color: #FDF6E9;
  box-shadow: 0 2px 12px var(--cinnabar-glow), var(--shadow-card);
}
.big-btn--approve:hover:not(:disabled) { transform: translateY(-2px); box-shadow: 0 4px 18px var(--cinnabar-glow), var(--shadow-glow-rouge); }
.big-btn--reject {
  background: var(--card);
  border-color: color-mix(in srgb, var(--cinnabar) 55%, transparent);
  color: var(--cinnabar);
}
.big-btn--reject:hover:not(:disabled) { transform: translateY(-2px); background: color-mix(in srgb, var(--cinnabar) 8%, transparent); }
.big-btn--ghost {
  flex-direction: column;
  gap: 6px;
  min-height: 88px;
  background: var(--card);
  border-color: var(--gold-line);
  color: var(--ink-soft);
  font-size: 14px;
  letter-spacing: 2px;
}
.big-btn--ghost:hover:not(:disabled) {
  transform: translateY(-2px);
  border-color: var(--rouge);
  color: var(--cinnabar);
  box-shadow: var(--shadow-glow-rouge);
}
.big-btn--on {
  border-color: color-mix(in srgb, var(--bamboo) 60%, transparent);
  background: color-mix(in srgb, var(--bamboo) 12%, transparent);
  color: color-mix(in srgb, var(--bamboo) 70%, var(--ink));
}
.action-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}
@media (max-width: 380px) {
  .action-grid { grid-template-columns: 1fr; }
}

/* ── 消息流气泡 ── */
.msg-flow { display: grid; gap: 10px; padding: 2px 0 4px; }
.msg { display: grid; gap: 3px; max-width: 86%; }
.msg[data-role='me'] { justify-self: end; justify-items: end; }
.msg[data-role='agent'] { justify-self: start; justify-items: start; }
.msg[data-role='sys'] { justify-self: center; max-width: 100%; }
.msg-bubble {
  padding: 10px 14px;
  border-radius: 16px;
  font-size: 13px;
  line-height: 1.75;
  overflow-wrap: anywhere;
  border: 1px solid transparent;
}
.msg[data-role='me'] .msg-bubble {
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  color: #FDF6E9;
  border-bottom-right-radius: 6px;
  box-shadow: 0 2px 10px var(--cinnabar-glow);
}
.msg[data-role='agent'] .msg-bubble {
  background: var(--card);
  border-color: var(--line);
  color: var(--ink);
  border-bottom-left-radius: 6px;
}
.msg[data-role='sys'] .msg-bubble {
  background: color-mix(in srgb, var(--gold) 8%, transparent);
  border-color: var(--gold-line);
  color: var(--ink-muted);
  font-size: 11px;
  padding: 6px 12px;
}
.msg-time { font-family: var(--font-mono); font-size: 9px; color: var(--ink-muted); padding: 0 6px; }
.msg[data-role='sys'] .msg-time { display: none; }
.msg-end { height: 1px; }

/* ── 上下文弹层 ── */
.ctx-mask {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: grid;
  place-items: center;
  padding: 20px;
  background: color-mix(in srgb, var(--ink) 38%, transparent);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
}
.ctx-panel {
  width: 100%;
  max-width: 440px;
  display: grid;
  gap: 14px;
  padding: 22px;
  background: var(--card-solid);
  border: 1px solid var(--gold-line);
  border-radius: 20px;
  box-shadow: var(--shadow-lift);
}
.ctx-head { display: flex; align-items: center; gap: 10px; }
.ctx-seal {
  font-family: var(--font-kai);
  font-size: 14px;
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
.ctx-title { font-family: var(--font-kai); font-size: 20px; letter-spacing: 4px; color: var(--ink); }
.ctx-error {
  font-size: 12px;
  line-height: 1.7;
  color: var(--cinnabar-deep);
  overflow-wrap: anywhere;
}
.ctx-bar {
  height: 12px;
  border-radius: 999px;
  background: var(--line-soft);
  border: 1px solid var(--line);
  overflow: hidden;
}
.ctx-bar-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--bamboo), var(--gold), var(--cinnabar));
  transition: width .4s ease;
}
.ctx-nums { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; text-align: center; }
.ctx-num { display: grid; gap: 4px; }
.ctx-num-v { font-family: var(--font-kai); font-size: 20px; font-weight: 700; color: var(--ink); }
.ctx-num-l { font-size: 10px; letter-spacing: 1px; color: var(--ink-muted); }
.ctx-note { font-size: 12px; line-height: 1.7; color: var(--ink-soft); overflow-wrap: anywhere; }
.ctx-actions { display: flex; justify-content: flex-end; gap: 8px; }

/* ── 轻提示 ── */
.m-toast {
  position: fixed;
  left: 50%;
  bottom: 92px;
  transform: translateX(-50%);
  z-index: 70;
  max-width: min(480px, calc(100vw - 40px));
  padding: 10px 18px;
  border-radius: 999px;
  background: var(--card-solid);
  border: 1px solid var(--gold-line);
  box-shadow: var(--shadow-lift);
  color: var(--ink);
  font-size: 12px;
  letter-spacing: 1px;
  text-align: center;
}
.toast-enter-active, .toast-leave-active { transition: opacity .25s ease, transform .25s ease; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateX(-50%) translateY(8px); }

/* ── 底部固定操作栏（对话输入） ── */
.composer {
  position: fixed;
  left: 50%;
  bottom: 0;
  transform: translateX(-50%);
  z-index: 50;
  width: min(560px, 100%);
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 12px 14px calc(12px + env(safe-area-inset-bottom, 0px));
  background: var(--card);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-top: 1px solid var(--gold-line);
  border-radius: 20px 20px 0 0;
  box-shadow: 0 -6px 24px rgba(51, 46, 42, .08);
}
.composer-input {
  flex: 1;
  min-width: 0;
  height: 48px;
  padding: 0 18px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--card-solid);
  color: var(--ink);
  font-size: 14px;
  transition: border-color .2s ease, box-shadow .2s ease;
}
.composer-input:focus {
  outline: none;
  border-color: var(--cinnabar);
  box-shadow: 0 0 0 3px var(--rouge-glow);
}
.composer-input:disabled { opacity: .6; }
.composer-send {
  flex-shrink: 0;
  height: 48px;
  min-width: 84px;
  padding: 0 20px;
  border: 1px solid transparent;
  border-radius: 999px;
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  color: #FDF6E9;
  font-family: var(--font-kai);
  font-size: 15px;
  letter-spacing: 3px;
  box-shadow: 0 2px 12px var(--cinnabar-glow);
  transition: transform .18s ease, box-shadow .18s ease;
}
.composer-send:hover:not(:disabled) { transform: translateY(-2px); box-shadow: 0 4px 18px var(--cinnabar-glow), var(--shadow-glow-rouge); }
.composer-send:active { transform: translateY(1px) scale(.98); }
.composer-send:disabled { opacity: .55; cursor: not-allowed; transform: none; box-shadow: none; }
</style>
