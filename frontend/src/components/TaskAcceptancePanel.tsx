import { useCallback, useEffect, useMemo, useState } from 'react'
import toast from 'react-hot-toast'
import { Check, History, RotateCcw, Send } from 'lucide-react'
import { api } from '@/api/client'
import type { Task, TaskAcceptance, TaskAcceptanceCriterion } from '@/api/types'
import { useAuth } from '@/contexts/AuthContext'

interface TaskAcceptancePanelProps {
  task: Task
  onUpdated?: () => void
}

type Evidence = Record<string, { comment: string; url: string }>
type ReviewComments = Record<string, string>

const kindLabels: Record<TaskAcceptanceCriterion['kind'], string> = {
  required: 'Обязательный',
  optional: 'Необязательный',
  quality_gate: 'Quality gate',
}

const statusLabels: Record<TaskAcceptanceCriterion['status'], string> = {
  pending: 'Ожидает сдачи',
  submitted: 'На приемке',
  accepted: 'Принят',
  returned: 'Возвращен',
  not_applicable: 'Не применяется',
}

const statusClasses: Record<TaskAcceptanceCriterion['status'], string> = {
  pending: 'border-slate-200 bg-slate-50 text-slate-600',
  submitted: 'border-sky-200 bg-sky-50 text-sky-700',
  accepted: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  returned: 'border-amber-200 bg-amber-50 text-amber-800',
  not_applicable: 'border-slate-200 bg-slate-50 text-slate-500',
}

const planStateLabels: Record<TaskAcceptance['state'], string> = {
  none: 'Не начата',
  submitted: 'На приемке',
  partially_accepted: 'Частично принято',
  returned: 'Есть возвраты',
  accepted: 'Принято',
}

const eventLabels: Record<TaskAcceptanceCriterion['events'][number]['event_type'], string> = {
  submitted: 'Отправлен на приемку',
  accepted: 'Принят',
  returned: 'Возвращен',
  not_applicable: 'Не применяется',
}

function formatEventDate(value: string): string {
  return new Date(value).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function TaskAcceptancePanel({ task, onUpdated }: TaskAcceptancePanelProps) {
  const { user: currentUser } = useAuth()
  const [plan, setPlan] = useState<TaskAcceptance | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [evidence, setEvidence] = useState<Evidence>({})
  const [reviewComments, setReviewComments] = useState<ReviewComments>({})

  const loadPlan = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.get<TaskAcceptance>(`/api/tasks/${task.id}/acceptance`)
      setPlan(data)
      setSelected(new Set())
    } catch (error) {
      setPlan(null)
      toast.error(error instanceof Error ? error.message : 'Не удалось загрузить критерии приемки')
    } finally {
      setLoading(false)
    }
  }, [task.id])

  useEffect(() => {
    void loadPlan()
  }, [loadPlan])

  const selectableCriteria = useMemo(
    () => plan?.criteria.filter((criterion) => criterion.status === 'pending' || criterion.status === 'returned') ?? [],
    [plan]
  )
  const isAdminOverride = Boolean(
    currentUser?.role === 'admin' && plan && plan.owner_id !== currentUser.id
  )
  const acceptedCount = plan?.criteria.filter((criterion) => criterion.status === 'accepted').length ?? 0
  const requiredCriteria = plan?.criteria.filter((criterion) => criterion.kind !== 'optional') ?? []
  const acceptedRequiredCount = requiredCriteria.filter((criterion) => criterion.status === 'accepted').length

  const toggleSelected = (criterionId: string) => {
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(criterionId)) next.delete(criterionId)
      else next.add(criterionId)
      return next
    })
  }

  const updateEvidence = (criterionId: string, field: 'comment' | 'url', value: string) => {
    setEvidence((current) => ({
      ...current,
      [criterionId]: { comment: current[criterionId]?.comment ?? '', url: current[criterionId]?.url ?? '', [field]: value },
    }))
  }

  const submitSelected = async () => {
    if (!plan || selected.size === 0) return
    const missingEvidence = [...selected].some((criterionId) => {
      const value = evidence[criterionId]
      return !value?.comment.trim() && !value?.url.trim()
    })
    if (missingEvidence) {
      toast.error('Для каждого выбранного критерия добавьте комментарий или ссылку')
      return
    }
    setBusy(true)
    try {
      await api.post(`/api/tasks/${task.id}/acceptance/submit`, {
        items: [...selected].map((criterionId) => ({
          criterion_id: criterionId,
          evidence_comment: evidence[criterionId]?.comment.trim() || undefined,
          evidence_url: evidence[criterionId]?.url.trim() || undefined,
        })),
      })
      toast.success('Критерии отправлены на приемку')
      setEvidence({})
      await loadPlan()
      onUpdated?.()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось отправить критерии')
    } finally {
      setBusy(false)
    }
  }

  const reviewCriterion = async (criterion: TaskAcceptanceCriterion, approved: boolean) => {
    const comment = reviewComments[criterion.id]?.trim() || ''
    if (!approved && !comment) {
      toast.error('Укажите причину возврата')
      return
    }
    if (approved && isAdminOverride && !comment) {
      toast.error('Для приемки по override укажите причину')
      return
    }
    setBusy(true)
    try {
      await api.post(`/api/tasks/${task.id}/acceptance/review`, {
        decisions: [{ criterion_id: criterion.id, approved, comment: comment || undefined }],
      })
      toast.success(approved ? 'Критерий принят' : 'Критерий возвращен')
      setReviewComments((current) => ({ ...current, [criterion.id]: '' }))
      await loadPlan()
      onUpdated?.()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось обработать критерий')
    } finally {
      setBusy(false)
    }
  }

  if (loading) {
    return <p className="text-sm text-slate-500">Загрузка критериев приемки...</p>
  }

  if (!plan) return null

  return (
    <section className="rounded-lg border border-sky-200 bg-sky-50/40 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-sky-800">Критерии приемки</p>
          <p className="mt-1 text-sm font-medium text-slate-800">
            Принято {acceptedCount} из {plan.criteria.length}
            {plan.owner_name ? ` · Принимает: ${plan.owner_name}` : ''}
          </p>
          <p className="mt-0.5 text-xs text-slate-500">
            Обязательных принято: {acceptedRequiredCount}/{requiredCriteria.length}
          </p>
        </div>
        <span className="rounded-full border border-sky-200 bg-white px-2 py-0.5 text-xs font-medium text-sky-700">
          {planStateLabels[plan.state]}
        </span>
      </div>
      <p className="mt-2 text-xs text-slate-600">Q начисляется после полной приемки.</p>
      <p className="mt-1 text-xs text-slate-500">Для сдачи каждого пункта добавьте комментарий или ссылку на подтверждение.</p>

      <div className="mt-3 space-y-3">
        {plan.criteria.map((criterion) => {
          const canSubmitCriterion = plan.can_submit && (criterion.status === 'pending' || criterion.status === 'returned')
          const canReviewCriterion = plan.can_review && criterion.status === 'submitted'
          const comment = reviewComments[criterion.id] ?? ''
          const needsOverrideReason = canReviewCriterion && isAdminOverride
          return (
            <div key={criterion.id} className="rounded-md border border-slate-200 bg-white p-3">
              <div className="flex items-start gap-2">
                {canSubmitCriterion && (
                  <input
                    type="checkbox"
                    checked={selected.has(criterion.id)}
                    onChange={() => toggleSelected(criterion.id)}
                    className="mt-1 h-4 w-4 rounded border-slate-300 text-primary"
                    aria-label={`Выбрать критерий: ${criterion.title}`}
                  />
                )}
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-medium text-slate-800">{criterion.title}</p>
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                      {kindLabels[criterion.kind]}
                    </span>
                    <span className={`rounded-full border px-2 py-0.5 text-xs font-medium ${statusClasses[criterion.status]}`}>
                      {statusLabels[criterion.status]}
                    </span>
                  </div>
                  {criterion.description && <p className="mt-1 text-sm text-slate-600">{criterion.description}</p>}
                  {criterion.evidence_comment && <p className="mt-2 whitespace-pre-wrap text-sm text-slate-700">{criterion.evidence_comment}</p>}
                  {criterion.evidence_url && (
                    <a className="mt-1 block truncate text-sm text-primary hover:underline" href={criterion.evidence_url} target="_blank" rel="noopener noreferrer">
                      {criterion.evidence_url}
                    </a>
                  )}
                  {criterion.reviewer_comment && (
                    <p className="mt-2 whitespace-pre-wrap text-sm text-amber-800">{criterion.reviewer_comment}</p>
                  )}
                  {criterion.events.length > 0 && (
                    <details className="mt-2 border-t border-slate-100 pt-2">
                      <summary className="inline-flex cursor-pointer items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-700">
                        <History className="h-3.5 w-3.5" /> История ({criterion.events.length})
                      </summary>
                      <ol className="mt-2 space-y-2 border-l border-slate-200 pl-3">
                        {criterion.events.map((event) => (
                          <li key={event.id} className="text-xs text-slate-600">
                            <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                              <span className="font-medium text-slate-700">{eventLabels[event.event_type]}</span>
                              <span>{formatEventDate(event.created_at)}</span>
                              {event.actor_name && <span>· {event.actor_name}</span>}
                            </div>
                            {event.comment && <p className="mt-0.5 whitespace-pre-wrap">{event.comment}</p>}
                          </li>
                        ))}
                      </ol>
                    </details>
                  )}
                </div>
              </div>

              {canSubmitCriterion && selected.has(criterion.id) && (
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  <textarea
                    value={evidence[criterion.id]?.comment ?? ''}
                    onChange={(event) => updateEvidence(criterion.id, 'comment', event.target.value)}
                    rows={2}
                    placeholder="Комментарий к результату"
                    className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                  />
                  <input
                    type="url"
                    value={evidence[criterion.id]?.url ?? ''}
                    onChange={(event) => updateEvidence(criterion.id, 'url', event.target.value)}
                    placeholder="Ссылка на результат"
                    className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                  />
                </div>
              )}

              {canReviewCriterion && (
                <div className="mt-3 space-y-2 border-t border-slate-100 pt-3">
                  <textarea
                    value={comment}
                    onChange={(event) => setReviewComments((current) => ({ ...current, [criterion.id]: event.target.value }))}
                    rows={2}
                    placeholder={needsOverrideReason ? 'Причина admin override обязательна' : 'Комментарий к приемке'}
                    className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                  />
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => void reviewCriterion(criterion, true)}
                      disabled={busy || (needsOverrideReason && !comment.trim())}
                      title={needsOverrideReason && !comment.trim() ? 'Для admin override нужна причина' : undefined}
                      className="inline-flex items-center gap-1 rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
                    >
                      <Check className="h-4 w-4" /> Принять
                    </button>
                    <button
                      type="button"
                      onClick={() => void reviewCriterion(criterion, false)}
                      disabled={busy || !comment.trim()}
                      title={!comment.trim() ? 'Для возврата укажите причину' : undefined}
                      className="inline-flex items-center gap-1 rounded-md border border-amber-300 bg-white px-3 py-1.5 text-sm font-medium text-amber-800 hover:bg-amber-50 disabled:opacity-50"
                    >
                      <RotateCcw className="h-4 w-4" /> Вернуть
                    </button>
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {plan.can_submit && selectableCriteria.length > 0 && (
        <div className="mt-3 flex justify-end border-t border-sky-100 pt-3">
          <button
            type="button"
            onClick={() => void submitSelected()}
            disabled={busy || selected.size === 0}
            className="inline-flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
          >
            <Send className="h-4 w-4" /> Отправить выбранные
          </button>
        </div>
      )}
    </section>
  )
}
