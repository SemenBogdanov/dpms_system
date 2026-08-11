import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import toast from 'react-hot-toast'
import { Check, History, RefreshCcw, RotateCcw, Send } from 'lucide-react'
import { api } from '@/api/client'
import type { Task, TaskAcceptance, TaskAcceptanceCriterion } from '@/api/types'
import { useAuth } from '@/contexts/AuthContext'
import {
  clearTaskAcceptanceDraft,
  readAcceptanceDraft,
  writeAcceptanceDraft,
  type AcceptanceEvidence,
  type AcceptanceReviewComments,
  type StoredAcceptanceDraft,
} from '@/lib/acceptanceDraft'

interface TaskAcceptancePanelProps {
  task: Task
  onUpdated?: () => void
  onDraftStateChange?: (state: { dirty: boolean; busy: boolean }) => void
}

type Evidence = AcceptanceEvidence
type ReviewComments = AcceptanceReviewComments

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
  decision_changed: 'Решение изменено',
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

function formatLoadedAt(value: string | null): string {
  if (!value) return 'нет сохраненной копии'
  return `данные от ${new Date(value).toLocaleTimeString('ru-RU', {
    hour: '2-digit',
    minute: '2-digit',
  })}`
}

export function TaskAcceptancePanel({ task, onUpdated, onDraftStateChange }: TaskAcceptancePanelProps) {
  const { user: currentUser } = useAuth()
  const [plan, setPlan] = useState<TaskAcceptance | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [lastLoadedAt, setLastLoadedAt] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [evidence, setEvidence] = useState<Evidence>({})
  const [reviewComments, setReviewComments] = useState<ReviewComments>({})
  const [revisionCriterionId, setRevisionCriterionId] = useState<string | null>(null)
  const [revisionComments, setRevisionComments] = useState<ReviewComments>({})
  const [hydratedTaskId, setHydratedTaskId] = useState<string | null>(null)
  const [draftRevision, setDraftRevision] = useState(task.acceptance_revision)
  const [draftCriterionTitles, setDraftCriterionTitles] = useState<Record<string, string>>({})
  const mutationInFlightRef = useRef(false)

  const beginMutation = () => {
    if (mutationInFlightRef.current) return false
    mutationInFlightRef.current = true
    setBusy(true)
    return true
  }

  const endMutation = () => {
    mutationInFlightRef.current = false
    setBusy(false)
  }

  const loadPlan = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const data = await api.get<TaskAcceptance>(`/api/tasks/${task.id}/acceptance`)
      setPlan(data)
      setLastLoadedAt(new Date().toISOString())
      setDraftCriterionTitles((current) => ({
        ...current,
        ...Object.fromEntries(data.criteria.map((criterion) => [criterion.id, criterion.title])),
      }))
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : 'Не удалось загрузить критерии приемки')
    } finally {
      setLoading(false)
    }
  }, [task.id])

  useEffect(() => {
    setPlan(null)
    setLoadError(null)
    setLastLoadedAt(null)
    void loadPlan()
  }, [loadPlan])

  useEffect(() => {
    const draft = readAcceptanceDraft(task.id)
    setSelected(new Set(draft?.selected ?? []))
    setEvidence(draft?.evidence ?? {})
    setReviewComments(draft?.reviewComments ?? {})
    setRevisionCriterionId(draft?.revisionCriterionId ?? null)
    setRevisionComments(draft?.revisionComments ?? {})
    setDraftRevision(draft?.acceptanceRevision ?? task.acceptance_revision)
    setDraftCriterionTitles(draft?.criterionTitles ?? {})
    setHydratedTaskId(task.id)
  }, [task.acceptance_revision, task.id])

  const dirty = useMemo(
    () => selected.size > 0
      || Object.values(evidence).some((value) => Boolean(value.comment.trim() || value.url.trim()))
      || Object.values(reviewComments).some((value) => Boolean(value.trim()))
      || Boolean(revisionCriterionId)
      || Object.values(revisionComments).some((value) => Boolean(value.trim())),
    [evidence, reviewComments, revisionComments, revisionCriterionId, selected],
  )

  useEffect(() => {
    onDraftStateChange?.({ dirty, busy })
  }, [busy, dirty, onDraftStateChange])

  useEffect(() => {
    if (hydratedTaskId !== task.id) return
    if (!dirty) {
      clearTaskAcceptanceDraft(task.id)
      if (draftRevision !== task.acceptance_revision) setDraftRevision(task.acceptance_revision)
      return
    }
    const draft: StoredAcceptanceDraft = {
      savedAt: Date.now(),
      acceptanceRevision: draftRevision,
      selected: [...selected],
      evidence,
      reviewComments,
      revisionCriterionId,
      revisionComments,
      criterionTitles: draftCriterionTitles,
    }
    writeAcceptanceDraft(task.id, draft)
  }, [
    dirty,
    draftCriterionTitles,
    draftRevision,
    evidence,
    hydratedTaskId,
    reviewComments,
    revisionComments,
    revisionCriterionId,
    selected,
    task.acceptance_revision,
    task.id,
  ])

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
  const activeCriterionIds = useMemo(
    () => new Set(plan?.criteria.map((criterion) => criterion.id) ?? []),
    [plan],
  )
  const draftCriterionIds = useMemo(
    () => new Set([
      ...selected,
      ...Object.keys(evidence),
      ...Object.keys(reviewComments),
      ...Object.keys(revisionComments),
      ...(revisionCriterionId ? [revisionCriterionId] : []),
    ]),
    [evidence, reviewComments, revisionComments, revisionCriterionId, selected],
  )
  const orphanedDraftIds = useMemo(
    () => [...draftCriterionIds].filter((criterionId) => !activeCriterionIds.has(criterionId)),
    [activeCriterionIds, draftCriterionIds],
  )
  const draftConflict = dirty && (
    draftRevision !== task.acceptance_revision
    || orphanedDraftIds.length > 0
  )
  const actionsDisabled = busy || loading || Boolean(loadError) || draftConflict

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
    const invalidUrl = [...selected].find((criterionId) => {
      const rawUrl = evidence[criterionId]?.url.trim()
      if (!rawUrl) return false
      try {
        const parsed = new URL(rawUrl)
        return parsed.protocol !== 'http:' && parsed.protocol !== 'https:'
      } catch {
        return true
      }
    })
    if (invalidUrl) {
      toast.error('Ссылка на результат должна начинаться с http:// или https://')
      return
    }
    if (!beginMutation()) return
    try {
      const submittedIds = [...selected]
      await api.post(`/api/tasks/${task.id}/acceptance/submit`, {
        items: submittedIds.map((criterionId) => ({
          criterion_id: criterionId,
          evidence_comment: evidence[criterionId]?.comment.trim() || undefined,
          evidence_url: evidence[criterionId]?.url.trim() || undefined,
        })),
      })
      toast.success('Критерии отправлены на приемку')
      setSelected((current) => new Set([...current].filter((criterionId) => !submittedIds.includes(criterionId))))
      setEvidence((current) => Object.fromEntries(
        Object.entries(current).filter(([criterionId]) => !submittedIds.includes(criterionId)),
      ))
      await loadPlan()
      onUpdated?.()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось отправить критерии')
    } finally {
      endMutation()
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
    if (!beginMutation()) return
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
      endMutation()
    }
  }

  const reviseCriterion = async (criterion: TaskAcceptanceCriterion) => {
    const comment = revisionComments[criterion.id]?.trim() || ''
    if (!comment) {
      toast.error('Укажите причину изменения решения')
      return
    }
    const approved = criterion.status === 'returned'
    if (!beginMutation()) return
    try {
      await api.post(`/api/tasks/${task.id}/acceptance/revise`, {
        criterion_id: criterion.id,
        approved,
        comment,
      })
      toast.success(approved ? 'Решение изменено: критерий принят' : 'Решение изменено: критерий возвращен')
      setRevisionComments((current) => ({ ...current, [criterion.id]: '' }))
      setRevisionCriterionId(null)
      await loadPlan()
      onUpdated?.()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось изменить решение')
    } finally {
      endMutation()
    }
  }

  if (loading && !plan) {
    return <p className="text-sm text-slate-500">Загрузка критериев приемки...</p>
  }

  if (!plan) {
    return (
      <section
        className="rounded-lg border border-rose-200 bg-rose-50/70 p-3"
        aria-live="polite"
      >
        <p className="text-sm font-semibold text-rose-900">Критерии приемки не загрузились</p>
        <p className="mt-1 text-sm text-rose-800">{loadError || 'Неизвестная ошибка загрузки'}</p>
        <button
          type="button"
          onClick={() => void loadPlan()}
          disabled={loading}
          className="mt-3 inline-flex min-h-11 items-center gap-2 rounded-md border border-rose-300 bg-white px-3 py-2 text-sm font-medium text-rose-800 hover:bg-rose-100 disabled:opacity-50"
        >
          <RefreshCcw className="h-4 w-4" /> {loading ? 'Повторяем...' : 'Повторить загрузку'}
        </button>
      </section>
    )
  }

  return (
    <section
      className="rounded-lg border border-sky-200 bg-sky-50/40 p-3"
      aria-busy={busy || loading}
      data-acceptance-busy={busy ? 'true' : 'false'}
    >
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

      {loadError && (
        <div
          className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900"
          aria-live="polite"
        >
          <div>
            <p className="font-medium">Не удалось обновить приемку</p>
            <p className="text-xs">Показаны {formatLoadedAt(lastLoadedAt)}. Действия временно заблокированы.</p>
          </div>
          <button
            type="button"
            onClick={() => void loadPlan()}
            disabled={loading}
            className="inline-flex min-h-11 items-center gap-2 rounded-md border border-amber-300 bg-white px-3 py-2 text-sm font-medium hover:bg-amber-100 disabled:opacity-50"
          >
            <RefreshCcw className="h-4 w-4" /> {loading ? 'Обновляем...' : 'Повторить'}
          </button>
        </div>
      )}

      {draftConflict && (
        <div
          className="mt-3 rounded-md border border-violet-300 bg-violet-50 px-3 py-2 text-sm text-violet-950"
          role="status"
        >
          <p className="font-medium">Критерии изменились после создания черновика</p>
          <p className="mt-1 text-xs">
            Ввод не удален, но отправка заблокирована до сверки с актуальной версией. Закройте окно и явно удалите старый черновик, затем заполните новые критерии.
          </p>
          {orphanedDraftIds.length > 0 && (
            <details className="mt-2 rounded border border-violet-200 bg-white/70 px-2.5 py-2">
              <summary className="cursor-pointer text-xs font-medium">
                Несопоставленные данные ({orphanedDraftIds.length})
              </summary>
              <div className="mt-2 space-y-2">
                {orphanedDraftIds.map((criterionId) => (
                  <div key={criterionId} className="rounded border border-violet-100 bg-white p-2 text-xs">
                    <p className="font-medium">{draftCriterionTitles[criterionId] || `Критерий ${criterionId}`}</p>
                    {evidence[criterionId]?.comment && <p className="mt-1 whitespace-pre-wrap">{evidence[criterionId].comment}</p>}
                    {evidence[criterionId]?.url && <p className="mt-1 break-all">{evidence[criterionId].url}</p>}
                    {reviewComments[criterionId] && <p className="mt-1 whitespace-pre-wrap">{reviewComments[criterionId]}</p>}
                    {revisionComments[criterionId] && <p className="mt-1 whitespace-pre-wrap">{revisionComments[criterionId]}</p>}
                  </div>
                ))}
              </div>
            </details>
          )}
        </div>
      )}

      <div className="mt-3 space-y-3">
        {plan.criteria.map((criterion) => {
          const canSubmitCriterion = plan.can_submit && (criterion.status === 'pending' || criterion.status === 'returned')
          const canReviewCriterion = plan.can_review && criterion.status === 'submitted'
          const hasRecordedDecision = criterion.status === 'accepted' || criterion.status === 'returned'
          const canReviseCriterion = plan.can_review && hasRecordedDecision && criterion.decision_change_count < 2
          const comment = reviewComments[criterion.id] ?? ''
          const revisionComment = revisionComments[criterion.id] ?? ''
          const needsOverrideReason = canReviewCriterion && isAdminOverride
          return (
            <div key={criterion.id} className="rounded-md border border-slate-200 bg-white p-3">
              <div className="flex items-start gap-2">
                {canSubmitCriterion && (
                  <input
                    type="checkbox"
                    checked={selected.has(criterion.id)}
                    onChange={() => toggleSelected(criterion.id)}
                    disabled={actionsDisabled}
                    data-acceptance-draft="true"
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
                              <span className="font-medium text-slate-700">
                                {event.event_type === 'decision_changed'
                                  ? `Решение изменено: ${event.to_status === 'accepted' ? 'принят' : 'возвращен'}`
                                  : eventLabels[event.event_type]}
                              </span>
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
                    aria-label={`Комментарий к результату: ${criterion.title}`}
                    data-acceptance-draft="true"
                    className="min-h-[4.75rem] w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                  />
                  <textarea
                    inputMode="url"
                    value={evidence[criterion.id]?.url ?? ''}
                    onChange={(event) => updateEvidence(criterion.id, 'url', event.target.value)}
                    rows={2}
                    placeholder="Ссылка на результат"
                    aria-label={`Ссылка на результат: ${criterion.title}`}
                    data-acceptance-draft="true"
                    className="min-h-[4.75rem] w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
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
                    data-acceptance-draft="true"
                    className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                  />
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => void reviewCriterion(criterion, true)}
                      disabled={actionsDisabled || (needsOverrideReason && !comment.trim())}
                      title={needsOverrideReason && !comment.trim() ? 'Для admin override нужна причина' : undefined}
                      className="inline-flex items-center gap-1 rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
                    >
                      <Check className="h-4 w-4" /> Принять
                    </button>
                    <button
                      type="button"
                      onClick={() => void reviewCriterion(criterion, false)}
                      disabled={actionsDisabled || !comment.trim()}
                      title={!comment.trim() ? 'Для возврата укажите причину' : undefined}
                      className="inline-flex items-center gap-1 rounded-md border border-amber-300 bg-white px-3 py-1.5 text-sm font-medium text-amber-800 hover:bg-amber-50 disabled:opacity-50"
                    >
                      <RotateCcw className="h-4 w-4" /> Вернуть
                    </button>
                  </div>
                </div>
              )}

              {plan.can_review && hasRecordedDecision && (
                <div className="mt-3 border-t border-slate-100 pt-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-xs text-slate-500">
                      Изменения решения: {criterion.decision_change_count}/2
                    </p>
                    {canReviseCriterion && (
                      <button
                        type="button"
                        onClick={() => setRevisionCriterionId((current) => current === criterion.id ? null : criterion.id)}
                        disabled={actionsDisabled}
                        className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                      >
                        <RefreshCcw className="h-3.5 w-3.5" /> Изменить решение
                      </button>
                    )}
                    {!canReviseCriterion && criterion.decision_change_count >= 2 && (
                      <span className="text-xs font-medium text-slate-500">Лимит исчерпан</span>
                    )}
                  </div>
                  {canReviseCriterion && revisionCriterionId === criterion.id && (
                    <div className="mt-2 space-y-2 rounded-md border border-slate-200 bg-slate-50 p-2.5">
                      <textarea
                        value={revisionComment}
                        onChange={(event) => setRevisionComments((current) => ({
                          ...current,
                          [criterion.id]: event.target.value,
                        }))}
                        rows={2}
                        placeholder="Причина изменения решения"
                        aria-label={`Причина изменения решения: ${criterion.title}`}
                        data-acceptance-draft="true"
                        className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
                      />
                      <div className="flex justify-end">
                        <button
                          type="button"
                          onClick={() => void reviseCriterion(criterion)}
                          disabled={actionsDisabled || !revisionComment.trim()}
                          className={criterion.status === 'accepted'
                            ? 'inline-flex items-center gap-1 rounded-md border border-amber-300 bg-white px-3 py-1.5 text-sm font-medium text-amber-800 hover:bg-amber-50 disabled:opacity-50'
                            : 'inline-flex items-center gap-1 rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50'}
                        >
                          {criterion.status === 'accepted'
                            ? <><RotateCcw className="h-4 w-4" /> Вернуть критерий</>
                            : <><Check className="h-4 w-4" /> Принять критерий</>}
                        </button>
                      </div>
                    </div>
                  )}
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
            disabled={actionsDisabled || selected.size === 0}
            className="inline-flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
          >
            <Send className="h-4 w-4" /> Отправить выбранные
          </button>
        </div>
      )}
    </section>
  )
}
