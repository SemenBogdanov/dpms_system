import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, Loader2, RefreshCw } from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'
import { ApiError, ApiUnavailableError } from '@/api/client'
import { graphsApi, type GraphDocument, type GraphPayload } from '@/api/graphs'

type FrameState = 'loading' | 'ready' | 'error'

const LOAD_TIMEOUT_MS = 12_000
const HOST_READY_MESSAGE = 'dpms-graphs-host-ready'
const WORKSPACE_READY_MESSAGE = 'dpms-graphs-workspace-ready'
const STORAGE_REQUEST_MESSAGE = 'dpms-graphs-storage-request'
const STORAGE_RESPONSE_MESSAGE = 'dpms-graphs-storage-response'

type StorageOperation = 'list' | 'get' | 'put' | 'delete'

type StorageRequest = {
  type: typeof STORAGE_REQUEST_MESSAGE
  version: 1
  requestId: string
  operation: StorageOperation
  clientId?: string
  baseRevision?: number | null
  payload?: GraphPayload
}

function isStorageRequest(value: unknown): value is StorageRequest {
  if (!value || typeof value !== 'object') return false
  const request = value as Partial<StorageRequest>
  return request.type === STORAGE_REQUEST_MESSAGE
    && request.version === 1
    && typeof request.requestId === 'string'
    && ['list', 'get', 'put', 'delete'].includes(request.operation || '')
}

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
    const sendToWorkspace = (message: object) => {
      frameRef.current?.contentWindow?.postMessage(message, window.location.origin)
    }

    const handleMessage = async (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return
      if (event.source !== frameRef.current?.contentWindow) return
      if (event.data?.type === WORKSPACE_READY_MESSAGE && event.data?.version === 1) {
        setFrameState('ready')
        return
      }
      if (!isStorageRequest(event.data)) return

      const request = event.data
      try {
        let data: unknown
        if (request.operation === 'list') {
          data = await graphsApi.list()
        } else if (request.operation === 'get' && request.clientId) {
          data = await graphsApi.get(request.clientId)
        } else if (request.operation === 'put' && request.clientId && request.payload) {
          data = await graphsApi.put(
            request.clientId,
            typeof request.baseRevision === 'number' ? request.baseRevision : null,
            request.payload
          )
        } else if (
          request.operation === 'delete'
          && request.clientId
          && typeof request.baseRevision === 'number'
        ) {
          data = await graphsApi.delete(request.clientId, request.baseRevision)
        } else {
          throw new Error('Некорректный запрос хранилища графов')
        }
        sendToWorkspace({
          type: STORAGE_RESPONSE_MESSAGE,
          version: 1,
          requestId: request.requestId,
          ok: true,
          data,
        })
      } catch (error) {
        let serverDocument: GraphDocument | null = null
        if (error instanceof ApiError && error.status === 409 && request.clientId) {
          serverDocument = await graphsApi.get(request.clientId).catch(() => null)
        }
        sendToWorkspace({
          type: STORAGE_RESPONSE_MESSAGE,
          version: 1,
          requestId: request.requestId,
          ok: false,
          error: {
            status: error instanceof ApiError ? error.status : 0,
            code: error instanceof ApiError
              ? error.code || 'api_error'
              : error instanceof ApiUnavailableError
                ? 'network_unavailable'
                : 'storage_error',
            message: error instanceof Error ? error.message : 'Не удалось выполнить операцию',
            serverDocument,
          },
        })
      }
    }

    window.addEventListener('message', handleMessage)
    return () => window.removeEventListener('message', handleMessage)
  }, [revision])

  const handleLoad = () => {
    frameRef.current?.contentWindow?.postMessage(
      { type: HOST_READY_MESSAGE, version: 1 },
      window.location.origin
    )
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
