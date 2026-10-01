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
 * 控制台 API 类型定义 —— 与 backend/app 的响应契约逐字段对齐。
 */

export interface Health {
  status: string
  name: string
  version: string
}

/* ── 智能体 ── */

export interface AgentPermissions {
  fs_read: boolean
  fs_write: boolean
  shell: boolean
  network: boolean
  git: boolean
}

export interface Agent {
  id: string
  name: string
  role: string
  persona: string
  depth: string
  gear: string
  permissions: AgentPermissions
  provider_pid: string
  model: string
  goal: string
  created_at: string
}

export interface AgentInput {
  name: string
  role: string
  persona: string
  depth: string
  gear: string
  permissions: AgentPermissions
  provider_pid: string
  model: string
  goal: string
}

/* ── 对话 ── */

export interface ChatRequest {
  message: string
  agent_id?: string | null
  depth?: string | null
  gear?: string | null
  previous_run_id?: string | null
  goal?: string | null
}

export interface PendingConfirmation {
  confirm_token: string
  operation?: string
  command?: string
  path?: string
  expires_at?: string
  content_preview?: string
  bytes?: number
  run_id?: string
}

export interface ConfirmationResult {
  ok: boolean
  denied?: boolean
  exit_code?: number
  stdout?: string
  stderr?: string
  error?: string
  reason?: string
  run_id?: string
  status?: string
  pending_confirmations?: PendingConfirmation[]
}

/** 智能体过程步骤：思考 / 工具调用 / 工具结果（透明化"它是怎么做的"） */
export interface ProcessStep {
  kind: 'run_started' | 'capability' | 'thinking' | 'tool_call' | 'tool_result'
  capabilities?: Record<string, unknown>
  tool?: string
  run_id?: string
  status?: string
  args?: string
  result?: string | Record<string, unknown>
  text?: string
  /** 思考持续时间（秒） */
  duration_s?: number
  /** 破坏性命令被挂起时附带的确认票据（仅 tool_result 且 needs_confirm 时有） */
  confirm_token?: string
}

export interface ChatResponse {
  reply: string
  context_tokens: number
  run_id: string
  depth: string
  gear: string
  engine: string
  provider_used: string
  agent_id: string | null
  memory_injection: 'ok' | 'empty' | 'unavailable'
  process_steps?: ProcessStep[]
  status?: string
  capabilities?: Record<string, unknown>
  pending_confirmations?: PendingConfirmation[]
}

/* ── 运行 ── */

export type RunStatus =
  | 'queued' | 'running' | 'awaiting_review' | 'done' | 'failed' | 'cancelled' | 'rejected'

export interface RunStep {
  id: string
  index: number
  name: string
  kind: string
  title: string
  status: 'pending' | 'running' | 'awaiting_review' | 'done' | 'rejected' | 'skipped'
  needs_review: boolean
  detail: string
  started_at: string | null
  finished_at: string | null
}

export interface Run {
  id: string
  kind: 'solo' | 'team' | 'chat' | 'subagent'
  agent_id: string | null
  agent_name: string
  team_id: string | null
  team_name: string
  orchestration: string
  parent_run_id: string | null
  task: string
  goal: string
  depth: string
  gear: string
  provider_pid: string
  model: string
  status: RunStatus
  engine: string
  steps: RunStep[]
  cursor: number
  result: string
  error: string
  created_at: string
  updated_at: string
  finished_at: string | null
  memory_injection?: 'ok' | 'empty' | 'unavailable'
  provider_used?: string | null
  pending_confirmations?: PendingConfirmation[]
}

export interface RunList {
  items: Run[]
  total: number
  limit: number | null
  offset: number
}

/* ── 上下文估算 ── */

export interface ContextSize {
  agent_id: string | null
  system_prompt: number
  memory_instructions: number
  history: number
  total_tokens: number
  limit: number
  previews: {
    system_prompt: string
    memory_instructions: string
    history_runs: number
  }
}

/* ── 模型接入 ── */

export interface ProviderConfig {
  pid: string
  configured: boolean
  enabled: boolean
  base_url: string
  model: string
  has_api_key: boolean
  api_key_tail: string
  api_key_masked: string
  extra: Record<string, string>
  updated_at: string
}

export interface ProviderCatalogEntry {
  id: string
  name: string
  kind: 'aggregator' | 'cloud' | 'local' | 'oauth' | 'custom'
  base_url: string
  models: string[]
  auth_modes: string[]
  docs_url: string
  aux_capable: boolean
  description: string
}

export interface ProviderConfigInput {
  api_key?: string
  base_url?: string
  model?: string
  enabled?: boolean
  extra?: Record<string, string>
}

export interface ProviderTestResult {
  ok: boolean
  pid: string
  mode?: string
  status_code?: number
  latency_ms?: number
  note?: string
  reason?: string
  response_preview?: string
}

export interface ProviderAux {
  pid: string
  model: string
  enabled: boolean
  purpose: string
}

/* ── 记忆指令 ── */

export interface Instructions {
  lines: string[]
  count: number
  max: number
  updated_at: string
}

/* ── 审计 ── */

export interface AuditEntry {
  audit_id: string
  event_type: string
  /** JSON 编码字符串，消费方需 JSON.parse */
  payload: string
  created_at: string
}
