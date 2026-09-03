import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, HardDrive, RefreshCcw, Send, X } from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '@/api/client'
import type { StorageQuotaRequest, StorageQuotaSummary } from '@/api/types'
import { cn } from '@/lib/utils'


const MIB = 1024 * 1024
const WARNING_LEVELS = new Set(['normal', 'warning', 'critical', 'blocked'])

function isStorageQuotaSummary(value: unknown): value is StorageQuotaSummary {
  if (!value || typeof value !== 'object') return false
  const summary = value as Partial<StorageQuotaSummary>
  const pending = summary.pending_request
  return (
    typeof summary.quota_bytes === 'number'
    && typeof summary.used_bytes === 'number'
    && typeof summary.reserved_bytes === 'number'
    && typeof summary.available_bytes === 'number'
    && typeof summary.usage_percent === 'number'
    && typeof summary.warning_level === 'string'
    && WARNING_LEVELS.has(summary.warning_level)
    && typeof summary.warning_message === 'string'
    && (
      pending === null
      || (
        typeof pending === 'object'
        && typeof pending.id === 'string'
        && typeof pending.requested_limit_bytes === 'number'
        && typeof pending.reason === 'string'
      )
    )
  )
}

function formatBytes(value: number) {
  if (value < MIB) return `${(value / 1024).toFixed(value < 1024 ? 0 : 1)} КиБ`
  return `${(value / MIB).toFixed(1)} МиБ`
}

const warningClasses: Record<StorageQuotaSummary['warning_level'], string> = {
  normal: 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-200',
  warning: 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200',
  critical: 'border-orange-200 bg-orange-50 text-orange-800 dark:border-orange-900 dark:bg-orange-950/30 dark:text-orange-200',
  blocked: 'border-red-200 bg-red-50 text-red-800 dark:border-red-900 dark:bg-red-950/30 dark:text-red-200',
}

const barClasses: Record<StorageQuotaSummary['warning_level'], string> = {
  normal: 'bg-emerald-500',
  warning: 'bg-amber-500',
  critical: 'bg-orange-500',
  blocked: 'bg-red-500',
}

export function StorageQuotaSettingsPanel() {
  const [summary, setSummary] = useState<StorageQuotaSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [requestedMiB, setRequestedMiB] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const data = await api.get<unknown>('/api/storage-quota/me')
      if (!isStorageQuotaSummary(data)) {
        throw new Error('Сервер вернул некорректное состояние хранилища')
      }
      setSummary(data)
      setRequestedMiB((current) => current || String(Math.ceil(data.quota_bytes / MIB) + 50))
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : 'Не удалось загрузить состояние хранилища')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const requestedBytes = useMemo(() => {
    const value = Number(requestedMiB)
    return Number.isFinite(value) ? Math.round(value * MIB) : 0
  }, [requestedMiB])

  const submitRequest = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!summary) return
    if (requestedBytes <= summary.quota_bytes) {
      setFormError('Новый общий лимит должен быть больше текущего')
      return
    }
    if (reason.trim().length < 10) {
      setFormError('Кратко опишите причину минимум в 10 символах')
      return
    }
    setBusy(true)
    setFormError(null)
    try {
      await api.post<StorageQuotaRequest>('/api/storage-quota/me/requests', {
        requested_limit_bytes: requestedBytes,
        reason: reason.trim(),
      })
      setReason('')
      toast.success('Заявка отправлена администратору')
      await load()
    } catch (error) {
      setFormError(error instanceof Error ? error.message : 'Не удалось отправить заявку')
    } finally {
      setBusy(false)
    }
  }

  const cancelRequest = async () => {
    if (!summary?.pending_request) return
    setBusy(true)
    setFormError(null)
    try {
      await api.delete(`/api/storage-quota/me/requests/${summary.pending_request.id}`)
      toast.success('Заявка отменена')
      await load()
    } catch (error) {
      setFormError(error instanceof Error ? error.message : 'Не удалось отменить заявку')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-900">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
            <HardDrive className="h-5 w-5" />
          </span>
          <div>
            <h2 className="font-semibold text-slate-900 dark:text-slate-100">Хранилище</h2>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              Файлы заметок и все версии материалов личных задач.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
        >
          <RefreshCcw className={cn('h-4 w-4', loading && 'animate-spin')} />
          Обновить
        </button>
      </div>

      {loadError ? (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700" role="alert">
          <span>{loadError}</span>
          <button type="button" onClick={() => void load()} className="min-h-11 font-medium underline">
            Повторить
          </button>
        </div>
      ) : loading && !summary ? (
        <div className="mt-4 text-sm text-slate-500">Загрузка...</div>
      ) : summary ? (
        <>
          <div className="mt-5 flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="text-2xl font-semibold text-slate-900 dark:text-slate-100">
                {formatBytes(summary.used_bytes)} <span className="text-base font-normal text-slate-400">из {formatBytes(summary.quota_bytes)}</span>
              </p>
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                Свободно {formatBytes(summary.available_bytes)}
                {summary.reserved_bytes > 0 && ` · загружается ${formatBytes(summary.reserved_bytes)}`}
              </p>
            </div>
            <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">{summary.usage_percent.toFixed(1)}%</span>
          </div>
          <div
            className="mt-3 h-2.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800"
            role="progressbar"
            aria-label="Использование личного хранилища"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.min(100, summary.usage_percent)}
            aria-valuetext={`Использовано ${formatBytes(summary.used_bytes)} из ${formatBytes(summary.quota_bytes)}`}
          >
            <div
              className={cn('h-full rounded-full transition-[width]', barClasses[summary.warning_level])}
              style={{ width: `${Math.min(100, summary.usage_percent)}%` }}
            />
          </div>
          <div className={cn('mt-4 flex items-start gap-2 rounded-lg border p-3 text-sm', warningClasses[summary.warning_level])}>
            {summary.warning_level !== 'normal' && <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />}
            <p>{summary.warning_message}</p>
          </div>

          {summary.pending_request ? (
            <div className="mt-4 rounded-lg border border-sky-200 bg-sky-50 p-4 dark:border-sky-900 dark:bg-sky-950/30">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="font-medium text-sky-900 dark:text-sky-100">Заявка рассматривается</p>
                  <p className="mt-1 text-sm text-sky-700 dark:text-sky-200">
                    Запрошен общий лимит {formatBytes(summary.pending_request.requested_limit_bytes)}.
                  </p>
                  <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{summary.pending_request.reason}</p>
                </div>
                <button
                  type="button"
                  onClick={() => void cancelRequest()}
                  disabled={busy}
                  className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-sky-200 bg-white px-3 py-2 text-sm font-medium text-sky-700 hover:bg-sky-100 disabled:opacity-50 dark:border-sky-800 dark:bg-slate-900 dark:text-sky-200"
                >
                  <X className="h-4 w-4" />
                  Отменить
                </button>
              </div>
            </div>
          ) : (
            <form onSubmit={submitRequest} className="mt-4 grid gap-3 lg:grid-cols-[180px_minmax(0,1fr)_auto] lg:items-end">
              <label className="text-sm font-medium text-slate-700 dark:text-slate-200">
                Общий лимит, МиБ
                <input
                  type="number"
                  min={Math.ceil(summary.quota_bytes / MIB) + 1}
                  max={10 * 1024}
                  step={1}
                  value={requestedMiB}
                  onChange={(event) => setRequestedMiB(event.target.value)}
                  className="mt-1 min-h-11 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 dark:border-slate-700 dark:bg-slate-950"
                  required
                />
              </label>
              <label className="text-sm font-medium text-slate-700 dark:text-slate-200">
                Причина увеличения
                <input
                  type="text"
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  maxLength={1000}
                  placeholder="Какие файлы планируется хранить"
                  className="mt-1 min-h-11 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 dark:border-slate-700 dark:bg-slate-950"
                  required
                />
              </label>
              <button
                type="submit"
                disabled={busy}
                className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
              >
                <Send className="h-4 w-4" />
                Запросить
              </button>
            </form>
          )}
          {formError && <p className="mt-3 text-sm text-red-600" role="alert">{formError}</p>}
        </>
      ) : null}
    </section>
  )
}
