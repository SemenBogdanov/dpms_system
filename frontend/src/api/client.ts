/**
 * API-клиент: базовый URL и fetch-обёртка.
 * Authorization: Bearer добавляется из localStorage. При 401 — logout и redirect на /login.
 */
import { getToken, clearToken } from '@/lib/auth'

const API_BASE =
  import.meta.env.VITE_API_URL ||
  (typeof window !== 'undefined' ? window.location.origin : '')

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

async function request<T>(
  path: string,
  options: RequestInit = {},
  jsonRequest = true
): Promise<T> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`
  const token = getToken()
  const res = await fetch(url, {
    ...options,
    headers: {
      ...(jsonRequest && { 'Content-Type': 'application/json' }),
      ...(token && { Authorization: `Bearer ${token}` }),
      ...options.headers,
    },
  })
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
  const res = await fetch(url, {
    headers: {
      ...(token && { Authorization: `Bearer ${token}` }),
    },
  })
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
