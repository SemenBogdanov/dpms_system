type ClientEventInput = {
  event_type: string
  message?: string
  name?: string
  stack?: string
}

const MAX_MESSAGE = 800
const MAX_STACK = 2000

function trim(value: unknown, limit: number) {
  if (typeof value !== 'string') return undefined
  return value.length > limit ? value.slice(0, limit) : value
}

function serializeError(reason: unknown): Pick<ClientEventInput, 'message' | 'name' | 'stack'> {
  if (reason instanceof Error) {
    return {
      message: trim(reason.message, MAX_MESSAGE),
      name: trim(reason.name, 120),
      stack: trim(reason.stack, MAX_STACK),
    }
  }
  if (typeof reason === 'string') {
    return { message: trim(reason, MAX_MESSAGE), name: 'StringError' }
  }
  try {
    return { message: trim(JSON.stringify(reason), MAX_MESSAGE), name: 'UnknownError' }
  } catch {
    return { message: String(reason), name: 'UnknownError' }
  }
}

export function reportClientEvent(input: ClientEventInput) {
  if (typeof window === 'undefined') return

  const payload = {
    event_type: input.event_type,
    message: trim(input.message, MAX_MESSAGE) ?? '',
    name: trim(input.name, 120),
    stack: trim(input.stack, MAX_STACK),
    route: `${window.location.pathname}${window.location.search}`,
    release: import.meta.env.VITE_RELEASE_ID ?? import.meta.env.MODE,
    user_agent: navigator.userAgent,
    viewport: `${window.innerWidth}x${window.innerHeight}@${window.devicePixelRatio || 1}`,
    occurred_at: new Date().toISOString(),
  }
  const body = JSON.stringify(payload)

  try {
    if (navigator.sendBeacon) {
      const sent = navigator.sendBeacon('/api/client-events', new Blob([body], { type: 'application/json' }))
      if (sent) return
    }
  } catch {
    // Ignore telemetry failures.
  }

  void fetch('/api/client-events', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body,
    keepalive: true,
  }).catch(() => undefined)
}

export function installClientDiagnostics() {
  if (typeof window === 'undefined') return

  window.addEventListener('error', (event) => {
    reportClientEvent({
      event_type: 'window_error',
      message: event.message,
      name: event.error?.name ?? 'WindowError',
      stack: event.error?.stack,
    })
  })

  window.addEventListener('unhandledrejection', (event) => {
    reportClientEvent({
      event_type: 'unhandled_rejection',
      ...serializeError(event.reason),
    })
  })
}
