import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { AlertTriangle, Check, ChevronDown, ChevronLeft, ChevronRight, RefreshCw } from 'lucide-react'
import { api, ApiError } from '@/api/client'

type Usage = {
  start_date: string
  end_date: string
  timezone: 'Europe/Moscow'
  login_count: number
  login_users: number
  section_view_count: number
  section_users: number
  first_login_at: string | null
  first_section_view_at: string | null
  sections: Array<{ section: string; label: string; views: number; users: number }>
  users: Array<{ id: string; name: string; email: string; logins: number }>
  daily: Array<{ date: string; logins: number; section_views: number }>
  logins: {
    total: number
    items: Array<{
      id: string; user_id: string; name: string; email: string; occurred_at: string
      device: string | null; browser: string | null; os: string | null
    }>
  }
}

const PAGE_SIZE = 25
const MAX_DAYS = 366
const MAX_OFFSET = 100_000
const TIMEZONE = 'Europe/Moscow'
const numbers = new Intl.NumberFormat('ru-RU')
const dateFormat = new Intl.DateTimeFormat('ru-RU', {
  timeZone: TIMEZONE, day: '2-digit', month: '2-digit', year: 'numeric',
})
const timeFormat = new Intl.DateTimeFormat('ru-RU', {
  timeZone: TIMEZONE, day: '2-digit', month: '2-digit', year: 'numeric',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
})
const dayFormat = new Intl.DateTimeFormat('en-CA', {
  timeZone: TIMEZONE, year: 'numeric', month: '2-digit', day: '2-digit',
})
const focus = 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-surface'
const control = `h-11 min-w-0 max-w-full rounded-md border border-border bg-surface px-3 text-base text-foreground sm:text-sm ${focus}`
const iconButton = `inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-md border border-border bg-surface text-foreground hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-50 ${focus}`
const cell = 'min-w-0 px-2 py-3 text-left align-top [overflow-wrap:anywhere]'

function dayInMoscow(date = new Date()) {
  const parts = dayFormat.formatToParts(date)
  return ['year', 'month', 'day'].map((part) => parts.find((item) => item.type === part)?.value).join('-')
}

function dateRange(days: number) {
  const end = dayInMoscow()
  const start = new Date(`${end}T12:00:00Z`)
  start.setUTCDate(start.getUTCDate() - days + 1)
  return { start: start.toISOString().slice(0, 10), end }
}

function validDay(value: string | null): value is string {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value < '0001-01-01') return false
  const date = new Date(`${value}T12:00:00Z`)
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value
}

function beforeFirst(day: string, first: string | null) {
  return !first || !Number.isFinite(Date.parse(first)) || day < dayInMoscow(new Date(first))
}

function MoscowTime({ value }: { value: string | null }) {
  return value && Number.isFinite(Date.parse(value))
    ? <time dateTime={value} className="tabular-nums">{timeFormat.format(new Date(value))}</time>
    : <span>нет записей</span>
}

export function AdminUsagePanel() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [defaults] = useState(() => dateRange(7))
  const rawStart = searchParams.get('usage_start')
  const rawEnd = searchParams.get('usage_end')
  const validPeriod = validDay(rawStart) && validDay(rawEnd) && rawStart <= rawEnd
    && (Date.parse(rawEnd) - Date.parse(rawStart)) / 86_400_000 < MAX_DAYS
  const start = validPeriod ? rawStart : defaults.start
  const end = validPeriod ? rawEnd : defaults.end
  const user = searchParams.get('usage_user') || ''
  const rawOffset = Number(searchParams.get('usage_offset') || 0)
  const offset = Number.isSafeInteger(rawOffset) && rawOffset >= 0 && rawOffset <= MAX_OFFSET && rawOffset % PAGE_SIZE === 0 ? rawOffset : 0
  const [draft, setDraft] = useState({ start, end })
  const [validation, setValidation] = useState<string | null>(null)
  const startInput = useRef<HTMLInputElement>(null)
  const endInput = useRef<HTMLInputElement>(null)
  const [revision, setRevision] = useState(0)
  const [journalOpen, setJournalOpen] = useState(false)
  const [dailyOpen, setDailyOpen] = useState(false)
  const requestId = JSON.stringify([start, end, user, offset, revision])
  const [response, setResponse] = useState<{ id: string; data?: Usage; error?: 'forbidden' | 'failed' } | null>(null)
  const current = response?.id === requestId ? response : null
  const data = current?.data
  const error = current?.error
  const loading = !data && !error

  useEffect(() => {
    setDraft({ start, end })
    setValidation(null)
  }, [start, end])

  useEffect(() => {
    const controller = new AbortController()
    setResponse({ id: requestId })
    api.get<Usage>('/api/admin/usage', {
      start_date: start, end_date: end, limit: String(PAGE_SIZE), offset: String(offset),
      ...(user ? { user_id: user } : {}),
    }, { signal: controller.signal }).then((result) => {
      if (controller.signal.aborted) return
      // A fresh snapshot can remove the current page; recover without a stale empty page.
      if (offset > 0 && offset >= result.logins.total) {
        const lastOffset = Math.min(MAX_OFFSET, Math.max(0, Math.ceil(result.logins.total / PAGE_SIZE) - 1) * PAGE_SIZE)
        setSearchParams((previous) => {
          const next = new URLSearchParams(previous)
          next.set('usage_offset', String(lastOffset))
          return next
        }, { replace: true, preventScrollReset: true })
        return
      }
      setResponse({ id: requestId, data: result })
    }).catch((cause: unknown) => {
      if (controller.signal.aborted) return
      // Backend errors may contain operational details; show only a safe local message.
      setResponse({ id: requestId, error: cause instanceof ApiError && cause.status === 403 ? 'forbidden' : 'failed' })
    })
    return () => controller.abort()
  }, [start, end, user, offset, requestId, setSearchParams])

  function updateFilters(values: Record<string, string>) {
    setSearchParams((previous) => {
      const next = new URLSearchParams(previous)
      Object.entries(values).forEach(([name, value]) => {
        if (value) next.set(name, value)
        else next.delete(name)
      })
      return next
    }, { preventScrollReset: true })
  }

  function applyPeriod(event: FormEvent) {
    event.preventDefault()
    if (!validDay(draft.start) || !validDay(draft.end) || draft.start > draft.end) {
      setValidation('Укажите даты: начало периода не должно быть позже окончания.')
      if (!validDay(draft.start) || draft.start > draft.end) startInput.current?.focus()
      else endInput.current?.focus()
      return
    }
    if ((Date.parse(draft.end) - Date.parse(draft.start)) / 86_400_000 >= MAX_DAYS) {
      setValidation('Период не должен превышать 366 дней. Укажите более близкую дату окончания.')
      endInput.current?.focus()
      return
    }
    setValidation(null)
    updateFilters({ usage_start: draft.start, usage_end: draft.end, usage_offset: '' })
  }

  const refresh = () => setRevision((value) => value + 1)
  const hasLoginData = data && !beforeFirst(end, data.first_login_at)
  const hasSectionData = data && !beforeFirst(end, data.first_section_view_at)
  const sections = data ? [...data.sections].sort((a, b) => b.views - a.views || a.label.localeCompare(b.label, 'ru')) : []
  const users = data ? [...data.users].sort((a, b) => b.logins - a.logins || a.name.localeCompare(b.name, 'ru')) : []
  const dirtyPeriod = draft.start !== start || draft.end !== end

  return (
    <section aria-labelledby="admin-usage-heading" className="w-full min-w-0 border-y border-border bg-surface px-3 py-4 text-foreground sm:px-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id="admin-usage-heading" className="text-base font-semibold">Обзор использования</h2>
          <p className="mt-1 text-xs text-muted-foreground">МСК (Europe/Moscow, UTC+3). Даты включительно.</p>
        </div>
        <button type="button" className={iconButton} onClick={refresh} disabled={loading} title="Обновить статистику" aria-label="Обновить статистику">
          <RefreshCw className={`h-4 w-4 ${loading ? 'motion-safe:animate-spin' : ''}`} aria-hidden="true" />
        </button>
      </div>

      <form onSubmit={applyPeriod} noValidate className="mt-4 border-y border-border py-3">
        <div className="flex flex-wrap items-end gap-3">
          <div role="group" aria-label="Быстрый период" className="inline-flex shrink-0 overflow-hidden rounded-md border border-border">
            {[3, 7, 30].map((days) => {
              const range = dateRange(days)
              const selected = draft.start === range.start && draft.end === range.end
              return <button key={days} type="button" aria-pressed={selected} onClick={() => { setDraft(range); setValidation(null) }} className={`min-h-11 px-3 text-sm font-medium focus-visible:ring-inset ${focus} ${selected ? 'bg-primary text-primary-foreground' : 'bg-surface hover:bg-surface-muted'}`}>{days} {days === 3 ? 'дня' : 'дней'}</button>
            })}
          </div>
          <label className="block min-w-0 flex-1 basis-36 text-xs text-muted-foreground sm:max-w-48">
            С даты
            <input ref={startInput} type="date" name="usage-start" autoComplete="off" value={draft.start} onChange={(event) => { setDraft((value) => ({ ...value, start: event.target.value })); setValidation(null) }} aria-invalid={!!validation} aria-describedby={validation ? 'usage-period-error' : undefined} className={`mt-1 block w-full ${control}`} />
          </label>
          <label className="block min-w-0 flex-1 basis-36 text-xs text-muted-foreground sm:max-w-48">
            По дату
            <input ref={endInput} type="date" name="usage-end" autoComplete="off" value={draft.end} onChange={(event) => { setDraft((value) => ({ ...value, end: event.target.value })); setValidation(null) }} aria-invalid={!!validation} aria-describedby={validation ? 'usage-period-error' : undefined} className={`mt-1 block w-full ${control}`} />
          </label>
          <button type="submit" disabled={loading && !dirtyPeriod} className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50 ${focus}`}>
            <Check className="h-4 w-4 shrink-0" aria-hidden="true" />Применить
          </button>
        </div>
        {validation && <p id="usage-period-error" role="alert" className="mt-2 text-sm">{validation}</p>}
      </form>

      <p className="mt-3 text-sm tabular-nums">Период: {dateFormat.format(new Date(`${start}T12:00:00Z`))} – {dateFormat.format(new Date(`${end}T12:00:00Z`))}</p>
      <div aria-live="polite" aria-busy={loading}>
        {loading && <p role="status" className="py-4 text-sm text-muted-foreground">Загрузка статистики…</p>}
        {error && <div role="alert" className="flex flex-wrap items-center justify-between gap-2 py-4 text-sm">
          <p className="flex min-w-0 items-start gap-2"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />{error === 'forbidden' ? 'Просмотр доступен только администратору.' : 'Не удалось загрузить статистику. Повторите запрос.'}</p>
          {error !== 'forbidden' && <button type="button" onClick={refresh} className={`min-h-11 px-2 text-primary underline underline-offset-4 ${focus}`}>Повторить</button>}
        </div>}
      </div>

      {data && <>
        <dl aria-label="Показатели за период" className="grid grid-cols-2 gap-x-4 gap-y-3 border-b border-border py-4 lg:grid-cols-4">
          {[
            ['Записанные успешные входы', hasLoginData ? numbers.format(data.login_count) : 'Нет данных'],
            ['Входившие сотрудники', hasLoginData ? numbers.format(data.login_users) : 'Нет данных'],
            ['Записанные посещения разделов', hasSectionData ? numbers.format(data.section_view_count) : 'Нет данных'],
            ['Посетители разделов', hasSectionData ? numbers.format(data.section_users) : 'Нет данных'],
          ].map(([label, value]) => <div key={label} className="min-w-0">
            <dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-1 break-words text-lg font-semibold tabular-nums">{value}</dd>
          </div>)}
        </dl>
        <div className="space-y-1 py-3 text-xs text-muted-foreground">
          <p>Первый записанный вход: <MoscowTime value={data.first_login_at} /></p>
          <p>Первое записанное посещение раздела: <MoscowTime value={data.first_section_view_at} /></p>
          <p>Показаны только записанные события. Историческая полнота не гарантируется; посещения разделов до начала сбора неизвестны.</p>
        </div>
        {data.login_count === 0 && data.section_view_count === 0 && <p role="status" className="py-2 text-sm">За выбранный период событий не записано.</p>}
        <section aria-labelledby="usage-sections-heading" className="border-t border-border py-3">
          <h3 id="usage-sections-heading" className="text-sm font-semibold">Популярные разделы</h3>
          {!hasSectionData ? <p className="py-3 text-sm text-muted-foreground">Нет данных о посещениях разделов за этот период.</p> : sections.length === 0 ? <p className="py-3 text-sm text-muted-foreground">За выбранный период посещений разделов не записано.</p> : <table aria-label="Популярные разделы" className="mt-2 w-full table-fixed text-sm">
            <thead className="border-b border-border text-xs text-muted-foreground"><tr>
              <th scope="col" className={`${cell} w-1/2 font-medium`}>Раздел</th>
              <th scope="col" aria-label="Посещения" className="whitespace-nowrap px-1 py-3 text-left align-top font-medium sm:px-2"><span aria-hidden="true" className="sm:hidden">Визиты</span><span aria-hidden="true" className="hidden sm:inline">Посещения</span></th>
              <th scope="col" aria-label="Сотрудники" className="whitespace-nowrap px-1 py-3 text-left align-top font-medium sm:px-2"><span aria-hidden="true" className="sm:hidden">Люди</span><span aria-hidden="true" className="hidden sm:inline">Сотрудники</span></th>
            </tr></thead>
            <tbody>{sections.map((section) => <tr key={section.section} className="border-b border-border last:border-0">
              <th scope="row" className={`${cell} font-medium`}>{section.label || section.section}</th><td className={`${cell} tabular-nums`}>{numbers.format(section.views)}</td><td className={`${cell} tabular-nums`}>{numbers.format(section.users)}</td>
            </tr>)}</tbody>
          </table>}
        </section>
      </>}

      <details open={dailyOpen} onToggle={(event) => setDailyOpen(event.currentTarget.open)} className="group border-t border-border">
        <summary className={`flex min-h-11 cursor-pointer list-none items-center justify-between gap-2 text-sm font-semibold [&::-webkit-details-marker]:hidden ${focus}`}>
          По дням<ChevronDown className={`h-4 w-4 shrink-0 ${dailyOpen ? 'rotate-180' : ''}`} aria-hidden="true" />
        </summary>
        {data && <table aria-label="События по дням" className="mb-3 w-full table-fixed text-sm">
          <thead className="border-b border-border text-xs text-muted-foreground"><tr><th scope="col" className={`${cell} font-medium`}>Дата</th><th scope="col" className={`${cell} font-medium`}>Входы</th><th scope="col" className={`${cell} font-medium`}>Посещения разделов</th></tr></thead>
          <tbody>{[...data.daily].sort((a, b) => b.date.localeCompare(a.date)).map((day) => <tr key={day.date} className="border-b border-border last:border-0">
            <th scope="row" className={`${cell} font-normal tabular-nums`}><time dateTime={day.date}>{validDay(day.date) ? dateFormat.format(new Date(`${day.date}T12:00:00Z`)) : day.date}</time></th>
            <td className={`${cell} tabular-nums`}>{beforeFirst(day.date, data.first_login_at) ? 'Нет данных' : numbers.format(day.logins)}</td>
            <td className={`${cell} tabular-nums`}>{beforeFirst(day.date, data.first_section_view_at) ? 'Нет данных' : numbers.format(day.section_views)}</td>
          </tr>)}</tbody>
        </table>}
      </details>

      <details open={journalOpen} onToggle={(event) => setJournalOpen(event.currentTarget.open)} className="border-t border-border">
        <summary className={`flex min-h-11 cursor-pointer list-none items-center justify-between gap-2 text-sm font-semibold [&::-webkit-details-marker]:hidden ${focus}`}>
          Журнал входов<ChevronDown className={`h-4 w-4 shrink-0 ${journalOpen ? 'rotate-180' : ''}`} aria-hidden="true" />
        </summary>
        <label className="block min-w-0 py-2 text-xs text-muted-foreground">
          Сотрудник в журнале
          <select name="usage-user" value={user} disabled={error === 'forbidden'} onChange={(event) => updateFilters({ usage_user: event.target.value, usage_offset: '' })} className={`mt-1 block w-full sm:max-w-md ${control}`}>
            <option value="">Все сотрудники</option>
            {user && !users.some((item) => item.id === user) && <option value={user}>Выбранный сотрудник</option>}
            {users.map((item) => <option key={item.id} value={item.id}>{item.name || item.email || 'Без имени'} · {item.email} · входов: {numbers.format(item.logins)}</option>)}
          </select>
        </label>
        {loading && <p className="py-3 text-sm text-muted-foreground">Загрузка журнала…</p>}
        {data && <>
          {data.logins.items.length === 0 ? <p className="py-3 text-sm text-muted-foreground">{user ? 'У выбранного сотрудника за период входов не записано.' : 'За выбранный период входов не записано.'}</p> : <table aria-label="Журнал успешных входов" className="block w-full text-sm md:table md:table-fixed">
            <thead className="sr-only text-xs text-muted-foreground md:not-sr-only md:table-header-group"><tr className="border-b border-border"><th scope="col" className={`${cell} w-1/3 font-medium`}>Сотрудник</th><th scope="col" className={`${cell} font-medium`}>Время, МСК</th><th scope="col" className={`${cell} font-medium`}>Устройство</th><th scope="col" className={`${cell} font-medium`}>Браузер / ОС</th></tr></thead>
            <tbody className="block md:table-row-group">{data.logins.items.map((login) => <tr key={login.id} className="grid min-w-0 grid-cols-2 gap-x-3 border-b border-border py-2 last:border-0 md:table-row md:py-0">
              <th scope="row" className={`${cell} col-span-2 font-medium md:table-cell`}><span className="block">{login.name || 'Без имени'}</span><span className="block text-xs font-normal text-muted-foreground">{login.email}</span></th>
              <td className={`${cell} col-span-2 md:table-cell`}><span className="mb-1 block text-xs text-muted-foreground md:hidden">Время, МСК</span><MoscowTime value={login.occurred_at} /></td>
              <td className={`${cell} md:table-cell`}><span className="mb-1 block text-xs text-muted-foreground md:hidden">Устройство</span>{login.device?.trim() || 'Неизвестно'}</td>
              <td className={`${cell} md:table-cell`}><span className="mb-1 block text-xs text-muted-foreground md:hidden">Браузер / ОС</span>{login.browser?.trim() || 'Неизвестный браузер'}<span className="block text-xs text-muted-foreground">{login.os?.trim() || 'Неизвестная ОС'}</span></td>
            </tr>)}</tbody>
          </table>}
        </>}
        <div className="flex flex-wrap items-center justify-between gap-2 py-3">
          <p role="status" className="text-xs tabular-nums text-muted-foreground">{data ? data.logins.total ? `${numbers.format(offset + 1)}–${numbers.format(Math.min(offset + PAGE_SIZE, data.logins.total))} из ${numbers.format(data.logins.total)}` : '0 записей' : ''}</p>
          <div className="flex shrink-0 gap-2">
            <button type="button" className={iconButton} title="Предыдущие входы" aria-label="Предыдущие входы" disabled={loading || !!error || offset === 0} onClick={() => updateFilters({ usage_offset: String(Math.max(0, offset - PAGE_SIZE)) })}><ChevronLeft className="h-4 w-4" aria-hidden="true" /></button>
            <button type="button" className={iconButton} title="Следующие входы" aria-label="Следующие входы" disabled={!data || offset + PAGE_SIZE >= data.logins.total || offset + PAGE_SIZE > MAX_OFFSET} onClick={() => updateFilters({ usage_offset: String(offset + PAGE_SIZE) })}><ChevronRight className="h-4 w-4" aria-hidden="true" /></button>
          </div>
        </div>
      </details>
    </section>
  )
}
