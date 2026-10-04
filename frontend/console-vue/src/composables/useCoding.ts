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

/**
 * 编程工作台状态中枢。
 *
 * 统一持有：框架元信息（能力/工具/策略/角色）、会话列表与详情、
 * 事件流（SSE 增量 + 轮询兜底）、文件树、可审计记忆。
 *
 * 事件流设计：优先用 fetch 流式读取 SSE（带 ``X-API-Key`` 头，
 * ``EventSource`` 无法带自定义头故不采用）；流不可用时自动降级为
 * 增量轮询，二者产出同构事件，前端渲染逻辑无需分支。
 */

import { computed, reactive, ref } from 'vue'
import { codingApi } from '@/api/coding'
import { getApiKey } from '@/api/client'
import type {
  CodingEvent,
  CodingOverview,
  FileNode,
  MemoryItem,
  PolicyMatrix,
  SessionBrief,
  SessionDetail,
  SkillSpec,
  SubagentRole,
  ToolSpec,
} from '@/api/coding'

const overview = ref<CodingOverview | null>(null)
const tools = ref<ToolSpec[]>([])
const skills = ref<SkillSpec[]>([])
const roles = ref<SubagentRole[]>([])
const policy = ref<PolicyMatrix | null>(null)

const sessions = ref<SessionBrief[]>([])
const activeId = ref<string>('')
const detail = ref<SessionDetail | null>(null)
const events = ref<CodingEvent[]>([])
const tree = ref<FileNode[]>([])
const memory = reactive<{ items: MemoryItem[]; summary: Record<string, number>; available: boolean }>({
  items: [], summary: {}, available: true,
})

const booted = ref(false)
const busy = reactive<Record<string, boolean>>({})
const error = ref('')
/** 最近一次工具调用的结果（工具台展示用） */
const toolResult = ref<{ status: string; summary: string; output: unknown } | null>(null)

let streamAbort: AbortController | null = null
let pollTimer: ReturnType<typeof setInterval> | null = null

const activeBrief = computed(() => sessions.value.find((s) => s.id === activeId.value) || null)
const isRunning = computed(() => Boolean(detail.value?.running))
const pendingApprovals = computed(() => (detail.value?.approvals || []).filter((a) => a.status === 'pending'))

function setBusy(key: string, value: boolean) {
  busy[key] = value
}

function fail(err: unknown) {
  error.value = err instanceof Error ? err.message : String(err)
}

function clearError() {
  error.value = ''
}

/* ── 事件合并（按 seq 去重、升序） ── */
function mergeEvents(incoming: CodingEvent[]) {
  if (!incoming.length) return
  const map = new Map<number, CodingEvent>()
  for (const e of events.value) map.set(e.seq, e)
  for (const e of incoming) map.set(e.seq, e)
  events.value = [...map.values()].sort((a, b) => a.seq - b.seq).slice(-400)
}

function lastSeq(): number {
  return events.value.length ? events.value[events.value.length - 1].seq : 0
}

/* ── 元信息 ── */
async function bootstrap() {
  if (booted.value) return
  try {
    const [ov, tl, sk, rl, pl] = await Promise.all([
      codingApi.overview(), codingApi.tools(), codingApi.skills(),
      codingApi.subagentRoles(), codingApi.policy(),
    ])
    overview.value = ov
    tools.value = tl.items
    skills.value = sk.items
    roles.value = rl.items
    policy.value = pl
    booted.value = true
  } catch (err) { fail(err) }
  await refreshSessions()
}

async function refreshSessions() {
  try {
    const res = await codingApi.listSessions()
    sessions.value = res.items
  } catch (err) { fail(err) }
}

/* ── 会话 ── */
async function refreshDetail(id = activeId.value) {
  if (!id) return
  try {
    const res = await codingApi.getSession(id)
    detail.value = res
    mergeEvents(res.events)
    // 状态可能已变化，同步列表项
    const idx = sessions.value.findIndex((s) => s.id === id)
    if (idx >= 0) sessions.value[idx] = { ...sessions.value[idx], ...res }
  } catch (err) { fail(err) }
}

async function selectSession(id: string) {
  if (id === activeId.value && detail.value) return
  stopStream()
  activeId.value = id
  events.value = []
  detail.value = null
  memory.items = []
  await refreshDetail(id)
  await Promise.all([loadTree(), loadMemory()])
  startStream()
}

async function createSession(input: { task: string; workspace: string; policy_mode: string; title?: string }) {
  setBusy('create', true)
  clearError()
  try {
    const created = await codingApi.createSession(input)
    await refreshSessions()
    await selectSession(created.id)
    return created
  } catch (err) { fail(err); return null } finally { setBusy('create', false) }
}

async function deleteSession(id: string) {
  setBusy('delete', true)
  try {
    await codingApi.deleteSession(id)
    if (activeId.value === id) {
      stopStream()
      activeId.value = ''
      detail.value = null
      events.value = []
      tree.value = []
      memory.items = []
    }
    await refreshSessions()
  } catch (err) { fail(err) } finally { setBusy('delete', false) }
}

/* ── 计划 / 执行 ── */
async function generatePlan(useLlm = false) {
  if (!activeId.value) return
  setBusy('plan', true)
  clearError()
  try {
    await codingApi.generatePlan(activeId.value, useLlm)
    await refreshDetail()
  } catch (err) { fail(err) } finally { setBusy('plan', false) }
}

async function confirmPlan(approved: boolean) {
  if (!activeId.value) return
  setBusy('confirm', true)
  clearError()
  try {
    await codingApi.confirmPlan(activeId.value, approved)
    await refreshDetail()
  } catch (err) { fail(err) } finally { setBusy('confirm', false) }
}

async function run() {
  if (!activeId.value) return
  setBusy('run', true)
  clearError()
  try {
    await codingApi.run(activeId.value)
    startStream()
    await refreshDetail()
    await refreshSessions()
  } catch (err) { fail(err) } finally { setBusy('run', false) }
}

async function resume() {
  if (!activeId.value) return
  setBusy('resume', true)
  clearError()
  try {
    await codingApi.resume(activeId.value)
    startStream()
    await refreshDetail()
  } catch (err) { fail(err) } finally { setBusy('resume', false) }
}

/* ── 工具 / 审批 ── */
async function invokeTool(toolId: string, params: Record<string, unknown>) {
  if (!activeId.value) return null
  setBusy('tool', true)
  clearError()
  toolResult.value = null
  try {
    const res = await codingApi.invokeTool(activeId.value, toolId, params)
    toolResult.value = {
      status: res.result?.status || 'error',
      summary: res.result?.summary || '',
      output: res.result?.output ?? null,
    }
    await refreshDetail()
    return res
  } catch (err) { fail(err); return null } finally { setBusy('tool', false) }
}

async function resolveApproval(approvalId: string, approved: boolean, note = '') {
  if (!activeId.value) return
  setBusy('approval', true)
  clearError()
  try {
    await codingApi.resolveApproval(activeId.value, approvalId, approved, note)
    await refreshDetail()
  } catch (err) { fail(err) } finally { setBusy('approval', false) }
}

/* ── 待办 ── */
async function addTodos(items: string[]) {
  if (!activeId.value || !items.length) return
  try {
    await codingApi.addTodos(activeId.value, items)
    await refreshDetail()
  } catch (err) { fail(err) }
}

async function updateTodo(todoId: string, state: string) {
  if (!activeId.value) return
  try {
    await codingApi.updateTodo(activeId.value, todoId, state)
    await refreshDetail()
  } catch (err) { fail(err) }
}

/* ── 子智能体 ── */
async function runSubagent(role: string, task: string) {
  if (!activeId.value) return null
  setBusy('subagent', true)
  clearError()
  try {
    const res = await codingApi.runSubagent(activeId.value, role, task)
    await refreshDetail()
    return res.subagent
  } catch (err) { fail(err); return null } finally { setBusy('subagent', false) }
}

/* ── 记忆 ── */
async function loadMemory() {
  if (!activeId.value) return
  try {
    const res = await codingApi.listMemory(activeId.value)
    memory.items = res.items || []
    memory.summary = res.summary || {}
    memory.available = res.ok !== false
  } catch (err) { fail(err) }
}

async function writeMemory(kind: string, title: string, text: string) {
  if (!activeId.value) return false
  setBusy('memory', true)
  clearError()
  try {
    const res = await codingApi.writeMemory(activeId.value, kind, title, text)
    await loadMemory()
    await refreshDetail()
    return res.ok
  } catch (err) { fail(err); return false } finally { setBusy('memory', false) }
}

async function forgetMemory(capsuleId: string) {
  if (!activeId.value) return null
  setBusy('memory', true)
  clearError()
  try {
    const res = await codingApi.forgetMemory(activeId.value, capsuleId)
    await loadMemory()
    await refreshDetail()
    return res
  } catch (err) { fail(err); return null } finally { setBusy('memory', false) }
}

/* ── 文件树 ── */
async function loadTree() {
  if (!activeId.value) return
  try {
    const res = await codingApi.tree(activeId.value, 2)
    tree.value = res.tree || []
  } catch (err) { fail(err) }
}

/* ── 事件流：SSE 优先，轮询兜底 ── */
function stopStream() {
  if (streamAbort) { streamAbort.abort(); streamAbort = null }
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

function startPolling() {
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    if (!activeId.value) return
    try {
      const res = await codingApi.events(activeId.value, lastSeq())
      if (res.items?.length) {
        mergeEvents(res.items)
        await refreshDetail()
      } else if (detail.value?.running) {
        await refreshDetail()
      }
    } catch { /* 静默：下一轮重试 */ }
  }, 1500)
}

async function startStream() {
  stopStream()
  if (!activeId.value) return
  // 调试/兼容开关：URL 带 ``?stream=0`` 时跳过 SSE 直接用轮询
  // （某些反向代理会缓冲 SSE，或自动化工具会因长连接而无法判定页面静止）。
  if (new URLSearchParams(window.location.search).get('stream') === '0') {
    await refreshDetail()
    startPolling()
    return
  }
  const id = activeId.value
  const ctrl = new AbortController()
  streamAbort = ctrl
  const key = getApiKey()
  try {
    const res = await fetch(codingApi.streamUrl(id, lastSeq()), {
      headers: key ? { 'X-API-Key': key } : {},
      signal: ctrl.signal,
    })
    if (!res.ok || !res.body) throw new Error('sse unavailable')
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let cut = buffer.indexOf('\n\n')
      while (cut >= 0) {
        const chunk = buffer.slice(0, cut)
        buffer = buffer.slice(cut + 2)
        for (const line of chunk.split('\n')) {
          if (!line.startsWith('data:')) continue
          try { mergeEvents([JSON.parse(line.slice(5).trim())]) } catch { /* 忽略半包 */ }
        }
        cut = buffer.indexOf('\n\n')
      }
    }
  } catch {
    // SSE 不可用（代理/鉴权/网络）→ 降级轮询，功能不受影响
    if (!ctrl.signal.aborted) startPolling()
    return
  }
  // 流正常结束：拉一次全量并保持轮询，捕捉执行中的后续事件
  await refreshDetail()
  startPolling()
}

export function useCoding() {
  return {
    // 元信息
    overview, tools, skills, roles, policy,
    // 会话
    sessions, activeId, activeBrief, detail, events, tree, memory,
    isRunning, pendingApprovals, busy, error, booted, toolResult,
    // 动作
    bootstrap, refreshSessions, refreshDetail, selectSession, createSession, deleteSession,
    generatePlan, confirmPlan, run, resume,
    invokeTool, resolveApproval,
    addTodos, updateTodo,
    runSubagent,
    loadMemory, writeMemory, forgetMemory,
    loadTree, startStream, stopStream,
    clearError,
  }
}
