import { useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, ChevronLeft, ChevronRight, Clock3, RefreshCw } from 'lucide-react'
import { api, ApiError } from '@/api/client'

type ServerBoots = {
  period_days: number
  total: number
  all_time_count: number
  last_7_days_count: number
  first_imported_at: string | null
  items: Array<{
    source_id: string
    event_id: string
    boot_time: string
    recorded_at: string
    imported_at: string
    uptime_seconds: number
    reason: 'unknown'
    clock: 'system_clock_not_independently_verified'
  }>
  import_status: {
    state: 'waiting' | 'ok' | 'degraded' | 'stale'
    last_attempt_at: string | null
    last_success_at: string | null
    invalid_files: number
    conflicting_files: number
    checked_files: number
    error_code: string | null
  }
}

const PAGE_SIZE = 25
const dateFormat = new Intl.DateTimeFormat('ru-RU', {
  timeZone: 'Europe/Moscow',
  day: '2-digit', month: '2-digit', year: 'numeric',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
})
const numberFormat = new Intl.NumberFormat('ru-RU')
const iconButton = 'inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-md border border-border bg-surface text-foreground hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:cursor-not-allowed disabled:opacity-50'
const statusLabels = {
  waiting: 'Синхронизация ещё не запускалась',
  ok: 'Синхронизирован',
  stale: 'Проверка устарела',
  degraded: 'Импорт с ошибками',
}
const importErrors: Record<string, string> = {
  directory_missing: 'Каталог журнала не найден на сервере.',
  directory_unreadable: 'Каталог журнала недоступен для чтения.',
  scan_failed: 'Проверка каталога не завершилась.',
  too_many_files: 'Превышен лимит файлов за одну проверку.',
  invalid_files: 'Часть файлов имеет неподдерживаемый формат.',
  conflicting_files: 'Обнаружены изменения уже импортированных записей.',
}

function MoscowTime({ value }: { value: string | null }) {
  if (!value || !Number.isFinite(Date.parse(value))) return <span>нет данных</span>
  return <time dateTime={value} className="tabular-nums">{dateFormat.format(new Date(value))}</time>
}

export function AdminServerBootPanel() {
  const [query, setQuery] = useState({ days: 0, offset: 0, revision: 0 })
  const [data, setData] = useState<ServerBoots | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    setData(null)
    api.get<ServerBoots>('/api/admin/server-boots', {
      days: String(query.days), limit: String(PAGE_SIZE), offset: String(query.offset),
    }, { signal: controller.signal })
      .then((result) => {
        if (controller.signal.aborted) return
        // A refreshed result may have fewer pages than the previous snapshot.
        if (query.offset > 0 && query.offset >= result.total) {
          setQuery((current) => ({
            ...current,
            offset: Math.max(0, Math.ceil(result.total / PAGE_SIZE) - 1) * PAGE_SIZE,
          }))
          return
        }
        setData(result)
        setLoading(false)
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return
        // Server errors can contain operational details; never render their raw message.
        setError(cause instanceof ApiError && cause.status === 403
          ? 'Просмотр доступен только администратору.'
          : 'Не удалось загрузить записи. Повторите запрос.')
        setLoading(false)
      })
    return () => controller.abort()
  }, [query])

  const refresh = () => setQuery((current) => ({ ...current, revision: current.revision + 1 }))
  const status = data?.import_status
  const StatusIcon = status?.state === 'ok' ? CheckCircle2
    : status?.state === 'degraded' || status?.state === 'waiting' ? AlertTriangle : Clock3
  const emptyMessage = data && !data.first_imported_at && !status?.last_success_at
    ? 'Импорт ещё не выполнен.'
    : data?.all_time_count === 0
      ? 'События загрузки не найдены.'
      : 'За выбранный период загрузок нет.'

  return (
    <section aria-labelledby="server-boots-heading" className="w-full min-w-0 border-y border-border bg-surface px-3 py-4 text-foreground sm:px-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id="server-boots-heading" className="text-base font-semibold">Загрузки сервера</h2>
          <dl className="mt-1 flex flex-wrap gap-x-5 gap-y-1 text-sm">
            <div className="flex gap-2"><dt className="text-muted-foreground">Всего</dt><dd className="font-medium tabular-nums">{data ? numberFormat.format(data.all_time_count) : '—'}</dd></div>
            <div className="flex gap-2"><dt className="text-muted-foreground">За 7 дней</dt><dd className="font-medium tabular-nums">{data ? numberFormat.format(data.last_7_days_count) : '—'}</dd></div>
          </dl>
        </div>
        <div className="flex max-w-full flex-wrap items-end gap-2">
          <label className="min-w-0 text-xs text-muted-foreground">
            Период
            <select
              name="server-boot-period"
              value={query.days}
              onChange={(event) => setQuery({ days: Number(event.target.value), offset: 0, revision: 0 })}
              className="mt-1 block h-11 max-w-full rounded-md border border-border bg-surface px-2 text-base text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary sm:text-sm"
            >
              <option value={0}>Всё время</option>
              <option value={7}>7 дней</option>
              <option value={30}>30 дней</option>
              <option value={90}>90 дней</option>
              <option value={366}>366 дней</option>
            </select>
          </label>
          <button type="button" onClick={refresh} disabled={loading} className={iconButton} title="Обновить записи загрузок" aria-label="Обновить записи загрузок">
            <RefreshCw className={`h-4 w-4 ${loading ? 'motion-safe:animate-spin' : ''}`} aria-hidden="true" />
          </button>
        </div>
      </div>

      <p id="server-boots-timezone" className="mt-3 text-xs text-muted-foreground">МСК (Europe/Moscow, UTC+3)</p>
      <div aria-live="polite" aria-busy={loading} className="mt-2 min-w-0 text-sm">
        {loading && <p className="py-4 text-muted-foreground" role="status">Загрузка записей…</p>}
        {error && (
          <div className="flex flex-wrap items-center justify-between gap-2 border-y border-border py-2" role="alert">
            <p className="flex min-w-0 items-start gap-2"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />{error}</p>
            <button type="button" onClick={refresh} className="min-h-11 rounded px-2 font-medium text-primary underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">Повторить</button>
          </div>
        )}
        {data && status && (
          <>
            <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
              <p className="inline-flex items-center gap-2 font-medium">
                <StatusIcon className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
                Импорт при последнем запросе: {statusLabels[status.state]}
              </p>
              <p className="text-xs text-muted-foreground">Последняя проверка: <MoscowTime value={status.last_attempt_at} /></p>
            </div>
            {(status.state === 'degraded' || status.state === 'stale') && (
              <div className="mt-2 border-l-2 border-primary pl-3 text-xs text-muted-foreground">
                {status.error_code && <p className="mb-1">{importErrors[status.error_code] ?? 'Ошибка импорта журнала.'}</p>}
                <p>Последняя успешная проверка: <MoscowTime value={status.last_success_at} /></p>
                <p className="mt-1">Проверено файлов: {numberFormat.format(status.checked_files)}. Некорректных: {numberFormat.format(status.invalid_files)}. Конфликтующих: {numberFormat.format(status.conflicting_files)}.</p>
              </div>
            )}
          </>
        )}
      </div>

      {data && (
        <>
          {data.items.length === 0 ? <p role="status" className="py-5 text-sm text-muted-foreground">{emptyMessage}</p> : (
            <div role="region" aria-label="Список записей загрузок" tabIndex={0} className="mt-3 max-h-80 overflow-y-auto focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
            <table role="table" aria-label="Записи загрузок сервера" aria-describedby="server-boots-timezone" className="block w-full table-fixed text-left text-sm md:table">
              <thead role="rowgroup" className="sr-only md:not-sr-only md:table-header-group">
                <tr role="row" className="text-xs text-muted-foreground">
                  {['Время загрузки', 'Записано', 'Импортировано в БД', 'Причина'].map((label) => <th key={label} role="columnheader" scope="col" className="px-2 py-2 font-medium">{label}</th>)}
                </tr>
              </thead>
              <tbody role="rowgroup" className="block md:table-row-group">
                {data.items.map((item) => (
                  <tr key={`${item.source_id}:${item.event_id}`} role="row" className="block border-t border-border py-2 align-top md:table-row md:py-0">
                    {[
                      { label: 'Время загрузки', value: item.boot_time },
                      { label: 'Записано', value: item.recorded_at },
                      { label: 'Импортировано в БД', value: item.imported_at },
                    ].map(({ label, value }) => (
                      <td key={label} role="cell" className="grid min-w-0 grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)] gap-2 px-2 py-1 md:table-cell md:py-2">
                        <span aria-hidden="true" className="text-xs text-muted-foreground md:hidden">{label}</span>
                        <MoscowTime value={value} />
                      </td>
                    ))}
                    <td role="cell" className="grid min-w-0 grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)] gap-2 px-2 py-1 text-muted-foreground md:table-cell md:py-2">
                      <span aria-hidden="true" className="text-xs md:hidden">Причина</span>
                      <span>Неизвестна</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          )}
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-2">
            <p role="status" className="text-xs tabular-nums text-muted-foreground">
              {data.total === 0 ? '0 записей' : `${numberFormat.format(query.offset + 1)}–${numberFormat.format(query.offset + data.items.length)} из ${numberFormat.format(data.total)}`}
            </p>
            <nav aria-label="Страницы загрузок сервера" className="flex gap-2">
              <button type="button" disabled={loading || query.offset === 0} onClick={() => setQuery((current) => ({ ...current, offset: Math.max(0, current.offset - PAGE_SIZE) }))} className={iconButton} title="Предыдущие записи" aria-label="Предыдущие записи"><ChevronLeft className="h-4 w-4" aria-hidden="true" /></button>
              <button type="button" disabled={loading || query.offset + PAGE_SIZE >= data.total} onClick={() => setQuery((current) => ({ ...current, offset: current.offset + PAGE_SIZE }))} className={iconButton} title="Следующие записи" aria-label="Следующие записи"><ChevronRight className="h-4 w-4" aria-hidden="true" /></button>
            </nav>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">Время событий по часам сервера; независимая проверка не проводилась.</p>
        </>
      )}
    </section>
  )
}
