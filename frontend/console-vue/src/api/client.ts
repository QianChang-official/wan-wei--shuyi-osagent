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

export interface ApiState { online: boolean; version: string; name: string }

export interface PlatformModule {
  id: string
  name_cn: string
  name_en: string
  pillar: string
  status: 'done' | 'partial' | 'planned'
  backend_refs: string[]
  frontend_refs: string[]
  competition_refs: string[]
  description: string
}

export interface ModelProvider {
  provider: string
  api_base: string
  api_key_alias: string
  model: string
  enabled: boolean
  status: string
  notes: string
}

export interface ModelGatewayConfig {
  provider: string
  api_base: string
  api_key: '***'
  model: string
  enabled: boolean
  notes: string
}

export interface ModelGatewayConfigInput {
  provider: string
  api_base: string
  api_key: string
  model: string
  enabled: boolean
  notes: string
}

export interface RegistryTool {
  id: string
  name_cn: string
  kind: string
  permission_mode: string
  sandbox: string
  status: string
  result_storage: string
  description: string
}

export interface RegistrySkill {
  id: string
  name_cn: string
  scope: string
  status: string
  entrypoint: string
  description: string
}

export interface ExportPackage {
  id: string
  name_cn: string
  status: string
  evidence_files: string[]
  demo_path: string
}

export interface ResearchTechnology {
  id: string
  name: string
  source_level: string
  publication_status: string
  core_idea: string
  target_modules: string[]
  adoption_ratio: number
  current_status: 'done' | 'partial' | 'planned' | 'pending'
  v08_actions: string[]
  v09_risk_controls: string[]
  evidence_files: string[]
  source_urls: string[]
}

export interface AdoptionRoute {
  route_id: string
  name_cn: string
  target_pillar: string
  backend_plan: string[]
  frontend_plan: string[]
  arena_plan: string[]
  status: string
  expected_impact: string
}

export interface VersionMapping {
  version: string
  positioning: string
  authoritative_support: string[]
  completed: string[]
  unfinished: string[]
  inherited_by: string[]
  evidence_files: string[]
}

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
let credentialRevision = 0
const credentialListeners = new Set<() => void>()
export const getCredentialRevision = () => credentialRevision
export function onApiKeyChange(listener: () => void): () => void {
  credentialListeners.add(listener)
  return () => { credentialListeners.delete(listener) }
}

export function getApiKey(): string {
  return apiKey
}

/** 修改访问身份会同步清空客户端会话/缓存；不把访问密钥当作会话标识落盘。 */
export function setApiKey(value: string): void {
  const changed = apiKey !== value.trim()
  apiKey = value.trim()
  try {
    if (apiKey) localStorage.setItem(API_KEY_STORAGE, apiKey)
    else localStorage.removeItem(API_KEY_STORAGE)
  } catch { /* 隐私模式等场景下静默失败 */ }
  if (changed) {
    credentialRevision++
    credentialListeners.forEach((listener) => listener())
  }
}

export interface ReqOptions {
  /** 超时毫秒数，默认 30000；传 0 表示不设置超时 */
  timeoutMs?: number
  /** 调用方自带的中止信号，与超时并存，先触发者生效 */
  signal?: AbortSignal
}

const DEFAULT_TIMEOUT_MS = 30_000

async function request<T>(path: string, init?: RequestInit, options?: ReqOptions): Promise<T> {
  const revision = getCredentialRevision()
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
    const result = await res.json() as T
    if (revision !== getCredentialRevision()) throw new Error('访问身份已变更，请重试')
    return result
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

const req = request

async function reqBlob(path: string): Promise<string> {
  const headers = new Headers()
  if (apiKey) headers.set('X-API-Key', apiKey)
  const res = await fetch(path, { headers })
  if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status} on ${path}`)
  return URL.createObjectURL(await res.blob())
}

export interface StreamOptions extends ReqOptions {
  connectTimeoutMs?: number
  idleTimeoutMs?: number
}

/** A finite stream: connect/idle/overall deadlines, terminal event required, abort always settles. */
async function chatStream(
  input: ChatRequest,
  handlers: { onStep: (step: import('./types').ProcessStep) => void; onFinal: (res: ChatResponse) => void },
  options: StreamOptions = {},
): Promise<void> {
  const controller = new AbortController()
  const revision = getCredentialRevision()
  const abort = () => controller.abort('caller')
  const signal = options.signal
  if (signal?.aborted) abort()
  else signal?.addEventListener('abort', abort, { once: true })
  const total = setTimeout(() => controller.abort('timeout'), options.timeoutMs ?? 180_000)
  let deadline = setTimeout(() => controller.abort('timeout'), options.connectTimeoutMs ?? 30_000)
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined
  let terminal = false
  try {
    const headers = new Headers({ 'Content-Type': 'application/json', Accept: 'text/event-stream' })
    if (apiKey) headers.set('X-API-Key', apiKey)
    const res = await fetch('/platform/agents/chat/stream', {
      method: 'POST', headers, body: JSON.stringify(input), signal: controller.signal,
    })
    if (!res.ok) {
      let detail: string | undefined
      try { detail = parseApiErrorDetail(await res.json()) } catch { /* HTTP status remains useful */ }
      throw new ApiError(res.status, detail || `HTTP ${res.status}`, detail)
    }
    if (!res.body) throw new Error('响应没有事件流')
    reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (!terminal) {
      clearTimeout(deadline)
      deadline = setTimeout(() => controller.abort('timeout'), options.idleTimeoutMs ?? 60_000)
      const { done, value } = await reader.read()
      if (controller.signal.aborted) throw new DOMException('已停止接收', 'AbortError')
      if (revision !== getCredentialRevision()) throw new DOMException('访问身份已变更', 'AbortError')
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true })
      if (buffer.length > 1_048_576) throw new Error('事件流单帧过大')
      let sep: RegExpExecArray | null
      while (!terminal && (sep = /\r?\n\r?\n/.exec(buffer))) {
        const frame = buffer.slice(0, sep.index)
        buffer = buffer.slice(sep.index + sep[0].length)
        let event = 'message'
        const data: string[] = []
        for (const line of frame.split(/\r?\n/)) {
          if (line.startsWith('event:')) event = line.slice(6).trim()
          else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''))
        }
        if (!data.length) continue
        const payload = JSON.parse(data.join('\n'))
        if (event === 'step') handlers.onStep(payload)
        else if (event === 'final') {
          if (typeof payload.reply !== 'string') throw new Error('最终响应缺少答案')
          terminal = true
          handlers.onFinal(payload)
        } else if (event === 'error') {
          const detail = [payload.error, payload.reason].filter(Boolean).join('：') || '后端流错误'
          throw new ApiError(payload.error === 'gateway_unavailable' ? 502 : 500, detail, detail)
        }
      }
      if (done && !terminal) throw new Error('连接提前结束，未收到最终结果；请查看运行记录后重试')
    }
  } catch (err) {
    if (controller.signal.reason === 'timeout') throw new ApiError(0, '连接或处理超时，请查看运行记录后重试', undefined, true)
    if (controller.signal.aborted) throw new DOMException('已停止接收', 'AbortError')
    throw err
  } finally {
    clearTimeout(total)
    clearTimeout(deadline)
    signal?.removeEventListener('abort', abort)
    if (!terminal) controller.abort()
    if (reader) { void reader.cancel().catch(() => {}); reader.releaseLock() }
  }
}

export const api = {
  health: () => get<Health>('/health'),
  arenaMetrics: () => req<Record<string, any>>('/arena/metrics'),
  listCapsules: (limit = 50) =>
    req<{ items: any[] }>(`/memory/v2/capsules?limit=${limit}`),
  getCapsule: (id: string) => req<any>(`/memory/v2/capsules/${id}`),
  writeCapsule: (body: Record<string, unknown>) =>
    req<any>('/memory/v2/capsules', { method: 'POST', body: JSON.stringify(body) }),
  search: (q: string, topK = 5, highRisk = false) =>
    req<any>(`/memory/v2/search?q=${encodeURIComponent(q)}&top_k=${topK}&high_risk=${highRisk}`),
  command: (goal: string, scene = 'general', topK = 5) =>
    req<any>('/memory/v2/command', {
      method: 'POST',
      body: JSON.stringify({ goal, scene, top_k: topK }),
    }),
  reflection: (body: Record<string, unknown>) =>
    req<any>('/memory/v2/reflection', { method: 'POST', body: JSON.stringify(body) }),
  auditLogs: (limit = 50, traceId = '') =>
    req<{ items: any[] }>(`/audit/logs?limit=${limit}${traceId ? `&trace_id=${encodeURIComponent(traceId)}` : ''}`),
  securityScore: () => req<any>('/security/score'),
  agentAuditRun: () => req<any>('/audit/agent/run', { method: 'POST' }),
  platformModules: () => req<{ items: PlatformModule[]; summary: any }>('/platform/modules'),
  modelProviders: () => req<{ items: ModelProvider[] }>('/model-gateway/providers'),
  modelGatewayConfigs: () => req<{ items: ModelGatewayConfig[] }>('/model-gateway/configs'),
  saveModelGatewayConfig: (body: ModelGatewayConfigInput) =>
    req<ModelGatewayConfig>('/model-gateway/configs', { method: 'POST', body: JSON.stringify(body) }),
  deleteModelGatewayConfig: (provider: string) =>
    req<{ deleted: boolean }>(`/model-gateway/configs/${encodeURIComponent(provider)}`, { method: 'DELETE' }),
  testModelProvider: (body: Record<string, unknown>) =>
    req<any>('/model-gateway/test', { method: 'POST', body: JSON.stringify(body) }),
  registryTools: () => req<{ items: RegistryTool[] }>('/tool-registry/tools'),
  registrySkills: () => req<{ items: RegistrySkill[] }>('/tool-registry/skills'),
  tuningDefaults: () => req<{ defaults: Record<string, Record<string, unknown>> }>('/tuning/defaults'),
  tuningPolicies: () => req<{ items: any[] }>('/tuning/policies'),
  exportPackages: () => req<{ items: ExportPackage[] }>('/exports/packages'),
  researchTechnologies: () => req<{ items: ResearchTechnology[] }>('/research-adoption/technologies'),
  researchRoutes: () => req<{ items: AdoptionRoute[] }>('/research-adoption/routes'),
  researchVersionMap: () => req<{ items: VersionMapping[] }>('/research-adoption/version-map'),
  workflowDesign: () => req<any>('/workflow/design'),
  workflowCompetitionMapping: () => req<any>('/workflow/competition-mapping'),
  workflowRunDryRun: (body: Record<string, unknown>) =>
    req<any>('/workflow/run-dry-run', { method: 'POST', body: JSON.stringify(body) }),
  workflowCreateRun: (body: Record<string, unknown>) =>
    req<any>('/workflow/runs', { method: 'POST', body: JSON.stringify(body) }),
  workflowGetRun: (runId: string) => req<any>(`/workflow/runs/${encodeURIComponent(runId)}`),
  workflowTrace: (runId: string) => req<any>(`/workflow/runs/${encodeURIComponent(runId)}/trace`),
  workflowArtifacts: (runId: string) => req<any>(`/workflow/runs/${encodeURIComponent(runId)}/artifacts`),
  reproductionSystems: () => req<any>('/reproduction/systems'),
  reproductionWorkbench: () => req<any>('/reproduction/memoryarena/workbench'),
  reproductionHippoGraph: () => req<any>('/reproduction/hippo-lite/graph'),
  reproductionHippoRecall: (body: Record<string, unknown>) =>
    req<any>('/reproduction/hippo-lite/recall', { method: 'POST', body: JSON.stringify(body) }),
  reproductionRetentionState: () => req<any>('/reproduction/retention/state'),
  reproductionRetentionSimulate: (body: Record<string, unknown>) =>
    req<any>('/reproduction/retention/simulate', { method: 'POST', body: JSON.stringify(body) }),
  reproductionReflexionEvaluator: () => req<any>('/reproduction/reflexion/evaluator'),
  reproductionReflexionEvaluate: (body: Record<string, unknown>) =>
    req<any>('/reproduction/reflexion/evaluate', { method: 'POST', body: JSON.stringify(body) }),
  reproductionMemoryTools: () => req<any>('/reproduction/memory-tools'),
  reproductionMemoryToolDryRun: (body: Record<string, unknown>) =>
    req<any>('/reproduction/memory-tools/dry-run', { method: 'POST', body: JSON.stringify(body) }),
  reproductionMemcubeSchema: () => req<any>('/reproduction/memcube/schema'),
  reproductionMemoryTiers: () => req<any>('/reproduction/memory-tiers'),
  reproductionLocomoTemplate: () => req<any>('/reproduction/locomo/template'),
  reproductionGenerativeTemplate: () => req<any>('/reproduction/generative-stream/template'),
  deepeningSessionCoreDesign: () => req<any>('/deepening/session-core/design'),
  deepeningSessionCoreDemoTrace: () => req<any>('/deepening/session-core/demo-trace'),
  deepeningReasoningDepthDesign: () => req<any>('/deepening/reasoning-depth/design'),
  deepeningReasoningDepthSimulate: (body: Record<string, unknown>) =>
    req<any>('/deepening/reasoning-depth/simulate', { method: 'POST', body: JSON.stringify(body) }),
  deepeningRedQueenEvaluatorDesign: () => req<any>('/deepening/redqueen/evaluator-design'),
  deepeningRedQueenEvaluateDryRun: (body: Record<string, unknown>) =>
    req<any>('/deepening/redqueen/evaluate-dry-run', { method: 'POST', body: JSON.stringify(body) }),
  deepeningContractSourceOfTruth: () => req<any>('/deepening/contracts/source-of-truth'),
  deepeningContractDriftCheck: () => req<any>('/deepening/contracts/drift-check'),
  deepeningAgiAsiPathways: () => req<any>('/deepening/agi-asi/pathways'),
  deepeningInterrogationQuestions: () => req<any>('/deepening/interrogation/questions'),
  deepeningInterrogationAnswerDryRun: (body: Record<string, unknown>) =>
    req<any>('/deepening/interrogation/answer-dry-run', { method: 'POST', body: JSON.stringify(body) }),
  deepeningVisualVerificationProtocol: () => req<any>('/deepening/visual-verification/protocol'),
  deepeningVisualVerificationChecklistDryRun: (body: Record<string, unknown>) =>
    req<any>('/deepening/visual-verification/checklist-dry-run', { method: 'POST', body: JSON.stringify(body) }),
  // v0.11 Soul Awakening
  soulConnect: (soulId?: string) =>
    req<{ soul_id: string; injection_prompt: string; persona: any }>('/soul/connect', {
      method: 'POST',
      body: JSON.stringify({ soul_id: soulId || null }),
    }),
  soulChat: (soulId: string, messages: any[], model = 'default') =>
    req<any>('/soul/chat', {
      method: 'POST',
      body: JSON.stringify({ soul_id: soulId, messages, model }),
    }),
  soulState: (soulId: string) => req<any>(`/soul/state/${encodeURIComponent(soulId)}`),
  soulPersonaUpdate: (soulId: string, body: Record<string, unknown>) =>
    req<any>(`/soul/persona/${encodeURIComponent(soulId)}`, { method: 'PUT', body: JSON.stringify(body) }),
  soulAffect: (soulId: string) => req<any>(`/soul/affect/${encodeURIComponent(soulId)}`),
  soulAffectPut: (soulId: string, trigger: string, intensity = 1.0) =>
    req<any>(`/soul/affect/${encodeURIComponent(soulId)}?trigger=${encodeURIComponent(trigger)}&intensity=${intensity}`, { method: 'PUT' }),
  // MemoryOS 治理层
  governanceReleaseGate: () => req<any>('/memory/governance/release-gate'),
  governanceIncidents: (limit = 50, unresolvedOnly = false) =>
    req<{ items: any[] }>(`/memory/governance/incidents?limit=${limit}${unresolvedOnly ? '&unresolved_only=true' : ''}`),
  governanceProvenance: (capsuleId: string) =>
    req<any>(`/memory/governance/provenance/${encodeURIComponent(capsuleId)}`),
  governanceVerifyDeletion: (capsuleId: string) =>
    req<any>(`/memory/governance/verify-deletion/${encodeURIComponent(capsuleId)}`),
  governanceVerifyDeletionCertificate: (capsuleId: string) =>
    reqBlob(`/memory/governance/verify-deletion/${encodeURIComponent(capsuleId)}/certificate`),
  memoryHealth: () => req<any>('/memory/health'),
  memoryHealthTrend: () => req<any>('/memory/health/trend'),
  memoryLedger: (capsuleId: string, limit = 50) =>
    req<{ items: any[] }>(`/memory/ledger/${encodeURIComponent(capsuleId)}?limit=${limit}`),
  memoryLifecycle: (capsuleId: string) =>
    req<any>(`/memory/lifecycle/${encodeURIComponent(capsuleId)}`),

  /* 智能体 */
  listAgents: () => get<{ items: Agent[]; total: number }>('/platform/agents'),
  createAgent: (input: AgentInput) => post<Agent>('/platform/agents', input),
  updateAgent: (id: string, patch: Partial<AgentInput>) => put<Agent>(`/platform/agents/${id}`, patch),
  deleteAgent: (id: string) => del<{ ok: boolean; id: string }>(`/platform/agents/${id}`),

  /** 对话：模型网关真实调用（网关未配置时后端返回 502），超宽限 120s */
  chat: (input: ChatRequest) => post<ChatResponse>('/platform/agents/chat', input, { timeoutMs: 120_000 }),

  /** SSE 只流式提供过程事件；答案以 final 为准。 */
  chatStream,

  /** 破坏性命令确认门：放行/拒绝挂起的命令 */
  confirmCommand: (token: string, approved: boolean) =>
    post<import('./types').ConfirmationResult>(
      '/platform/agents/chat/confirm', { token, approved }, { timeoutMs: 70_000 },
    ),

  /* 运行 */
  listRuns: (limit = 50, agentId?: string | null) =>
    get<RunList>(`/platform/agents/runs?limit=${limit}${agentId ? `&agent_id=${encodeURIComponent(agentId)}` : ''}`),
  getRun: (id: string, options?: ReqOptions) => get<Run>(`/platform/agents/runs/${encodeURIComponent(id)}`, options),
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

// ── Soul 追加封装（Worker E，纯追加，未改既有代码） ──
// POST /soul/dream 的 SoulDreamIn 要求 task_id 必填；原 api.soulDream 未携带 task_id、
// 调用即 422 且全仓零调用，已删除（09-#10）。梦境触发统一走此封装。
export function soulDreamCycle(soulId: string, taskId = 'manual-dream'): Promise<any> {
  return req<any>('/soul/dream', {
    method: 'POST',
    body: JSON.stringify({ soul_id: soulId, task_id: taskId }),
  })
}
