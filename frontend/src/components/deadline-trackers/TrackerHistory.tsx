import { useEffect, useState } from 'react'
import { CheckCircle2, Pencil, RefreshCw, Square } from 'lucide-react'
import type { DeadlineTracker } from '@/api/types'
import { TrackerDialog, trackerButton } from './TrackerDialog'

export type TrackerOccurrence = NonNullable<DeadlineTracker['current_occurrence']>
export interface TrackerHistoryData {
  occurrences: TrackerOccurrence[]
  events: Array<{ id: string; event_type: string; details: Record<string, unknown>; created_at: string }>
  alerts: Array<{ id: string; scheduled_for: string; delivered_at: string | null; status: 'pending' | 'sent' | 'suppressed' | 'cancelled'; is_read?: boolean | null }>
}

const eventLabels: Record<string, string> = {
  created: 'Трекер создан', updated: 'Трекер изменен', occurrence_completed: 'Повторение завершено',
  series_finished: 'Серия завершена', paused: 'Пауза', resumed: 'Пауза снята', archived: 'Архив',
  recurrence_changed: 'Правило повторения изменено', reminders_changed: 'Напоминания изменены',
  schedule_changed: 'Расписание изменено', completed: 'Завершено',
}
const alertLabels = { pending: 'Запланировано', sent: 'Доставлено', suppressed: 'Приостановлено', cancelled: 'Отменено' }
const occurrenceLabels = { pending: 'Ожидается', completed: 'Завершено', cancelled: 'Отменено' }
function date(value: string, timezone?: string) {
  return new Date(value).toLocaleString('ru-RU', { timeZone: timezone, dateStyle: 'short', timeStyle: 'short' })
}

export function TrackerHistory({ tracker, busy, error, readError, onRetryRead, onLoad, onComplete, onFinish, onEdit, onClose }: {
  tracker: DeadlineTracker; busy: boolean; error?: string; readError?: string; onRetryRead: () => void
  onLoad: (id: string, signal: AbortSignal, offset?: number) => Promise<TrackerHistoryData>
  onComplete: (occurrence: TrackerOccurrence) => Promise<void>
  onFinish: () => void; onEdit: () => void; onClose: () => void
}) {
  const [history, setHistory] = useState<TrackerHistoryData | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [revision, setRevision] = useState(0)
  const [offset, setOffset] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  useEffect(() => { setOffset(0) }, [revision, tracker.updated_at, tracker.current_occurrence?.id])
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setLoadError('')
    void onLoad(tracker.id, controller.signal, offset).then((data) => {
      if (!controller.signal.aborted) {
        setHasMore(data.occurrences.length === 100 || data.events.length === 100 || data.alerts.length === 100)
        setHistory((previous) => {
          if (!offset || !previous) return data
          return {
            occurrences: [...previous.occurrences.filter((item) => !data.occurrences.some((row) => row.id === item.id)), ...data.occurrences],
            events: [...previous.events.filter((item) => !data.events.some((row) => row.id === item.id)), ...data.events],
            alerts: [...previous.alerts.filter((item) => !data.alerts.some((row) => row.id === item.id)), ...data.alerts],
          }
        })
      }
    }).catch((cause) => {
      if (!controller.signal.aborted) setLoadError(cause instanceof Error ? cause.message : 'Не удалось загрузить историю')
    }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [offset, onLoad, revision, tracker.id, tracker.updated_at, tracker.current_occurrence?.id])
  const timezone = tracker.recurrence?.timezone
  const live = tracker.status === 'active' || tracker.status === 'paused'
  const noCurrentOccurrence = Boolean(tracker.recurrence && tracker.current_occurrence?.status !== 'pending')
  return <TrackerDialog title={tracker.title} busy={busy} onClose={onClose} footer={<>
    <button type="button" className={trackerButton} disabled={busy} onClick={onEdit}><Pencil className="h-4 w-4" aria-hidden="true" />Редактировать трекер</button>
    {tracker.recurrence && live && <button type="button" className={trackerButton} disabled={busy} onClick={onFinish}><Square className="h-4 w-4" aria-hidden="true" />Завершить серию</button>}
  </>}>
    <div className="space-y-4">
      {error && <p role="alert" className="text-sm text-rose-700 dark:text-rose-300">{error}</p>}
      {readError && <div role="alert" className="text-sm text-rose-700 dark:text-rose-300">{readError}<button type="button" className={trackerButton} onClick={onRetryRead}>Повторить отметку прочтения</button></div>}
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-2 text-sm">
        <dt className="text-slate-500">Источник</dt><dd>{tracker.personal_task_id ? 'Личная задача' : tracker.linked_task_id ? 'Q-задача' : 'Самостоятельный'}</dd>
        <dt className="text-slate-500">{noCurrentOccurrence ? 'Повторения' : tracker.recurrence ? 'Ближайший срок' : 'Дедлайн'}</dt><dd className="break-words tabular-nums">{noCurrentOccurrence ? tracker.series_exhausted ? 'Повторения завершены' : 'Нет текущего повторения' : date(tracker.current_occurrence?.due_at || tracker.due_at, timezone)}</dd>
        {timezone && <><dt className="text-slate-500">Часовой пояс</dt><dd className="break-words">{timezone}</dd></>}
        {tracker.next_action && <><dt className="text-slate-500">Далее</dt><dd className="break-words">{tracker.next_action}</dd></>}
      </dl>
      {tracker.description && <p className="whitespace-pre-wrap break-words text-sm">{tracker.description}</p>}
      {tracker.url && /^https?:\/\//i.test(tracker.url) && <a href={tracker.url} target="_blank" rel="noreferrer" className="block break-all text-sm text-primary underline">{tracker.url}</a>}
      <section aria-label="История повторений" className="border-t border-slate-200 pt-3 dark:border-slate-700">
        <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold">{tracker.recurrence ? 'История повторений' : 'Срок'}</h3><button type="button" className={trackerButton} disabled={loading || busy} onClick={() => setRevision((value) => value + 1)}><RefreshCw className="h-4 w-4" aria-hidden="true" />Обновить</button></div>
        {loading && <p role="status" className="py-3 text-sm text-slate-500">Загрузка истории...</p>}
        {loadError && <p role="alert" className="py-3 text-sm text-rose-700 dark:text-rose-300">{loadError}</p>}
        <ol className="divide-y divide-slate-200 dark:divide-slate-700">{history?.occurrences.map((occurrence) => <li key={occurrence.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
          <div className="min-w-0 text-sm"><div className="break-words tabular-nums">#{occurrence.sequence} · {date(occurrence.due_at, timezone)}</div><div className="text-xs text-slate-500">{occurrenceLabels[occurrence.status]}{occurrence.completed_at && ` · ${date(occurrence.completed_at, timezone)}`}</div></div>
          {tracker.recurrence && live && !noCurrentOccurrence && occurrence.status === 'pending' && <button type="button" className={trackerButton} disabled={busy} onClick={() => void onComplete(occurrence).then(() => setRevision((value) => value + 1))}><CheckCircle2 className="h-4 w-4 text-emerald-600" aria-hidden="true" />Завершить повторение</button>}
        </li>)}</ol>
        {!loading && !loadError && !history?.occurrences.length && <p className="py-3 text-sm text-slate-500">Нет повторений</p>}
      </section>
      {!!history?.alerts.length && <details className="border-t border-slate-200 pt-3 dark:border-slate-700"><summary className="min-h-11 cursor-pointer py-2 text-sm font-semibold">Доставка напоминаний</summary><ul className="space-y-2 text-sm">{history.alerts.map((alert) => <li key={alert.id} className="flex flex-wrap justify-between gap-2"><span className="tabular-nums">{date(alert.scheduled_for, timezone)}</span><span>{alertLabels[alert.status]}{alert.is_read ? ' · Прочитано' : ''}</span></li>)}</ul></details>}
      {!!history?.events.length && <details className="border-t border-slate-200 pt-3 dark:border-slate-700"><summary className="min-h-11 cursor-pointer py-2 text-sm font-semibold">Журнал изменений</summary><ul className="space-y-2 text-sm">{history.events.map((event) => <li key={event.id} className="flex flex-wrap justify-between gap-2"><span>{eventLabels[event.event_type] || 'Изменение трекера'}</span><span className="tabular-nums text-slate-500">{date(event.created_at, timezone)}</span></li>)}</ul></details>}
      {hasMore && <button type="button" className={trackerButton} disabled={loading || busy} onClick={() => setOffset((value) => value + 100)}>Загрузить еще историю</button>}
    </div>
  </TrackerDialog>
}
