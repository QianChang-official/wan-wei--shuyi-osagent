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
 * 宛委·枢忆 控制台统一 API 客户端。
 *
 * 单一请求通道：同源 fetch + X-API-Key 鉴权 + 默认 30s 超时。
 * 密钥解析顺序：开发注入（vite define）→ 桌面端 preload → localStorage。
 * 生产构建不包含任何默认密钥（见 tests/api-key-security.test.mjs）。
 */

import type {
  Agent,
  AgentInput,
  AuditEntry,
  ChatRequest,
  ChatResponse,
  ContextSize,
  Health,
  Instructions,
  ProviderAux,
  ProviderCatalogEntry,
  ProviderConfig,
  ProviderConfigInput,
  ProviderTestResult,
  Run,
  RunList,
} from './types'

export class ApiError extends Error {
  status: number
  detail?: string
  /** true 表示请求因超时中止（此时无 HTTP 响应，status 恒为 0） */
  timeout: boolean
  constructor(status: number, message: string, detail?: string, timeout = false) {
    super(message)
    this.status = status
    this.detail = detail
    this.timeout = timeout
  }
}

export function isAuthError(err: unknown): err is ApiError {
  return err instanceof ApiError && (err.status === 401 || err.status === 403)
}

export function isNetworkError(err: unknown): boolean {
  return err instanceof TypeError || (err instanceof Error && /fetch|network/i.test(err.message))
}

export function isTimeoutError(err: unknown): err is ApiError {
  return err instanceof ApiError && err.timeout
}

/** 模型网关未就绪（chat 502）的机器可读标记 */
export function isGatewayUnavailable(err: unknown): boolean {
  return err instanceof ApiError && err.status === 502 && !!err.detail && /gateway_unavailable/.test(err.detail)
}

/** FastAPI 错误体展开：detail 可能是字符串、校验数组或 {error, reason} 对象 */
export function parseApiErrorDetail(body: unknown): string | undefined {
  if (!body || typeof body !== 'object') return undefined
  const detail = (body as Record<string, unknown>).detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((item) => (item && typeof item === 'object' ? (item as Record<string, unknown>).msg : item))
      .filter(Boolean)
      .join('；')
  }
  if (detail && typeof detail === 'object') {
    const d = detail as Record<string, unknown>
    if (typeof d.error === 'string' && typeof d.reason === 'string') return `${d.error}：${d.reason}`
    if (typeof d.error === 'string') return d.error
    if (typeof d.reason === 'string') return d.reason
    return JSON.stringify(d)
  }
  return undefined
}

const API_KEY_STORAGE = 'wanwei-desktop-api-key'

function loadApiKey(): string {
  if (import.meta.env.DEV) {
    return import.meta.env.VITE_WANWEI_DEV_API_KEY || ''
  }
  // 桌面端优先通过 preload 提供的受控接口读取，避免明文落入 localStorage
  try {
    const desktopKey = (window as unknown as { wanweiDesktop?: { getApiKey?: () => string } }).wanweiDesktop?.getApiKey?.()
    if (desktopKey) return desktopKey
  } catch { /* ignore */ }
  // 向后兼容：旧版 preload 或降级场景回退 localStorage
  try {
    return localStorage.getItem(API_KEY_STORAGE) || ''
  } catch {
    return ''
  }
}

let apiKey = loadApiKey()

export function getApiKey(): string {
  return apiKey
}

/** 设置访问密钥：仅保存在本进程内存（会话内有效）。
 *  持久化只走桌面端 preload 的原生受控通道；浏览器侧明文落盘
 *  （localStorage/sessionStorage）一律不做 —— CodeQL 明文存储告警的正式口径。 */
export function setApiKey(value: string): void {
  apiKey = value.trim()
}

export interface ReqOptions {
  /** 超时毫秒数，默认 30000；传 0 表示不设置超时 */
  timeoutMs?: number
  /** 调用方自带的中止信号，与超时并存，先触发者生效 */
  signal?: AbortSignal
}

const DEFAULT_TIMEOUT_MS = 30_000

async function request<T>(path: string, init?: RequestInit, options?: ReqOptions): Promise<T> {
  const headers = new Headers(init?.headers)
  headers.set('Content-Type', 'application/json')
  if (apiKey) headers.set('X-API-Key', apiKey)
  else headers.delete('X-API-Key')

  const timeoutMs = options?.timeoutMs ?? DEFAULT_TIMEOUT_MS
  const controller = new AbortController()
  const callerSignal = options?.signal
  const onCallerAbort = () => controller.abort('caller')
  if (callerSignal) {
    if (callerSignal.aborted) controller.abort('caller')
    else callerSignal.addEventListener('abort', onCallerAbort, { once: true })
  }
  const timer: ReturnType<typeof setTimeout> | undefined =
    timeoutMs > 0 ? setTimeout(() => controller.abort('timeout'), timeoutMs) : undefined

  try {
    const res = await fetch(path, { ...init, headers, signal: controller.signal })
    if (!res.ok) {
      let detail: string | undefined
      try {
        detail = parseApiErrorDetail(await res.json())
      } catch (err) {
        if (controller.signal.aborted) throw err
        // ignore parse failure
      }
      const message = detail ? `HTTP ${res.status}: ${detail}` : `HTTP ${res.status} on ${path}`
      throw new ApiError(res.status, message, detail)
    }
    return await res.json() as T
  } catch (err) {
    if (controller.signal.aborted && controller.signal.reason === 'timeout') {
      throw new ApiError(0, `请求超时（${Math.round(timeoutMs / 1000)}s）：${path}`, undefined, true)
    }
    throw err
  } finally {
    if (timer !== undefined) clearTimeout(timer)
    if (callerSignal) callerSignal.removeEventListener('abort', onCallerAbort)
  }
}

function get<T>(path: string, options?: ReqOptions): Promise<T> {
  return request<T>(path, undefined, options)
}

function post<T>(path: string, body?: unknown, options?: ReqOptions): Promise<T> {
  return request<T>(path, { method: 'POST', body: JSON.stringify(body ?? {}) }, options)
}

function put<T>(path: string, body?: unknown, options?: ReqOptions): Promise<T> {
  return request<T>(path, { method: 'PUT', body: JSON.stringify(body ?? {}) }, options)
}

function del<T>(path: string, options?: ReqOptions): Promise<T> {
  return request<T>(path, { method: 'DELETE' }, options)
}

/* ══ 类型化端点（全部直通后端真实接口，无本地模拟） ══ */

export const api = {
  health: () => get<Health>('/health'),
  auditLogs: (limit = 50) => get<{ items: AuditEntry[] }>(`/audit/logs?limit=${limit}`),

  /* 智能体 */
  listAgents: () => get<{ items: Agent[]; total: number }>('/platform/agents'),
  createAgent: (input: AgentInput) => post<Agent>('/platform/agents', input),
  updateAgent: (id: string, patch: Partial<AgentInput>) => put<Agent>(`/platform/agents/${id}`, patch),
  deleteAgent: (id: string) => del<{ ok: boolean; id: string }>(`/platform/agents/${id}`),

  /** 对话：模型网关真实调用（网关未配置时后端返回 502），超宽限 120s */
  chat: (input: ChatRequest) => post<ChatResponse>('/platform/agents/chat', input, { timeoutMs: 120_000 }),

  /* 运行 */
  listRuns: (limit = 50) => get<RunList>(`/platform/agents/runs?limit=${limit}`),
  approveRun: (id: string, approved: boolean, note = '') =>
    post<Run>(`/platform/agents/runs/${id}/approve`, { approved, note }),
  cancelRun: (id: string) => post<Run>(`/platform/agents/runs/${id}/cancel`),

  contextSize: (agentId?: string) =>
    get<ContextSize>(agentId
      ? `/platform/agents/context-size?agent_id=${encodeURIComponent(agentId)}`
      : '/platform/agents/context-size'),

  /* 模型接入 */
  listProviderConfigs: () => get<ProviderConfig[]>('/platform/providers/configs'),
  listProviderCatalog: () => get<ProviderCatalogEntry[]>('/platform/providers/catalog'),
  saveProviderConfig: (pid: string, input: ProviderConfigInput) =>
    put<ProviderConfig>(`/platform/providers/configs/${pid}`, input),
  deleteProviderConfig: (pid: string) => del<{ ok: boolean }>(`/platform/providers/configs/${pid}`),
  testProvider: (pid: string) => post<ProviderTestResult>('/platform/providers/test', { pid }, { timeoutMs: 60_000 }),
  getAuxProvider: () => get<ProviderAux>('/platform/providers/aux'),

  /* 记忆指令 */
  getInstructions: () => get<Instructions>('/platform/memory/instructions'),
  putInstructions: (lines: string[]) =>
    put<Instructions & { ok: boolean }>('/platform/memory/instructions', { lines }),
}
