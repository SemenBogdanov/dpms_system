import { useCallback, useEffect, useState } from 'react'
import { Check, Database, RefreshCcw, X } from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '@/api/client'
import type { AdminStorageQuotaRequest } from '@/api/types'
import { useAuth } from '@/contexts/AuthContext'


const MIB = 1024 * 1024

function formatMiB(bytes: number) {
  return `${(bytes / MIB).toFixed(1)} МиБ`
}

type DecisionDraft = {
  approvedMiB: string
  comment: string
  error: string | null
}

export function AdminStorageQuotaRequestsPanel() {
  const { user } = useAuth()
  const [requests, setRequests] = useState<AdminStorageQuotaRequest[]>([])
  const [drafts, setDrafts] = useState<Record<string, DecisionDraft>>({})
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (user?.role !== 'admin') return
    setLoading(true)
    setLoadError(null)
    try {
      const data = await api.get<AdminStorageQuotaRequest[]>('/api/storage-quota/admin/requests', { status: 'pending' })
      setRequests(data)
      setDrafts((current) => Object.fromEntries(data.map((request) => [
        request.id,
        current[request.id] ?? {
          approvedMiB: String(Math.round(request.requested_limit_bytes / MIB)),
          comment: '',
          error: null,
        },
      ])))
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : 'Не удалось загрузить заявки')
    } finally {
      setLoading(false)
    }
  }, [user?.role])

  useEffect(() => {
    void load()
  }, [load])

  if (user?.role !== 'admin') return null

  const updateDraft = (requestId: string, patch: Partial<DecisionDraft>) => {
    setDrafts((current) => ({
      ...current,
      [requestId]: { ...current[requestId], ...patch },
    }))
  }

  const decide = async (request: AdminStorageQuotaRequest, decision: 'approved' | 'rejected') => {
    const draft = drafts[request.id]
    if (!draft || draft.comment.trim().length < 3) {
      updateDraft(request.id, { error: 'Для решения нужен комментарий минимум в 3 символа' })
      return
    }
    const approvedLimitBytes = Math.round(Number(draft.approvedMiB) * MIB)
    if (
      decision === 'approved'
      && (!Number.isFinite(approvedLimitBytes)
        || approvedLimitBytes <= request.current_limit_bytes
        || approvedLimitBytes > request.requested_limit_bytes)
    ) {
      updateDraft(request.id, { error: 'Лимит должен быть выше текущего и не больше запрошенного' })
      return
    }
    setBusyId(request.id)
    updateDraft(request.id, { error: null })
    try {
      await api.post(`/api/storage-quota/admin/requests/${request.id}/decision`, {
        decision,
        comment: draft.comment.trim(),
        approved_limit_bytes: decision === 'approved' ? approvedLimitBytes : null,
      })
      setRequests((current) => current.filter((item) => item.id !== request.id))
      toast.success(decision === 'approved' ? 'Лимит увеличен' : 'Заявка отклонена')
    } catch (error) {
      updateDraft(request.id, { error: error instanceof Error ? error.message : 'Не удалось сохранить решение' })
      if (error instanceof Error && /уже обработал|зафиксировано|409/i.test(error.message)) {
        await load()
      }
    } finally {
      setBusyId(null)
    }
  }

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-600">
            <Database className="h-5 w-5" />
          </span>
          <div>
            <h2 className="font-medium text-slate-900">Заявки на хранилище</h2>
            <p className="mt-1 text-sm text-slate-500">Увеличение личного лимита фиксируется вместе с решением администратора.</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">{requests.length}</span>
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50"
          >
            <RefreshCcw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            Обновить
          </button>
        </div>
      </div>

      {loadError && (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700" role="alert">
          <span>{loadError}</span>
          <button type="button" onClick={() => void load()} className="min-h-11 font-medium underline">Повторить</button>
        </div>
      )}
      {!loadError && loading && requests.length === 0 && <p className="mt-4 text-sm text-slate-500">Загрузка...</p>}
      {!loading && !loadError && requests.length === 0 && (
        <p className="mt-4 rounded-lg border border-dashed border-slate-300 p-4 text-sm text-slate-500">Новых заявок нет.</p>
      )}
      <div className="mt-4 grid gap-3 xl:grid-cols-2">
        {requests.map((request) => {
          const draft = drafts[request.id] ?? { approvedMiB: '', comment: '', error: null }
          return (
            <article key={request.id} className="rounded-lg border border-slate-200 p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <h3 className="truncate font-medium text-slate-900">{request.user_name}</h3>
                  <p className="truncate text-xs text-slate-500">{request.user_email}</p>
                </div>
                <time className="text-xs text-slate-400" dateTime={request.created_at}>
                  {new Date(request.created_at).toLocaleString('ru-RU')}
                </time>
              </div>
              <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
                <div className="rounded-md bg-slate-50 p-2"><span className="block text-slate-400">Занято</span><strong>{formatMiB(request.used_bytes + request.reserved_bytes)}</strong></div>
                <div className="rounded-md bg-slate-50 p-2"><span className="block text-slate-400">Сейчас</span><strong>{formatMiB(request.current_limit_bytes)}</strong></div>
                <div className="rounded-md bg-sky-50 p-2 text-sky-800"><span className="block text-sky-500">Запрошено</span><strong>{formatMiB(request.requested_limit_bytes)}</strong></div>
              </div>
              <p className="mt-3 whitespace-pre-wrap text-sm text-slate-600">{request.reason}</p>
              <div className="mt-4 grid gap-3 sm:grid-cols-[150px_minmax(0,1fr)]">
                <label className="text-xs font-medium text-slate-600">
                  Одобрить, МиБ
                  <input
                    type="number"
                    min={Math.floor(request.current_limit_bytes / MIB) + 1}
                    max={Math.floor(request.requested_limit_bytes / MIB)}
                    value={draft.approvedMiB}
                    onChange={(event) => updateDraft(request.id, { approvedMiB: event.target.value, error: null })}
                    className="mt-1 min-h-11 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                  />
                </label>
                <label className="text-xs font-medium text-slate-600">
                  Комментарий к решению
                  <input
                    type="text"
                    maxLength={1000}
                    value={draft.comment}
                    onChange={(event) => updateDraft(request.id, { comment: event.target.value, error: null })}
                    className="mt-1 min-h-11 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                    placeholder="Почему лимит изменен или отклонен"
                  />
                </label>
              </div>
              {draft.error && <p className="mt-2 text-sm text-red-600" role="alert">{draft.error}</p>}
              <div className="mt-4 flex flex-wrap justify-end gap-2">
                <button
                  type="button"
                  onClick={() => void decide(request, 'rejected')}
                  disabled={busyId === request.id}
                  className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                >
                  <X className="h-4 w-4" />
                  Отклонить
                </button>
                <button
                  type="button"
                  onClick={() => void decide(request, 'approved')}
                  disabled={busyId === request.id}
                  className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
                >
                  <Check className="h-4 w-4" />
                  Одобрить
                </button>
              </div>
            </article>
          )
        })}
      </div>
    </section>
  )
}
