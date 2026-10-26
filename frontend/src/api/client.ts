/**
 * API-клиент: базовый URL и fetch-обёртка.
 * Authorization: Bearer добавляется из localStorage. При 401 — logout и redirect на /login.
 */
import { getToken, clearToken } from '@/lib/auth'

const API_BASE =
  import.meta.env.VITE_API_URL ||
  (typeof window !== 'undefined' ? window.location.origin : '')

export class ApiError extends Error {
  status: number
  code: string | null

  constructor(status: number, message: string, code: string | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

function apiErrorDetails(payload: unknown, fallback: string): { message: string; code: string | null } {
  if (!payload || typeof payload !== 'object') return { message: fallback, code: null }
  const detail = (payload as { detail?: unknown }).detail
  if (typeof detail === 'string') return { message: detail, code: null }
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    const message = (detail as { message?: unknown }).message
    const code = (detail as { code?: unknown }).code
    if (typeof message === 'string') {
      return { message, code: typeof code === 'string' ? code : null }
    }
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (!item || typeof item !== 'object') return null
        const message = (item as { msg?: unknown }).msg
        const location = (item as { loc?: unknown }).loc
        const field = Array.isArray(location) ? location.slice(1).join('.') : ''
        return typeof message === 'string' ? `${field ? `${field}: ` : ''}${message}` : null
      })
      .filter(Boolean)
    if (messages.length) return { message: messages.join('; '), code: 'validation_error' }
  }
  return { message: fallback, code: null }
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
    const err = await res.json().catch(() => ({ detail: 'Требуется авторизация' }))
    const details = apiErrorDetails(err, 'Требуется авторизация')
    throw new ApiError(res.status, details.message, details.code)
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    const details = apiErrorDetails(err, res.statusText || 'Ошибка запроса')
    throw new ApiError(res.status, details.message, details.code)
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
    const err = await res.json().catch(() => ({ detail: 'Требуется авторизация' }))
    const details = apiErrorDetails(err, 'Требуется авторизация')
    throw new ApiError(res.status, details.message, details.code)
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    const details = apiErrorDetails(err, res.statusText || 'Ошибка запроса')
    throw new ApiError(res.status, details.message, details.code)
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
