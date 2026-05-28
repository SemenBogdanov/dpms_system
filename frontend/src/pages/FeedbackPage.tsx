import { useCallback, useEffect, useMemo, useState } from 'react'
import { Clipboard, ExternalLink, MessageSquare, Plus, X } from 'lucide-react'
import { api } from '@/api/client'
import type {
  FeedbackCategory,
  FeedbackObjectType,
  FeedbackPriority,
  FeedbackRequest,
  FeedbackRequestCreate,
  FeedbackRequestListResponse,
  FeedbackRequestUpdate,
  FeedbackStatus,
  User,
} from '@/api/types'
import { useAuth } from '@/contexts/AuthContext'
import toast from 'react-hot-toast'

const categoryLabel: Record<FeedbackCategory, string> = {
  improvement: 'Улучшение',
  disagreement: 'Несогласие',
  bug: 'Ошибка',
  process: 'Процесс',
  other: 'Другое',
}

const statusLabel: Record<FeedbackStatus, string> = {
  new: 'Новое',
  in_review: 'На рассмотрении',
  triage: 'Разбор',
  needs_info: 'Нужна информация',
  accepted: 'Принято',
  planned: 'Запланировано',
  rejected: 'Отклонено',
  done: 'Закрыто',
  withdrawn: 'Отозвано',
}

const priorityLabel: Record<FeedbackPriority, string> = {
  low: 'Низкий',
  medium: 'Средний',
  high: 'Высокий',
}

const objectTypeLabel: Record<FeedbackObjectType, string> = {
  task: 'Задача',
  shop: 'Магазин',
  report: 'Отчет',
  rule: 'Правило',
  kb: 'База знаний',
  other: 'Другое',
}

const statusOptions: FeedbackStatus[] = ['new', 'triage', 'needs_info', 'accepted', 'planned', 'done', 'rejected', 'withdrawn']
const statStatuses: FeedbackStatus[] = ['new', 'triage', 'needs_info', 'accepted', 'planned', 'done']

const EMPTY_FORM: FeedbackRequestCreate = {
  category: 'improvement',
  priority: 'medium',
  title: '',
  description: '',
  object_type: 'other',
  object_ref: '',
  expected_result: '',
  impact: '',
  evidence_links: [],
}

function formatDate(value: string | null): string {
  if (!value) return '—'
  return new Date(value).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function statusClass(status: FeedbackStatus): string {
  if (status === 'new') return 'bg-blue-50 text-blue-700 ring-blue-100'
  if (status === 'triage' || status === 'in_review') return 'bg-amber-50 text-amber-700 ring-amber-100'
  if (status === 'needs_info') return 'bg-orange-50 text-orange-700 ring-orange-100'
  if (status === 'accepted' || status === 'planned') return 'bg-emerald-50 text-emerald-700 ring-emerald-100'
  if (status === 'rejected') return 'bg-red-50 text-red-700 ring-red-100'
  return 'bg-slate-100 text-slate-700 ring-slate-200'
}

function priorityClass(priority: FeedbackPriority): string {
  if (priority === 'high') return 'bg-red-50 text-red-700'
  if (priority === 'medium') return 'bg-slate-100 text-slate-700'
  return 'bg-slate-50 text-slate-500'
}

function parseLinks(value: string): string[] {
  return value
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean)
    .filter((item, index, array) => array.indexOf(item) === index)
    .slice(0, 10)
}

function linksToText(value: string[] | null | undefined): string {
  return (value ?? []).join('\n')
}

async function copyText(value: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value)
    return
  }
  const element = document.createElement('textarea')
  element.value = value
  document.body.appendChild(element)
  element.select()
  document.execCommand('copy')
  element.remove()
}

export function FeedbackPage() {
  const { user: currentUser } = useAuth()
  const isManager = currentUser?.role === 'admin' || currentUser?.role === 'teamlead'
  const [response, setResponse] = useState<FeedbackRequestListResponse | null>(null)
  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<'all' | FeedbackStatus>('all')
  const [categoryFilter, setCategoryFilter] = useState<'all' | FeedbackCategory>('all')
  const [authorFilter, setAuthorFilter] = useState('all')
  const [createOpen, setCreateOpen] = useState(false)
  const [form, setForm] = useState<FeedbackRequestCreate>(EMPTY_FORM)
  const [formLinksText, setFormLinksText] = useState('')
  const [selected, setSelected] = useState<FeedbackRequest | null>(null)
  const [reviewForm, setReviewForm] = useState<FeedbackRequestUpdate>({})
  const [reviewLinksText, setReviewLinksText] = useState('')
  const [busy, setBusy] = useState(false)

  const loadFeedback = useCallback(async () => {
    const params: Record<string, string> = { limit: '200' }
    if (statusFilter !== 'all') params.status = statusFilter
    if (categoryFilter !== 'all') params.category = categoryFilter
    if (isManager && authorFilter !== 'all') params.author_id = authorFilter
    try {
      const data = await api.get<FeedbackRequestListResponse>('/api/feedback', params)
      setResponse(data)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [authorFilter, categoryFilter, isManager, statusFilter])

  useEffect(() => {
    loadFeedback()
  }, [loadFeedback])

  useEffect(() => {
    if (!isManager) return
    api.get<User[]>('/api/users').then(setUsers).catch(() => setUsers([]))
  }, [isManager])

  const items = useMemo(() => response?.items ?? [], [response])
  const managerUsers = users.filter((u) => u.role === 'admin' || u.role === 'teamlead')
  const stats = useMemo(() => {
    return items.reduce(
      (acc, item) => {
        acc.total += 1
        acc[item.status] += 1
        return acc
      },
      {
        total: 0,
        new: 0,
        in_review: 0,
        triage: 0,
        needs_info: 0,
        accepted: 0,
        planned: 0,
        rejected: 0,
        done: 0,
        withdrawn: 0,
      } as Record<FeedbackStatus | 'total', number>
    )
  }, [items])

  const openDetails = (item: FeedbackRequest) => {
    setSelected(item)
    setReviewLinksText(linksToText(item.evidence_links))
    setReviewForm({
      status: item.status === 'in_review' ? 'triage' : item.status,
      priority: item.priority,
      reviewer_id: item.reviewer_id,
      resolution: item.resolution ?? '',
      object_type: item.object_type,
      object_ref: item.object_ref ?? '',
      expected_result: item.expected_result ?? '',
      impact: item.impact ?? '',
      evidence_links: item.evidence_links,
      decision_summary: item.decision_summary ?? '',
      decision_reason: item.decision_reason ?? '',
      next_action: item.next_action ?? '',
      target_release: item.target_release ?? '',
    })
  }

  const handleCopy = async (item: FeedbackRequest) => {
    try {
      await copyText(`${item.feedback_code} — ${item.title}`)
      toast.success('Номер и заголовок скопированы')
    } catch {
      toast.error('Не удалось скопировать')
    }
  }

  const handleCreate = async () => {
    setBusy(true)
    try {
      const payload: FeedbackRequestCreate = {
        ...form,
        evidence_links: parseLinks(formLinksText),
      }
      const created = await api.post<FeedbackRequest>('/api/feedback', payload)
      toast.success(`Обращение ${created.feedback_code} создано`)
      setCreateOpen(false)
      setForm(EMPTY_FORM)
      setFormLinksText('')
      setSelected(created)
      await loadFeedback()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка создания')
    } finally {
      setBusy(false)
    }
  }

  const handleReviewSave = async () => {
    if (!selected) return
    setBusy(true)
    try {
      const payload: FeedbackRequestUpdate = {
        ...reviewForm,
        reviewer_id: reviewForm.reviewer_id || null,
        resolution: reviewForm.resolution || null,
        evidence_links: parseLinks(reviewLinksText),
        object_ref: reviewForm.object_ref || null,
        expected_result: reviewForm.expected_result || null,
        impact: reviewForm.impact || null,
        decision_summary: reviewForm.decision_summary || null,
        decision_reason: reviewForm.decision_reason || null,
        next_action: reviewForm.next_action || null,
        target_release: reviewForm.target_release || null,
      }
      const updated = await api.patch<FeedbackRequest>(`/api/feedback/${selected.id}`, payload)
      toast.success(`Решение по ${updated.feedback_code} сохранено`)
      setSelected(updated)
      setReviewLinksText(linksToText(updated.evidence_links))
      await loadFeedback()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка сохранения')
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <div className="text-slate-500">Загрузка...</div>
  if (error) return <div className="text-red-600">{error}</div>

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Обратная связь</h1>
          <p className="mt-1 text-sm text-slate-500">Реестр обращений, несогласий, ошибок и предложений.</p>
        </div>
        <button
          type="button"
          onClick={() => setCreateOpen(true)}
          className="inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-dark"
        >
          <Plus className="h-4 w-4" />
          Создать
        </button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
        {statStatuses.map((status) => (
          <button
            key={status}
            type="button"
            onClick={() => setStatusFilter(statusFilter === status ? 'all' : status)}
            className="rounded-lg border border-slate-200 bg-white p-3 text-left shadow-sm hover:bg-slate-50"
          >
            <div className="text-xs text-slate-500">{statusLabel[status]}</div>
            <div className="mt-1 text-xl font-semibold text-slate-900">{stats[status]}</div>
          </button>
        ))}
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="grid gap-3 md:grid-cols-4">
          <label className="text-sm font-medium text-slate-700">
            Статус
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as 'all' | FeedbackStatus)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            >
              <option value="all">Все</option>
              {statusOptions.map((value) => <option key={value} value={value}>{statusLabel[value]}</option>)}
            </select>
          </label>
          <label className="text-sm font-medium text-slate-700">
            Тип
            <select
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value as 'all' | FeedbackCategory)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            >
              <option value="all">Все</option>
              {Object.entries(categoryLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          {isManager && (
            <label className="text-sm font-medium text-slate-700 md:col-span-2">
              Автор
              <select
                value={authorFilter}
                onChange={(e) => setAuthorFilter(e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              >
                <option value="all">Все сотрудники</option>
                {users.map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}
              </select>
            </label>
          )}
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <div className="font-medium text-slate-800">Реестр обращений</div>
          <div className="text-sm text-slate-500">Всего: {response?.total ?? stats.total}</div>
        </div>
        {items.length === 0 ? (
          <div className="flex flex-col items-center gap-2 p-8 text-center text-slate-500">
            <MessageSquare className="h-8 w-8 text-slate-300" />
            <p>Обращений пока нет</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-4 py-3">Номер</th>
                  <th className="px-4 py-3">Статус</th>
                  <th className="px-4 py-3">Обращение</th>
                  <th className="px-4 py-3">Объект</th>
                  <th className="px-4 py-3">Автор</th>
                  <th className="px-4 py-3">Ответственный</th>
                  <th className="px-4 py-3">Обновлено</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                    <td className="px-4 py-3 align-top">
                      <button
                        type="button"
                        onClick={() => handleCopy(item)}
                        className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-2 py-1 font-mono text-xs font-semibold text-slate-700 hover:bg-slate-200"
                        title="Скопировать номер и заголовок"
                      >
                        {item.feedback_code}
                        <Clipboard className="h-3.5 w-3.5" />
                      </button>
                    </td>
                    <td className="px-4 py-3 align-top">
                      <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ring-1 ${statusClass(item.status)}`}>
                        {statusLabel[item.status]}
                      </span>
                    </td>
                    <td className="min-w-[280px] px-4 py-3 align-top">
                      <button type="button" onClick={() => openDetails(item)} className="text-left">
                        <div className="font-medium text-slate-900 hover:text-accent-dark">{item.title}</div>
                        <div className="mt-1 flex flex-wrap gap-2 text-xs">
                          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-600">{categoryLabel[item.category]}</span>
                          <span className={`rounded-full px-2 py-0.5 ${priorityClass(item.priority)}`}>{priorityLabel[item.priority]}</span>
                          {item.target_release && <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-emerald-700">{item.target_release}</span>}
                        </div>
                      </button>
                    </td>
                    <td className="px-4 py-3 align-top text-slate-600">
                      <div>{objectTypeLabel[item.object_type]}</div>
                      {item.object_ref && <div className="mt-1 max-w-[180px] truncate text-xs text-slate-400">{item.object_ref}</div>}
                    </td>
                    <td className="px-4 py-3 align-top text-slate-600">{item.author_name}</td>
                    <td className="px-4 py-3 align-top text-slate-600">{item.reviewer_name ?? '—'}</td>
                    <td className="px-4 py-3 align-top text-slate-500">{formatDate(item.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {createOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
          <div className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-xl bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-slate-100 p-4">
              <h2 className="font-semibold text-slate-900">Новое обращение</h2>
              <button type="button" onClick={() => setCreateOpen(false)} className="rounded-lg p-1 text-slate-400 hover:bg-slate-100">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="space-y-5 p-4">
              <section className="space-y-4">
                <div className="grid gap-3 sm:grid-cols-2">
                  <label className="text-sm font-medium text-slate-700">
                    Тип
                    <select value={form.category} onChange={(e) => setForm((v) => ({ ...v, category: e.target.value as FeedbackCategory }))} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
                      {Object.entries(categoryLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                    </select>
                  </label>
                  <label className="text-sm font-medium text-slate-700">
                    Приоритет
                    <select value={form.priority} onChange={(e) => setForm((v) => ({ ...v, priority: e.target.value as FeedbackPriority }))} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
                      {Object.entries(priorityLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                    </select>
                  </label>
                </div>
                <label className="block text-sm font-medium text-slate-700">
                  Заголовок
                  <input value={form.title} onChange={(e) => setForm((v) => ({ ...v, title: e.target.value }))} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
                </label>
                <label className="block text-sm font-medium text-slate-700">
                  Описание
                  <textarea value={form.description} onChange={(e) => setForm((v) => ({ ...v, description: e.target.value }))} rows={5} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
                </label>
              </section>

              <section className="rounded-xl border border-slate-200 p-4">
                <h3 className="font-medium text-slate-800">Контекст</h3>
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  <label className="text-sm font-medium text-slate-700">
                    Объект
                    <select value={form.object_type} onChange={(e) => setForm((v) => ({ ...v, object_type: e.target.value as FeedbackObjectType }))} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
                      {Object.entries(objectTypeLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                    </select>
                  </label>
                  <label className="text-sm font-medium text-slate-700">
                    Ссылка / номер / правило
                    <input value={form.object_ref ?? ''} onChange={(e) => setForm((v) => ({ ...v, object_ref: e.target.value }))} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
                  </label>
                </div>
                <label className="mt-3 block text-sm font-medium text-slate-700">
                  Ожидаемый результат
                  <textarea value={form.expected_result ?? ''} onChange={(e) => setForm((v) => ({ ...v, expected_result: e.target.value }))} rows={3} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
                </label>
                <label className="mt-3 block text-sm font-medium text-slate-700">
                  Влияние
                  <textarea value={form.impact ?? ''} onChange={(e) => setForm((v) => ({ ...v, impact: e.target.value }))} rows={3} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
                </label>
                <label className="mt-3 block text-sm font-medium text-slate-700">
                  Ссылки на доказательства
                  <textarea value={formLinksText} onChange={(e) => setFormLinksText(e.target.value)} rows={3} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
                </label>
              </section>
            </div>
            <div className="flex justify-end gap-2 border-t border-slate-100 p-4">
              <button type="button" onClick={() => setCreateOpen(false)} className="rounded-lg border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50">Отмена</button>
              <button type="button" onClick={handleCreate} disabled={busy} className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-dark disabled:opacity-50">Создать</button>
            </div>
          </div>
        </div>
      )}

      {selected && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
          <div className="max-h-[90vh] w-full max-w-4xl overflow-y-auto rounded-xl bg-white shadow-xl">
            <div className="flex items-start justify-between gap-3 border-b border-slate-100 p-4">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <button type="button" onClick={() => handleCopy(selected)} className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-2 py-1 font-mono text-xs font-semibold text-slate-700 hover:bg-slate-200">
                    {selected.feedback_code}
                    <Clipboard className="h-3.5 w-3.5" />
                  </button>
                  <span className={`rounded-full px-2.5 py-1 text-xs font-medium ring-1 ${statusClass(selected.status)}`}>{statusLabel[selected.status]}</span>
                </div>
                <h2 className="mt-2 font-semibold text-slate-900">{selected.title}</h2>
                <p className="mt-1 text-sm text-slate-500">{categoryLabel[selected.category]} · {selected.author_name}</p>
              </div>
              <button type="button" onClick={() => setSelected(null)} className="rounded-lg p-1 text-slate-400 hover:bg-slate-100">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="grid gap-5 p-4 lg:grid-cols-[1fr_280px]">
              <div className="space-y-5">
                <section>
                  <h3 className="text-sm font-medium text-slate-700">Описание</h3>
                  <p className="mt-2 whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-sm leading-6 text-slate-700">{selected.description}</p>
                </section>
                <section className="rounded-xl border border-slate-200 p-4">
                  <h3 className="font-medium text-slate-800">Артефакты заявки</h3>
                  <div className="mt-3 grid gap-3 sm:grid-cols-2">
                    <div>
                      <div className="text-xs text-slate-500">Объект</div>
                      <div className="mt-1 text-sm text-slate-800">{objectTypeLabel[selected.object_type]}</div>
                    </div>
                    <div>
                      <div className="text-xs text-slate-500">Ссылка / номер / правило</div>
                      <div className="mt-1 break-words text-sm text-slate-800">{selected.object_ref || '—'}</div>
                    </div>
                  </div>
                  <div className="mt-3 grid gap-3 sm:grid-cols-2">
                    <div>
                      <div className="text-xs text-slate-500">Ожидаемый результат</div>
                      <div className="mt-1 whitespace-pre-wrap text-sm text-slate-800">{selected.expected_result || '—'}</div>
                    </div>
                    <div>
                      <div className="text-xs text-slate-500">Влияние</div>
                      <div className="mt-1 whitespace-pre-wrap text-sm text-slate-800">{selected.impact || '—'}</div>
                    </div>
                  </div>
                  <div className="mt-3">
                    <div className="text-xs text-slate-500">Доказательства</div>
                    {selected.evidence_links.length > 0 ? (
                      <div className="mt-2 flex flex-col gap-1">
                        {selected.evidence_links.map((link) => (
                          <a key={link} href={link} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 break-all text-sm text-accent-dark hover:underline">
                            {link}
                            <ExternalLink className="h-3.5 w-3.5 shrink-0" />
                          </a>
                        ))}
                      </div>
                    ) : <div className="mt-1 text-sm text-slate-500">—</div>}
                  </div>
                </section>

                <section className="rounded-xl border border-slate-200 p-4">
                  <h3 className="font-medium text-slate-800">Решение</h3>
                  <div className="mt-3 space-y-3 text-sm">
                    <div>
                      <div className="text-xs text-slate-500">Коротко</div>
                      <div className="mt-1 whitespace-pre-wrap text-slate-800">{selected.decision_summary || selected.resolution || 'Решение пока не зафиксировано.'}</div>
                    </div>
                    <div>
                      <div className="text-xs text-slate-500">Обоснование</div>
                      <div className="mt-1 whitespace-pre-wrap text-slate-800">{selected.decision_reason || '—'}</div>
                    </div>
                    <div className="grid gap-3 sm:grid-cols-2">
                      <div>
                        <div className="text-xs text-slate-500">Следующее действие</div>
                        <div className="mt-1 whitespace-pre-wrap text-slate-800">{selected.next_action || '—'}</div>
                      </div>
                      <div>
                        <div className="text-xs text-slate-500">Релиз / срок</div>
                        <div className="mt-1 text-slate-800">{selected.target_release || '—'}</div>
                      </div>
                    </div>
                    <div className="text-xs text-slate-500">
                      {selected.decided_by_name ? `${selected.decided_by_name} · ${formatDate(selected.decided_at)}` : 'Решение не принято'}
                    </div>
                  </div>
                </section>

                {isManager && (
                  <section className="rounded-xl border border-slate-200 p-4">
                    <h3 className="font-medium text-slate-800">Рассмотрение</h3>
                    <div className="mt-3 grid gap-3 sm:grid-cols-3">
                      <label className="text-sm font-medium text-slate-700">
                        Статус
                        <select value={reviewForm.status ?? selected.status} onChange={(e) => setReviewForm((v) => ({ ...v, status: e.target.value as FeedbackStatus }))} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
                          {statusOptions.map((value) => <option key={value} value={value}>{statusLabel[value]}</option>)}
                        </select>
                      </label>
                      <label className="text-sm font-medium text-slate-700">
                        Приоритет
                        <select value={reviewForm.priority ?? selected.priority} onChange={(e) => setReviewForm((v) => ({ ...v, priority: e.target.value as FeedbackPriority }))} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
                          {Object.entries(priorityLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                        </select>
                      </label>
                      <label className="text-sm font-medium text-slate-700">
                        Ответственный
                        <select value={reviewForm.reviewer_id ?? ''} onChange={(e) => setReviewForm((v) => ({ ...v, reviewer_id: e.target.value || null }))} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
                          <option value="">Не назначен</option>
                          {managerUsers.map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}
                        </select>
                      </label>
                    </div>

                    <div className="mt-4 rounded-lg bg-slate-50 p-3">
                      <div className="grid gap-3 sm:grid-cols-2">
                        <label className="text-sm font-medium text-slate-700">
                          Объект
                          <select value={reviewForm.object_type ?? selected.object_type} onChange={(e) => setReviewForm((v) => ({ ...v, object_type: e.target.value as FeedbackObjectType }))} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
                            {Object.entries(objectTypeLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                          </select>
                        </label>
                        <label className="text-sm font-medium text-slate-700">
                          Ссылка / номер / правило
                          <input value={reviewForm.object_ref ?? ''} onChange={(e) => setReviewForm((v) => ({ ...v, object_ref: e.target.value }))} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
                        </label>
                      </div>
                      <label className="mt-3 block text-sm font-medium text-slate-700">
                        Ссылки на доказательства
                        <textarea value={reviewLinksText} onChange={(e) => setReviewLinksText(e.target.value)} rows={3} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
                      </label>
                    </div>

                    <div className="mt-4 grid gap-3 sm:grid-cols-2">
                      <label className="text-sm font-medium text-slate-700">
                        Решение коротко
                        <textarea value={reviewForm.decision_summary ?? ''} onChange={(e) => setReviewForm((v) => ({ ...v, decision_summary: e.target.value }))} rows={4} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
                      </label>
                      <label className="text-sm font-medium text-slate-700">
                        Обоснование
                        <textarea value={reviewForm.decision_reason ?? ''} onChange={(e) => setReviewForm((v) => ({ ...v, decision_reason: e.target.value }))} rows={4} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
                      </label>
                    </div>
                    <div className="mt-3 grid gap-3 sm:grid-cols-2">
                      <label className="text-sm font-medium text-slate-700">
                        Следующее действие
                        <textarea value={reviewForm.next_action ?? ''} onChange={(e) => setReviewForm((v) => ({ ...v, next_action: e.target.value }))} rows={3} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
                      </label>
                      <label className="text-sm font-medium text-slate-700">
                        Релиз / срок
                        <input value={reviewForm.target_release ?? ''} onChange={(e) => setReviewForm((v) => ({ ...v, target_release: e.target.value }))} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
                      </label>
                    </div>
                    <div className="mt-3 flex justify-end">
                      <button type="button" onClick={handleReviewSave} disabled={busy} className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-dark disabled:opacity-50">Сохранить решение</button>
                    </div>
                  </section>
                )}
              </div>

              <aside className="space-y-4">
                <section className="rounded-xl border border-slate-200 p-4">
                  <h3 className="font-medium text-slate-800">События</h3>
                  <div className="mt-3 space-y-3 text-sm">
                    <div>
                      <div className="text-slate-800">Создано</div>
                      <div className="text-xs text-slate-500">{formatDate(selected.created_at)}</div>
                    </div>
                    {selected.reviewed_at && (
                      <div>
                        <div className="text-slate-800">В разборе</div>
                        <div className="text-xs text-slate-500">{formatDate(selected.reviewed_at)}</div>
                      </div>
                    )}
                    {selected.decided_at && (
                      <div>
                        <div className="text-slate-800">Решение</div>
                        <div className="text-xs text-slate-500">{formatDate(selected.decided_at)}</div>
                      </div>
                    )}
                    {selected.closed_at && (
                      <div>
                        <div className="text-slate-800">Закрыто</div>
                        <div className="text-xs text-slate-500">{formatDate(selected.closed_at)}</div>
                      </div>
                    )}
                  </div>
                </section>
                <section className="rounded-xl border border-slate-200 p-4 text-sm">
                  <h3 className="font-medium text-slate-800">Параметры</h3>
                  <div className="mt-3 space-y-2">
                    <div className="flex justify-between gap-3"><span className="text-slate-500">Приоритет</span><span className="text-slate-800">{priorityLabel[selected.priority]}</span></div>
                    <div className="flex justify-between gap-3"><span className="text-slate-500">Ответственный</span><span className="text-right text-slate-800">{selected.reviewer_name ?? '—'}</span></div>
                    <div className="flex justify-between gap-3"><span className="text-slate-500">Обновлено</span><span className="text-right text-slate-800">{formatDate(selected.updated_at)}</span></div>
                  </div>
                </section>
              </aside>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
