// Same-origin API client for v0.6 MemoryOps Runtime.
// In dev, Vite proxies /memory,/health,/audit to the FastAPI backend.
// In prod, the built dist is mounted under /console on the same FastAPI server.

export interface ApiState { online: boolean; version: string; name: string }

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
}
