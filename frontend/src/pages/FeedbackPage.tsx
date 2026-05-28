import { useCallback, useEffect, useMemo, useState } from 'react'
import { MessageSquare, Plus, X } from 'lucide-react'
import { api } from '@/api/client'
import type {
  FeedbackCategory,
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
  accepted: 'Принято',
  rejected: 'Отклонено',
  done: 'Закрыто',
}

const priorityLabel: Record<FeedbackPriority, string> = {
  low: 'Низкий',
  medium: 'Средний',
  high: 'Высокий',
}

const EMPTY_FORM: FeedbackRequestCreate = {
  category: 'improvement',
  priority: 'medium',
  title: '',
  description: '',
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
  if (status === 'in_review') return 'bg-amber-50 text-amber-700 ring-amber-100'
  if (status === 'accepted') return 'bg-emerald-50 text-emerald-700 ring-emerald-100'
  if (status === 'rejected') return 'bg-red-50 text-red-700 ring-red-100'
  return 'bg-slate-100 text-slate-700 ring-slate-200'
}

function priorityClass(priority: FeedbackPriority): string {
  if (priority === 'high') return 'bg-red-50 text-red-700'
  if (priority === 'medium') return 'bg-slate-100 text-slate-700'
  return 'bg-slate-50 text-slate-500'
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
  const [selected, setSelected] = useState<FeedbackRequest | null>(null)
  const [reviewForm, setReviewForm] = useState<FeedbackRequestUpdate>({})
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
      { total: 0, new: 0, in_review: 0, accepted: 0, rejected: 0, done: 0 } as Record<FeedbackStatus | 'total', number>
    )
  }, [items])

  const openDetails = (item: FeedbackRequest) => {
    setSelected(item)
    setReviewForm({
      status: item.status,
      priority: item.priority,
      reviewer_id: item.reviewer_id,
      resolution: item.resolution ?? '',
    })
  }

  const handleCreate = async () => {
    setBusy(true)
    try {
      const created = await api.post<FeedbackRequest>('/api/feedback', form)
      toast.success('Обращение создано')
      setCreateOpen(false)
      setForm(EMPTY_FORM)
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
      }
      const updated = await api.patch<FeedbackRequest>(`/api/feedback/${selected.id}`, payload)
      toast.success('Решение сохранено')
      setSelected(updated)
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
          <p className="mt-1 text-sm text-slate-500">Запросы на изменения, несогласия, ошибки и процессные вопросы.</p>
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

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {(['new', 'in_review', 'accepted', 'rejected', 'done'] as FeedbackStatus[]).map((status) => (
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
              {Object.entries(statusLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
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
                  <th className="px-4 py-3">Статус</th>
                  <th className="px-4 py-3">Обращение</th>
                  <th className="px-4 py-3">Автор</th>
                  <th className="px-4 py-3">Ответственный</th>
                  <th className="px-4 py-3">Дата</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                    <td className="px-4 py-3 align-top">
                      <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ring-1 ${statusClass(item.status)}`}>
                        {statusLabel[item.status]}
                      </span>
                    </td>
                    <td className="px-4 py-3 align-top">
                      <button type="button" onClick={() => openDetails(item)} className="text-left">
                        <div className="font-medium text-slate-900 hover:text-primary">{item.title}</div>
                        <div className="mt-1 flex flex-wrap gap-2 text-xs">
                          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-600">{categoryLabel[item.category]}</span>
                          <span className={`rounded-full px-2 py-0.5 ${priorityClass(item.priority)}`}>{priorityLabel[item.priority]}</span>
                        </div>
                      </button>
                    </td>
                    <td className="px-4 py-3 align-top text-slate-600">{item.author_name}</td>
                    <td className="px-4 py-3 align-top text-slate-600">{item.reviewer_name ?? '—'}</td>
                    <td className="px-4 py-3 align-top text-slate-500">{formatDate(item.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {createOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
          <div className="w-full max-w-2xl rounded-xl bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-slate-100 p-4">
              <h2 className="font-semibold text-slate-900">Новое обращение</h2>
              <button type="button" onClick={() => setCreateOpen(false)} className="rounded-lg p-1 text-slate-400 hover:bg-slate-100">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="space-y-4 p-4">
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
                <textarea value={form.description} onChange={(e) => setForm((v) => ({ ...v, description: e.target.value }))} rows={6} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
              </label>
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
          <div className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-xl bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-slate-100 p-4">
              <div>
                <h2 className="font-semibold text-slate-900">{selected.title}</h2>
                <p className="mt-1 text-sm text-slate-500">{categoryLabel[selected.category]} · {selected.author_name}</p>
              </div>
              <button type="button" onClick={() => setSelected(null)} className="rounded-lg p-1 text-slate-400 hover:bg-slate-100">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="space-y-5 p-4">
              <div className="flex flex-wrap gap-2 text-xs">
                <span className={`rounded-full px-2.5 py-1 font-medium ring-1 ${statusClass(selected.status)}`}>{statusLabel[selected.status]}</span>
                <span className={`rounded-full px-2.5 py-1 ${priorityClass(selected.priority)}`}>{priorityLabel[selected.priority]}</span>
                <span className="rounded-full bg-slate-100 px-2.5 py-1 text-slate-600">Создано: {formatDate(selected.created_at)}</span>
              </div>
              <section>
                <h3 className="text-sm font-medium text-slate-700">Описание</h3>
                <p className="mt-2 whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-sm leading-6 text-slate-700">{selected.description}</p>
              </section>
              <section>
                <h3 className="text-sm font-medium text-slate-700">Решение</h3>
                <p className="mt-2 whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-sm leading-6 text-slate-700">{selected.resolution || 'Решение пока не зафиксировано.'}</p>
              </section>
              {isManager && (
                <section className="rounded-xl border border-slate-200 p-4">
                  <h3 className="font-medium text-slate-800">Рассмотрение</h3>
                  <div className="mt-3 grid gap-3 sm:grid-cols-3">
                    <label className="text-sm font-medium text-slate-700">
                      Статус
                      <select value={reviewForm.status ?? selected.status} onChange={(e) => setReviewForm((v) => ({ ...v, status: e.target.value as FeedbackStatus }))} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
                        {Object.entries(statusLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
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
                  <label className="mt-3 block text-sm font-medium text-slate-700">
                    Решение / ответ
                    <textarea value={reviewForm.resolution ?? ''} onChange={(e) => setReviewForm((v) => ({ ...v, resolution: e.target.value }))} rows={5} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
                  </label>
                  <div className="mt-3 flex justify-end">
                    <button type="button" onClick={handleReviewSave} disabled={busy} className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-dark disabled:opacity-50">Сохранить решение</button>
                  </div>
                </section>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
