import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, Loader2, RefreshCw } from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'

type FrameState = 'loading' | 'ready' | 'error'

const LOAD_TIMEOUT_MS = 12_000
const HOST_READY_MESSAGE = 'dpms-graphs-host-ready'
const WORKSPACE_READY_MESSAGE = 'dpms-graphs-workspace-ready'

export function GraphsPage() {
  const { user } = useAuth()
  const frameRef = useRef<HTMLIFrameElement>(null)
  const [frameState, setFrameState] = useState<FrameState>('loading')
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    if (frameState !== 'loading') return
    const timeout = window.setTimeout(() => setFrameState('error'), LOAD_TIMEOUT_MS)
    return () => window.clearTimeout(timeout)
  }, [frameState, revision])

  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      if (event.source !== frameRef.current?.contentWindow) return
      if (event.data?.type !== WORKSPACE_READY_MESSAGE || event.data?.version !== 1) return
      setFrameState('ready')
    }

    window.addEventListener('message', handleMessage)
    return () => window.removeEventListener('message', handleMessage)
  }, [revision])

  const handleLoad = () => {
    frameRef.current?.contentWindow?.postMessage({ type: HOST_READY_MESSAGE, version: 1 }, '*')
  }

  const reload = () => {
    setFrameState('loading')
    setRevision((current) => current + 1)
  }

  return (
    <section className="absolute inset-0 grid grid-rows-[minmax(0,1fr)_calc(64px+env(safe-area-inset-bottom))] bg-background lg:block">
      <div className="relative h-full min-h-0 overflow-hidden bg-background">
        <iframe
          key={revision}
          ref={frameRef}
          title="Рабочее пространство графов"
          src={`/graph-workspace/index.html?embedded=1&owner=${encodeURIComponent(user?.id || 'unknown')}&revision=${revision}`}
          className="h-full w-full border-0 bg-background"
          referrerPolicy="same-origin"
          onLoad={handleLoad}
          onError={() => setFrameState('error')}
        />

        {frameState === 'loading' && (
          <div className="absolute inset-0 grid place-items-center bg-background" role="status" aria-live="polite">
            <div className="flex items-center gap-3 text-sm text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin" aria-hidden="true" />
              <span>Открываем графы…</span>
            </div>
          </div>
        )}

        {frameState === 'error' && (
          <div className="absolute inset-0 grid place-items-center bg-background px-5">
            <div className="max-w-sm text-center">
              <AlertTriangle className="mx-auto h-7 w-7 text-amber-600" aria-hidden="true" />
              <h1 className="mt-3 text-base font-semibold text-foreground">Не удалось открыть графы</h1>
              <p className="mt-1 text-sm text-muted-foreground">
                Рабочее пространство не загрузилось. Повторите попытку без перезагрузки всей системы.
              </p>
              <button
                type="button"
                onClick={reload}
                className="mt-4 inline-flex min-h-11 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
              >
                <RefreshCw className="h-4 w-4" aria-hidden="true" />
                Открыть повторно
              </button>
            </div>
          </div>
        )}
      </div>
      <div className="lg:hidden" aria-hidden="true" />
    </section>
  )
}
