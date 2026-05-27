import { useCallback, useEffect, useMemo, useState } from 'react'
import { CalendarDays, Pencil, Plus, Trash2, X } from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '@/api/client'
import type { AbsencePayload, AbsenceType, GlobalHoliday, HolidayPayload, User, UserAbsence } from '@/api/types'
import { useAuth } from '@/contexts/AuthContext'
import { cn } from '@/lib/utils'

const TYPE_LABELS: Record<AbsenceType, string> = {
  vacation: 'Отпуск',
  sick_leave: 'Больничный',
  day_off: 'Отгул',
  other: 'Другое',
}

const TYPE_STYLES: Record<AbsenceType, string> = {
  vacation: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  sick_leave: 'border-red-200 bg-red-50 text-red-800',
  day_off: 'border-amber-200 bg-amber-50 text-amber-800',
  other: 'border-slate-200 bg-slate-50 text-slate-700',
}

const HOLIDAY_STYLE = 'border-sky-200 bg-sky-50 text-sky-800'

const emptyForm = {
  user_id: '',
  start_date: '',
  end_date: '',
  type: 'vacation' as AbsenceType,
  affects_plan: true,
  comment: '',
}

const emptyHolidayForm = {
  date: '',
  name: '',
}

function currentMonthValue() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

function monthRange(period: string) {
  const [yearRaw, monthRaw] = period.split('-').map(Number)
  const year = yearRaw || new Date().getFullYear()
  const month = monthRaw || new Date().getMonth() + 1
  const lastDay = new Date(year, month, 0).getDate()
  const start = `${year}-${String(month).padStart(2, '0')}-01`
  const end = `${year}-${String(month).padStart(2, '0')}-${String(lastDay).padStart(2, '0')}`
  const days = Array.from({ length: lastDay }, (_, index) => `${year}-${String(month).padStart(2, '0')}-${String(index + 1).padStart(2, '0')}`)
  return { start, end, days }
}

function formatDate(value: string) {
  return new Date(`${value}T00:00:00`).toLocaleDateString('ru-RU')
}

function shortDay(value: string) {
  const date = new Date(`${value}T00:00:00`)
  return date.toLocaleDateString('ru-RU', { day: '2-digit', weekday: 'short' })
}

function isWeekend(value: string) {
  const day = new Date(`${value}T00:00:00`).getDay()
  return day === 0 || day === 6
}

export function AbsencesPage() {
  const { user: currentUser } = useAuth()
  const canEdit = currentUser?.role === 'admin'
  const [period, setPeriod] = useState(currentMonthValue())
  const [userFilter, setUserFilter] = useState('')
  const [users, setUsers] = useState<User[]>([])
  const [absences, setAbsences] = useState<UserAbsence[]>([])
  const [holidays, setHolidays] = useState<GlobalHoliday[]>([])
  const [loading, setLoading] = useState(true)
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<UserAbsence | null>(null)
  const [form, setForm] = useState(emptyForm)
  const [saving, setSaving] = useState(false)
  const [holidayFormOpen, setHolidayFormOpen] = useState(false)
  const [editingHoliday, setEditingHoliday] = useState<GlobalHoliday | null>(null)
  const [holidayForm, setHolidayForm] = useState(emptyHolidayForm)
  const [savingHoliday, setSavingHoliday] = useState(false)

  const { start, end, days } = useMemo(() => monthRange(period), [period])

  const loadUsers = useCallback(() => {
    api.get<User[]>('/api/users', { is_active: 'true' }).then(setUsers).catch(() => setUsers([]))
  }, [])

  const loadAbsences = useCallback(() => {
    setLoading(true)
    const params: Record<string, string> = { from: start, to: end }
    if (userFilter) params.user_id = userFilter
    api
      .get<UserAbsence[]>('/api/absences', params)
      .then(setAbsences)
      .catch((error) => toast.error(error instanceof Error ? error.message : 'Ошибка загрузки отсутствий'))
      .finally(() => setLoading(false))
  }, [start, end, userFilter])

  const loadHolidays = useCallback(() => {
    api
      .get<GlobalHoliday[]>('/api/absences/holidays', { from: start, to: end })
      .then(setHolidays)
      .catch((error) => toast.error(error instanceof Error ? error.message : 'Ошибка загрузки праздников'))
  }, [start, end])

  useEffect(() => {
    loadUsers()
  }, [loadUsers])

  useEffect(() => {
    loadAbsences()
  }, [loadAbsences])

  useEffect(() => {
    loadHolidays()
  }, [loadHolidays])

  const absencesByDay = useMemo(() => {
    const map = new Map<string, UserAbsence[]>()
    for (const day of days) {
      map.set(day, absences.filter((absence) => absence.start_date <= day && absence.end_date >= day))
    }
    return map
  }, [absences, days])

  const holidaysByDay = useMemo(() => {
    const map = new Map<string, GlobalHoliday[]>()
    for (const day of days) {
      map.set(day, holidays.filter((holiday) => holiday.date === day))
    }
    return map
  }, [holidays, days])

  const holidayWorkingDays = holidays.filter((holiday) => holiday.affects_plan && !isWeekend(holiday.date)).length
  const totalWorkingDays = absences.reduce((sum, absence) => sum + (absence.affects_plan ? absence.working_days : 0), 0) + holidayWorkingDays
  const today = new Date().toISOString().slice(0, 10)
  const activeToday = absences.filter((absence) => absence.start_date <= today && absence.end_date >= today)
  const activeHolidayToday = holidays.filter((holiday) => holiday.date === today)

  const openCreate = () => {
    setEditing(null)
    setForm({ ...emptyForm, user_id: userFilter || users[0]?.id || '', start_date: start, end_date: start })
    setFormOpen(true)
  }

  const openEdit = (absence: UserAbsence) => {
    setEditing(absence)
    setForm({
      user_id: absence.user_id,
      start_date: absence.start_date,
      end_date: absence.end_date,
      type: absence.type,
      affects_plan: absence.affects_plan,
      comment: absence.comment ?? '',
    })
    setFormOpen(true)
  }

  const closeForm = () => {
    setFormOpen(false)
    setEditing(null)
    setForm(emptyForm)
  }

  const openCreateHoliday = () => {
    setEditingHoliday(null)
    setHolidayForm({ ...emptyHolidayForm, date: start })
    setHolidayFormOpen(true)
  }

  const openEditHoliday = (holiday: GlobalHoliday) => {
    setEditingHoliday(holiday)
    setHolidayForm({ date: holiday.date, name: holiday.name })
    setHolidayFormOpen(true)
  }

  const closeHolidayForm = () => {
    setHolidayFormOpen(false)
    setEditingHoliday(null)
    setHolidayForm(emptyHolidayForm)
  }

  const handleSubmit = async () => {
    if (!form.user_id || !form.start_date || !form.end_date) {
      toast.error('Заполните сотрудника и даты')
      return
    }
    const payload: AbsencePayload = {
      user_id: form.user_id,
      start_date: form.start_date,
      end_date: form.end_date,
      type: form.type,
      affects_plan: form.affects_plan,
      comment: form.comment.trim() || null,
    }
    setSaving(true)
    try {
      if (editing) {
        await api.patch<UserAbsence>(`/api/absences/${editing.id}`, payload)
        toast.success('Отсутствие обновлено')
      } else {
        await api.post<UserAbsence>('/api/absences', payload)
        toast.success('Отсутствие добавлено')
      }
      closeForm()
      loadAbsences()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Ошибка сохранения')
    } finally {
      setSaving(false)
    }
  }

  const handleHolidaySubmit = async () => {
    if (!holidayForm.date || !holidayForm.name.trim()) {
      toast.error('Заполните дату и название праздника')
      return
    }
    const payload: HolidayPayload = {
      date: holidayForm.date,
      name: holidayForm.name.trim(),
    }
    setSavingHoliday(true)
    try {
      if (editingHoliday) {
        await api.patch<GlobalHoliday>(`/api/absences/holidays/${editingHoliday.id}`, payload)
        toast.success('Праздничный день обновлен')
      } else {
        await api.post<GlobalHoliday>('/api/absences/holidays', payload)
        toast.success('Праздничный день добавлен')
      }
      closeHolidayForm()
      loadHolidays()
      loadAbsences()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Ошибка сохранения праздника')
    } finally {
      setSavingHoliday(false)
    }
  }

  const handleDelete = async (absence: UserAbsence) => {
    if (!window.confirm(`Удалить отсутствие: ${absence.user_name}, ${formatDate(absence.start_date)} - ${formatDate(absence.end_date)}?`)) return
    try {
      await api.delete(`/api/absences/${absence.id}`)
      toast.success('Отсутствие удалено')
      loadAbsences()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Ошибка удаления')
    }
  }

  const handleDeleteHoliday = async (holiday: GlobalHoliday) => {
    if (!window.confirm(`Удалить праздник «${holiday.name}» (${formatDate(holiday.date)})?`)) return
    try {
      await api.delete(`/api/absences/holidays/${holiday.id}`)
      toast.success('Праздничный день удален')
      loadHolidays()
      loadAbsences()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Ошибка удаления праздника')
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Отсутствия</h1>
          <p className="mt-1 text-sm text-slate-500">{totalWorkingDays} раб. дн. исключено из плана за период</p>
        </div>
        {canEdit && (
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={openCreate}
              className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
            >
              <Plus className="h-4 w-4" aria-hidden="true" />
              Добавить отсутствие
            </button>
            <button
              type="button"
              onClick={openCreateHoliday}
              className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              <CalendarDays className="h-4 w-4" aria-hidden="true" />
              Добавить праздник
            </button>
          </div>
        )}
      </div>

      <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="grid gap-3 sm:grid-cols-[180px_minmax(220px,320px)_1fr] sm:items-end">
          <label className="block text-sm font-medium text-slate-700">
            Месяц
            <input
              type="month"
              value={period}
              onChange={(event) => setPeriod(event.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
            />
          </label>
          <label className="block text-sm font-medium text-slate-700">
            Сотрудник
            <select
              value={userFilter}
              onChange={(event) => setUserFilter(event.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
            >
              <option value="">Все сотрудники</option>
              {users.map((user) => (
                <option key={user.id} value={user.id}>{user.full_name}</option>
              ))}
            </select>
          </label>
          <div className="flex flex-wrap gap-2 text-sm">
            <span className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-slate-700">Отсутствий: {absences.length}</span>
            <span className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-slate-700">Праздников: {holidays.length}</span>
            <span className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-slate-700">Сегодня: {activeToday.length + activeHolidayToday.length}</span>
          </div>
        </div>
      </section>

      {holidayFormOpen && (
        <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm" aria-labelledby="holiday-form-title">
          <div className="flex items-center justify-between gap-3">
            <h2 id="holiday-form-title" className="font-medium text-slate-800">
              {editingHoliday ? 'Редактирование праздника' : 'Новый праздничный день'}
            </h2>
            <button type="button" onClick={closeHolidayForm} className="rounded-lg p-2 text-slate-400 hover:bg-slate-50 hover:text-slate-600" aria-label="Закрыть форму праздника">
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-[180px_minmax(260px,1fr)_auto] sm:items-end">
            <label className="block text-sm font-medium text-slate-700">
              Дата
              <input
                type="date"
                value={holidayForm.date}
                onChange={(event) => setHolidayForm((current) => ({ ...current, date: event.target.value }))}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
            </label>
            <label className="block text-sm font-medium text-slate-700">
              Название праздника
              <input
                type="text"
                value={holidayForm.name}
                onChange={(event) => setHolidayForm((current) => ({ ...current, name: event.target.value }))}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                placeholder="Например, День Победы"
              />
            </label>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={closeHolidayForm} className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
                Отмена
              </button>
              <button type="button" onClick={handleHolidaySubmit} disabled={savingHoliday} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50">
                {savingHoliday ? 'Сохранение...' : 'Сохранить'}
              </button>
            </div>
          </div>
        </section>
      )}

      {formOpen && (
        <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm" aria-labelledby="absence-form-title">
          <div className="flex items-center justify-between gap-3">
            <h2 id="absence-form-title" className="font-medium text-slate-800">
              {editing ? 'Редактирование отсутствия' : 'Новое отсутствие'}
            </h2>
            <button type="button" onClick={closeForm} className="rounded-lg p-2 text-slate-400 hover:bg-slate-50 hover:text-slate-600" aria-label="Закрыть форму">
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <label className="block text-sm font-medium text-slate-700 lg:col-span-2">
              Сотрудник
              <select
                value={form.user_id}
                onChange={(event) => setForm((current) => ({ ...current, user_id: event.target.value }))}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              >
                <option value="">Выберите сотрудника</option>
                {users.map((user) => (
                  <option key={user.id} value={user.id}>{user.full_name}</option>
                ))}
              </select>
            </label>
            <label className="block text-sm font-medium text-slate-700">
              Начало
              <input
                type="date"
                value={form.start_date}
                onChange={(event) => setForm((current) => ({ ...current, start_date: event.target.value }))}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
            </label>
            <label className="block text-sm font-medium text-slate-700">
              Конец
              <input
                type="date"
                value={form.end_date}
                onChange={(event) => setForm((current) => ({ ...current, end_date: event.target.value }))}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
            </label>
            <label className="block text-sm font-medium text-slate-700">
              Тип
              <select
                value={form.type}
                onChange={(event) => setForm((current) => ({ ...current, type: event.target.value as AbsenceType }))}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              >
                {Object.entries(TYPE_LABELS).map(([type, label]) => (
                  <option key={type} value={type}>{label}</option>
                ))}
              </select>
            </label>
          </div>
          <div className="mt-3 grid gap-3 lg:grid-cols-[1fr_auto] lg:items-end">
            <label className="block text-sm font-medium text-slate-700">
              Комментарий
              <input
                type="text"
                value={form.comment}
                onChange={(event) => setForm((current) => ({ ...current, comment: event.target.value }))}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
            </label>
            <label className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={form.affects_plan}
                onChange={(event) => setForm((current) => ({ ...current, affects_plan: event.target.checked }))}
                className="h-4 w-4 rounded border-slate-300 text-primary focus:ring-primary/30"
              />
              Уменьшает план
            </label>
          </div>
          <div className="mt-4 flex justify-end gap-2">
            <button type="button" onClick={closeForm} className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
              Отмена
            </button>
            <button type="button" onClick={handleSubmit} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50">
              {saving ? 'Сохранение...' : 'Сохранить'}
            </button>
          </div>
        </section>
      )}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm" aria-labelledby="absence-calendar-title">
          <div className="mb-4 flex items-center gap-2">
            <CalendarDays className="h-5 w-5 text-slate-500" aria-hidden="true" />
            <h2 id="absence-calendar-title" className="font-medium text-slate-800">Календарь</h2>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-7">
            {days.map((day) => {
              const items = absencesByDay.get(day) ?? []
              const holidayItems = holidaysByDay.get(day) ?? []
              return (
                <div
                  key={day}
                  className={cn(
                    'min-h-28 rounded-lg border p-2 text-xs',
                    items.length || holidayItems.length ? 'border-primary/50 bg-primary/5' : 'border-slate-200 bg-white',
                    isWeekend(day) && 'bg-slate-50 text-slate-400'
                  )}
                >
                  <div className="mb-2 font-medium text-slate-700">{shortDay(day)}</div>
                  <div className="space-y-1">
                    {holidayItems.map((holiday) => (
                      <span key={holiday.id} className={cn('block truncate rounded border px-1.5 py-0.5', HOLIDAY_STYLE)} title={holiday.name}>
                        {holiday.name}
                      </span>
                    ))}
                    {items.slice(0, 3).map((absence) => (
                      <span key={absence.id} className={cn('block truncate rounded border px-1.5 py-0.5', TYPE_STYLES[absence.type])} title={absence.user_name}>
                        {absence.user_name}
                      </span>
                    ))}
                    {items.length > 3 && <span className="block text-slate-400">+{items.length - 3}</span>}
                  </div>
                </div>
              )
            })}
          </div>
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm" aria-labelledby="absence-list-title">
          <h2 id="absence-list-title" className="font-medium text-slate-800">Список</h2>
          <div className="mt-4 space-y-3">
            {loading && <p className="text-sm text-slate-500">Загрузка...</p>}
            {!loading && absences.length === 0 && holidays.length === 0 && <p className="text-sm text-slate-500">Нет отсутствий</p>}
            {!loading && holidays.map((holiday) => (
              <article key={holiday.id} className="rounded-lg border border-slate-200 p-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate font-medium text-slate-900">{holiday.name}</p>
                    <p className="mt-1 text-xs text-slate-500">{formatDate(holiday.date)}</p>
                  </div>
                  <span className={cn('shrink-0 rounded border px-2 py-0.5 text-xs font-medium', HOLIDAY_STYLE)}>
                    Праздник
                  </span>
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                  <span>{isWeekend(holiday.date) ? 0 : 1} раб. дн.</span>
                  <span>для всех сотрудников</span>
                </div>
                {canEdit && (
                  <div className="mt-3 flex justify-end gap-2">
                    <button type="button" onClick={() => openEditHoliday(holiday)} className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-slate-500 hover:bg-slate-50 hover:text-slate-700">
                      <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                      Изменить
                    </button>
                    <button type="button" onClick={() => handleDeleteHoliday(holiday)} className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-red-500 hover:bg-red-50 hover:text-red-700">
                      <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                      Удалить
                    </button>
                  </div>
                )}
              </article>
            ))}
            {!loading && absences.map((absence) => (
              <article key={absence.id} className="rounded-lg border border-slate-200 p-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate font-medium text-slate-900">{absence.user_name}</p>
                    <p className="mt-1 text-xs text-slate-500">{formatDate(absence.start_date)} - {formatDate(absence.end_date)}</p>
                  </div>
                  <span className={cn('shrink-0 rounded border px-2 py-0.5 text-xs font-medium', TYPE_STYLES[absence.type])}>
                    {TYPE_LABELS[absence.type]}
                  </span>
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                  <span>{absence.working_days} раб. дн.</span>
                  {!absence.affects_plan && <span>не влияет на план</span>}
                  {absence.comment && <span className="truncate">{absence.comment}</span>}
                </div>
                {canEdit && (
                  <div className="mt-3 flex justify-end gap-2">
                    <button type="button" onClick={() => openEdit(absence)} className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-slate-500 hover:bg-slate-50 hover:text-slate-700">
                      <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                      Изменить
                    </button>
                    <button type="button" onClick={() => handleDelete(absence)} className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-red-500 hover:bg-red-50 hover:text-red-700">
                      <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                      Удалить
                    </button>
                  </div>
                )}
              </article>
            ))}
          </div>
        </section>
      </div>
    </div>
  )
}
