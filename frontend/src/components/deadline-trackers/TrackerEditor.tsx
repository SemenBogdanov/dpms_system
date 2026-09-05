import { useRef, useState, type FormEvent } from 'react'
import { Plus, Save, Trash2 } from 'lucide-react'
import type { PersonalTask } from '@/api/types'
import { ApiError, ApiUnavailableError } from '@/api/client'
import { cn } from '@/lib/utils'
import { TrackerDialog, TrackerField, TrackerIconButton, trackerButton, trackerInput } from './TrackerDialog'
import { localDateInput, validateTrackerForm, type TrackerForm, type TrackerOrganization } from './trackerForm'

export function TrackerEditor({ initial, editing, linkedSource, groups, categories, personalTasks, sourceError, onRetrySources, onClose, onSave }: {
  initial: TrackerForm
  editing: boolean
  linkedSource?: { label: string; assignee: string | null; startsAt: string; dueAt: string; href: string | null }
  groups: TrackerOrganization[]
  categories: TrackerOrganization[]
  personalTasks: PersonalTask[]
  sourceError: string | null
  onRetrySources: () => void
  onClose: () => void
  onSave: (form: TrackerForm) => Promise<void>
}) {
  const [form, setForm] = useState(initial)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [saveError, setSaveError] = useState('')
  const [busy, setBusy] = useState(false)
  const [uncertain, setUncertain] = useState(false)
  const inFlight = useRef(false)
  const selectedTask = personalTasks.find((task) => task.id === form.personalTaskId)
  const linked = Boolean(linkedSource || selectedTask)
  const dirty = JSON.stringify(initial) !== JSON.stringify(form)
  const change = <K extends keyof TrackerForm>(name: K, value: TrackerForm[K]) => {
    setForm((previous) => ({ ...previous, [name]: value }))
    setErrors((previous) => ({ ...previous, [name]: '' }))
  }
  const field = (name: keyof TrackerForm) => ({
    id: `tracker-${name}`, name, className: trackerInput,
    'aria-invalid': Boolean(errors[name]), 'aria-describedby': errors[name] ? `tracker-${name}-error` : undefined,
  })
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (inFlight.current || uncertain) return
    const nextErrors = validateTrackerForm(form, linked)
    if (selectedTask && !selectedTask.due_at) nextErrors.personalTaskId = 'В исходной задаче не задан срок. Сначала укажите его в задаче.'
    setErrors(nextErrors)
    if (Object.keys(nextErrors).length) {
      const first = Object.keys(nextErrors)[0]
      const element = document.getElementById(`tracker-${first}`)
      const details = element?.closest('details')
      if (details) details.open = true
      element?.focus()
      return
    }
    inFlight.current = true
    setBusy(true)
    setSaveError('')
    try { await onSave(form) } catch (error) {
      const unknownOutcome = error instanceof ApiUnavailableError || (error instanceof ApiError && error.status >= 500)
      setUncertain(unknownOutcome)
      setSaveError(unknownOutcome ? 'Ответ сервера потерян. Изменения могли сохраниться. Перед повторным сохранением закройте форму и проверьте актуальный трекер.' : error instanceof Error ? error.message : 'Не удалось сохранить трекер')
    } finally { inFlight.current = false; setBusy(false) }
  }

  return <TrackerDialog title={editing ? 'Редактирование трекера' : 'Новый трекер срока'} dirty={dirty} busy={busy} onClose={onClose}
    footer={<button type="submit" form="deadline-tracker-editor" disabled={busy || uncertain} className={cn(trackerButton, 'border-primary bg-primary text-primary-foreground hover:bg-primary/90 dark:text-primary-foreground')}>
      <Save className="h-4 w-4" aria-hidden="true" />{editing ? 'Сохранить' : 'Создать трекер'}
    </button>}>
    <form id="deadline-tracker-editor" onSubmit={(event) => void submit(event)} noValidate autoComplete="off">
      <fieldset disabled={busy} className="min-w-0 space-y-4">
        {saveError && <p role="alert" className="whitespace-pre-line break-words text-sm text-rose-700 dark:text-rose-300">{saveError}</p>}
        <TrackerField name="title" label="Название" error={errors.title}><input {...field('title')} value={form.title} readOnly={linked} maxLength={200} onChange={(e) => change('title', e.target.value)} /></TrackerField>
        <div className="grid gap-3 sm:grid-cols-2">
          <TrackerField name="groupId" label="Группа"><select {...field('groupId')} value={form.groupId} onChange={(e) => change('groupId', e.target.value)}>
            <option value="">Без группы</option>
            {groups.filter((item) => !item.is_archived || item.id === form.groupId).map((item) => <option key={item.id} value={item.id}>{item.name}{item.is_archived ? ' (архив)' : ''}</option>)}
          </select></TrackerField>
          <TrackerField name="categoryId" label="Категория"><select {...field('categoryId')} value={form.categoryId} onChange={(e) => change('categoryId', e.target.value)}>
            <option value="">Без категории</option>
            {categories.filter((item) => !item.is_archived || item.id === form.categoryId).map((item) => <option key={item.id} value={item.id}>{item.name}{item.is_archived ? ' (архив)' : ''}</option>)}
          </select></TrackerField>
        </div>
        <div role="group" aria-label="Периодичность" className="flex border-b border-slate-200 dark:border-slate-700">
          {(['once', 'recurring'] as const).map((mode) => <button key={mode} type="button" aria-pressed={form.mode === mode} disabled={linked && mode === 'recurring'}
            className={cn('min-h-11 flex-1 border-b-2 px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-50', form.mode === mode ? 'border-primary text-primary' : 'border-transparent text-slate-500')}
            onClick={() => change('mode', mode)}>{mode === 'once' ? 'Разовый' : 'Периодический'}</button>)}
        </div>
        {linked ? <div className="space-y-1 border-l-2 border-sky-300 pl-3 text-sm">
          {linkedSource && !linkedSource.href ? <p>Источник недоступен</p> : <a className="break-words text-primary underline" href={linkedSource?.href || `/personal-tasks?task=${selectedTask?.id}`}>{linkedSource?.label || `Личная задача ${selectedTask?.task_key}`}</a>}
          <p>Исполнитель: {linkedSource?.assignee || selectedTask?.responsible || 'не указан'}</p>
          <p>Старт: {localDateInput(linkedSource?.startsAt || selectedTask?.start_at).replace('T', ' ') || 'не задан'}</p>
          <p>Дедлайн: {localDateInput(linkedSource?.dueAt || selectedTask?.due_at).replace('T', ' ') || 'не задан'}</p>
        </div> : <div className="grid gap-3 sm:grid-cols-2">
          <TrackerField name="startsAt" label="Старт периода" error={errors.startsAt}><input {...field('startsAt')} type="datetime-local" value={form.startsAt} onChange={(e) => change('startsAt', e.target.value)} /></TrackerField>
          <TrackerField name="dueAt" label={form.mode === 'recurring' ? 'Первый срок' : 'Дедлайн'} error={errors.dueAt}><input {...field('dueAt')} type="datetime-local" value={form.dueAt} onChange={(e) => change('dueAt', e.target.value)} /></TrackerField>
          <p className="text-xs text-slate-500 sm:col-span-2">Часовой пояс дат: {Intl.DateTimeFormat().resolvedOptions().timeZone}</p>
        </div>}
        {form.mode === 'recurring' && !linked && <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <TrackerField name="interval" label="Каждые" error={errors.interval}><input {...field('interval')} type="number" min="1" step="1" value={form.interval} onChange={(e) => change('interval', e.target.value)} /></TrackerField>
            <TrackerField name="frequency" label="Период"><select {...field('frequency')} value={form.frequency} onChange={(e) => change('frequency', e.target.value as TrackerForm['frequency'])}>
              <option value="day">День</option><option value="week">Неделя</option><option value="month">Месяц</option><option value="year">Год</option>
            </select></TrackerField>
          </div>
          <TrackerField name="timezone" label="Часовой пояс серии" error={errors.timezone}><input {...field('timezone')} list="tracker-timezones" spellCheck={false} value={form.timezone} onChange={(e) => change('timezone', e.target.value)} /><datalist id="tracker-timezones">{['UTC', 'Europe/Moscow', 'Europe/Berlin', 'Asia/Yekaterinburg', 'Asia/Novosibirsk', 'Asia/Vladivostok', 'America/New_York'].map((zone) => <option key={zone} value={zone} />)}</datalist></TrackerField>
          <div className="grid gap-3 sm:grid-cols-2">
            <TrackerField name="end" label="Окончание"><select {...field('end')} value={form.end} onChange={(e) => change('end', e.target.value as TrackerForm['end'])}><option value="never">Никогда</option><option value="date">До даты</option><option value="count">После N повторений</option></select></TrackerField>
            {form.end === 'date' && <TrackerField name="until" label="Дата окончания" error={errors.until}><input {...field('until')} type="date" value={form.until} onChange={(e) => change('until', e.target.value)} /></TrackerField>}
            {form.end === 'count' && <TrackerField name="count" label="Число повторений" error={errors.count}><input {...field('count')} type="number" min="1" step="1" value={form.count} onChange={(e) => change('count', e.target.value)} /></TrackerField>}
          </div>
        </div>}
        <section className="space-y-2 border-t border-slate-200 pt-3 dark:border-slate-700" aria-label="Напоминания">
          <div className="flex items-center justify-between gap-2"><h3 className="text-sm font-semibold">Напоминания <span className="font-normal text-slate-500">{form.reminders.length}/10</span></h3>
            <TrackerIconButton label="Добавить напоминание" icon={Plus} disabled={busy || form.reminders.length >= 10} onClick={() => change('reminders', [...form.reminders, { value: '1', unit: 'day' }])} /></div>
          {!form.reminders.length && <p className="text-sm text-slate-500">Без напоминаний</p>}
          {form.reminders.map((point, index) => <div key={index} className="space-y-1">
            <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)_44px] items-end gap-2">
              <TrackerField name={`reminder-${index}`} label="За" error={errors[`reminder-${index}`]}><input id={`tracker-reminder-${index}`} aria-label={`Напоминание ${index + 1}: число`} aria-invalid={Boolean(errors[`reminder-${index}`])} aria-describedby={errors[`reminder-${index}`] ? `tracker-reminder-${index}-error` : undefined} className={trackerInput} type="number" min="0" step="1" value={point.value} onChange={(e) => change('reminders', form.reminders.map((item, i) => i === index ? { ...item, value: e.target.value } : item))} /></TrackerField>
              <TrackerField name={`reminder-unit-${index}`} label="До срока"><select id={`tracker-reminder-unit-${index}`} aria-label={`Напоминание ${index + 1}: единица`} className={trackerInput} value={point.unit} onChange={(e) => change('reminders', form.reminders.map((item, i) => i === index ? { ...item, unit: e.target.value as typeof point.unit } : item))}><option value="minute">Минут</option><option value="hour">Часов</option><option value="day">Дней</option><option value="week">Недель</option></select></TrackerField>
              <TrackerIconButton label={`Удалить напоминание ${index + 1}`} icon={Trash2} tone="danger" onClick={() => change('reminders', form.reminders.filter((_, i) => i !== index))} />
            </div>
          </div>)}
        </section>
        <details className="border-t border-slate-200 pt-3 dark:border-slate-700">
          <summary className="min-h-11 cursor-pointer py-2 text-sm font-semibold focus-visible:ring-2 focus-visible:ring-primary">Дополнительно</summary>
          <div className="space-y-3 pt-2">
            <TrackerField name="url" label="URL" error={errors.url}><input {...field('url')} type="url" spellCheck={false} value={form.url} onChange={(e) => change('url', e.target.value)} /></TrackerField>
            <TrackerField name="description" label={linked ? 'Заметки источника' : 'Заметки'}><textarea {...field('description')} rows={3} readOnly={linked} value={form.description} onChange={(e) => change('description', e.target.value)} /></TrackerField>
            <TrackerField name="nextAction" label="Следующее действие" error={errors.nextAction}><input {...field('nextAction')} maxLength={500} value={form.nextAction} onChange={(e) => change('nextAction', e.target.value)} /></TrackerField>
            <TrackerField name="tags" label="Теги через запятую" error={errors.tags}><input {...field('tags')} value={form.tags} onChange={(e) => change('tags', e.target.value)} /></TrackerField>
            {!editing && <TrackerField name="personalTaskId" label="Личная задача" error={errors.personalTaskId}>
              <select {...field('personalTaskId')} value={form.personalTaskId} onChange={(e) => {
                change('personalTaskId', e.target.value)
                const task = personalTasks.find((item) => item.id === e.target.value)
                if (task) {
                  change('mode', 'once'); change('title', task.title); change('description', task.description || '')
                  change('startsAt', localDateInput(task.start_at)); change('dueAt', localDateInput(task.due_at))
                }
              }}><option value="">Без личной задачи</option>{personalTasks.map((task) => <option key={task.id} value={task.id}>{task.task_key} · {task.title}</option>)}</select>
              {sourceError && <div role="alert" className="text-sm text-rose-700">{sourceError} <button type="button" className={trackerButton} onClick={onRetrySources}>Повторить загрузку задач</button></div>}
            </TrackerField>}
          </div>
        </details>
      </fieldset>
    </form>
  </TrackerDialog>
}
