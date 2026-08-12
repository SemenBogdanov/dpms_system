/** Realtime channel with reconnect and REST-resync fallback for quick notes. */
import { useEffect, useRef, useState } from 'react'
import { getToken } from '@/lib/auth'

export type LiveStatus = 'idle' | 'connecting' | 'live' | 'reconnecting' | 'offline'

export interface QuickNoteLiveEvent {
  type: string
  note_id: string
  active_users?: number
  revision?: number
  [key: string]: unknown
}

export interface QuickNoteLiveHandlers {
  /** Coalesced resync — вызывается один раз на пачку событий (not on ready). */
  onResync?: (event: QuickNoteLiveEvent) => void
  /** Сразу после ready — полная resync деталей. */
  onReady?: (event: QuickNoteLiveEvent) => void
  onDeleted?: (event: QuickNoteLiveEvent) => void
  onRevoked?: (event: QuickNoteLiveEvent) => void
}

export interface QuickNoteLiveResult {
  status: LiveStatus
  activeUsers: number
  /** Принудительный полный resync (иммитация ready). */
  sync: () => void
}

const MIN_BACKOFF_MS = 1000
const MAX_BACKOFF_MS = 30_000
const RESYNC_COALESCE_MS = 250
const FALLBACK_SYNC_MS = 15_000
const HEARTBEAT_MS = 25_000

function wsUrlFor(noteId: string): string {
  const apiBase =
    import.meta.env.VITE_API_URL ||
    (typeof window !== 'undefined' ? window.location.origin : '')
  const base = (apiBase || (typeof window !== 'undefined' ? window.location.origin : '')).replace(/^http/i, 'ws')
  return `${base}/api/quick-notes/${noteId}/live`
}

export function useQuickNoteLive(
  noteId: string | null | undefined,
  handlers: QuickNoteLiveHandlers,
): QuickNoteLiveResult {
  const noteIdKey = noteId ?? null
  const handlersRef = useRef(handlers)
  handlersRef.current = handlers

  const [status, setStatus] = useState<LiveStatus>('idle')
  const [activeUsers, setActiveUsers] = useState(0)

  const wsRef = useRef<WebSocket | null>(null)
  const backoffRef = useRef<number>(MIN_BACKOFF_MS)
  const reconnectTimer = useRef<number | null>(null)
  const heartbeatTimer = useRef<number | null>(null)
  const resyncTimer = useRef<number | null>(null)
  const lastResyncEvent = useRef<QuickNoteLiveEvent | null>(null)
  const manualSyncRef = useRef<(() => void) | null>(null)
  const wasLiveRef = useRef(false)

  const clearResyncTimer = () => {
    if (resyncTimer.current !== null) {
      window.clearTimeout(resyncTimer.current)
      resyncTimer.current = null
    }
  }

  const clearReconnectTimer = () => {
    if (reconnectTimer.current !== null) {
      window.clearTimeout(reconnectTimer.current)
      reconnectTimer.current = null
    }
  }

  const clearHeartbeat = () => {
    if (heartbeatTimer.current !== null) {
      window.clearInterval(heartbeatTimer.current)
      heartbeatTimer.current = null
    }
  }

  const flushResync = () => {
    clearResyncTimer()
    const event = lastResyncEvent.current
    lastResyncEvent.current = null
    if (event) handlersRef.current.onResync?.(event)
  }

  const scheduleResync = (event: QuickNoteLiveEvent) => {
    lastResyncEvent.current = event
    clearResyncTimer()
    resyncTimer.current = window.setTimeout(flushResync, RESYNC_COALESCE_MS)
  }

  useEffect(() => {
    if (!noteIdKey) {
      setStatus('idle')
      setActiveUsers(0)
      return
    }
    let closed = false

    const resetBackoff = () => {
      backoffRef.current = MIN_BACKOFF_MS
    }

    const scheduleReconnect = () => {
      clearReconnectTimer()
      const delay = Math.min(backoffRef.current, MAX_BACKOFF_MS)
      backoffRef.current = Math.min(backoffRef.current * 2, MAX_BACKOFF_MS)
      reconnectTimer.current = window.setTimeout(() => {
        if (!closed) connect()
      }, delay)
    }

    const connect = () => {
      if (closed) return
      const token = getToken()
      if (!token) {
        setStatus('offline')
        return
      }

      let socket: WebSocket
      try {
        socket = new WebSocket(wsUrlFor(noteIdKey))
      } catch {
        scheduleReconnect()
        setStatus(wasLiveRef.current ? 'reconnecting' : 'connecting')
        return
      }
      wsRef.current = socket
      setStatus(wasLiveRef.current ? 'reconnecting' : 'connecting')

      socket.onopen = () => {
        if (closed) {
          try { socket.close() } catch { /* ignore */ }
          return
        }
        resetBackoff()
        try {
          socket.send(JSON.stringify({ type: 'auth', token }))
          clearHeartbeat()
          heartbeatTimer.current = window.setInterval(() => {
            if (socket.readyState === WebSocket.OPEN) {
              socket.send(JSON.stringify({ type: 'ping' }))
            }
          }, HEARTBEAT_MS)
        } catch {
          try { socket.close() } catch { /* ignore */ }
        }
      }

      socket.onmessage = (message) => {
        if (closed) return
        let event: QuickNoteLiveEvent
        try {
          const parsed = JSON.parse(message.data as string) as QuickNoteLiveEvent
          if (!parsed || typeof parsed.type !== 'string') return
          event = parsed
        } catch {
          return
        }

        if (event.type === 'ready' || event.type === 'presence') {
          if (typeof event.active_users === 'number') {
            setActiveUsers(event.active_users)
          }
        }

        if (event.type === 'ready') {
          wasLiveRef.current = true
          setStatus('live')
          resetBackoff()
          flushResync()
          handlersRef.current.onReady?.(event)
          return
        }
        if (event.type === 'presence') {
          setStatus((current) => (current === 'live' ? 'live' : current))
          return
        }
        if (event.type === 'note.deleted') {
          flushResync()
          handlersRef.current.onDeleted?.(event)
          return
        }
        if (event.type === 'access.revoked') {
          flushResync()
          setStatus('offline')
          handlersRef.current.onRevoked?.(event)
          return
        }
        if (event.type === 'access.changed') {
          flushResync()
          scheduleResync(event)
          return
        }
        if (event.type === 'note.updated' || event.type === 'comment.created' || event.type === 'attachment.created') {
          scheduleResync(event)
        }
      }

      const handleClose = (event?: CloseEvent) => {
        if (closed) return
        clearHeartbeat()
        wsRef.current = null
        if (event?.code === 1008) {
          setStatus('offline')
          handlersRef.current.onReady?.({ type: 'ready', note_id: noteIdKey })
          return
        }
        if (typeof navigator !== 'undefined' && !navigator.onLine) {
          setStatus('offline')
          return
        }
        setStatus('reconnecting')
        scheduleReconnect()
      }

      socket.onclose = handleClose
      socket.onerror = () => {
        try { socket.close() } catch { /* ignore */ }
      }
    }

    setStatus('connecting')
    connect()
    manualSyncRef.current = () => {
      flushResync()
      handlersRef.current.onReady?.({ type: 'ready', note_id: noteIdKey })
    }

    const handleOnline = () => {
      if (closed) return
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return
      clearReconnectTimer()
      backoffRef.current = MIN_BACKOFF_MS
      connect()
    }
    const handleVisible = () => {
      if (document.visibilityState === 'visible') handleOnline()
    }
    const handleOffline = () => {
      clearReconnectTimer()
      setStatus('offline')
      wsRef.current?.close()
    }
    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)
    window.addEventListener('focus', handleOnline)
    document.addEventListener('visibilitychange', handleVisible)

    return () => {
      closed = true
      wasLiveRef.current = false
      clearReconnectTimer()
      clearHeartbeat()
      clearResyncTimer()
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
      window.removeEventListener('focus', handleOnline)
      document.removeEventListener('visibilitychange', handleVisible)
      const socket = wsRef.current
      wsRef.current = null
      if (socket) {
        socket.onclose = null
        socket.onmessage = null
        socket.onopen = null
        socket.onerror = null
        try { socket.close() } catch { /* ignore */ }
      }
      setStatus('idle')
      setActiveUsers(0)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [noteIdKey])

  useEffect(() => {
    if (!noteIdKey || status === 'live' || status === 'idle') return
    const timer = window.setInterval(() => {
      handlersRef.current.onReady?.({ type: 'ready', note_id: noteIdKey })
    }, FALLBACK_SYNC_MS)
    return () => window.clearInterval(timer)
  }, [noteIdKey, status])

  const sync = () => {
    manualSyncRef.current?.()
  }

  return { status, activeUsers, sync }
}
