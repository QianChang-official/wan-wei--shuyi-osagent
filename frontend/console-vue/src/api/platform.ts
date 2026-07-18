// 万枢协作平台 API 薄封装（base: /platform）。
// client.ts 未导出其内部通用 req，故按其模式新写：
// 同样的 JSON 头 + X-API-Key 鉴权。密钥状态独立维护，
// 通过 setPlatformApiKey 注入（与 client.setApiKey 同源调用即可）。

let apiKey = import.meta.env.DEV ? import.meta.env.VITE_WANWEI_DEV_API_KEY : ''

export function setPlatformApiKey(value: string): void {
  apiKey = value.trim()
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  headers.set('Content-Type', 'application/json')
  if (apiKey) headers.set('X-API-Key', apiKey)

  const res = await fetch(`/platform${path}`, {
    ...init,
    headers,
  })
  if (!res.ok) throw new Error(`HTTP ${res.status} on /platform${path}`)
  return res.json() as Promise<T>
}

export function apiGet<T>(path: string): Promise<T> {
  return req<T>(path)
}

export function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return req<T>(path, { method: 'POST', body: JSON.stringify(body ?? {}) })
}

export function apiPut<T>(path: string, body?: unknown): Promise<T> {
  return req<T>(path, { method: 'PUT', body: JSON.stringify(body ?? {}) })
}

export function apiDel<T>(path: string): Promise<T> {
  return req<T>(path, { method: 'DELETE' })
}
