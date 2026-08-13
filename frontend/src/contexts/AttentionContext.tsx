import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { api } from '@/api/client'
import type { AttentionSummary } from '@/api/types'
import { getToken } from '@/lib/auth'
import { AttentionContext } from '@/contexts/attentionState'

const emptySummary: AttentionSummary = { direct_count: 0, important_count: 0 }

const POLL_MS = 30_000
const HEARTBEAT_MS = 25_000
const MAX_BACKOFF_MS = 30_000
const REFRESH_EVENT = 'dpms:attention-refresh'

function messagesWsUrl(): string {
  const apiBase =
    import.meta.env.VITE_API_URL ||
    (typeof window !== 'undefined' ? window.location.origin : '')
  return `${apiBase.replace(/^http/i, 'ws')}/api/messages/live`
}

export function AttentionProvider({ children }: { children: ReactNode }) {
  const [summary, setSummary] = useState<AttentionSummary>(emptySummary)
  const [loading, setLoading] = useState(true)
  const [stale, setStale] = useState(false)
  const [revision, setRevision] = useState(0)
  const inFlight = useRef<Promise<void> | null>(null)

  const refresh = useCallback(async () => {
    if (inFlight.current) return inFlight.current
    const operation = api.get<AttentionSummary>('/api/messages/summary').then(
      (next) => {
        setSummary(next)
        setStale(false)
      },
      () => {
        // Preserve the last confirmed counts when the network is unavailable.
        setStale(true)
      },
    ).finally(() => {
      inFlight.current = null
      setLoading(false)
    })
    inFlight.current = operation
    return operation
  }, [])

  useEffect(() => {
    void refresh()
    const interval = window.setInterval(() => void refresh(), POLL_MS)
    const handleRefresh = () => void refresh()
    const handleVisible = () => {
      if (document.visibilityState === 'visible') void refresh()
    }
    window.addEventListener('focus', handleRefresh)
    window.addEventListener('online', handleRefresh)
    window.addEventListener(REFRESH_EVENT, handleRefresh)
    document.addEventListener('visibilitychange', handleVisible)
    return () => {
      window.clearInterval(interval)
      window.removeEventListener('focus', handleRefresh)
      window.removeEventListener('online', handleRefresh)
      window.removeEventListener(REFRESH_EVENT, handleRefresh)
      document.removeEventListener('visibilitychange', handleVisible)
    }
  }, [refresh])

  useEffect(() => {
    let stopped = false
    let socket: WebSocket | null = null
    let reconnectTimer: number | null = null
    let heartbeatTimer: number | null = null
    let backoff = 1_000

    const clearTimers = () => {
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer)
      if (heartbeatTimer !== null) window.clearInterval(heartbeatTimer)
      reconnectTimer = null
      heartbeatTimer = null
    }

    const scheduleReconnect = () => {
      if (stopped || reconnectTimer !== null) return
      const delay = backoff
      backoff = Math.min(backoff * 2, MAX_BACKOFF_MS)
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null
        connect()
      }, delay)
    }

    const connect = () => {
      if (stopped || !navigator.onLine) return
      const token = getToken()
      if (!token) return
      try {
        socket = new WebSocket(messagesWsUrl())
      } catch {
        scheduleReconnect()
        return
      }
      socket.onopen = () => {
        backoff = 1_000
        socket?.send(JSON.stringify({ type: 'auth', token }))
        heartbeatTimer = window.setInterval(() => {
          if (socket?.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: 'ping' }))
          }
        }, HEARTBEAT_MS)
      }
      socket.onmessage = (message) => {
        try {
          const event = JSON.parse(message.data as string) as { type?: string }
          if (!event.type || event.type === 'pong') return
          void refresh()
          if (event.type !== 'ready') setRevision((value) => value + 1)
        } catch {
          // Ignore malformed transport frames; REST remains authoritative.
        }
      }
      socket.onerror = () => socket?.close()
      socket.onclose = (event) => {
        if (heartbeatTimer !== null) window.clearInterval(heartbeatTimer)
        heartbeatTimer = null
        socket = null
        if (!stopped && event.code !== 1008) scheduleReconnect()
      }
    }

    const handleOnline = () => {
      if (!socket || socket.readyState === WebSocket.CLOSED) connect()
    }
    connect()
    window.addEventListener('online', handleOnline)
    return () => {
      stopped = true
      clearTimers()
      window.removeEventListener('online', handleOnline)
      socket?.close()
    }
  }, [refresh])

  return (
    <AttentionContext.Provider value={{ summary, loading, stale, revision, refresh }}>
      {children}
    </AttentionContext.Provider>
  )
}
