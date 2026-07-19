// 万枢协作平台 API 薄封装（base: /platform）。
// client.ts 未导出其内部通用 req，故按其模式新写：
// 同样的 JSON 头 + X-API-Key 鉴权。密钥状态独立维护，
// 通过 setPlatformApiKey 注入（与 client.setApiKey 同源调用即可）。
// 所有请求默认 30s 超时（AbortController），可用可选参数覆盖（09-#13）。

function _loadApiKey(): string {
  if (import.meta.env.DEV) {
    return import.meta.env.VITE_WANWEI_DEV_API_KEY || ''
  }
  // 桌面端 preload 会把密钥写入 localStorage，生产/打包构建时优先读取
  try {
    return localStorage.getItem('wanwei-desktop-api-key') || ''
  } catch {
    return ''
  }
}

let apiKey = _loadApiKey()

export function setPlatformApiKey(value: string): void {
  apiKey = value.trim()
}

export class PlatformApiError extends Error {
  status: number
  detail?: string
  /** true 表示请求因超时而被中止（此时无 HTTP 响应，status 恒为 0） */
  timeout: boolean
  constructor(status: number, message: string, detail?: string, timeout = false) {
    super(message)
    this.status = status
    this.detail = detail
    this.timeout = timeout
  }
}

export function isAuthError(err: unknown): err is PlatformApiError {
  return err instanceof PlatformApiError && (err.status === 401 || err.status === 403)
}

export function isNetworkError(err: unknown): boolean {
  return err instanceof TypeError || (err instanceof Error && /fetch|network/i.test(err.message))
}

export function isTimeoutError(err: unknown): err is PlatformApiError {
  return err instanceof PlatformApiError && err.timeout
}

/** 请求可选参数（向后兼容：全部可选，缺省行为与旧版一致 + 30s 超时） */
export interface ReqOptions {
  /** 超时毫秒数，默认 30000；传 0 表示不设置超时 */
  timeoutMs?: number
  /** 调用方自带的中止信号，与超时并存，先触发者生效 */
  signal?: AbortSignal
}

export const DEFAULT_TIMEOUT_MS = 30_000

async function req<T>(path: string, init?: RequestInit, options?: ReqOptions): Promise<T> {
  const headers = new Headers(init?.headers)
  headers.set('Content-Type', 'application/json')
  if (apiKey) headers.set('X-API-Key', apiKey)

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

  let res: Response
  try {
    res = await fetch(`/platform${path}`, {
      ...init,
      headers,
      signal: controller.signal,
    })
  } catch (err) {
    if (controller.signal.aborted && controller.signal.reason === 'timeout') {
      throw new PlatformApiError(
        0,
        `请求超时（${Math.round(timeoutMs / 1000)}s）：/platform${path}`,
        undefined,
        true,
      )
    }
    throw err
  } finally {
    if (timer !== undefined) clearTimeout(timer)
    if (callerSignal) callerSignal.removeEventListener('abort', onCallerAbort)
  }

  if (!res.ok) {
    let detail: string | undefined
    try {
      const body = await res.json()
      if (body && typeof body.detail === 'string') detail = body.detail
    } catch {
      // ignore parse failure
    }
    const message = detail ? `HTTP ${res.status}: ${detail}` : `HTTP ${res.status} on /platform${path}`
    throw new PlatformApiError(res.status, message, detail)
  }
  return res.json() as Promise<T>
}

export function apiGet<T>(path: string, options?: ReqOptions): Promise<T> {
  return req<T>(path, undefined, options)
}

export function apiPost<T>(path: string, body?: unknown, options?: ReqOptions): Promise<T> {
  return req<T>(path, { method: 'POST', body: JSON.stringify(body ?? {}) }, options)
}

export function apiPut<T>(path: string, body?: unknown, options?: ReqOptions): Promise<T> {
  return req<T>(path, { method: 'PUT', body: JSON.stringify(body ?? {}) }, options)
}

export function apiDel<T>(path: string, options?: ReqOptions): Promise<T> {
  return req<T>(path, { method: 'DELETE' }, options)
}
