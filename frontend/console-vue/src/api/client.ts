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

let apiKey = ''

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
  if (!res.ok) throw new Error(`HTTP ${res.status} on ${path}`)
  return res.json() as Promise<T>
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
  platformModules: () => req<{ items: PlatformModule[]; summary: any }>('/platform/modules'),
  modelProviders: () => req<{ items: ModelProvider[] }>('/model-gateway/providers'),
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
}
