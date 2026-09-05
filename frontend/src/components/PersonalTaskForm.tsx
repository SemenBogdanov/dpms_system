import { useCallback, useContext, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Inbox, Loader2, Save, X } from 'lucide-react'
import { UNSAFE_NavigationContext } from 'react-router-dom'
import { api, ApiError, ApiUnavailableError } from '@/api/client'
import type { PersonalTask, PersonalTaskCategory, PersonalTaskCreate, PersonalTaskPriority, PersonalTaskStatus, QuickNote } from '@/api/types'
import { preventBackdropDismiss, useProtectedModal } from '@/hooks/useProtectedModal'
import { cn } from '@/lib/utils'
import { protectPersonalTaskPop } from './PersonalTaskFormNavigation'

type Props = {
  task: PersonalTask | null
  quickNotes: QuickNote[]
  statusLabels: Record<PersonalTaskStatus, string>
  priorityLabels: Record<PersonalTaskPriority, string>
  categoryLabels: Record<PersonalTaskCategory, string>
  onClose: () => void
  onSaved: () => void
}

function inputDate(value: string | null) {
  if (!value) return ''
  const date = new Date(value)
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
}

function initialForm(task: PersonalTask | null) {
  return {
    title: task?.title || '',
    description: task?.description || '',
    notes: task?.notes || '',
    status: task?.status || 'inbox',
    priority: task?.priority || 'medium',
    category: task?.category || 'work',
    project: task?.project || '',
    context: task?.context || '',
    responsible: task?.responsible || '',
    tags: task?.tags.join(', ') || '',
    acceptance_criteria: task?.acceptance_criteria || '',
    next_step: task?.next_step || '',
    next_step_at: inputDate(task?.next_step_at || null),
    start_at: inputDate(task?.start_at || task?.created_at || new Date().toISOString()),
    due_at: inputDate(task?.due_at || null),
    waiting_for: task?.waiting_for || '',
    blocked_reason: task?.blocked_reason || '',
    impact: task?.impact ? String(task.impact) : '',
    effort: task?.effort ? String(task.effort) : '',
    source_quick_note_id: task?.source_quick_note_id || '',
  }
}

type Values = ReturnType<typeof initialForm>
type Field = keyof Values
type Errors = Partial<Record<Field | '_form', string>>

// BrowserRouter has no data-router blocker. Keep this guard local to the form;
// restore cancelled browser Back/Forward before the router observes popstate.
function useFormNavigationProtection(protectedDraft: boolean, busy: React.MutableRefObject<boolean>, requestDiscard: (leave: () => void) => void) {
  const { navigator } = useContext(UNSAFE_NavigationContext)
  useEffect(() => {
    if (!protectedDraft) return
    const push = navigator.push
    const replace = navigator.replace
    const index = window.history.state?.idx as number | undefined
    let restoringDelta = 0
    let forwarding = false
    const guardedPush: typeof push = (...args) => {
      if (!restoringDelta && !busy.current) requestDiscard(() => push(...args))
    }
    const guardedReplace: typeof replace = (...args) => {
      if (!restoringDelta && !busy.current) requestDiscard(() => replace(...args))
    }
    const onPopState = (event: PopStateEvent) => {
      if (forwarding) return
      event.stopImmediatePropagation()
      if (restoringDelta) {
        const delta = restoringDelta
        restoringDelta = 0
        if (!busy.current) requestDiscard(() => {
          forwarding = true
          window.history.go(delta)
        })
        return
      }
      const nextIndex = event.state?.idx as number | undefined
      if (typeof index === 'number' && typeof nextIndex === 'number' && index !== nextIndex) {
        restoringDelta = nextIndex - index
        window.history.go(index - nextIndex)
      }
    }
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    navigator.push = guardedPush
    navigator.replace = guardedReplace
    const releasePopGuard = protectPersonalTaskPop(onPopState)
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => {
      if (navigator.push === guardedPush) navigator.push = push
      if (navigator.replace === guardedReplace) navigator.replace = replace
      releasePopGuard()
      window.removeEventListener('beforeunload', onBeforeUnload)
    }
  }, [busy, navigator, protectedDraft, requestDiscard])
}

function validationErrors(form: Values, editing: boolean): Errors {
  const errors: Errors = {}
  if (!form.title.trim()) errors.title = 'Укажите название'
  for (const name of ['title', 'project', 'context', 'responsible', 'waiting_for', 'next_step'] as const) {
    const limit = name === 'next_step' ? 500 : 200
    if (form[name].trim().length > limit) errors[name] = `Не более ${limit} символов`
  }
  for (const name of ['start_at', 'due_at', 'next_step_at'] as const) {
    if (form[name] && !Number.isFinite(new Date(form[name]).getTime())) errors[name] = 'Укажите корректную дату'
  }
  if (editing && !form.start_at) errors.start_at = 'Укажите дату старта'
  if (form.start_at && form.due_at && new Date(form.due_at).getTime() <= new Date(form.start_at).getTime()) {
    errors.due_at = 'Дедлайн должен быть позже даты старта'
  }
  if (editing && form.status === 'waiting' && !form.waiting_for.trim()) errors.waiting_for = 'Укажите, что или кого ждем'
  if (editing && form.status === 'blocked' && !form.blocked_reason.trim()) errors.blocked_reason = 'Укажите причину блокировки'
  return errors
}

function requestErrors(error: unknown, form: Values, editing: boolean): Errors {
  const message = error instanceof Error ? error.message : 'Ошибка сохранения. Повторите попытку.'
  if (!(error instanceof ApiError)) return { _form: message }
  const errors: Errors = {}
  // ApiError exposes flattened "field: message" lines, not the raw 422 detail.
  for (const line of message.split('\n')) {
    const match = line.match(/^(\w+)(?:\.\d+)?:\s*(.+)$/)
    if (match && Object.prototype.hasOwnProperty.call(form, match[1])) {
      errors[match[1] as Field] = match[2]
    } else if (/Дедлайн должен/i.test(line)) {
      errors.due_at = line
    } else if (/что или кого ждем/i.test(line)) {
      errors.waiting_for = line
    } else if (/причину блокировки/i.test(line)) {
      errors.blocked_reason = line
    } else if (/связанная заметка/i.test(line)) {
      errors.source_quick_note_id = line
    } else if (editing && error.status === 409 && /Q-задач|задача Q|очеред|queue_handoff/i.test(`${error.code || ''} ${line}`)) {
      errors.status = line
    } else if (error.status === 422 && line.startsWith('Обязательные поля нельзя очистить:')) {
      for (const name of line.slice(line.indexOf(':') + 1).split(',').map((part) => part.trim())) {
        if (Object.prototype.hasOwnProperty.call(form, name)) errors[name as Field] = 'Поле обязательно'
        else errors._form = line
      }
    } else {
      errors._form = [errors._form, line].filter(Boolean).join('\n')
    }
  }
  for (const name of ['status', 'waiting_for', 'blocked_reason'] as const) {
    const visible = editing && (name === 'status' || (name === 'waiting_for' ? form.status === 'waiting' : form.status === 'blocked'))
    if (errors[name] && !visible) {
      errors._form = [errors._form, errors[name]].filter(Boolean).join('\n')
      delete errors[name]
    }
  }
  return Object.keys(errors).length ? errors : { _form: message }
}

export function PersonalTaskForm({ task, quickNotes, statusLabels, priorityLabels, categoryLabels, onClose, onSaved }: Props) {
  const [baseline] = useState(() => initialForm(task))
  const [form, setForm] = useState(baseline)
  const [errors, setErrors] = useState<Errors>({})
  const [focusAttempt, setFocusAttempt] = useState(0)
  const [busy, setBusy] = useState(false)
  const [uncertain, setUncertain] = useState(false)
  const [discardAction, setDiscardAction] = useState<(() => void) | null>(null)
  const busyRef = useRef(false)
  const panelRef = useProtectedModal<HTMLDivElement>(!discardAction)
  const discardRef = useProtectedModal<HTMLDivElement>(Boolean(discardAction))
  const dirty = (Object.keys(baseline) as Field[]).some((name) => form[name] !== baseline[name])
  const requestDiscard = useCallback((action: () => void) => setDiscardAction(() => action), [])
  useFormNavigationProtection(dirty || busy, busyRef, requestDiscard)

  useEffect(() => {
    const target = panelRef.current?.querySelector<HTMLElement>('[aria-invalid="true"], [data-form-error]')
    if (!target) return
    const details = target.closest('details')
    if (details) details.open = true
    target.focus()
  }, [focusAttempt, panelRef])

  const close = () => {
    if (busyRef.current) return
    if (dirty) requestDiscard(() => undefined)
    else onClose()
  }

  const submit = async () => {
    if (busyRef.current || uncertain) return
    const nextErrors = validationErrors(form, Boolean(task))
    setErrors(nextErrors)
    setFocusAttempt((attempt) => attempt + 1)
    if (Object.keys(nextErrors).length) return
    busyRef.current = true
    setBusy(true)
    const date = (value: string) => value ? new Date(value).toISOString() : null
    const payload: PersonalTaskCreate = {
      ...form,
      title: form.title.trim(),
      description: form.description || null,
      notes: form.notes || null,
      status: task ? form.status as PersonalTaskStatus : 'inbox',
      priority: form.priority as PersonalTaskPriority,
      category: form.category as PersonalTaskCategory,
      project: form.project || null,
      context: form.context || null,
      responsible: form.responsible || null,
      tags: form.tags.split(',').map((tag) => tag.trim()).filter(Boolean).slice(0, 20),
      acceptance_criteria: form.acceptance_criteria || null,
      next_step: form.next_step || null,
      next_step_at: date(form.next_step_at),
      start_at: date(form.start_at),
      due_at: date(form.due_at),
      waiting_for: !task || (task.status !== form.status && form.status !== 'waiting') ? null : form.waiting_for || null,
      blocked_reason: !task || (task.status !== form.status && form.status !== 'blocked') ? null : form.blocked_reason || null,
      impact: form.impact ? Number(form.impact) : null,
      effort: form.effort ? Number(form.effort) : null,
      source_quick_note_id: form.source_quick_note_id || null,
    }
    try {
      if (task) await api.patch<PersonalTask>(`/api/personal-tasks/${task.id}`, payload)
      else await api.post<PersonalTask>('/api/personal-tasks', payload)
    } catch (error) {
      const unknownOutcome = error instanceof ApiUnavailableError || (error instanceof ApiError && error.status >= 500)
      setUncertain(unknownOutcome)
      setErrors(unknownOutcome
        ? { _form: 'Ответ сервера потерян. Изменения могли сохраниться. Перед повторным сохранением закройте форму и проверьте список задач.' }
        : requestErrors(error, form, Boolean(task)))
      setFocusAttempt((attempt) => attempt + 1)
      return
    } finally {
      busyRef.current = false
      setBusy(false)
    }
    onSaved()
  }

  const field = (name: Field, label: string, options: { type?: string; rows?: number; choices?: [string, string][] } = {}) => {
    const error = errors[name]
    const props = {
      id: `personal-form-${name}`,
      name,
      value: form[name],
      'aria-invalid': error ? true as const : undefined,
      'aria-describedby': error ? `personal-error-${name}` : undefined,
      onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
        const value = event.target.value
        setForm((current) => ({ ...current, [name]: value }))
        setErrors((current) => {
          const next = { ...current }
          delete next[name]
          if (!uncertain) delete next._form
          return next
        })
      },
      className: cn('min-h-11 w-full min-w-0 max-w-full rounded-lg border bg-surface px-3 py-2 text-base font-normal text-foreground outline-none focus-visible:ring-2 focus-visible:ring-primary sm:text-sm', error ? 'border-rose-500' : 'border-border'),
    }
    return (
      <div className="min-w-0 space-y-1">
        <label htmlFor={props.id} className="block text-sm font-medium text-foreground">{label}</label>
        {options.choices ? (
          <select {...props}>{options.choices.map(([value, text]) => <option key={value} value={value}>{text}</option>)}</select>
        ) : options.rows ? (
          <textarea {...props} autoComplete="off" rows={options.rows} className={cn(props.className, 'resize-y')} />
        ) : (
          <input {...props} autoComplete="off" type={options.type || 'text'} />
        )}
        {error && <p id={`personal-error-${name}`} className="break-words text-sm text-rose-700 dark:text-rose-300" aria-live="polite">{error}</p>}
      </div>
    )
  }

  const sourceChoices: [string, string][] = [['', 'Без связанной заметки'], ...quickNotes.map((note): [string, string] => [note.id, note.title])]
  if (form.source_quick_note_id && !quickNotes.some((note) => note.id === form.source_quick_note_id)) {
    sourceChoices.push([form.source_quick_note_id, 'Текущая связанная заметка'])
  }
  const scoreChoices: [string, string][] = [['', 'Не задано'], ...[1, 2, 3, 4, 5].map((value): [string, string] => [String(value), String(value)])]

  return createPortal(
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/50" data-testid="personal-form-backdrop" onPointerDown={preventBackdropDismiss}>
      <div ref={panelRef} role="dialog" aria-modal="true" aria-hidden={discardAction ? true : undefined} aria-labelledby="personal-task-form-heading" tabIndex={-1} className="flex h-[100dvh] w-full min-w-0 flex-col bg-surface text-foreground shadow-xl sm:max-w-xl sm:border-l sm:border-border">
        <header className="flex shrink-0 items-center justify-between gap-3 border-b border-border px-4 pb-3 pt-[max(0.75rem,env(safe-area-inset-top))] sm:px-6">
          <div className="min-w-0">
            <h2 id="personal-task-form-heading" className="break-words text-base font-semibold">{task ? `Редактирование ${task.task_key}` : 'Новая личная задача'}</h2>
            {!task && <span className="mt-1 inline-flex items-center gap-1 text-xs text-muted-foreground"><Inbox aria-hidden="true" className="h-3.5 w-3.5" />Входящие</span>}
          </div>
          <button type="button" onClick={close} disabled={busy} title="Закрыть форму" aria-label="Закрыть форму" className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-muted-foreground hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary disabled:opacity-50"><X aria-hidden="true" className="h-5 w-5" /></button>
        </header>
        <form noValidate onSubmit={(event) => { event.preventDefault(); void submit() }} className="flex min-h-0 flex-1 flex-col" aria-busy={busy}>
          <fieldset disabled={busy} className="min-h-0 min-w-0 flex-1 space-y-4 overflow-y-auto overscroll-contain px-4 py-4 sm:px-6">
            {field('title', 'Название', { rows: 2 })}
            {field('next_step', 'Следующий шаг', { rows: 2 })}
            {field('due_at', 'Срок', { type: 'datetime-local' })}
            {task && field('status', 'Статус', { choices: Object.entries(statusLabels) })}
            {task && form.status === 'waiting' && field('waiting_for', 'Кого / чего ждем')}
            {task && form.status === 'blocked' && field('blocked_reason', 'Причина блокировки', { rows: 2 })}
            <details className="border-t border-border pt-1">
              <summary tabIndex={0} className="min-h-11 cursor-pointer py-3 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary">Дополнительно</summary>
              <div className="space-y-4 pb-2">
                {field('project', 'Проект / поток')}
                {field('context', 'Контекст')}
                {field('responsible', 'Ответственный / кому поручено')}
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  {field('priority', 'Приоритет', { choices: Object.entries(priorityLabels) })}
                  {field('category', 'Категория', { choices: Object.entries(categoryLabels) })}
                </div>
                {field('start_at', 'Дата старта', { type: 'datetime-local' })}
                {field('next_step_at', 'Дата следующего шага', { type: 'datetime-local' })}
                {field('description', 'Описание', { rows: 3 })}
                {field('acceptance_criteria', 'Критерии готовности / приемки', { rows: 3 })}
                {field('notes', 'Рабочие заметки', { rows: 3 })}
                {field('tags', 'Теги через запятую')}
                <div className="grid grid-cols-2 gap-4">
                  {field('impact', 'Влияние', { choices: scoreChoices })}
                  {field('effort', 'Усилие', { choices: scoreChoices })}
                </div>
                {field('source_quick_note_id', 'Источник: заметка', { choices: sourceChoices })}
              </div>
            </details>
            {errors._form && <p data-form-error tabIndex={-1} role="alert" className="whitespace-pre-line break-words text-sm text-rose-700 outline-none dark:text-rose-300">{errors._form}</p>}
          </fieldset>
          <footer className="flex shrink-0 flex-wrap justify-end gap-2 border-t border-border px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:px-6">
            <button type="button" onClick={close} disabled={busy} className="min-h-11 rounded-lg border border-border px-3 text-sm hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary disabled:opacity-50">Отмена</button>
            <button type="submit" disabled={busy || uncertain} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary disabled:opacity-60">
              {busy ? <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin motion-reduce:animate-none" /> : <Save aria-hidden="true" className="h-4 w-4" />}
              {task ? 'Сохранить' : 'Создать задачу'}
            </button>
          </footer>
        </form>
      </div>
      {discardAction && (
        <div className="absolute inset-0 flex items-center justify-center bg-slate-950/50 p-4" onPointerDown={preventBackdropDismiss}>
          <div ref={discardRef} role="alertdialog" aria-modal="true" aria-labelledby="personal-discard-title" aria-describedby="personal-discard-description" tabIndex={-1} className="w-full max-w-sm rounded-lg border border-border bg-surface p-4 text-foreground shadow-xl">
            <h2 id="personal-discard-title" className="text-base font-semibold">Отменить изменения?</h2>
            <p id="personal-discard-description" className="mt-2 text-sm text-muted-foreground">Несохраненные изменения личной задачи будут потеряны.</p>
            <div className="mt-4 flex flex-wrap justify-end gap-2">
              <button type="button" onClick={() => setDiscardAction(null)} className="min-h-11 rounded-lg border border-border px-3 text-sm hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary">Продолжить заполнение</button>
              <button type="button" onClick={() => { onClose(); discardAction() }} className="min-h-11 rounded-lg border border-rose-300 px-3 text-sm text-rose-700 hover:bg-rose-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary dark:text-rose-300 dark:hover:bg-rose-950">Отменить изменения</button>
            </div>
          </div>
        </div>
      )}
    </div>,
    document.body,
  )
}
