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

// Same-origin API client for v0.9.3 MemoryOps Workflow Run Platform.
// In dev, Vite proxies backend paths to FastAPI; in prod dist is mounted under /console.

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

export function parseApiErrorDetail(body: unknown): string | undefined {
  if (!body || typeof body !== 'object') return undefined
  const b = body as Record<string, unknown>
  if (typeof b.detail === 'string') return b.detail
  if (b.detail && typeof b.detail === 'object') {
    const d = b.detail as Record<string, unknown>
    if (typeof d.error === 'string') return d.error
    if (typeof d.reason === 'string') return d.reason
  }
  if (typeof b.error === 'string') return b.error
  if (typeof b.reason === 'string') return b.reason
  return undefined
}

function _loadApiKey(): string {
  if (import.meta.env.DEV) {
    return import.meta.env.VITE_WANWEI_DEV_API_KEY || ''
  }
  // 桌面端优先通过 preload 提供的受控接口读取，避免明文落入 localStorage
  try {
    const desktopKey = (window as any).wanweiDesktop?.getApiKey?.()
    if (desktopKey) return desktopKey
  } catch { /* ignore */ }
  // 向后兼容：旧版 preload 或降级场景回退 localStorage
  try {
    return localStorage.getItem('wanwei-desktop-api-key') || ''
  } catch {
    return ''
  }
}

let apiKey = _loadApiKey()

export function setApiKey(value: string): void {
  apiKey = value.trim()
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  headers.set('Content-Type', 'application/json')
  if (apiKey) headers.set('X-API-Key', apiKey)

  const res = await fetch(path, {
    ...init,
    headers,
  })
  if (!res.ok) {
    let detail: string | undefined
    try {
      const body = await res.json()
      detail = parseApiErrorDetail(body)
    } catch {
      // ignore parse failure
    }
    const message = detail ? `HTTP ${res.status}: ${detail}` : `HTTP ${res.status} on ${path}`
    throw new Error(message)
  }
  return res.json() as Promise<T>
}

/** 带鉴权下载二进制文件（如 PDF 证书），返回 Blob URL 供 <a download> 使用。 */
async function reqBlob(path: string): Promise<string> {
  const headers = new Headers()
  if (apiKey) headers.set('X-API-Key', apiKey)
  const res = await fetch(path, { headers })
  if (!res.ok) {
    const message = `HTTP ${res.status} on ${path}`
    throw new Error(message)
  }
  const blob = await res.blob()
  return URL.createObjectURL(blob)
}

export const api = {
  health: () => req<{ status: string; name: string; version: string }>('/health'),
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
