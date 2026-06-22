import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  ArrowLeft,
  BookOpenCheck,
  BarChart3,
  CheckCircle2,
  ClipboardCopy,
  Edit3,
  FileJson,
  Hammer,
  HelpCircle,
  Map,
  Plus,
  Send,
  Target,
  Timer,
  Trash2,
  X,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '@/api/client'
import type {
  CompetencyAccess,
  CompetencyAttemptStartResponse,
  CompetencyListResponse,
  CompetencyQuestionRead,
  CompetencyResultResponse,
  CompetencySummary,
  ConstructorAssignmentSet,
  ConstructorAssignmentRead,
  ConstructorCompetencyDetail,
  ConstructorCompetencyCreate,
  ConstructorCompetencyUpdate,
  ConstructorReportResponse,
  DevelopmentPlanItem,
  DevelopmentPlanItemCreate,
  DevelopmentPlanAdminSummaryResponse,
  DevelopmentPlanImportResponse,
  DevelopmentPlanPromptResponse,
  DevelopmentPlanReportResponse,
  DevelopmentPlanStatus,
  User,
} from '@/api/types'
import { cn } from '@/lib/utils'

type SectionKey = 'home' | 'assessment' | 'plan' | 'constructor'

type PlanForm = {
  competency_id: string
  goal: string
  action_text: string
  expected_result: string
  due_at: string
}

type ConstructorForm = {
  title: string
  description: string
  department: string
  visibility: 'assigned' | 'all'
  questions: ConstructorQuestionForm[]
  interpretation: string
  target_user_id: string
}

type ConstructorQuestionForm = {
  text: string
  choices: string[]
}

type HelpModalKey = 'overview' | 'result' | null

const QUESTION_SECONDS = 60
const growthHelpButtonClass =
  'inline-flex items-center gap-2 rounded-md border border-white/15 bg-white/10 px-3 py-2 text-sm text-cyan-50 shadow-sm shadow-cyan-500/10 transition hover:border-cyan-300/50 hover:bg-cyan-400/10 focus:outline-none focus:ring-2 focus:ring-cyan-300/50'
const growthHomeCardClass =
  'group rounded-lg border border-slate-200 bg-white p-5 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-cyan-300 hover:shadow-[0_14px_32px_rgba(14,165,233,0.16)] focus:outline-none focus:ring-2 focus:ring-cyan-300/50'
const growthToolbarButtonClass =
  'inline-flex items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:border-cyan-300 hover:bg-cyan-50 hover:text-cyan-900 focus:outline-none focus:ring-2 focus:ring-cyan-300/50'
const growthModalBackdropClass =
  'fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 px-4 py-6 backdrop-blur-md'
const growthModalPanelClass =
  'w-full rounded-lg border border-cyan-300/35 bg-white shadow-[0_0_0_1px_rgba(14,165,233,0.18),0_28px_80px_rgba(2,6,23,0.38),0_0_44px_rgba(14,165,233,0.18)] dark:bg-slate-900'

const planStatusLabel: Record<DevelopmentPlanStatus, string> = {
  planned: 'Запланировано',
  in_progress: 'В работе',
  done: 'Выполнено',
  cancelled: 'Отменено',
}

const initialPlanForm: PlanForm = {
  competency_id: '',
  goal: '',
  action_text: '',
  expected_result: '',
  due_at: '',
}

function createEmptyConstructorQuestion(): ConstructorQuestionForm {
  return {
    text: '',
    choices: ['', '', '', '', ''],
  }
}

function createInitialConstructorForm(): ConstructorForm {
  return {
    title: '',
    description: '',
    department: '',
    visibility: 'assigned',
    questions: [createEmptyConstructorQuestion()],
    interpretation: '',
    target_user_id: '',
  }
}

function addQuestionToForm(form: ConstructorForm): ConstructorForm {
  return { ...form, questions: [...form.questions, createEmptyConstructorQuestion()] }
}

function removeQuestionFromForm(form: ConstructorForm, index: number): ConstructorForm {
  return {
    ...form,
    questions: form.questions.length === 1 ? form.questions : form.questions.filter((_, itemIndex) => itemIndex !== index),
  }
}

function updateQuestionTextInForm(form: ConstructorForm, index: number, text: string): ConstructorForm {
  return {
    ...form,
    questions: form.questions.map((question, itemIndex) => (itemIndex === index ? { ...question, text } : question)),
  }
}

function updateChoiceInForm(form: ConstructorForm, questionIndex: number, choiceIndex: number, text: string): ConstructorForm {
  return {
    ...form,
    questions: form.questions.map((question, itemIndex) => {
      if (itemIndex !== questionIndex) return question
      const choices = [...question.choices]
      choices[choiceIndex] = text
      return { ...question, choices }
    }),
  }
}

function formFromConstructorDetail(detail: ConstructorCompetencyDetail): ConstructorForm {
  return {
    title: detail.title,
    description: detail.description || '',
    department: detail.department || '',
    visibility: detail.visibility === 'all' ? 'all' : 'assigned',
    questions: detail.questions.map((question) => ({
      text: question.text,
      choices: question.choices
        .sort((left, right) => left.position - right.position)
        .map((choice) => choice.text),
    })),
    interpretation: detail.interpretations[0]?.text || '',
    target_user_id: '',
  }
}

function formatDate(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleDateString('ru-RU')
}

function statusLabel(status: string): string {
  if (status === 'completed') return 'Завершено'
  if (status === 'in_progress') return 'В процессе'
  if (status === 'assigned') return 'Назначено'
  if (status === 'assessment_completed') return 'Оценка пройдена'
  if (status === 'planned') return 'Запланировано'
  if (status === 'done') return 'Выполнено'
  if (status === 'cancelled') return 'Отменено'
  return 'Не начато'
}

function statusBadgeClass(status: string): string {
  if (status === 'completed' || status === 'done' || status === 'assessment_completed') return 'bg-emerald-50 text-emerald-700'
  if (status === 'in_progress') return 'bg-amber-50 text-amber-700'
  if (status === 'assigned') return 'bg-sky-50 text-sky-700'
  if (status === 'cancelled') return 'bg-rose-50 text-rose-700'
  if (status === 'planned') return 'bg-slate-100 text-slate-600'
  return 'bg-slate-100 text-slate-600'
}

function isRetakeAllowed(competency: CompetencySummary): boolean {
  if (competency.status !== 'completed') return true
  if (!competency.retake_allowed_at) return false
  const date = new Date(competency.retake_allowed_at)
  return !Number.isNaN(date.getTime()) && date.getTime() <= Date.now()
}

function startButtonLabel(competency: CompetencySummary): string {
  if (competency.status === 'completed') return isRetakeAllowed(competency) ? 'Повторить' : 'Завершено'
  if (competency.status === 'in_progress') return 'Продолжить'
  return 'Начать'
}

function cleanLines(text: string | null): string[] {
  return (text || '')
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean)
}

function dateSortValue(value: string | null | undefined): number {
  if (!value) return Number.MAX_SAFE_INTEGER
  const time = new Date(value).getTime()
  return Number.isNaN(time) ? Number.MAX_SAFE_INTEGER : time
}

function DevelopmentReportContent({
  report,
  onDeleteAssessment,
}: {
  report: DevelopmentPlanReportResponse
  onDeleteAssessment?: (attemptId: string) => void
}) {
  const sortedRoadmap = [...report.roadmap].sort((a, b) => dateSortValue(a.due_at) - dateSortValue(b.due_at))

  return (
    <div className="space-y-5">
      <div className="grid gap-3 md:grid-cols-4">
        <div className="rounded-md border border-slate-200 px-3 py-2">
          <div className="text-lg font-semibold text-slate-900">{report.completed_assessments_count}</div>
          <div className="text-xs text-slate-500">оценок</div>
        </div>
        <div className="rounded-md border border-slate-200 px-3 py-2">
          <div className="text-lg font-semibold text-slate-900">{report.plan_total}</div>
          <div className="text-xs text-slate-500">пунктов ИПР</div>
        </div>
        <div className="rounded-md border border-slate-200 px-3 py-2">
          <div className="text-lg font-semibold text-emerald-700">{report.plan_done}</div>
          <div className="text-xs text-slate-500">выполнено</div>
        </div>
        <div className="rounded-md border border-slate-200 px-3 py-2">
          <div className="text-lg font-semibold text-blue-700">{report.progress_percent}%</div>
          <div className="text-xs text-slate-500">прогресс</div>
        </div>
      </div>

      <div className="space-y-3">
        <h3 className="text-sm font-medium text-slate-900">Дорожная карта</h3>
        <div className="relative space-y-3 pl-5 before:absolute before:left-2 before:top-2 before:h-[calc(100%-16px)] before:w-px before:bg-slate-200">
          {sortedRoadmap.length === 0 && <p className="text-sm text-slate-500">Нет точек дорожной карты.</p>}
          {sortedRoadmap.map((point, index) => (
            <div key={`${point.id || point.title}-${index}`} className="relative rounded-md border border-slate-200 bg-white px-3 py-2">
              <span className="absolute -left-[17px] top-3 h-3 w-3 rounded-full border-2 border-white bg-slate-300 shadow-sm" />
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h4 className="text-sm font-medium text-slate-900">{point.title}</h4>
                <span className={cn('rounded px-2 py-0.5 text-xs font-medium', statusBadgeClass(point.status))}>
                  {statusLabel(point.status)}
                </span>
              </div>
              {point.description && <p className="mt-1 text-sm text-slate-600">{point.description}</p>}
              <p className="mt-1 text-xs text-slate-400">
                {point.completed_at ? `выполнено: ${formatDate(point.completed_at)}` : `срок: ${formatDate(point.due_at)}`}
              </p>
            </div>
          ))}
        </div>
      </div>

      <div className="space-y-2">
        <h3 className="text-sm font-medium text-slate-900">Пройденные оценки</h3>
        {report.assessments.length === 0 && <p className="text-sm text-slate-500">Оценки пока не завершены.</p>}
        {report.assessments.map((assessment) => (
          <div key={assessment.competency_id} className="rounded-md border border-slate-200 px-3 py-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h4 className="text-sm font-medium text-slate-900">{assessment.competency_title}</h4>
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-500">
                  ИБ: {assessment.score_ib ?? '—'} · ИЧ: {assessment.score_ich ?? '—'}
                </span>
                {onDeleteAssessment && (
                  <button
                    type="button"
                    onClick={() => onDeleteAssessment(assessment.attempt_id)}
                    className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-rose-200 text-rose-700 hover:bg-rose-50"
                    title="Удалить результат оценки"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                )}
              </div>
            </div>
            {assessment.interpretation_text && (
              <p className="mt-1 line-clamp-3 text-sm text-slate-600">{assessment.interpretation_text}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

export function CompetenciesPage() {
  const { assignmentId } = useParams<{ assignmentId?: string }>()
  const [section, setSection] = useState<SectionKey>('home')
  const [access, setAccess] = useState<CompetencyAccess | null>(null)
  const [competencies, setCompetencies] = useState<CompetencySummary[]>([])
  const [descriptionCompetency, setDescriptionCompetency] = useState<CompetencySummary | null>(null)
  const [pendingStartCompetency, setPendingStartCompetency] = useState<CompetencySummary | null>(null)
  const [planItems, setPlanItems] = useState<DevelopmentPlanItem[]>([])
  const [constructorItems, setConstructorItems] = useState<CompetencySummary[]>([])
  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [startingCompetencyId, setStartingCompetencyId] = useState<string | null>(null)
  const [activeAttempt, setActiveAttempt] = useState<CompetencyAttemptStartResponse | null>(null)
  const [questionIndex, setQuestionIndex] = useState(0)
  const [secondsLeft, setSecondsLeft] = useState(QUESTION_SECONDS)
  const [result, setResult] = useState<CompetencyResultResponse | null>(null)
  const [planForm, setPlanForm] = useState<PlanForm>(initialPlanForm)
  const [constructorForm, setConstructorForm] = useState<ConstructorForm>(() => createInitialConstructorForm())
  const [lastAssignment, setLastAssignment] = useState<ConstructorAssignmentRead | null>(null)
  const [helpModal, setHelpModal] = useState<HelpModalKey>(null)
  const [editingCompetency, setEditingCompetency] = useState<ConstructorCompetencyDetail | null>(null)
  const [editForm, setEditForm] = useState<ConstructorForm | null>(null)
  const [assignCompetency, setAssignCompetency] = useState<CompetencySummary | null>(null)
  const [assignSelectedIds, setAssignSelectedIds] = useState<string[]>([])
  const [assignVisibility, setAssignVisibility] = useState<'assigned' | 'all'>('assigned')
  const [report, setReport] = useState<ConstructorReportResponse | null>(null)
  const [deleteCompetency, setDeleteCompetency] = useState<CompetencySummary | null>(null)
  const [aiPrompt, setAiPrompt] = useState<DevelopmentPlanPromptResponse | null>(null)
  const [importResponseOpen, setImportResponseOpen] = useState(false)
  const [importResponseText, setImportResponseText] = useState('')
  const [developmentReport, setDevelopmentReport] = useState<DevelopmentPlanReportResponse | null>(null)
  const [adminPlanReport, setAdminPlanReport] = useState<DevelopmentPlanAdminSummaryResponse | null>(null)
  const [adminSelectedUserId, setAdminSelectedUserId] = useState('')
  const [adminUserReport, setAdminUserReport] = useState<DevelopmentPlanReportResponse | null>(null)
  const questionStartedAtRef = useRef(Date.now())
  const answeringRef = useRef(false)
  const timeoutHandledRef = useRef(false)

  const canUseDevelopment = Boolean(access?.development_enabled)
  const canUseConstructor = Boolean(access?.constructor_enabled)
  const activeQuestion: CompetencyQuestionRead | null = activeAttempt?.questions[questionIndex] ?? null
  const completedCount = useMemo(() => competencies.filter((item) => item.status === 'completed').length, [competencies])

  const loadAll = useCallback(async () => {
    setLoading(true)
    try {
      const accessData = await api.get<CompetencyAccess>('/api/competencies/access')
      setAccess(accessData)

      if (!accessData.development_enabled && accessData.constructor_enabled) {
        setSection('constructor')
      }

      if (accessData.development_enabled) {
        const [competencyData, planData] = await Promise.all([
          api.get<CompetencyListResponse>('/api/competencies/my'),
          api.get<DevelopmentPlanItem[]>('/api/competencies/development-plan/my'),
        ])
        setCompetencies(competencyData.competencies)
        setPlanItems(planData)
      } else {
        setCompetencies([])
        setPlanItems([])
      }

      if (accessData.constructor_enabled) {
        const [constructorData, userData] = await Promise.all([
          api.get<CompetencySummary[]>('/api/competencies/constructor'),
          api.get<User[]>('/api/users?is_active=true'),
        ])
        setConstructorItems(constructorData)
        setUsers(userData)
      } else {
        setConstructorItems([])
        setUsers([])
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка загрузки раздела')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadAll()
  }, [loadAll])

  useEffect(() => {
    if (!assignmentId) return

    let cancelled = false
    const loadAssignment = async () => {
      setBusy(true)
      try {
        const data = await api.get<CompetencySummary>(`/api/competencies/assignments/${assignmentId}`)
        if (cancelled) return
        setCompetencies((prev) => {
          if (prev.some((item) => item.id === data.id)) {
            return prev.map((item) => (item.id === data.id ? { ...item, ...data } : item))
          }
          return [data, ...prev]
        })
        setSection('assessment')
      } catch (e) {
        if (!cancelled) {
          toast.error(e instanceof Error ? e.message : 'Назначение не найдено')
        }
      } finally {
        if (!cancelled) {
          setBusy(false)
        }
      }
    }

    loadAssignment()
    return () => {
      cancelled = true
    }
  }, [assignmentId])

  const loadResult = async (attemptId: string) => {
    setBusy(true)
    try {
      const data = await api.get<CompetencyResultResponse>(`/api/competencies/attempts/${attemptId}/result`)
      setResult(data)
      setActiveAttempt(null)
      setSection('assessment')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось открыть результат')
    } finally {
      setBusy(false)
    }
  }

  const startCompetency = async (competency: CompetencySummary) => {
    if (competency.status === 'completed' && !isRetakeAllowed(competency)) return
    setStartingCompetencyId(competency.id)
    setResult(null)
    setPendingStartCompetency(null)
    try {
      const attempt = await api.post<CompetencyAttemptStartResponse>(`/api/competencies/my/${competency.id}/start`, {})
      const nextCompetency = {
        ...competency,
        status: 'in_progress',
        active_attempt_id: attempt.attempt_id,
      }
      setCompetencies((prev) => prev.map((item) => (item.id === competency.id ? nextCompetency : item)))
      setActiveAttempt(attempt)
      setQuestionIndex(0)
      setSecondsLeft(QUESTION_SECONDS)
      questionStartedAtRef.current = Date.now()
      timeoutHandledRef.current = false
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось начать оценку')
    } finally {
      setStartingCompetencyId(null)
    }
  }

  const requestStartCompetency = (competency: CompetencySummary) => {
    if (competency.status === 'completed' && !isRetakeAllowed(competency)) return
    if (competency.status === 'in_progress') {
      void startCompetency(competency)
      return
    }
    setPendingStartCompetency(competency)
  }

  const answerQuestion = useCallback(async (choiceId: string | null, timedOut = false) => {
    if (!activeAttempt || !activeQuestion || answeringRef.current) return

    answeringRef.current = true
    setBusy(true)
    try {
      const elapsed = Math.max(0, Math.round((Date.now() - questionStartedAtRef.current) / 1000))
      await api.post(`/api/competencies/attempts/${activeAttempt.attempt_id}/answer`, {
        question_id: activeQuestion.id,
        choice_id: choiceId,
        time_spent_seconds: Math.min(elapsed, QUESTION_SECONDS),
        timed_out: timedOut,
      })

      const next = questionIndex + 1
      if (next < activeAttempt.questions.length) {
        setQuestionIndex(next)
        setSecondsLeft(QUESTION_SECONDS)
        questionStartedAtRef.current = Date.now()
        timeoutHandledRef.current = false
      } else {
        const data = await api.post<CompetencyResultResponse>(`/api/competencies/attempts/${activeAttempt.attempt_id}/finish`, {})
        setResult(data)
        setActiveAttempt(null)
        setCompetencies((prev) =>
          prev.map((item) =>
            item.id === data.competency_id
              ? {
                  ...item,
                  status: 'completed',
                  latest_attempt_id: data.attempt_id,
                  active_attempt_id: null,
                  score_ib: data.score_ib,
                  score_ich: data.score_ich,
                  is_overused: data.is_overused,
                  completed_at: data.completed_at,
                  retake_allowed_at: data.retake_allowed_at,
                }
              : item
          )
        )
        await loadAll()
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ответ не сохранен')
    } finally {
      answeringRef.current = false
      setBusy(false)
    }
  }, [activeAttempt, activeQuestion, questionIndex, loadAll])

  useEffect(() => {
    if (!activeAttempt || !activeQuestion) return

    timeoutHandledRef.current = false
    questionStartedAtRef.current = Date.now()
    setSecondsLeft(QUESTION_SECONDS)

    const timer = window.setInterval(() => {
      const elapsed = Math.floor((Date.now() - questionStartedAtRef.current) / 1000)
      const remaining = Math.max(0, QUESTION_SECONDS - elapsed)
      setSecondsLeft(remaining)
      if (remaining === 0 && !timeoutHandledRef.current) {
        timeoutHandledRef.current = true
        void answerQuestion(null, true)
      }
    }, 250)

    return () => window.clearInterval(timer)
  }, [activeAttempt, activeQuestion, answerQuestion])

  const createPlanItem = async () => {
    if (!planForm.goal.trim() || !planForm.action_text.trim()) {
      toast.error('Заполните цель и мероприятие')
      return
    }
    setBusy(true)
    try {
      const payload: DevelopmentPlanItemCreate = {
        competency_id: planForm.competency_id || null,
        goal: planForm.goal.trim(),
        action_text: planForm.action_text.trim(),
        expected_result: planForm.expected_result.trim() || null,
        due_at: planForm.due_at ? new Date(planForm.due_at).toISOString() : null,
      }
      await api.post<DevelopmentPlanItem>('/api/competencies/development-plan/my', payload)
      setPlanForm(initialPlanForm)
      await loadAll()
      toast.success('Пункт ИПР добавлен')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось добавить пункт ИПР')
    } finally {
      setBusy(false)
    }
  }

  const updatePlanStatus = async (item: DevelopmentPlanItem, status: DevelopmentPlanStatus) => {
    setBusy(true)
    try {
      await api.patch(`/api/competencies/development-plan/my/${item.id}`, { status })
      await loadAll()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось обновить пункт ИПР')
    } finally {
      setBusy(false)
    }
  }

  const deletePlanItem = async (item: DevelopmentPlanItem) => {
    setBusy(true)
    try {
      await api.delete(`/api/competencies/development-plan/my/${item.id}`)
      await loadAll()
      toast.success('Пункт ИПР удален')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось удалить пункт ИПР')
    } finally {
      setBusy(false)
    }
  }

  const openAiPrompt = async () => {
    setBusy(true)
    try {
      const data = await api.get<DevelopmentPlanPromptResponse>('/api/competencies/development-plan/my/ai-prompt')
      setAiPrompt(data)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось сформировать промпт')
    } finally {
      setBusy(false)
    }
  }

  const copyAiPrompt = async () => {
    if (!aiPrompt) return
    try {
      await navigator.clipboard.writeText(aiPrompt.prompt)
      toast.success('Промпт скопирован')
    } catch {
      toast.error('Не удалось скопировать промпт')
    }
  }

  const importAiResponse = async () => {
    if (!importResponseText.trim()) {
      toast.error('Вставьте JSON-ответ GPT-5')
      return
    }
    setBusy(true)
    try {
      const data = await api.post<DevelopmentPlanImportResponse>('/api/competencies/development-plan/my/import-ai', {
        raw_text: importResponseText,
      })
      setImportResponseText('')
      setImportResponseOpen(false)
      await loadAll()
      toast.success(`Добавлено в ИПР: ${data.imported_count}`)
      data.warnings.slice(0, 3).forEach((warning) => toast(warning))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось импортировать ИПР')
    } finally {
      setBusy(false)
    }
  }

  const openDevelopmentReport = async () => {
    setBusy(true)
    try {
      const data = await api.get<DevelopmentPlanReportResponse>('/api/competencies/development-plan/my/report')
      setDevelopmentReport(data)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось загрузить отчет')
    } finally {
      setBusy(false)
    }
  }

  const openAdminPlanReport = async () => {
    setBusy(true)
    try {
      const data = await api.get<DevelopmentPlanAdminSummaryResponse>('/api/competencies/development-plan/admin/report')
      setAdminPlanReport(data)
      setAdminSelectedUserId('')
      setAdminUserReport(null)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось загрузить отчетность')
    } finally {
      setBusy(false)
    }
  }

  const loadAdminUserPlanReport = async (userId: string) => {
    setAdminSelectedUserId(userId)
    if (!userId) {
      setAdminUserReport(null)
      return
    }
    setBusy(true)
    try {
      const data = await api.get<DevelopmentPlanReportResponse>('/api/competencies/development-plan/admin/report', { user_id: userId })
      setAdminUserReport(data)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось загрузить отчет сотрудника')
    } finally {
      setBusy(false)
    }
  }

  const deleteAssessmentAttempt = async (attemptId: string) => {
    if (!window.confirm('Удалить результат прохождения оценки? После удаления сотрудник сможет пройти оценку повторно.')) return
    setBusy(true)
    try {
      await api.delete(`/api/competencies/attempts/${attemptId}`)
      if (adminSelectedUserId) {
        await loadAdminUserPlanReport(adminSelectedUserId)
      }
      await loadAll()
      toast.success('Результат оценки удален')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось удалить результат оценки')
    } finally {
      setBusy(false)
    }
  }

  const addConstructorQuestion = () => {
    setConstructorForm(addQuestionToForm)
  }

  const removeConstructorQuestion = (index: number) => {
    setConstructorForm((prev) => removeQuestionFromForm(prev, index))
  }

  const updateConstructorQuestionText = (index: number, text: string) => {
    setConstructorForm((prev) => updateQuestionTextInForm(prev, index, text))
  }

  const updateConstructorChoice = (questionIndex: number, choiceIndex: number, text: string) => {
    setConstructorForm((prev) => updateChoiceInForm(prev, questionIndex, choiceIndex, text))
  }

  const buildConstructorPayload = (form: ConstructorForm): ConstructorCompetencyCreate | null => {
    if (!form.title.trim()) {
      toast.error('Заполните название компетенции')
      return null
    }
    const questions = form.questions
      .map((question) => ({
        text: question.text.trim(),
        choices: question.choices.map((item) => item.trim()).filter(Boolean),
      }))
      .filter((question) => question.text || question.choices.length > 0)
    if (questions.length === 0) {
      toast.error('Добавьте минимум один вопрос')
      return null
    }
    if (questions.some((question) => !question.text || question.choices.length < 2)) {
      toast.error('У каждого вопроса должен быть текст и минимум два варианта')
      return null
    }
    return {
      title: form.title.trim(),
      description: form.description.trim() || null,
      department: form.department.trim() || null,
      visibility: form.visibility,
      questions: questions.map((question) => ({
        text: question.text,
        question_type: 'custom',
        choices: question.choices.map((text, index) => ({ text, value: Math.min(index + 1, 5) })),
      })),
      interpretations: [
        {
          min_score_ib: 0,
          max_score_ib: 100,
          text: form.interpretation.trim() || 'Интерпретация будет уточнена автором компетенции.',
        },
      ],
    }
  }

  const createCustomCompetency = async () => {
    const payload = buildConstructorPayload(constructorForm)
    if (!payload) return
    setBusy(true)
    try {
      const competency = await api.post<CompetencySummary>('/api/competencies/constructor', payload)
      if (constructorForm.target_user_id) {
        const assignment = await api.post<ConstructorAssignmentRead>(`/api/competencies/constructor/${competency.id}/assign`, {
          target_user_id: constructorForm.target_user_id,
        })
        setLastAssignment(assignment)
      } else {
        setLastAssignment(null)
      }
      setConstructorForm(createInitialConstructorForm())
      await loadAll()
      toast.success('Компетенция создана')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось создать компетенцию')
    } finally {
      setBusy(false)
    }
  }

  const openEditCompetency = async (item: CompetencySummary) => {
    setBusy(true)
    try {
      const detail = await api.get<ConstructorCompetencyDetail>(`/api/competencies/constructor/${item.id}`)
      setEditingCompetency(detail)
      setEditForm(formFromConstructorDetail(detail))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось открыть редактирование')
    } finally {
      setBusy(false)
    }
  }

  const saveEditCompetency = async () => {
    if (!editingCompetency || !editForm) return
    const fullPayload = buildConstructorPayload(editForm)
    if (!fullPayload) return
    const payload: ConstructorCompetencyUpdate = editingCompetency.can_edit_content
      ? fullPayload
      : {
          title: editForm.title.trim(),
          description: editForm.description.trim() || null,
          department: editForm.department.trim() || null,
          visibility: editForm.visibility,
        }
    setBusy(true)
    try {
      await api.patch<ConstructorCompetencyDetail>(`/api/competencies/constructor/${editingCompetency.id}`, payload)
      setEditingCompetency(null)
      setEditForm(null)
      await loadAll()
      toast.success('Компетенция обновлена')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось обновить компетенцию')
    } finally {
      setBusy(false)
    }
  }

  const openAssignCompetency = async (item: CompetencySummary) => {
    setAssignCompetency(item)
    setAssignVisibility(item.visibility === 'all' ? 'all' : 'assigned')
    setBusy(true)
    try {
      const reportData = await api.get<ConstructorReportResponse>(`/api/competencies/constructor/${item.id}/report`)
      setAssignSelectedIds(reportData.rows.filter((row) => row.assignment_status).map((row) => row.user_id))
    } catch {
      setAssignSelectedIds([])
    } finally {
      setBusy(false)
    }
  }

  const saveAssignments = async () => {
    if (!assignCompetency) return
    const payload: ConstructorAssignmentSet = {
      target_user_ids: assignVisibility === 'all' ? [] : assignSelectedIds,
      visibility: assignVisibility,
    }
    setBusy(true)
    try {
      await api.put<CompetencySummary>(`/api/competencies/constructor/${assignCompetency.id}/assignments`, payload)
      setAssignCompetency(null)
      setAssignSelectedIds([])
      await loadAll()
      toast.success('Доступ обновлен')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось обновить доступ')
    } finally {
      setBusy(false)
    }
  }

  const openReport = async (item: CompetencySummary) => {
    setBusy(true)
    try {
      const data = await api.get<ConstructorReportResponse>(`/api/competencies/constructor/${item.id}/report`)
      setReport(data)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось загрузить отчет')
    } finally {
      setBusy(false)
    }
  }

  const confirmDeleteCompetency = async () => {
    if (!deleteCompetency) return
    setBusy(true)
    try {
      await api.delete<CompetencySummary>(`/api/competencies/constructor/${deleteCompetency.id}`)
      setDeleteCompetency(null)
      await loadAll()
      toast.success('Компетенция удалена')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось удалить компетенцию')
    } finally {
      setBusy(false)
    }
  }

  const goHome = () => {
    setSection('home')
    setActiveAttempt(null)
    setResult(null)
  }

  if (loading) {
    return <div className="text-slate-500">Загрузка...</div>
  }

  return (
    <div className="space-y-5">
      <div className="relative overflow-hidden rounded-lg border border-slate-800 bg-[radial-gradient(circle_at_78%_35%,rgba(14,165,233,0.28),transparent_34%),linear-gradient(135deg,#020617_0%,#07111f_48%,#020617_100%)] px-5 py-5 shadow-sm shadow-cyan-950/30">
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-px bg-gradient-to-r from-transparent via-cyan-400/70 to-transparent" />
        <div className="relative grid gap-5 lg:grid-cols-[minmax(0,1fr)_460px]">
          <div>
            <div className="inline-flex items-center rounded-full border border-cyan-300/25 bg-cyan-300/10 px-2.5 py-1 text-xs font-medium text-cyan-100">
              Контур развития
            </div>
            <h1 className="mt-3 text-2xl font-semibold text-white">Развитие компетенций</h1>
            <p className="mt-1 max-w-2xl text-sm text-slate-300">
              Оценка компетенций, индивидуальный план развития и конструктор. Фокус на измеримой динамике: пройти оценку, собрать ИПР, вернуться к повторной проверке.
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <button type="button" onClick={() => setHelpModal('overview')} className={growthHelpButtonClass}>
                <HelpCircle className="h-4 w-4" />
                Что я здесь делаю
              </button>
              <button type="button" onClick={() => setHelpModal('result')} className={growthHelpButtonClass}>
                <BarChart3 className="h-4 w-4" />
                Как читать результат
              </button>
            </div>
            <div className="mt-5 grid max-w-md grid-cols-3 gap-2 text-center text-sm lg:hidden">
              <div className="rounded-lg border border-white/10 bg-white/10 px-3 py-2 backdrop-blur">
                <div className="text-lg font-semibold text-white">{competencies.length}</div>
                <div className="text-xs text-slate-300">оценок</div>
              </div>
              <div className="rounded-lg border border-emerald-300/20 bg-emerald-300/10 px-3 py-2 backdrop-blur">
                <div className="text-lg font-semibold text-emerald-200">{completedCount}</div>
                <div className="text-xs text-slate-300">завершено</div>
              </div>
              <div className="rounded-lg border border-cyan-300/20 bg-cyan-300/10 px-3 py-2 backdrop-blur">
                <div className="text-lg font-semibold text-cyan-100">{planItems.length}</div>
                <div className="text-xs text-slate-300">пунктов ИПР</div>
              </div>
            </div>
          </div>
          <div className="pointer-events-none relative hidden min-h-72 lg:block">
            <img
              src="/competency-growth.svg"
              alt=""
              aria-hidden="true"
              className="absolute right-8 top-1/2 h-72 w-72 -translate-y-1/2 object-contain opacity-85 mix-blend-screen"
            />
            <div className="absolute bottom-0 right-0 grid w-[430px] grid-cols-3 gap-2 text-center text-sm">
              <div className="rounded-lg border border-white/10 bg-white/10 px-3 py-2 backdrop-blur">
                <div className="text-lg font-semibold text-white">{competencies.length}</div>
                <div className="text-xs text-slate-300">оценок</div>
              </div>
              <div className="rounded-lg border border-emerald-300/20 bg-emerald-300/10 px-3 py-2 backdrop-blur">
                <div className="text-lg font-semibold text-emerald-200">{completedCount}</div>
                <div className="text-xs text-slate-300">завершено</div>
              </div>
              <div className="rounded-lg border border-cyan-300/20 bg-cyan-300/10 px-3 py-2 backdrop-blur">
                <div className="text-lg font-semibold text-cyan-100">{planItems.length}</div>
                <div className="text-xs text-slate-300">пунктов ИПР</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {section === 'home' && (
        <div className="grid gap-3 md:grid-cols-3">
          {canUseDevelopment && (
            <button
              type="button"
              onClick={() => setSection('assessment')}
              className={growthHomeCardClass}
            >
              <span className="inline-flex h-10 w-10 items-center justify-center rounded-md border border-cyan-100 bg-cyan-50 text-cyan-700 transition group-hover:border-cyan-200 group-hover:bg-cyan-100">
                <BookOpenCheck className="h-5 w-5" />
              </span>
              <div className="mt-4 font-medium text-slate-900">Оценка компетенций</div>
              <div className="mt-1 text-sm text-slate-500">{competencies.length} доступных оценок</div>
            </button>
          )}
          {canUseDevelopment && (
            <button
              type="button"
              onClick={() => setSection('plan')}
              className={growthHomeCardClass}
            >
              <span className="inline-flex h-10 w-10 items-center justify-center rounded-md border border-emerald-100 bg-emerald-50 text-emerald-700 transition group-hover:border-emerald-200 group-hover:bg-emerald-100">
                <Target className="h-5 w-5" />
              </span>
              <div className="mt-4 font-medium text-slate-900">ИПР</div>
              <div className="mt-1 text-sm text-slate-500">{planItems.length} целей развития</div>
            </button>
          )}
          {canUseConstructor && (
            <button
              type="button"
              onClick={() => setSection('constructor')}
              className={growthHomeCardClass}
            >
              <span className="inline-flex h-10 w-10 items-center justify-center rounded-md border border-blue-100 bg-blue-50 text-blue-700 transition group-hover:border-blue-200 group-hover:bg-blue-100">
                <Hammer className="h-5 w-5" />
              </span>
              <div className="mt-4 font-medium text-slate-900">Конструктор</div>
              <div className="mt-1 text-sm text-slate-500">{constructorItems.length} custom-компетенций</div>
            </button>
          )}
        </div>
      )}

      {section === 'assessment' && canUseDevelopment && (
        <div className="space-y-4">
          <button
            type="button"
            onClick={goHome}
            className={growthToolbarButtonClass}
          >
            <ArrowLeft className="h-4 w-4" />
            Назад
          </button>

          <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center justify-between gap-3">
              <h2 className="font-medium text-slate-900">Доступные оценки</h2>
              <span className="text-xs text-slate-500">ИБ/ИЧ считаются после полного прохождения</span>
            </div>
            <div className="mt-4 divide-y divide-slate-100">
              {competencies.map((competency) => (
                <div key={competency.id} className="grid gap-3 py-3 lg:grid-cols-[minmax(0,1fr)_460px]">
                  <div className="min-w-0">
                    <div className="grid gap-2 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-start">
                      <div className="min-w-0">
                        <h3 className="font-medium text-slate-900">{competency.title}</h3>
                        <div className="mt-2 flex flex-wrap gap-3 text-xs text-slate-500">
                          <span>{competency.questions_count} вопросов</span>
                          {competency.score_ib !== null && <span>ИБ: {competency.score_ib}</span>}
                          {competency.score_ich !== null && <span>ИЧ: {competency.score_ich}</span>}
                          {competency.retake_allowed_at && <span>Повтор: {formatDate(competency.retake_allowed_at)}</span>}
                        </div>
                      </div>
                      <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                        <span className={cn('rounded px-2 py-0.5 text-xs font-medium', statusBadgeClass(competency.status))}>
                          {statusLabel(competency.status)}
                        </span>
                        {competency.source === 'custom' && (
                          <span className="rounded bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">custom</span>
                        )}
                        {competency.source === 'builtin' && (
                          <span className="rounded bg-violet-50 px-2 py-0.5 text-xs font-medium text-violet-700">
                            Базовая
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center justify-end gap-2">
                    <button
                      type="button"
                      onClick={() => setDescriptionCompetency(competency)}
                      className="rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                    >
                      Описание
                    </button>
                    {competency.latest_attempt_id && (
                      <button
                        type="button"
                        onClick={() => loadResult(competency.latest_attempt_id!)}
                        className={cn(
                          'rounded-md px-3 py-2 text-sm font-medium',
                          competency.status === 'completed'
                            ? 'bg-blue-600 text-white hover:bg-blue-700'
                            : 'border border-slate-200 text-slate-700 hover:bg-slate-50'
                        )}
                      >
                        Результат
                      </button>
                    )}
                    {access?.is_admin && competency.latest_attempt_id && (
                      <button
                        type="button"
                        onClick={() => deleteAssessmentAttempt(competency.latest_attempt_id!)}
                        className="inline-flex items-center gap-1 rounded-md border border-rose-200 px-3 py-2 text-sm font-medium text-rose-700 hover:bg-rose-50"
                        title="Сбросить результат оценки"
                      >
                        <Trash2 className="h-4 w-4" />
                        Сбросить
                      </button>
                    )}
                    <button
                      type="button"
                      disabled={startingCompetencyId === competency.id || (competency.status === 'completed' && !isRetakeAllowed(competency))}
                      onClick={() => requestStartCompetency(competency)}
                      className={cn(
                        'rounded-md px-3 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50',
                        competency.status === 'completed' && !isRetakeAllowed(competency)
                          ? 'border border-slate-200 bg-slate-50 text-slate-500'
                          : 'bg-primary text-primary-foreground hover:opacity-90'
                      )}
                    >
                      {startingCompetencyId === competency.id ? 'Загрузка...' : startButtonLabel(competency)}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </section>
        </div>
      )}

      {section === 'plan' && canUseDevelopment && (
        <div className="space-y-4">
          <button
            type="button"
            onClick={goHome}
            className={growthToolbarButtonClass}
          >
            <ArrowLeft className="h-4 w-4" />
            Назад
          </button>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={openAiPrompt}
              className={growthToolbarButtonClass}
            >
              <ClipboardCopy className="h-4 w-4" />
              Промпт
            </button>
            <button
              type="button"
              onClick={() => setImportResponseOpen(true)}
              className={growthToolbarButtonClass}
            >
              <FileJson className="h-4 w-4" />
              Импорт ответа
            </button>
            <button
              type="button"
              onClick={openDevelopmentReport}
              className={growthToolbarButtonClass}
            >
              <Map className="h-4 w-4" />
              Отчет
            </button>
            {access?.is_admin && (
              <button
                type="button"
                onClick={openAdminPlanReport}
                className={growthToolbarButtonClass}
              >
                <BarChart3 className="h-4 w-4" />
                Отчетность по сотрудникам
              </button>
            )}
          </div>
          <div className="grid gap-4 xl:grid-cols-[420px_minmax(0,1fr)]">
            <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
              <h2 className="font-medium text-slate-900">Новая цель ИПР</h2>
              <div className="mt-4 space-y-3">
                <select
                  value={planForm.competency_id}
                  onChange={(e) => setPlanForm((prev) => ({ ...prev, competency_id: e.target.value }))}
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                >
                  <option value="">Без привязки к компетенции</option>
                  {competencies.map((item) => (
                    <option key={item.id} value={item.id}>{item.title}</option>
                  ))}
                </select>
                <input
                  value={planForm.goal}
                  onChange={(e) => setPlanForm((prev) => ({ ...prev, goal: e.target.value }))}
                  placeholder="Цель развития"
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                />
                <textarea
                  value={planForm.action_text}
                  onChange={(e) => setPlanForm((prev) => ({ ...prev, action_text: e.target.value }))}
                  placeholder="Мероприятие или действие"
                  className="min-h-24 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                />
                <textarea
                  value={planForm.expected_result}
                  onChange={(e) => setPlanForm((prev) => ({ ...prev, expected_result: e.target.value }))}
                  placeholder="Ожидаемый результат"
                  className="min-h-20 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                />
                <input
                  type="date"
                  value={planForm.due_at}
                  onChange={(e) => setPlanForm((prev) => ({ ...prev, due_at: e.target.value }))}
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                />
                <button
                  type="button"
                  disabled={busy}
                  onClick={createPlanItem}
                  className="w-full rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
                >
                  Добавить в ИПР
                </button>
              </div>
            </section>
            <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
              <h2 className="font-medium text-slate-900">Мой индивидуальный план развития</h2>
              <div className="mt-4 divide-y divide-slate-100">
                {planItems.length === 0 && <p className="py-6 text-sm text-slate-500">Пока нет целей развития.</p>}
                {planItems.map((item) => (
                  <div key={item.id} className="grid gap-3 py-4 lg:grid-cols-[minmax(0,1fr)_260px]">
                    <div className="min-w-0">
                      <div>
                        <h3 className="font-medium text-slate-900">{item.goal}</h3>
                        <p className="text-sm text-slate-500">{item.competency_title || 'Без компетенции'} · срок: {formatDate(item.due_at)}</p>
                      </div>
                      <p className="mt-2 text-sm text-slate-700">{item.action_text}</p>
                      {item.expected_result && <p className="mt-1 text-sm text-slate-500">Результат: {item.expected_result}</p>}
                    </div>
                    <div className="flex items-start gap-2 lg:justify-end">
                      <select
                        value={item.status}
                        onChange={(e) => updatePlanStatus(item, e.target.value as DevelopmentPlanStatus)}
                        className="min-w-0 flex-1 rounded-md border border-slate-300 px-2 py-1 text-sm lg:max-w-[210px]"
                      >
                        {Object.entries(planStatusLabel).map(([value, label]) => (
                          <option key={value} value={value}>{label}</option>
                        ))}
                      </select>
                      <button
                        type="button"
                        onClick={() => deletePlanItem(item)}
                        className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-rose-200 text-rose-700 hover:bg-rose-50"
                        title="Удалить пункт ИПР"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          </div>
        </div>
      )}

      {section === 'constructor' && canUseConstructor && (
        <div className="space-y-4">
          <button
            type="button"
            onClick={goHome}
            className={growthToolbarButtonClass}
          >
            <ArrowLeft className="h-4 w-4" />
            Назад
          </button>
          <div className="grid gap-4 xl:grid-cols-[460px_minmax(0,1fr)]">
            <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
              <h2 className="font-medium text-slate-900">Создать custom-компетенцию</h2>
              <div className="mt-4 space-y-3">
                <input
                  value={constructorForm.title}
                  onChange={(e) => setConstructorForm((prev) => ({ ...prev, title: e.target.value }))}
                  placeholder="Название компетенции"
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                />
                <input
                  value={constructorForm.department}
                  onChange={(e) => setConstructorForm((prev) => ({ ...prev, department: e.target.value }))}
                  placeholder="Отдел или направление"
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                />
                <select
                  value={constructorForm.visibility}
                  onChange={(e) => setConstructorForm((prev) => ({ ...prev, visibility: e.target.value as 'assigned' | 'all' }))}
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                >
                  <option value="assigned">Видно только назначенным сотрудникам</option>
                  <option value="all">Видно всем сотрудникам с разделом развития</option>
                </select>
                <textarea
                  value={constructorForm.description}
                  onChange={(e) => setConstructorForm((prev) => ({ ...prev, description: e.target.value }))}
                  placeholder="Описание"
                  className="min-h-20 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                />
                <div className="space-y-3">
                  {constructorForm.questions.map((question, questionIndex) => (
                    <div key={questionIndex} className="rounded-md border border-slate-200 p-3">
                      <div className="mb-2 flex items-center justify-between gap-2">
                        <span className="text-sm font-medium text-slate-700">Вопрос {questionIndex + 1}</span>
                        {constructorForm.questions.length > 1 && (
                          <button
                            type="button"
                            onClick={() => removeConstructorQuestion(questionIndex)}
                            className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-slate-200 text-slate-500 hover:bg-slate-50"
                            title="Удалить вопрос"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        )}
                      </div>
                      <textarea
                        value={question.text}
                        onChange={(e) => updateConstructorQuestionText(questionIndex, e.target.value)}
                        placeholder="Текст вопроса"
                        className="min-h-20 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                      />
                      <div className="mt-2 space-y-2">
                        {question.choices.map((choice, choiceIndex) => (
                          <input
                            key={choiceIndex}
                            value={choice}
                            onChange={(e) => updateConstructorChoice(questionIndex, choiceIndex, e.target.value)}
                            placeholder={`Вариант ${choiceIndex + 1}`}
                            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                          />
                        ))}
                      </div>
                    </div>
                  ))}
                  <button
                    type="button"
                    onClick={addConstructorQuestion}
                    className="inline-flex w-full items-center justify-center gap-2 rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                  >
                    <Plus className="h-4 w-4" />
                    Добавить вопрос
                  </button>
                </div>
                <textarea
                  value={constructorForm.interpretation}
                  onChange={(e) => setConstructorForm((prev) => ({ ...prev, interpretation: e.target.value }))}
                  placeholder="Интерпретация результата"
                  className="min-h-20 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                />
                <select
                  value={constructorForm.target_user_id}
                  onChange={(e) => setConstructorForm((prev) => ({ ...prev, target_user_id: e.target.value }))}
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                >
                  <option value="">Создать без назначения</option>
                  {users.map((user) => (
                    <option key={user.id} value={user.id}>{user.full_name}</option>
                  ))}
                </select>
                <button
                  type="button"
                  disabled={busy}
                  onClick={createCustomCompetency}
                  className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
                >
                  <Send className="h-4 w-4" />
                  Создать
                </button>
                {lastAssignment && (
                  <p className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
                    Назначение создано. Внутренняя ссылка: {lastAssignment.link}
                  </p>
                )}
              </div>
            </section>
            <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
              <h2 className="font-medium text-slate-900">Созданные компетенции</h2>
              <div className="mt-4 divide-y divide-slate-100">
                {constructorItems.length === 0 && <p className="py-6 text-sm text-slate-500">Пока нет custom-компетенций.</p>}
                {constructorItems.map((item) => (
                  <div key={item.id} className="grid gap-3 py-3 xl:grid-cols-[minmax(0,1fr)_360px]">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="font-medium text-slate-900">{item.title}</h3>
                        <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
                          {item.visibility === 'all' ? 'для всех' : 'по назначению'}
                        </span>
                        {!item.can_edit_content && (
                          <span className="rounded bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700">
                            вопросы заблокированы
                          </span>
                        )}
                      </div>
                      <p className="mt-1 line-clamp-2 text-sm text-slate-500">{item.description || 'Описание не заполнено'}</p>
                      <div className="mt-2 flex flex-wrap gap-3 text-xs text-slate-500">
                        <span>{item.questions_count} вопросов</span>
                        <span>{item.assigned_count || 0} назначено</span>
                        <span>{item.attempts_count || 0} попыток</span>
                        <span>{item.completed_count || 0} завершено</span>
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center justify-end gap-2">
                      <button
                        type="button"
                        onClick={() => openEditCompetency(item)}
                        className="inline-flex items-center gap-1 rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                      >
                        <Edit3 className="h-4 w-4" />
                        Редактировать
                      </button>
                      <button
                        type="button"
                        onClick={() => openAssignCompetency(item)}
                        className="rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                      >
                        Доступ
                      </button>
                      <button
                        type="button"
                        onClick={() => openReport(item)}
                        className="inline-flex items-center gap-1 rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                      >
                        <BarChart3 className="h-4 w-4" />
                        Отчет
                      </button>
                      <button
                        type="button"
                        onClick={() => setDeleteCompetency(item)}
                        className="inline-flex items-center gap-1 rounded-md border border-rose-200 px-3 py-2 text-sm font-medium text-rose-700 hover:bg-rose-50"
                      >
                        <Trash2 className="h-4 w-4" />
                        Удалить
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          </div>
        </div>
      )}

      {aiPrompt && (
        <div className={growthModalBackdropClass}>
          <div className={cn(growthModalPanelClass, 'max-w-4xl')}>
            <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
              <div>
                <h2 className="font-medium text-slate-900">Промпт</h2>
                <p className="mt-1 text-sm text-slate-500">
                  Учтено завершенных оценок: {aiPrompt.completed_assessments_count}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setAiPrompt(null)}
                className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-slate-200 text-slate-500 hover:bg-slate-50"
                title="Закрыть"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="space-y-3 px-5 py-5">
              <textarea
                readOnly
                value={aiPrompt.prompt}
                className="h-[52vh] w-full rounded-md border border-slate-300 bg-slate-50 px-3 py-2 font-mono text-xs leading-5 text-slate-800"
              />
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setAiPrompt(null)}
                  className="rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                >
                  Закрыть
                </button>
                <button
                  type="button"
                  onClick={copyAiPrompt}
                  className="inline-flex items-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
                >
                  <ClipboardCopy className="h-4 w-4" />
                  Скопировать
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {importResponseOpen && (
        <div className={growthModalBackdropClass}>
          <div className={cn(growthModalPanelClass, 'max-w-3xl')}>
            <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
              <div>
                <h2 className="font-medium text-slate-900">Импорт ответа GPT-5</h2>
                <p className="mt-1 text-sm text-slate-500">Вставьте JSON формата dpms_ipr_v1 из ответа модели.</p>
              </div>
              <button
                type="button"
                onClick={() => setImportResponseOpen(false)}
                className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-slate-200 text-slate-500 hover:bg-slate-50"
                title="Закрыть"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="space-y-3 px-5 py-5">
              <textarea
                value={importResponseText}
                onChange={(e) => setImportResponseText(e.target.value)}
                placeholder='{"version":"dpms_ipr_v1","items":[...],"books":[...]}'
                className="h-[44vh] w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-xs leading-5"
              />
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setImportResponseOpen(false)}
                  className="rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                >
                  Отмена
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={importAiResponse}
                  className="rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
                >
                  Импортировать в ИПР
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {developmentReport && (
        <div className={growthModalBackdropClass}>
          <div className={cn(growthModalPanelClass, 'max-w-5xl')}>
            <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
              <div>
                <h2 className="font-medium text-slate-900">Моя дорожная карта развития</h2>
                <p className="mt-1 text-sm text-slate-500">{developmentReport.full_name}</p>
              </div>
              <button
                type="button"
                onClick={() => setDevelopmentReport(null)}
                className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-slate-200 text-slate-500 hover:bg-slate-50"
                title="Закрыть"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="max-h-[76vh] overflow-y-auto px-5 py-5">
              <DevelopmentReportContent report={developmentReport} />
            </div>
          </div>
        </div>
      )}

      {adminPlanReport && (
        <div className={growthModalBackdropClass}>
          <div className={cn(growthModalPanelClass, 'max-w-6xl')}>
            <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
              <div>
                <h2 className="font-medium text-slate-900">Отчетность по развитию сотрудников</h2>
                <p className="mt-1 text-sm text-slate-500">Агрегаты по оценкам и ИПР</p>
              </div>
              <button
                type="button"
                onClick={() => setAdminPlanReport(null)}
                className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-slate-200 text-slate-500 hover:bg-slate-50"
                title="Закрыть"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="max-h-[76vh] space-y-5 overflow-y-auto px-5 py-5">
              <div className="grid gap-3 md:grid-cols-5">
                <div className="rounded-md border border-slate-200 px-3 py-2">
                  <div className="text-lg font-semibold text-slate-900">{adminPlanReport.total_enabled_users}</div>
                  <div className="text-xs text-slate-500">с доступом</div>
                </div>
                <div className="rounded-md border border-slate-200 px-3 py-2">
                  <div className="text-lg font-semibold text-slate-900">{adminPlanReport.users_with_completed_assessments}</div>
                  <div className="text-xs text-slate-500">прошли оценки</div>
                </div>
                <div className="rounded-md border border-slate-200 px-3 py-2">
                  <div className="text-lg font-semibold text-slate-900">{adminPlanReport.completed_assessments_count}</div>
                  <div className="text-xs text-slate-500">оценок всего</div>
                </div>
                <div className="rounded-md border border-slate-200 px-3 py-2">
                  <div className="text-lg font-semibold text-slate-900">{adminPlanReport.users_with_plan}</div>
                  <div className="text-xs text-slate-500">создали ИПР</div>
                </div>
                <div className="rounded-md border border-slate-200 px-3 py-2">
                  <div className="text-lg font-semibold text-emerald-700">{adminPlanReport.plan_done}</div>
                  <div className="text-xs text-slate-500">пунктов выполнено</div>
                </div>
              </div>

              <div className="grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
                <section className="rounded-md border border-slate-200 p-3">
                  <h3 className="text-sm font-medium text-slate-900">Сотрудник</h3>
                  <select
                    value={adminSelectedUserId}
                    onChange={(e) => loadAdminUserPlanReport(e.target.value)}
                    className="mt-3 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                  >
                    <option value="">Выберите сотрудника</option>
                    {adminPlanReport.users.map((user) => (
                      <option key={user.user_id} value={user.user_id}>
                        {user.full_name}
                      </option>
                    ))}
                  </select>
                  <div className="mt-3 divide-y divide-slate-100">
                    {adminPlanReport.users.slice(0, 12).map((user) => (
                      <div key={user.user_id} className="py-2 text-sm">
                        <div className="font-medium text-slate-900">{user.full_name}</div>
                        <div className="text-xs text-slate-500">
                          оценок: {user.completed_assessments_count} · ИПР: {user.plan_total} · прогресс: {user.progress_percent}%
                        </div>
                      </div>
                    ))}
                  </div>
                </section>
                <section className="rounded-md border border-slate-200 p-3">
                  {adminUserReport ? (
                    <DevelopmentReportContent report={adminUserReport} onDeleteAssessment={deleteAssessmentAttempt} />
                  ) : (
                    <p className="py-10 text-center text-sm text-slate-500">Выберите сотрудника для просмотра дорожной карты.</p>
                  )}
                </section>
              </div>
            </div>
          </div>
        </div>
      )}

      {descriptionCompetency && (
        <div className={growthModalBackdropClass}>
          <div className={cn(growthModalPanelClass, 'max-w-3xl')}>
            <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="font-medium text-slate-900">{descriptionCompetency.title}</h2>
                  <span className={cn('rounded px-2 py-0.5 text-xs font-medium', statusBadgeClass(descriptionCompetency.status))}>
                    {statusLabel(descriptionCompetency.status)}
                  </span>
                  {descriptionCompetency.source === 'builtin' && (
                    <span className="rounded bg-violet-50 px-2 py-0.5 text-xs font-medium text-violet-700">
                      Базовая
                    </span>
                  )}
                </div>
                <p className="mt-1 text-sm text-slate-500">
                  {descriptionCompetency.questions_count} вопросов, {QUESTION_SECONDS} секунд на вопрос
                </p>
              </div>
              <button
                type="button"
                onClick={() => setDescriptionCompetency(null)}
                className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-slate-200 text-slate-500 hover:bg-slate-50"
                title="Закрыть"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="max-h-[70vh] overflow-y-auto px-5 py-5">
              <div className="space-y-3 text-sm leading-6 text-slate-700">
                {cleanLines(descriptionCompetency.description).length > 0 ? (
                  cleanLines(descriptionCompetency.description).map((line, index) => <p key={index}>{line}</p>)
                ) : (
                  <p className="text-slate-500">Описание не заполнено.</p>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {helpModal && (
        <div className={growthModalBackdropClass}>
          <div className={cn(growthModalPanelClass, 'max-w-3xl')}>
            <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
              <h2 className="font-medium text-slate-900">
                {helpModal === 'overview' ? 'Что я здесь делаю' : 'Как читать результат'}
              </h2>
              <button
                type="button"
                onClick={() => setHelpModal(null)}
                className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-slate-200 text-slate-500 hover:bg-slate-50"
                title="Закрыть"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="max-h-[72vh] space-y-4 overflow-y-auto px-5 py-5 text-sm leading-6 text-slate-700">
              {helpModal === 'overview' ? (
                <>
                  <p>
                    Раздел развития нужен, чтобы сотрудник сам оценил текущий уровень управленческих и рабочих компетенций,
                    увидел сильные стороны, дефициты и риски чрезмерного развития, а затем собрал индивидуальный план развития.
                  </p>
                  <p>
                    Базовые шесть компетенций основаны на логике Lominger: компетенция описывается не абстрактным качеством,
                    а наблюдаемыми поведенческими маркерами. Для каждой компетенции важны три зоны: развито, не развито,
                    чрезмерно развито.
                  </p>
                  <p>
                    Развитая компетенция проявляется как устойчивое поведение, которое помогает достигать результата.
                    Неразвитая компетенция проявляется как повторяющийся дефицит: сотрудник избегает действия, теряет темп,
                    не держит качество коммуникации или не переводит намерение в результат.
                  </p>
                  <p>
                    Чрезмерное развитие тоже риск. Сильная сторона, доведенная до перекоса, может блокировать другие
                    компетенции: высокая ориентация на действие может ломать командность, избыточная осторожность может
                    блокировать инициативу, сильная экспертность может снижать готовность делегировать.
                  </p>
                  <p>
                    Карта компетенции помогает отделить самооценку от общего впечатления: вопрос фиксирует конкретный
                    маркер поведения, варианты ответа переводят его в оценку, интерпретация показывает, куда стоит смотреть
                    при развитии и разговоре one-to-one.
                  </p>
                </>
              ) : (
                <>
                  <p>
                    ИБ показывает базовую выраженность компетенции по ответам. Чем выше ИБ, тем чаще сотрудник выбирает
                    поведение, соответствующее развитой компетенции.
                  </p>
                  <p>
                    ИЧ показывает риск чрезмерного развития. Высокий ИЧ не означает плохой результат сам по себе, но
                    подсвечивает возможный перекос: компетенция может использоваться слишком жестко и мешать другим
                    навыкам или командному взаимодействию.
                  </p>
                  <p>
                    Интерпретация не является приговором или кадровым решением. Это фактура для разговора: какие ситуации
                    стоит разобрать, какие маркеры подтвердились, какие действия внести в ИПР и по каким признакам затем
                    проверять прогресс.
                  </p>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {editingCompetency && editForm && (
        <div className={growthModalBackdropClass}>
          <div className={cn(growthModalPanelClass, 'max-w-4xl')}>
            <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
              <div>
                <h2 className="font-medium text-slate-900">Редактировать компетенцию</h2>
                <p className="mt-1 text-sm text-slate-500">
                  {editingCompetency.can_edit_content
                    ? 'Можно менять метаданные, вопросы и интерпретацию.'
                    : 'Есть попытки прохождения: вопросы заблокированы, доступны метаданные и видимость.'}
                </p>
              </div>
              <button
                type="button"
                onClick={() => {
                  setEditingCompetency(null)
                  setEditForm(null)
                }}
                className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-slate-200 text-slate-500 hover:bg-slate-50"
                title="Закрыть"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="max-h-[72vh] space-y-3 overflow-y-auto px-5 py-5">
              <input
                value={editForm.title}
                onChange={(e) => setEditForm((prev) => (prev ? { ...prev, title: e.target.value } : prev))}
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              />
              <div className="grid gap-3 md:grid-cols-2">
                <input
                  value={editForm.department}
                  onChange={(e) => setEditForm((prev) => (prev ? { ...prev, department: e.target.value } : prev))}
                  placeholder="Отдел или направление"
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                />
                <select
                  value={editForm.visibility}
                  onChange={(e) => setEditForm((prev) => (prev ? { ...prev, visibility: e.target.value as 'assigned' | 'all' } : prev))}
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                >
                  <option value="assigned">Видно только назначенным сотрудникам</option>
                  <option value="all">Видно всем сотрудникам с разделом развития</option>
                </select>
              </div>
              <textarea
                value={editForm.description}
                onChange={(e) => setEditForm((prev) => (prev ? { ...prev, description: e.target.value } : prev))}
                className="min-h-20 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              />
              {editingCompetency.can_edit_content && (
                <div className="space-y-3">
                  {editForm.questions.map((question, questionIndex) => (
                    <div key={questionIndex} className="rounded-md border border-slate-200 p-3">
                      <div className="mb-2 flex items-center justify-between gap-2">
                        <span className="text-sm font-medium text-slate-700">Вопрос {questionIndex + 1}</span>
                        {editForm.questions.length > 1 && (
                          <button
                            type="button"
                            onClick={() => setEditForm((prev) => (prev ? removeQuestionFromForm(prev, questionIndex) : prev))}
                            className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-slate-200 text-slate-500 hover:bg-slate-50"
                            title="Удалить вопрос"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        )}
                      </div>
                      <textarea
                        value={question.text}
                        onChange={(e) => setEditForm((prev) => (prev ? updateQuestionTextInForm(prev, questionIndex, e.target.value) : prev))}
                        className="min-h-20 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                      />
                      <div className="mt-2 space-y-2">
                        {question.choices.map((choice, choiceIndex) => (
                          <input
                            key={choiceIndex}
                            value={choice}
                            onChange={(e) => setEditForm((prev) => (prev ? updateChoiceInForm(prev, questionIndex, choiceIndex, e.target.value) : prev))}
                            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                          />
                        ))}
                      </div>
                    </div>
                  ))}
                  <button
                    type="button"
                    onClick={() => setEditForm((prev) => (prev ? addQuestionToForm(prev) : prev))}
                    className="inline-flex w-full items-center justify-center gap-2 rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                  >
                    <Plus className="h-4 w-4" />
                    Добавить вопрос
                  </button>
                  <textarea
                    value={editForm.interpretation}
                    onChange={(e) => setEditForm((prev) => (prev ? { ...prev, interpretation: e.target.value } : prev))}
                    placeholder="Интерпретация результата"
                    className="min-h-20 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                  />
                </div>
              )}
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => {
                    setEditingCompetency(null)
                    setEditForm(null)
                  }}
                  className="rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                >
                  Отмена
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={saveEditCompetency}
                  className="rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
                >
                  Сохранить
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {assignCompetency && (
        <div className={growthModalBackdropClass}>
          <div className={cn(growthModalPanelClass, 'max-w-2xl')}>
            <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
              <h2 className="font-medium text-slate-900">Доступ к опросу</h2>
              <button
                type="button"
                onClick={() => setAssignCompetency(null)}
                className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-slate-200 text-slate-500 hover:bg-slate-50"
                title="Закрыть"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="space-y-4 px-5 py-5">
              <select
                value={assignVisibility}
                onChange={(e) => setAssignVisibility(e.target.value as 'assigned' | 'all')}
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              >
                <option value="assigned">Только выбранные сотрудники</option>
                <option value="all">Все сотрудники с доступом к разделу развития</option>
              </select>
              {assignVisibility === 'assigned' ? (
                <div className="max-h-80 divide-y divide-slate-100 overflow-y-auto rounded-md border border-slate-200">
                  {users.map((user) => (
                    <label key={user.id} className="flex cursor-pointer items-center gap-3 px-3 py-2 text-sm hover:bg-slate-50">
                      <input
                        type="checkbox"
                        checked={assignSelectedIds.includes(user.id)}
                        onChange={(e) => {
                          setAssignSelectedIds((prev) =>
                            e.target.checked ? [...prev, user.id] : prev.filter((id) => id !== user.id)
                          )
                        }}
                      />
                      <span className="min-w-0 flex-1 truncate">{user.full_name}</span>
                      <span className="text-xs text-slate-400">{user.email}</span>
                    </label>
                  ))}
                </div>
              ) : (
                <p className="rounded-md bg-blue-50 px-3 py-2 text-sm text-blue-800">
                  Опрос будет виден всем активным сотрудникам, у которых включен раздел развития компетенций.
                </p>
              )}
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setAssignCompetency(null)}
                  className="rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                >
                  Отмена
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={saveAssignments}
                  className="rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
                >
                  Сохранить
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {report && (
        <div className={growthModalBackdropClass}>
          <div className={cn(growthModalPanelClass, 'max-w-5xl')}>
            <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
              <div>
                <h2 className="font-medium text-slate-900">Отчет: {report.title}</h2>
                <p className="mt-1 text-sm text-slate-500">
                  Назначено: {report.assigned_count}, завершено: {report.completed_count}, режим: {report.visibility === 'all' ? 'для всех' : 'по назначению'}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setReport(null)}
                className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-slate-200 text-slate-500 hover:bg-slate-50"
                title="Закрыть"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="max-h-[72vh] overflow-y-auto px-5 py-5">
              <div className="divide-y divide-slate-100 rounded-md border border-slate-200">
                {report.rows.length === 0 && <p className="px-3 py-6 text-sm text-slate-500">Пока нет сотрудников в отчете.</p>}
                {report.rows.map((row) => (
                  <div key={row.user_id} className="grid gap-3 px-3 py-3 lg:grid-cols-[240px_160px_140px_minmax(0,1fr)]">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-slate-900">{row.full_name}</div>
                      <div className="truncate text-xs text-slate-500">{row.email}</div>
                    </div>
                    <div className="text-sm text-slate-600">
                      {statusLabel(row.attempt_status)}
                      {row.completed_at && <div className="text-xs text-slate-400">{formatDate(row.completed_at)}</div>}
                    </div>
                    <div className="text-sm text-slate-600">
                      ИБ: {row.score_ib ?? '—'}<br />
                      ИЧ: {row.score_ich ?? '—'}
                    </div>
                    <div className="space-y-1 text-sm text-slate-700">
                      {row.attention_points.map((point, index) => (
                        <p key={index}>{point}</p>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {deleteCompetency && (
        <div className={growthModalBackdropClass}>
          <div className={cn(growthModalPanelClass, 'max-w-md')}>
            <div className="border-b border-slate-100 px-5 py-4">
              <h2 className="font-medium text-slate-900">Удалить опрос</h2>
            </div>
            <div className="space-y-4 px-5 py-5">
              <p className="text-sm leading-6 text-slate-700">
                Опрос «{deleteCompetency.title}» будет скрыт из конструктора и списка доступных оценок.
              </p>
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setDeleteCompetency(null)}
                  className="rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                >
                  Отмена
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={confirmDeleteCompetency}
                  className="rounded-md bg-rose-600 px-3 py-2 text-sm font-medium text-white hover:bg-rose-700 disabled:opacity-50"
                >
                  Удалить
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {pendingStartCompetency && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 px-4 py-6">
          <div className="w-full max-w-xl rounded-lg bg-white shadow-xl">
            <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
              <h2 className="font-medium text-slate-900">Начать оценку</h2>
              <button
                type="button"
                onClick={() => setPendingStartCompetency(null)}
                className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-slate-200 text-slate-500 hover:bg-slate-50"
                title="Закрыть"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="space-y-4 px-5 py-5">
              <p className="text-sm leading-6 text-slate-700">
                Вы начинаете оценку по компетенции «{pendingStartCompetency.title}». На каждый вопрос отводится {QUESTION_SECONDS} секунд.
              </p>
              <div className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">
                {pendingStartCompetency.status === 'completed'
                  ? 'Это повторная оценка. Следующая повторная оценка будет доступна только через три месяца после завершения.'
                  : 'После завершения повторная оценка будет доступна только через три месяца.'}
              </div>
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setPendingStartCompetency(null)}
                  className="rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                >
                  Отмена
                </button>
                <button
                  type="button"
                  disabled={startingCompetencyId === pendingStartCompetency.id}
                  onClick={() => startCompetency(pendingStartCompetency)}
                  className="rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
                >
                  {startingCompetencyId === pendingStartCompetency.id ? 'Загрузка...' : startButtonLabel(pendingStartCompetency)}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {activeAttempt && activeQuestion && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 px-4 py-6">
          <div className="w-full max-w-2xl rounded-lg bg-white shadow-xl">
            <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
              <div>
                <h2 className="font-medium text-slate-900">{activeAttempt.competency_title}</h2>
                <p className="mt-1 text-sm text-slate-500">Вопрос {questionIndex + 1} из {activeAttempt.questions.length}</p>
              </div>
              <div className={cn(
                'inline-flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium',
                secondsLeft <= 10 ? 'bg-red-50 text-red-700' : 'bg-slate-100 text-slate-700'
              )}>
                <Timer className="h-4 w-4" />
                {secondsLeft}
              </div>
            </div>
            <div className="space-y-4 px-5 py-5">
              <p className="text-base font-medium leading-7 text-slate-900">{activeQuestion.text}</p>
              <div className="space-y-2">
                {activeQuestion.choices.map((choice) => (
                  <button
                    key={choice.id}
                    type="button"
                    disabled={busy}
                    onClick={() => answerQuestion(choice.id)}
                    className="flex w-full items-center justify-between rounded-md border border-slate-200 px-4 py-3 text-left text-sm text-slate-800 hover:border-primary/40 hover:bg-slate-50 disabled:opacity-50"
                  >
                    {choice.text}
                    <CheckCircle2 className="h-4 w-4 text-slate-300" />
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {result && (
        <div className={growthModalBackdropClass}>
          <div className={cn(growthModalPanelClass, 'max-w-2xl')}>
            <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
              <div className="flex items-center gap-3">
                <CheckCircle2 className="h-6 w-6 text-emerald-600" />
                <div>
                  <h2 className="font-medium text-slate-900">{result.competency_title}</h2>
                  <p className="text-sm text-slate-500">Результат оценки</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setResult(null)}
                className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-slate-200 text-slate-500 hover:bg-slate-50"
                title="Закрыть"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="space-y-4 px-5 py-5">
              <div className="grid gap-3 sm:grid-cols-3">
                <div className="rounded-md bg-slate-50 px-3 py-2">
                  <div className="text-xs text-slate-500">ИБ</div>
                  <div className="text-xl font-semibold text-slate-900">{result.score_ib ?? '—'}</div>
                </div>
                <div className="rounded-md bg-slate-50 px-3 py-2">
                  <div className="text-xs text-slate-500">ИЧ</div>
                  <div className="text-xl font-semibold text-slate-900">{result.score_ich ?? '—'}</div>
                </div>
                <div className="rounded-md bg-slate-50 px-3 py-2">
                  <div className="text-xs text-slate-500">Повтор</div>
                  <div className="text-sm font-medium text-slate-900">{formatDate(result.retake_allowed_at)}</div>
                </div>
              </div>
              <div className="space-y-2 text-sm leading-6 text-slate-700">
                {cleanLines(result.interpretation_text).map((line, index) => (
                  <p key={index}>{line}</p>
                ))}
              </div>
              <button
                type="button"
                onClick={() => {
                  setResult(null)
                  setSection('assessment')
                }}
                className="rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
              >
                Закрыть
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
