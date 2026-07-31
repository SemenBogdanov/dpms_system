/**
 * API-клиент: базовый URL и fetch-обёртка.
 * Authorization: Bearer добавляется из localStorage. При 401 — logout и redirect на /login.
 */
import { getToken, clearToken } from '@/lib/auth'

const API_BASE =
  import.meta.env.VITE_API_URL ||
  (typeof window !== 'undefined' ? window.location.origin : '')

const GET_TIMEOUT_MS = 10_000
const WRITE_TIMEOUT_MS = 25_000
const UPLOAD_TIMEOUT_MS = 60_000
const RETRY_DELAY_MS = 350

export class ApiUnavailableError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ApiUnavailableError'
  }
}

function errorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== 'object') return fallback
  const detail = (payload as { detail?: unknown }).detail
  if (typeof detail === 'string' && detail) return detail
  if (detail && typeof detail === 'object') {
    const structured = detail as {
      message?: unknown
      readiness?: {
        issues?: Array<{ message?: unknown; guidance?: unknown }>
      }
    }
    const message = typeof structured.message === 'string' ? structured.message : ''
    const issueMessages = (structured.readiness?.issues || [])
      .map((issue) => {
        const issueMessage = typeof issue.message === 'string' ? issue.message : ''
        const guidance = typeof issue.guidance === 'string' ? issue.guidance : ''
        return [issueMessage, guidance].filter(Boolean).join(' ')
      })
      .filter(Boolean)
    const actionable = [message, ...issueMessages].filter(Boolean).join('\n')
    if (actionable) return actionable
  }
  return fallback
}

function requestMethod(options: RequestInit) {
  return (options.method || 'GET').toUpperCase()
}

function requestTimeout(options: RequestInit, jsonRequest: boolean) {
  if (!jsonRequest) return UPLOAD_TIMEOUT_MS
  return requestMethod(options) === 'GET' ? GET_TIMEOUT_MS : WRITE_TIMEOUT_MS
}

function unavailableMessage(timedOut: boolean) {
  if (typeof navigator !== 'undefined' && !navigator.onLine) {
    return 'Нет подключения к сети. Проверьте интернет и повторите попытку.'
  }
  if (timedOut) {
    return 'Сервер не ответил вовремя. Проверьте соединение и повторите попытку.'
  }
  return 'Не удалось связаться с сервером. Проверьте соединение и повторите попытку.'
}

async function fetchWithTimeout(url: string, options: RequestInit, timeoutMs: number) {
  const controller = new AbortController()
  const externalSignal = options.signal
  let timedOut = false

  const abortFromCaller = () => controller.abort()
  if (externalSignal?.aborted) {
    controller.abort()
  } else {
    externalSignal?.addEventListener('abort', abortFromCaller, { once: true })
  }

  const timeoutId = window.setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeoutMs)

  try {
    return await fetch(url, { ...options, signal: controller.signal })
  } catch (error) {
    if (externalSignal?.aborted) throw error
    if (
      timedOut ||
      error instanceof TypeError ||
      (error instanceof DOMException && error.name === 'AbortError')
    ) {
      throw new ApiUnavailableError(unavailableMessage(timedOut))
    }
    throw error
  } finally {
    window.clearTimeout(timeoutId)
    externalSignal?.removeEventListener('abort', abortFromCaller)
  }
}

async function fetchWithRetry(url: string, options: RequestInit, timeoutMs: number) {
  const attempts = requestMethod(options) === 'GET' ? 2 : 1
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await fetchWithTimeout(url, options, timeoutMs)
    } catch (error) {
      if (!(error instanceof ApiUnavailableError) || attempt === attempts) throw error
      await new Promise((resolve) => window.setTimeout(resolve, RETRY_DELAY_MS))
    }
  }
  throw new ApiUnavailableError(unavailableMessage(false))
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  jsonRequest = true
): Promise<T> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`
  const token = getToken()
  const requestOptions: RequestInit = {
    ...options,
    headers: {
      ...(jsonRequest && { 'Content-Type': 'application/json' }),
      ...(token && { Authorization: `Bearer ${token}` }),
      ...options.headers,
    },
  }
  const res = await fetchWithRetry(url, requestOptions, requestTimeout(options, jsonRequest))
  if (res.status === 401) {
    clearToken()
    if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
      window.location.href = '/login'
    }
    const err: unknown = await res.json().catch(() => null)
    throw new Error(errorMessage(err, 'Требуется авторизация'))
  }
  if (!res.ok) {
    const err: unknown = await res.json().catch(() => null)
    throw new Error(errorMessage(err, res.statusText || 'Ошибка запроса'))
  }
  const text = await res.text()
  return (text ? JSON.parse(text) : null) as T
}

async function requestBlob(path: string): Promise<Blob> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`
  const token = getToken()
  const res = await fetchWithRetry(url, {
    headers: {
      ...(token && { Authorization: `Bearer ${token}` }),
    },
  }, UPLOAD_TIMEOUT_MS)
  if (res.status === 401) {
    clearToken()
    if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
      window.location.href = '/login'
    }
    const err: unknown = await res.json().catch(() => null)
    throw new Error(errorMessage(err, 'Требуется авторизация'))
  }
  if (!res.ok) {
    const err: unknown = await res.json().catch(() => null)
    throw new Error(errorMessage(err, res.statusText || 'Ошибка запроса'))
  }
  return res.blob()
}

export const api = {
  get: <T>(path: string, params?: Record<string, string>) => {
    const url = params && Object.keys(params).length
      ? `${path}?${new URLSearchParams(params).toString()}`
      : path
    return request<T>(url)
  },
  post: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'POST', body: JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'PUT', body: JSON.stringify(body) }),
  upload: <T>(path: string, body: FormData) =>
    request<T>(path, { method: 'POST', body }, false),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
  delete: <T>(path: string) =>
    request<T>(path, { method: 'DELETE' }),
  blob: (path: string) => requestBlob(path),
}
