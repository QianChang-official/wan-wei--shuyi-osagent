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
 * 万枢编程框架 API 客户端。
 *
 * 复用控制台统一的鉴权与错误语义（``X-API-Key`` + ``ApiError``），
 * 但走独立的请求通道，因为编程框架的接口超时特征与聊天不同
 * （规划/执行可能较慢，工具调用需要更长宽限）。
 */

import { ApiError, getApiKey, parseApiErrorDetail } from './client'

/* ══ 类型 ══ */

export interface CodingOverview {
  name: string
  codename: string
  version: string
  positioning: string
  capabilities: { id: string; label: string; status: string }[]
  counts: { tools: number; skills: number; subagent_roles: number }
  policy_modes: { id: string; label: string }[]
  llm: { available: boolean }
}

export interface ToolSpec {
  id: string
  name_cn: string
  description: string
  risk: string
  risk_label: string
  parameters: Record<string, string>
  category: string
  dynamic_risk: boolean
}

export interface SkillSpec {
  id: string
  name: string
  description: string
  tools: string[]
  source: string
  path: string
}

export interface SubagentRole {
  role: string
  label: string
  readonly: boolean
  tools: string[]
  mission: string
}

export interface PolicyMatrix {
  modes: { id: string; label: string }[]
  risks: { id: string; label: string }[]
  matrix: Record<string, Record<string, string>>
  session_states: { id: string; label: string }[]
}

export interface PlanStep {
  id: string
  title: string
  detail: string
  tool_hint: string
  state: string
  state_label: string
  result: string
}

export interface Plan {
  steps: PlanStep[]
  confirmed: boolean
  source: string
  rationale: string
  total: number
  done: number
  progress: number
}

export interface Todo {
  id: string
  text: string
  state: string
  state_label: string
  note: string
}

export interface SubagentView {
  id: string
  role: string
  role_label: string
  task: string
  depth: number
  allowed_tools: string[]
  readonly: boolean
  status: string
  findings: Record<string, unknown>
  error: string
}

export interface Approval {
  id: string
  tool_id: string
  params: Record<string, unknown>
  risk: string
  summary: string
  status: string
  created_at: string
  resolved_at: string | null
  note: string
}

export interface CodingEvent {
  seq: number
  id: string
  session_id: string
  type: string
  payload: Record<string, any>
  at: string
}

export interface SessionBrief {
  id: string
  title: string
  task: string
  workspace: string
  policy_mode: string
  policy_label: string
  state: string
  state_label: string
  plan_total: number
  plan_done: number
  pending_approvals: number
  created_at: string
  updated_at: string
}

export interface SessionDetail extends SessionBrief {
  plan: Plan
  todos: Todo[]
  subagents: SubagentView[]
  approvals: Approval[]
  guard: Record<string, number>
  last_run: Record<string, unknown> | null
  events: CodingEvent[]
  running: boolean
}

export interface FileNode {
  name: string
  path: string
  type: 'dir' | 'file'
  children?: FileNode[]
}

export interface MemoryItem {
  capsule_id: string
  kind: string
  kind_label: string
  title: string
  text: string
  session_id: string
  created_at: string
  lifecycle: string
}

/* ══ 请求通道 ══ */

const DEFAULT_TIMEOUT_MS = 60_000

async function req<T>(path: string, init?: RequestInit, timeoutMs = DEFAULT_TIMEOUT_MS): Promise<T> {
  const headers = new Headers(init?.headers)
  headers.set('Content-Type', 'application/json')
  const key = getApiKey()
  if (key) headers.set('X-API-Key', key)

  const controller = new AbortController()
  const timer = timeoutMs > 0 ? setTimeout(() => controller.abort('timeout'), timeoutMs) : undefined
  try {
    const res = await fetch(path, { ...init, headers, signal: controller.signal })
    if (!res.ok) {
      let detail: string | undefined
      try { detail = parseApiErrorDetail(await res.json()) } catch { /* ignore */ }
      throw new ApiError(res.status, detail ? `HTTP ${res.status}: ${detail}` : `HTTP ${res.status}`, detail)
    }
    return (await res.json()) as T
  } finally {
    if (timer !== undefined) clearTimeout(timer)
  }
}

const get = <T>(p: string) => req<T>(p)
const post = <T>(p: string, body?: unknown, timeoutMs?: number) =>
  req<T>(p, { method: 'POST', body: JSON.stringify(body ?? {}) }, timeoutMs)
const del = <T>(p: string) => req<T>(p, { method: 'DELETE' })

const BASE = '/platform/coding'

/* ══ 端点 ══ */

export const codingApi = {
  overview: () => get<CodingOverview>(`${BASE}/overview`),
  tools: () => get<{ items: ToolSpec[] }>(`${BASE}/tools`),
  skills: (sessionId?: string) =>
    get<{ items: SkillSpec[] }>(sessionId ? `${BASE}/skills?session_id=${sessionId}` : `${BASE}/skills`),
  subagentRoles: () => get<{ items: SubagentRole[] }>(`${BASE}/subagents`),
  policy: () => get<PolicyMatrix>(`${BASE}/policy`),

  listSessions: () => get<{ items: SessionBrief[]; total: number }>(`${BASE}/sessions`),
  createSession: (input: { task: string; workspace: string; policy_mode: string; title?: string }) =>
    post<SessionDetail>(`${BASE}/sessions`, input),
  getSession: (id: string) => get<SessionDetail>(`${BASE}/sessions/${id}`),
  deleteSession: (id: string) => del<{ ok: boolean }>(`${BASE}/sessions/${id}`),

  generatePlan: (id: string, useLlm = false) =>
    post<{ plan: Plan; state: string }>(`${BASE}/sessions/${id}/plan`, { use_llm: useLlm }, 120_000),
  confirmPlan: (id: string, approved: boolean) =>
    post<{ plan: Plan; state: string }>(`${BASE}/sessions/${id}/plan/confirm`, { approved }),
  run: (id: string) => post<{ ok: boolean; status: string }>(`${BASE}/sessions/${id}/run`),
  resume: (id: string) => post<{ ok: boolean; status: string }>(`${BASE}/sessions/${id}/resume`),

  invokeTool: (id: string, toolId: string, params: Record<string, unknown>) =>
    post<{ result: ToolSpec & { status: string; summary: string; output: any }; approval?: Approval }>(
      `${BASE}/sessions/${id}/tool`, { tool_id: toolId, params }),
  resolveApproval: (id: string, approvalId: string, approved: boolean, note = '') =>
    post<{ approval: Approval; result: any }>(`${BASE}/sessions/${id}/approvals/${approvalId}`, { approved, note }),

  addTodos: (id: string, items: string[]) =>
    post<{ todos: Todo[] }>(`${BASE}/sessions/${id}/todos`, { items }),
  updateTodo: (id: string, todoId: string, state: string, note = '') =>
    post<{ todos: Todo[] }>(`${BASE}/sessions/${id}/todos/${todoId}`, { state, note }),

  runSubagent: (id: string, role: string, task: string) =>
    post<{ subagent: SubagentView }>(`${BASE}/sessions/${id}/subagents`, { role, task }, 120_000),

  listMemory: (id: string) =>
    get<{ ok: boolean; count: number; items: MemoryItem[]; summary: Record<string, number>; message?: string }>(
      `${BASE}/sessions/${id}/memory`),
  writeMemory: (id: string, kind: string, title: string, text: string) =>
    post<{ ok: boolean; capsule_id?: string; message?: string }>(`${BASE}/sessions/${id}/memory`, { kind, title, text }),
  forgetMemory: (id: string, capsuleId: string) =>
    post<{ ok: boolean; status?: string; deletion_verification?: Record<string, unknown> }>(
      `${BASE}/sessions/${id}/memory/${capsuleId}/forget`),

  runWorkflow: (id: string, nodes: unknown[], concurrency = 4) =>
    post<Record<string, any>>(`${BASE}/sessions/${id}/workflow`, { nodes, concurrency }, 180_000),

  tree: (id: string, depth = 2) => get<{ tree: FileNode[] }>(`${BASE}/sessions/${id}/tree?depth=${depth}`),
  events: (id: string, after = 0) =>
    get<{ items: CodingEvent[]; count: number; last_seq: number }>(`${BASE}/sessions/${id}/events?after=${after}`),
  streamUrl: (id: string, after = 0) => `${BASE}/sessions/${id}/stream?after=${after}`,
}
