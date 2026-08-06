import { useEffect, useMemo, useState } from 'react'
import {
  ArrowLeft,
  ArrowRight,
  CalendarDays,
  Check,
  CheckCircle2,
  ClipboardCheck,
  Loader2,
  Plus,
  Target,
  Trash2,
  UserRound,
  Users,
  X,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import type {
  Contact,
  GuidedProjectCreate,
  GuidedProjectCreated,
  WorkEntityMilestoneCriticality,
  WorkEntityTaskPriority,
} from '@/api/types'
import { cn } from '@/lib/utils'
import { preventBackdropDismiss, useProtectedModal } from '@/hooks/useProtectedModal'

type PersonOption = {
  id: string
  name: string
  email: string
}

type MilestoneDraft = {
  id: string
  title: string
  acceptanceCriteria: string
  at: string
  decisionOwnerId: string
  criticality: WorkEntityMilestoneCriticality
  criticalityReason: string
}

type TaskDraft = {
  id: string
  title: string
  acceptanceCriteria: string
  startsAt: string
  dueAt: string
  assigneeId: string
  priority: WorkEntityTaskPriority
  targetMilestoneId: string
}

type GuidedProjectWizardProps = {
  contacts: Contact[]
  onClose: () => void
  onCreated: (entityId: string) => Promise<void> | void
}

const steps = [
  { label: 'Результат', icon: Target },
  { label: 'Проверки', icon: CheckCircle2 },
  { label: 'Операции', icon: ClipboardCheck },
  { label: 'Команда', icon: Users },
] as const

function localDateTime(date: Date) {
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function asIso(value: string) {
  return new Date(value).toISOString()
}

function draftId() {
  return globalThis.crypto?.randomUUID?.() ??
    `draft-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function contactPerson(contact: Contact): PersonOption {
  return contact.direction === 'outgoing'
    ? {
        id: contact.recipient_id,
        name: contact.recipient_name,
        email: contact.recipient_email,
      }
    : {
        id: contact.requester_id,
        name: contact.requester_name,
        email: contact.requester_email,
      }
}

function newMilestone(at: string): MilestoneDraft {
  return {
    id: draftId(),
    title: '',
    acceptanceCriteria: '',
    at,
    decisionOwnerId: '',
    criticality: 'control',
    criticalityReason: '',
  }
}

function newTask(startsAt: string, dueAt: string, targetMilestoneId: string): TaskDraft {
  return {
    id: draftId(),
    title: '',
    acceptanceCriteria: '',
    startsAt,
    dueAt,
    assigneeId: '',
    priority: 'medium',
    targetMilestoneId,
  }
}

function FieldLabel({
  title,
  hint,
}: {
  title: string
  hint?: string
}) {
  return (
    <span className="mb-1.5 block">
      <span className="block text-sm font-medium text-slate-800">{title}</span>
      {hint && <span className="mt-0.5 block text-xs leading-5 text-slate-500">{hint}</span>}
    </span>
  )
}

export function GuidedProjectWizard({
  contacts,
  onClose,
  onCreated,
}: GuidedProjectWizardProps) {
  const { user } = useAuth()
  const initialStart = useMemo(() => {
    const start = new Date()
    start.setSeconds(0, 0)
    return localDateTime(start)
  }, [])
  const initialDue = useMemo(() => {
    const due = new Date()
    due.setDate(due.getDate() + 30)
    due.setHours(18, 0, 0, 0)
    return localDateTime(due)
  }, [])
  const [step, setStep] = useState(0)
  const [title, setTitle] = useState('')
  const [outcome, setOutcome] = useState('')
  const [successCriteria, setSuccessCriteria] = useState('')
  const [constraints, setConstraints] = useState('')
  const [startsAt, setStartsAt] = useState(initialStart)
  const [dueAt, setDueAt] = useState(initialDue)
  const [milestones, setMilestones] = useState<MilestoneDraft[]>([])
  const [tasks, setTasks] = useState<TaskDraft[]>([])
  const [selectedMemberIds, setSelectedMemberIds] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const panelRef = useProtectedModal<HTMLDivElement>()

  const acceptedContacts = useMemo(
    () =>
      contacts
        .filter((contact) => contact.status === 'accepted')
        .map(contactPerson)
        .sort((left, right) => left.name.localeCompare(right.name, 'ru')),
    [contacts],
  )
  const people = useMemo<PersonOption[]>(
    () => [
      ...(user
        ? [{ id: user.id, name: `${user.full_name} (вы)`, email: user.email }]
        : []),
      ...acceptedContacts.filter((contact) => selectedMemberIds.includes(contact.id)),
    ],
    [acceptedContacts, selectedMemberIds, user],
  )
  const sortedMilestones = useMemo(
    () =>
      [...milestones].sort(
        (left, right) => new Date(left.at).getTime() - new Date(right.at).getTime(),
      ),
    [milestones],
  )

  useEffect(() => {
    const availableIds = new Set(people.map((person) => person.id))
    setMilestones((current) =>
      current.map((item) =>
        item.decisionOwnerId && !availableIds.has(item.decisionOwnerId)
          ? { ...item, decisionOwnerId: '' }
          : item,
      ),
    )
    setTasks((current) =>
      current.map((item) =>
        item.assigneeId && !availableIds.has(item.assigneeId)
          ? { ...item, assigneeId: '' }
          : item,
      ),
    )
  }, [people])

  const ensureFinalMilestone = () => {
    if (milestones.length > 0) return
    setMilestones([
      {
        ...newMilestone(dueAt),
        title: 'Финальный результат принят',
        acceptanceCriteria: successCriteria.trim(),
        criticality: 'key',
        criticalityReason: 'Подтверждает достижение результата проекта',
      },
    ])
  }

  const validateStep = () => {
    if (step === 0) {
      if (!title.trim() || !outcome.trim() || !successCriteria.trim()) {
        toast.error('Заполните название, результат и критерии успеха')
        return false
      }
      if (!startsAt || !dueAt || new Date(dueAt) <= new Date(startsAt)) {
        toast.error('Проверьте даты начала и завершения')
        return false
      }
    }
    if (step === 1) {
      if (milestones.length === 0) {
        toast.error('Добавьте хотя бы одну контрольную точку')
        return false
      }
      if (
        milestones.some(
          (item) =>
            !item.title.trim() ||
            !item.acceptanceCriteria.trim() ||
            !item.at ||
            new Date(item.at) < new Date(startsAt) ||
            new Date(item.at) > new Date(dueAt) ||
            (item.criticality !== 'control' && !item.criticalityReason.trim()),
        )
      ) {
        toast.error('Заполните обязательные поля контрольных точек и проверьте даты')
        return false
      }
      const dates = sortedMilestones.map((item) => new Date(item.at).getTime())
      if (new Set(dates).size !== dates.length) {
        toast.error('Контрольные точки должны иметь разные даты')
        return false
      }
    }
    if (step === 2) {
      if (
        tasks.some(
          (item) =>
            !item.title.trim() ||
            !item.acceptanceCriteria.trim() ||
            !item.startsAt ||
            !item.dueAt ||
            !item.targetMilestoneId ||
            new Date(item.dueAt) <= new Date(item.startsAt) ||
            new Date(item.startsAt) < new Date(startsAt) ||
            new Date(item.dueAt) > new Date(dueAt) ||
            new Date(item.dueAt) >
              new Date(
                milestones.find((milestone) => milestone.id === item.targetMilestoneId)?.at ||
                  dueAt,
              ),
        )
      ) {
        toast.error('Заполните операции и завершите каждую до связанной проверки')
        return false
      }
    }
    return true
  }

  const nextStep = () => {
    if (!validateStep()) return
    if (step === 0) ensureFinalMilestone()
    setStep((current) => Math.min(current + 1, steps.length - 1))
  }

  const addMilestone = () => {
    const fallbackAt = milestones.length
      ? milestones[milestones.length - 1].at
      : dueAt
    setMilestones((current) => [...current, newMilestone(fallbackAt)])
  }

  const addTask = () => {
    const target = sortedMilestones[sortedMilestones.length - 1]
    if (!target) {
      toast.error('Сначала добавьте контрольную точку')
      return
    }
    setTasks((current) => [
      ...current,
      newTask(startsAt, target.at, target.id),
    ])
  }

  const submit = async () => {
    if (!validateStep() || !user) return
    const orderedMilestones = sortedMilestones
    const milestoneIndex = new Map(
      orderedMilestones.map((milestone, index) => [milestone.id, index]),
    )
    const payload: GuidedProjectCreate = {
      title: title.trim(),
      outcome_statement: outcome.trim(),
      success_criteria: successCriteria.trim(),
      constraints: constraints.trim() || null,
      starts_at: asIso(startsAt),
      due_at: asIso(dueAt),
      members: selectedMemberIds.map((userId) => ({
        user_id: userId,
        role: 'participant',
      })),
      milestones: orderedMilestones.map((milestone) => ({
        title: milestone.title.trim(),
        acceptance_criteria: milestone.acceptanceCriteria.trim(),
        baseline_at: asIso(milestone.at),
        decision_owner_id: milestone.decisionOwnerId || null,
        criticality: milestone.criticality,
        criticality_reason: milestone.criticalityReason.trim() || null,
      })),
      tasks: tasks.map((task) => ({
        title: task.title.trim(),
        acceptance_criteria: task.acceptanceCriteria.trim(),
        baseline_starts_at: asIso(task.startsAt),
        baseline_due_at: asIso(task.dueAt),
        assignee_id: task.assigneeId || null,
        priority: task.priority,
        target_milestone_index: milestoneIndex.get(task.targetMilestoneId) ?? 0,
      })),
    }
    setBusy(true)
    try {
      const result = await api.post<GuidedProjectCreated>(
        '/api/project-cockpit/projects',
        payload,
      )
      toast.success('Черновик проекта создан')
      await onCreated(result.entity_id)
      onClose()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось создать проект')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-slate-950/60 sm:items-center sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="guided-project-title"
      onPointerDown={preventBackdropDismiss}
    >
      <div
        ref={panelRef}
        tabIndex={-1}
        className="flex max-h-[96vh] w-full flex-col overflow-hidden rounded-t-lg bg-white shadow-2xl sm:max-w-5xl sm:rounded-lg"
      >
        <header className="flex items-start justify-between gap-4 border-b border-slate-200 px-4 py-3 sm:px-6">
          <div>
            <h2 id="guided-project-title" className="text-lg font-semibold text-slate-900">
              Новый проект
            </h2>
            <p className="mt-0.5 text-xs text-slate-500">
              Планируем от проверяемого результата к конкретным операциям.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 disabled:opacity-40"
            aria-label="Закрыть"
          >
            <X className="h-5 w-5" />
          </button>
        </header>

        <div className="border-b border-slate-200 px-4 py-3 sm:px-6">
          <ol className="grid grid-cols-4 gap-2" aria-label="Шаги создания проекта">
            {steps.map(({ label, icon: Icon }, index) => (
              <li key={label} className="min-w-0">
                <button
                  type="button"
                  onClick={() => index < step && setStep(index)}
                  disabled={index > step || busy}
                  className={cn(
                    'flex w-full items-center gap-2 border-b-2 pb-2 text-left text-xs font-medium transition sm:text-sm',
                    index === step
                      ? 'border-primary text-primary'
                      : index < step
                        ? 'border-emerald-500 text-emerald-700'
                        : 'border-slate-200 text-slate-400',
                  )}
                >
                  <span
                    className={cn(
                      'inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full',
                      index === step
                        ? 'bg-primary text-primary-foreground'
                        : index < step
                          ? 'bg-emerald-100 text-emerald-700'
                          : 'bg-slate-100',
                    )}
                  >
                    {index < step ? <Check className="h-4 w-4" /> : <Icon className="h-4 w-4" />}
                  </span>
                  <span className="hidden truncate sm:block">{label}</span>
                </button>
              </li>
            ))}
          </ol>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
          {step === 0 && (
            <div className="mx-auto max-w-3xl space-y-5">
              <div>
                <p className="text-xs font-semibold uppercase text-primary">Шаг 1</p>
                <h3 className="mt-1 text-xl font-semibold text-slate-900">
                  Что должно измениться к концу проекта?
                </h3>
              </div>
              <label className="block">
                <FieldLabel title="Название проекта" />
                <input
                  autoFocus
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  maxLength={240}
                  className="h-11 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
                  placeholder="Например: Сигнал «не беспокоить» в коворкинге"
                />
              </label>
              <label className="block">
                <FieldLabel
                  title="Ожидаемый результат"
                  hint="Опишите наблюдаемое состояние, а не перечень действий."
                />
                <textarea
                  value={outcome}
                  onChange={(event) => setOutcome(event.target.value)}
                  rows={4}
                  className="w-full resize-y rounded-lg border border-slate-200 px-3 py-2 text-sm leading-6 outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
                  placeholder="На 100 рабочих местах действует понятный сигнал «не беспокоить»..."
                />
              </label>
              <label className="block">
                <FieldLabel
                  title="Как поймем, что результат достигнут"
                  hint="Укажите факты, документы, измерения или решение о приемке."
                />
                <textarea
                  value={successCriteria}
                  onChange={(event) => setSuccessCriteria(event.target.value)}
                  rows={3}
                  className="w-full resize-y rounded-lg border border-slate-200 px-3 py-2 text-sm leading-6 outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
                  placeholder="Флажки размещены; инструкция опубликована; пилот принят..."
                />
              </label>
              <div className="grid gap-4 sm:grid-cols-2">
                <label>
                  <FieldLabel title="Начало" />
                  <input
                    type="datetime-local"
                    value={startsAt}
                    onChange={(event) => setStartsAt(event.target.value)}
                    className="h-11 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-primary"
                  />
                </label>
                <label>
                  <FieldLabel title="Конечный срок" />
                  <input
                    type="datetime-local"
                    value={dueAt}
                    min={startsAt}
                    onChange={(event) => setDueAt(event.target.value)}
                    className="h-11 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-primary"
                  />
                </label>
              </div>
              <label className="block">
                <FieldLabel
                  title="Ограничения"
                  hint="Бюджет, обязательные согласования, недоступные периоды или иные границы."
                />
                <textarea
                  value={constraints}
                  onChange={(event) => setConstraints(event.target.value)}
                  rows={2}
                  className="w-full resize-y rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-primary"
                />
              </label>
            </div>
          )}

          {step === 1 && (
            <div className="space-y-4">
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold uppercase text-primary">Шаг 2</p>
                  <h3 className="mt-1 text-xl font-semibold text-slate-900">
                    Где нужно принять результат или решение?
                  </h3>
                  <p className="mt-1 max-w-2xl text-sm text-slate-500">
                    Контрольная точка занимает одну дату. Если действие занимает время,
                    добавьте его на следующем шаге как операцию.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={addMilestone}
                  className="inline-flex h-10 items-center gap-2 rounded-lg bg-primary px-3 text-sm font-medium text-primary-foreground"
                >
                  <Plus className="h-4 w-4" />
                  Добавить проверку
                </button>
              </div>
              <div className="space-y-3">
                {milestones.map((milestone, index) => (
                  <section
                    key={milestone.id}
                    className="rounded-lg border border-slate-200 bg-slate-50/60 p-3"
                  >
                    <div className="flex items-start gap-3">
                      <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-xs font-semibold text-emerald-700">
                        {index + 1}
                      </span>
                      <div className="grid min-w-0 flex-1 gap-3 lg:grid-cols-[minmax(0,1.4fr)_minmax(190px,.6fr)]">
                        <label>
                          <FieldLabel title="Что должно быть подтверждено" />
                          <input
                            value={milestone.title}
                            onChange={(event) =>
                              setMilestones((current) =>
                                current.map((item) =>
                                  item.id === milestone.id
                                    ? { ...item, title: event.target.value }
                                    : item,
                                ),
                              )
                            }
                            className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-primary"
                          />
                        </label>
                        <label>
                          <FieldLabel title="Дата решения" />
                          <input
                            type="datetime-local"
                            value={milestone.at}
                            min={startsAt}
                            max={dueAt}
                            onChange={(event) =>
                              setMilestones((current) =>
                                current.map((item) =>
                                  item.id === milestone.id
                                    ? { ...item, at: event.target.value }
                                    : item,
                                ),
                              )
                            }
                            className="h-10 w-full rounded-lg border border-slate-200 bg-white px-2 text-sm outline-none focus:border-primary"
                          />
                        </label>
                        <label className="lg:col-span-2">
                          <FieldLabel title="Критерий прохождения" />
                          <textarea
                            value={milestone.acceptanceCriteria}
                            onChange={(event) =>
                              setMilestones((current) =>
                                current.map((item) =>
                                  item.id === milestone.id
                                    ? { ...item, acceptanceCriteria: event.target.value }
                                    : item,
                                ),
                              )
                            }
                            rows={2}
                            className="w-full resize-y rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-primary"
                          />
                        </label>
                        <label>
                          <FieldLabel title="Влияние на проект" />
                          <select
                            value={milestone.criticality}
                            onChange={(event) =>
                              setMilestones((current) =>
                                current.map((item) =>
                                  item.id === milestone.id
                                    ? {
                                        ...item,
                                        criticality: event.target
                                          .value as WorkEntityMilestoneCriticality,
                                      }
                                    : item,
                                ),
                              )
                            }
                            className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-primary"
                          >
                            <option value="control">Контроль хода исполнения</option>
                            <option value="key">Открывает следующий шаг</option>
                            <option value="critical">Определяет успех проекта</option>
                          </select>
                        </label>
                        {milestone.criticality !== 'control' && (
                          <label>
                            <FieldLabel title="Почему это важно" />
                            <input
                              value={milestone.criticalityReason}
                              onChange={(event) =>
                                setMilestones((current) =>
                                  current.map((item) =>
                                    item.id === milestone.id
                                      ? { ...item, criticalityReason: event.target.value }
                                      : item,
                                  ),
                                )
                              }
                              className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-primary"
                            />
                          </label>
                        )}
                      </div>
                      <button
                        type="button"
                        onClick={() =>
                          setMilestones((current) =>
                            current.filter((item) => item.id !== milestone.id),
                          )
                        }
                        className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-slate-400 hover:bg-red-50 hover:text-red-600"
                        aria-label="Удалить контрольную точку"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </section>
                ))}
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-4">
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold uppercase text-primary">Шаг 3</p>
                  <h3 className="mt-1 text-xl font-semibold text-slate-900">
                    Что нужно сделать до каждой проверки?
                  </h3>
                  <p className="mt-1 max-w-2xl text-sm text-slate-500">
                    Операция занимает время и заканчивается проверяемым результатом.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={addTask}
                  className="inline-flex h-10 items-center gap-2 rounded-lg bg-primary px-3 text-sm font-medium text-primary-foreground"
                >
                  <Plus className="h-4 w-4" />
                  Добавить операцию
                </button>
              </div>
              {tasks.length === 0 ? (
                <div className="rounded-lg border border-dashed border-slate-300 px-5 py-10 text-center">
                  <ClipboardCheck className="mx-auto h-7 w-7 text-slate-300" />
                  <p className="mt-2 text-sm font-medium text-slate-700">
                    Операции пока не добавлены
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    Проект можно сохранить только с проверками, но readiness попросит
                    добавить исполнимый scope до активации.
                  </p>
                </div>
              ) : (
                <div className="space-y-3">
                  {tasks.map((task, index) => (
                    <section
                      key={task.id}
                      className="rounded-lg border border-slate-200 bg-slate-50/60 p-3"
                    >
                      <div className="flex items-start gap-3">
                        <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-sky-100 text-xs font-semibold text-sky-700">
                          {index + 1}
                        </span>
                        <div className="grid min-w-0 flex-1 gap-3 lg:grid-cols-2">
                          <label className="lg:col-span-2">
                            <FieldLabel title="Что нужно сделать" />
                            <input
                              value={task.title}
                              onChange={(event) =>
                                setTasks((current) =>
                                  current.map((item) =>
                                    item.id === task.id
                                      ? { ...item, title: event.target.value }
                                      : item,
                                  ),
                                )
                              }
                              className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-primary"
                            />
                          </label>
                          <label className="lg:col-span-2">
                            <FieldLabel title="Какой результат операции примем" />
                            <textarea
                              value={task.acceptanceCriteria}
                              onChange={(event) =>
                                setTasks((current) =>
                                  current.map((item) =>
                                    item.id === task.id
                                      ? { ...item, acceptanceCriteria: event.target.value }
                                      : item,
                                  ),
                                )
                              }
                              rows={2}
                              className="w-full resize-y rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-primary"
                            />
                          </label>
                          <label>
                            <FieldLabel title="Начало операции" />
                            <input
                              type="datetime-local"
                              value={task.startsAt}
                              min={startsAt}
                              max={task.dueAt || dueAt}
                              onChange={(event) =>
                                setTasks((current) =>
                                  current.map((item) =>
                                    item.id === task.id
                                      ? { ...item, startsAt: event.target.value }
                                      : item,
                                  ),
                                )
                              }
                              className="h-10 w-full rounded-lg border border-slate-200 bg-white px-2 text-sm outline-none focus:border-primary"
                            />
                          </label>
                          <label>
                            <FieldLabel title="Завершить до" />
                            <input
                              type="datetime-local"
                              value={task.dueAt}
                              min={task.startsAt}
                              max={
                                milestones.find(
                                  (milestone) => milestone.id === task.targetMilestoneId,
                                )?.at || dueAt
                              }
                              onChange={(event) =>
                                setTasks((current) =>
                                  current.map((item) =>
                                    item.id === task.id
                                      ? { ...item, dueAt: event.target.value }
                                      : item,
                                  ),
                                )
                              }
                              className="h-10 w-full rounded-lg border border-slate-200 bg-white px-2 text-sm outline-none focus:border-primary"
                            />
                          </label>
                          <label>
                            <FieldLabel title="Готовит к проверке" />
                            <select
                              value={task.targetMilestoneId}
                              onChange={(event) =>
                                setTasks((current) =>
                                  current.map((item) =>
                                    item.id === task.id
                                      ? { ...item, targetMilestoneId: event.target.value }
                                      : item,
                                  ),
                                )
                              }
                              className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-primary"
                            >
                              {sortedMilestones.map((milestone) => (
                                <option key={milestone.id} value={milestone.id}>
                                  {milestone.title || 'Без названия'} ·{' '}
                                  {new Date(milestone.at).toLocaleDateString('ru-RU')}
                                </option>
                              ))}
                            </select>
                          </label>
                          <label>
                            <FieldLabel title="Приоритет исполнения" />
                            <select
                              value={task.priority}
                              onChange={(event) =>
                                setTasks((current) =>
                                  current.map((item) =>
                                    item.id === task.id
                                      ? {
                                          ...item,
                                          priority: event.target.value as WorkEntityTaskPriority,
                                        }
                                      : item,
                                  ),
                                )
                              }
                              className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-primary"
                            >
                              <option value="low">Низкий</option>
                              <option value="medium">Средний</option>
                              <option value="high">Высокий</option>
                              <option value="critical">Критический</option>
                            </select>
                          </label>
                        </div>
                        <button
                          type="button"
                          onClick={() =>
                            setTasks((current) =>
                              current.filter((item) => item.id !== task.id),
                            )
                          }
                          className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-slate-400 hover:bg-red-50 hover:text-red-600"
                          aria-label="Удалить операцию"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </section>
                  ))}
                </div>
              )}
            </div>
          )}

          {step === 3 && (
            <div className="grid gap-6 lg:grid-cols-[minmax(0,.8fr)_minmax(0,1.2fr)]">
              <section>
                <p className="text-xs font-semibold uppercase text-primary">Шаг 4</p>
                <h3 className="mt-1 text-xl font-semibold text-slate-900">
                  Кто входит в команду?
                </h3>
                <p className="mt-1 text-sm text-slate-500">
                  Выберите принятые контакты. Участники увидят проект и назначенную им
                  операцию.
                </p>
                <div className="mt-4 divide-y divide-slate-100 rounded-lg border border-slate-200">
                  {acceptedContacts.length === 0 ? (
                    <p className="px-4 py-8 text-center text-sm text-slate-500">
                      Принятых контактов пока нет. Проект можно создать для себя и
                      открыть доступ позднее.
                    </p>
                  ) : (
                    acceptedContacts.map((person) => (
                      <label
                        key={person.id}
                        className="flex min-h-14 cursor-pointer items-center gap-3 px-3 py-2 hover:bg-slate-50"
                      >
                        <input
                          type="checkbox"
                          checked={selectedMemberIds.includes(person.id)}
                          onChange={(event) =>
                            setSelectedMemberIds((current) =>
                              event.target.checked
                                ? [...current, person.id]
                                : current.filter((id) => id !== person.id),
                            )
                          }
                          className="h-4 w-4 rounded border-slate-300 text-primary focus:ring-primary"
                        />
                        <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-slate-100 text-slate-500">
                          <UserRound className="h-4 w-4" />
                        </span>
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-medium text-slate-800">
                            {person.name}
                          </span>
                          <span className="block truncate text-xs text-slate-500">
                            {person.email}
                          </span>
                        </span>
                      </label>
                    ))
                  )}
                </div>
              </section>

              <section>
                <div className="flex items-center gap-2">
                  <CalendarDays className="h-5 w-5 text-primary" />
                  <h3 className="text-base font-semibold text-slate-900">
                    Назначения и проверка
                  </h3>
                </div>
                <div className="mt-4 space-y-4">
                  <div>
                    <h4 className="text-xs font-semibold uppercase text-slate-500">
                      Ответственные за решения
                    </h4>
                    <div className="mt-2 space-y-2">
                      {sortedMilestones.map((milestone) => (
                        <label
                          key={milestone.id}
                          className="grid gap-2 rounded-lg border border-slate-200 p-3 sm:grid-cols-[minmax(0,1fr)_220px] sm:items-center"
                        >
                          <span className="min-w-0 text-sm font-medium text-slate-800">
                            {milestone.title || 'Контрольная точка'}
                          </span>
                          <select
                            value={milestone.decisionOwnerId}
                            onChange={(event) =>
                              setMilestones((current) =>
                                current.map((item) =>
                                  item.id === milestone.id
                                    ? { ...item, decisionOwnerId: event.target.value }
                                    : item,
                                ),
                              )
                            }
                            className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-primary"
                          >
                            <option value="">Назначить позднее</option>
                            {people.map((person) => (
                              <option key={person.id} value={person.id}>
                                {person.name}
                              </option>
                            ))}
                          </select>
                        </label>
                      ))}
                    </div>
                  </div>
                  {tasks.length > 0 && (
                    <div>
                      <h4 className="text-xs font-semibold uppercase text-slate-500">
                        Исполнители операций
                      </h4>
                      <div className="mt-2 space-y-2">
                        {tasks.map((task) => (
                          <label
                            key={task.id}
                            className="grid gap-2 rounded-lg border border-slate-200 p-3 sm:grid-cols-[minmax(0,1fr)_220px] sm:items-center"
                          >
                            <span className="min-w-0 text-sm font-medium text-slate-800">
                              {task.title || 'Операция'}
                            </span>
                            <select
                              value={task.assigneeId}
                              onChange={(event) =>
                                setTasks((current) =>
                                  current.map((item) =>
                                    item.id === task.id
                                      ? { ...item, assigneeId: event.target.value }
                                      : item,
                                  ),
                                )
                              }
                              className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-primary"
                            >
                              <option value="">Назначить позднее</option>
                              {people.map((person) => (
                                <option key={person.id} value={person.id}>
                                  {person.name}
                                </option>
                              ))}
                            </select>
                          </label>
                        ))}
                      </div>
                    </div>
                  )}
                  <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4">
                    <div className="flex items-center gap-2 text-sm font-semibold text-emerald-800">
                      <CheckCircle2 className="h-4 w-4" />
                      Будет создан единый черновик
                    </div>
                    <dl className="mt-3 grid grid-cols-3 gap-3 text-center">
                      <div>
                        <dt className="text-xs text-emerald-700">Проверок</dt>
                        <dd className="mt-0.5 text-lg font-semibold text-emerald-900">
                          {milestones.length}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-xs text-emerald-700">Операций</dt>
                        <dd className="mt-0.5 text-lg font-semibold text-emerald-900">
                          {tasks.length}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-xs text-emerald-700">Участников</dt>
                        <dd className="mt-0.5 text-lg font-semibold text-emerald-900">
                          {selectedMemberIds.length + 1}
                        </dd>
                      </div>
                    </dl>
                  </div>
                </div>
              </section>
            </div>
          )}
        </div>

        <footer className="flex items-center justify-between gap-3 border-t border-slate-200 bg-slate-50 px-4 py-3 sm:px-6">
          <button
            type="button"
            onClick={() => (step === 0 ? onClose() : setStep((current) => current - 1))}
            disabled={busy}
            className="inline-flex h-11 items-center gap-2 rounded-lg border border-slate-300 bg-white px-4 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-40"
          >
            {step > 0 && <ArrowLeft className="h-4 w-4" />}
            {step === 0 ? 'Отмена' : 'Назад'}
          </button>
          {step < steps.length - 1 ? (
            <button
              type="button"
              onClick={nextStep}
              className="inline-flex h-11 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:opacity-90"
            >
              Продолжить
              <ArrowRight className="h-4 w-4" />
            </button>
          ) : (
            <button
              type="button"
              onClick={() => void submit()}
              disabled={busy}
              className="inline-flex h-11 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
              Создать черновик
            </button>
          )}
        </footer>
      </div>
    </div>
  )
}
