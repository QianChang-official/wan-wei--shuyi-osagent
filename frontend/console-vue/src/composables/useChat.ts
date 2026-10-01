// Copyright (c) 2026 QianChang-official
//
// 宛委·枢忆 is licensed under Mulan PSL v2.
// You can use this software according to the terms of the Mulan PSL v2.
// You may obtain a copy of Mulan PSL v2 at:
// http://license.coscl.org.cn/MulanPSL2
//
// THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
// EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
// MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
// See the Mulan PSL v2 for more details.

/** 身份/智能体隔离的内存会话。后端保存运行；续聊仅引用成功运行，不回传本地气泡。 */
import { onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { api, getCredentialRevision, isAuthError, isGatewayUnavailable, onApiKeyChange } from '@/api/client'
import type { Agent, ChatRequest, ChatResponse, ConfirmationResult, PendingConfirmation, ProcessStep, Run } from '@/api/types'

export interface ChatConfirmation extends PendingConfirmation {
  state: 'pending' | 'submitting' | 'approved' | 'denied' | 'error' | 'unknown' | 'cancelled' | 'expired'
  result?: ConfirmationResult
  error?: string
}
export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  time: string
  pending?: boolean
  failed?: boolean
  cancelled?: boolean
  gatewayDown?: boolean
  authError?: boolean
  syncError?: string
  confirmations?: ChatConfirmation[]
  meta?: Partial<ChatResponse> & { process_steps?: ProcessStep[] }
}

const transcripts = reactive<Record<string, ChatMessage[]>>({})
const sending = reactive<Record<string, boolean>>({})
const controllers = new Map<string, AbortController>()
const previousRuns = new Map<string, string>()
/** 运行/上下文面板据此刷新，包括失败、取消和每个确认结果。 */
const revision = ref(0)
const MAX_MESSAGES = 200
const MAX_STEPS = 200
const newId = () => `m_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
const now = () => new Date().toISOString()

function messagesOf(agentId: string): ChatMessage[] {
  transcripts[agentId] ??= []
  // 必须返回代理；后续 SSE 与 confirmation 修改才会驱动组件更新。
  return transcripts[agentId]
}
function addTicket(msg: ChatMessage, ticket: PendingConfirmation) {
  if (!ticket.confirm_token) return
  msg.confirmations ??= []
  const existing = msg.confirmations.find(c => c.confirm_token === ticket.confirm_token)
  if (existing) Object.assign(existing, ticket)
  else msg.confirmations.push({ ...ticket, state: 'pending' })
}
function stepTicket(step: ProcessStep): PendingConfirmation {
  return {
    ...(typeof step.result === 'object' ? step.result : { command: step.result }),
    confirm_token: step.confirm_token!, operation: step.tool, run_id: step.run_id,
  }
}
function addStep(msg: ChatMessage, step: ProcessStep) {
  msg.meta ??= { process_steps: [] }
  if (step.run_id) msg.meta.run_id = step.run_id
  if (step.capabilities) msg.meta.capabilities = step.capabilities
  if (step.kind !== 'run_started' && step.kind !== 'capability') {
    const steps = msg.meta.process_steps ??= []
    steps.push(step)
    if (steps.length > MAX_STEPS) steps.splice(0, steps.length - MAX_STEPS)
  }
  if (step.confirm_token) addTicket(msg, stepTicket(step))
}

async function send(agent: Agent, text: string, controls: Pick<ChatRequest, 'depth' | 'gear'> = {}): Promise<void> {
  const message = text.trim()
  if (!message || sending[agent.id] || messagesOf(agent.id).some(m => m.confirmations?.some(c => c.state === 'pending' || c.state === 'submitting'))) return
  const scope = getCredentialRevision()
  const controller = new AbortController()
  controllers.set(agent.id, controller)
  sending[agent.id] = true
  const list = messagesOf(agent.id)
  // Don't evict unresolved operations when retaining the bounded transcript.
  while (list.length > MAX_MESSAGES - 2) {
    const index = list.findIndex(m => !m.pending && !m.confirmations?.some(c => c.state === 'pending' || c.state === 'submitting'))
    if (index < 0) break
    list.splice(index, 1)
  }
  list.push({ id: newId(), role: 'user', text: message, time: now() })
  list.push({ id: newId(), role: 'assistant', text: '', time: now(), pending: true, meta: { process_steps: [] } })
  const placeholder = list[list.length - 1]
  try {
    await api.chatStream({
      message, agent_id: agent.id, depth: controls.depth || agent.depth, gear: controls.gear || agent.gear,
      previous_run_id: previousRuns.get(agent.id) ?? null,
    }, {
      onStep: (step) => {
        if (scope === getCredentialRevision() && !controller.signal.aborted) addStep(placeholder, step)
      },
      onFinal: (res) => {
        if (scope !== getCredentialRevision() || controller.signal.aborted) return
        const steps = res.process_steps?.length ? res.process_steps.slice(-MAX_STEPS) : placeholder.meta?.process_steps
        placeholder.text = res.reply
        placeholder.meta = { ...res, process_steps: steps }
        for (const step of steps ?? []) if (step.confirm_token) addTicket(placeholder, stepTicket(step))
        for (const ticket of res.pending_confirmations ?? []) addTicket(placeholder, ticket)
        placeholder.failed = ['failed', 'cancelled', 'rejected'].includes(res.status ?? '')
        if (res.run_id && !placeholder.failed && res.status !== 'awaiting_review' && !placeholder.confirmations?.some(c => c.state === 'pending')) previousRuns.set(agent.id, res.run_id)
      },
    }, { signal: controller.signal })
  } catch (err) {
    if (scope !== getCredentialRevision()) return
    placeholder.cancelled = controller.signal.aborted
    placeholder.failed = !placeholder.cancelled
    placeholder.gatewayDown = isGatewayUnavailable(err)
    placeholder.authError = isAuthError(err)
    placeholder.text = placeholder.cancelled ? '已停止接收；运行取消状态请以右侧运行记录为准。'
      : placeholder.gatewayDown ? '模型网关未就绪，请在设置中检查模型接入后重试。'
      : placeholder.authError ? '访问密钥无效或权限不足，请在设置中更新后重试。'
      : `发送失败：${err instanceof Error ? err.message : String(err)}`
    for (const ticket of placeholder.confirmations ?? []) if (ticket.state === 'pending') ticket.state = 'cancelled'
  } finally {
    placeholder.pending = false
    if (controllers.get(agent.id) === controller) {
      controllers.delete(agent.id)
      sending[agent.id] = false
    }
    if (scope === getCredentialRevision()) revision.value++
  }
}

async function cancel(agentId: string): Promise<void> {
  const msg = [...messagesOf(agentId)].reverse().find(m => m.pending)
  controllers.get(agentId)?.abort()
  if (msg?.meta?.run_id) {
    try { await api.cancelRun(msg.meta.run_id) }
    catch (err) { msg.text += ` 取消请求未确认：${err instanceof Error ? err.message : String(err)}` }
    finally { revision.value++ }
  }
}

/** 一张票据只提交一次。网络失败代表结果未知，不安全重放，必须查看后端运行留痕。 */
async function confirmCommand(agent: Agent, msg: ChatMessage, token: string, approved: boolean): Promise<void> {
  const ticket = msg.confirmations?.find(c => c.confirm_token === token)
  if (!ticket || ticket.state !== 'pending') return
  if (ticketExpired(ticket)) { ticket.state = 'expired'; return }
  const scope = getCredentialRevision()
  ticket.state = 'submitting'
  try {
    const result = await api.confirmCommand(token, approved)
    if (scope !== getCredentialRevision()) return
    ticket.result = result
    ticket.state = result.denied ? 'denied' : !result.ok || (result.exit_code != null && result.exit_code !== 0) ? 'error' : approved ? 'approved' : 'denied'
    for (const pending of result.pending_confirmations ?? []) addTicket(msg, pending)
    const live = result.pending_confirmations?.map(c => c.confirm_token)
    for (const other of msg.confirmations ?? []) {
      if (other.state === 'pending' && (['failed', 'cancelled', 'rejected'].includes(result.status ?? '') || (live && !live.includes(other.confirm_token)))) other.state = 'cancelled'
    }
    if (msg.meta && result.status) msg.meta.status = result.status
    if (result.status === 'done' && result.run_id && result.ok) previousRuns.set(agent.id, result.run_id)
  } catch (err) {
    if (scope !== getCredentialRevision()) return
    ticket.state = 'unknown'
    ticket.error = `结果未确认，请查看运行记录，勿重复执行：${err instanceof Error ? err.message : String(err)}`
  } finally {
    if (scope === getCredentialRevision()) revision.value++
  }
}

function ticketExpired(ticket: ChatConfirmation): boolean {
  return !!ticket.expires_at && Date.parse(ticket.expires_at) <= Date.now()
}
function syncRuns(runs: Run[]): void {
  const byId = new Map(runs.map(run => [run.id, run]))
  for (const messages of Object.values(transcripts)) for (const msg of messages) {
    const run = byId.get(msg.meta?.run_id ?? '')
    if (!run || msg.pending) continue
    if (msg.meta) msg.meta.status = run.status
    const live = run.pending_confirmations?.map(ticket => ticket.confirm_token)
    for (const ticket of msg.confirmations ?? []) {
      if (ticket.state !== 'pending') continue
      if (ticketExpired(ticket) || run.error === 'approval_expired') ticket.state = 'expired'
      else if (['cancelled', 'failed', 'rejected'].includes(run.status)) ticket.state = 'cancelled'
      else if (run.status === 'done' || (live && !live.includes(ticket.confirm_token))) {
        // A ticket handled on another client is not evidence that its operation succeeded.
        ticket.state = 'unknown'
        ticket.error = '后端不再等待此票据；这不代表操作成功，请查看运行记录。'
      }
    }
  }
}

/** App-owned approval reconciliation, independent of whether the details panel is mounted. */
export function useChatLifecycle(): void {
  let active = false
  let timer: ReturnType<typeof setTimeout> | undefined
  let request: AbortController | undefined
  let cursor = 0
  const pendingMessages = () => Object.values(transcripts).flat().filter(msg =>
    !msg.pending && msg.confirmations?.some(ticket => ticket.state === 'pending'),
  )
  function schedule() {
    if (timer !== undefined) clearTimeout(timer)
    timer = undefined
    const messages = pendingMessages()
    if (!active || !messages.length) return
    const expiries = messages.flatMap(msg => (msg.confirmations ?? [])
      .filter(ticket => ticket.state === 'pending')
      .map(ticket => Date.parse(ticket.expires_at ?? '')).filter(Number.isFinite))
    const delay = Math.max(0, Math.min(4000, ...expiries.map(expiry => expiry - Date.now())))
    timer = setTimeout(tick, delay)
  }
  function tick() {
    timer = undefined
    if (!active) return
    const messages = pendingMessages()
    const runIds = [...new Set(messages.map(msg => msg.meta?.run_id).filter((id): id is string => !!id))]
    // Expiry stays responsive even when a reconciliation request is stalled/offline.
    for (const msg of messages) for (const ticket of msg.confirmations ?? []) {
      if (ticket.state === 'pending' && ticketExpired(ticket)) ticket.state = 'expired'
    }
    if (!request && runIds.length) {
      const ids = [...runIds.slice(cursor), ...runIds.slice(0, cursor)].slice(0, 4)
      cursor = (cursor + ids.length) % runIds.length
      const controller = new AbortController()
      request = controller
      const scope = getCredentialRevision()
      const before = revision.value
      void Promise.all(ids.map(async id => {
        try {
          const run = await api.getRun(id, { signal: controller.signal, timeoutMs: 10_000 })
          if (!active || controller.signal.aborted || scope !== getCredentialRevision() || before !== revision.value) return
          syncRuns([run])
          for (const msg of messages) if (msg.meta?.run_id === id) msg.syncError = ''
        } catch (err) {
          if (!active || controller.signal.aborted || scope !== getCredentialRevision()) return
          for (const msg of messages) if (msg.meta?.run_id === id) {
            msg.syncError = `运行状态同步失败：${err instanceof Error ? err.message : String(err)}。到期后本页不再提交票据；请核对运行留痕。`
          }
        }
      })).finally(() => { if (request === controller) request = undefined })
    }
    schedule()
  }
  function stopWork() {
    if (timer !== undefined) clearTimeout(timer)
    timer = undefined
    request?.abort()
    request = undefined
  }
  const unsubscribe = onApiKeyChange(stopWork)
  watch(() => pendingMessages().map(msg => [msg.id, msg.meta?.run_id,
    msg.confirmations?.map(ticket => [ticket.state, ticket.expires_at])]), schedule, { deep: true })
  onMounted(() => { active = true; schedule() })
  onUnmounted(() => { active = false; stopWork(); unsubscribe() })
}
function clear(agentId: string): void {
  if (sending[agentId] || messagesOf(agentId).some(m => m.confirmations?.some(c => c.state === 'pending' || c.state === 'submitting'))) return
  transcripts[agentId] = []
  previousRuns.delete(agentId)
}
onApiKeyChange(() => {
  controllers.forEach(controller => controller.abort())
  controllers.clear()
  previousRuns.clear()
  for (const id of Object.keys(transcripts)) delete transcripts[id]
  for (const id of Object.keys(sending)) delete sending[id]
  // 不载入旧版未按访问身份隔离的记录或过期确认票据。
  try {
    for (const key of Object.keys(localStorage)) if (key.startsWith('ww-chat:')) localStorage.removeItem(key)
  } catch { /* storage is optional */ }
  revision.value++
})
export function useChat() {
  return { sending, revision, messagesOf, send, cancel, clear, confirmCommand, syncRuns }
}
