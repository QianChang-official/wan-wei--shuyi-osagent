// Same-origin API client for v0.7 MemoryOps Autopilot Platform.
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

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) throw new Error(`HTTP ${res.status} on ${path}`)
  return res.json() as Promise<T>
}

export const api = {
  health: () => req<{ status: string; name: string; version: string }>('/health'),
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
  auditLogs: (limit = 20) => req<{ items: any[] }>(`/audit/logs?limit=${limit}`),
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
}
