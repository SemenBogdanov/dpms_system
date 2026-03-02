import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { api } from '@/api/client'
import type { CatalogItem, User, EstimateResponse } from '@/api/types'
import type { CartRow } from '@/components/EstimateCart'
import { CatalogPicker } from '@/components/CatalogPicker'
import { EstimateCart } from '@/components/EstimateCart'
import { TagInput } from '@/components/TagInput'

export function CalculatorPage() {
  const navigate = useNavigate()
  const [catalog, setCatalog] = useState<CatalogItem[]>([])
  const [teamleads, setTeamleads] = useState<User[]>([])
  const [cart, setCart] = useState<CartRow[]>([])
  const [estimateResult, setEstimateResult] = useState<EstimateResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [createModalOpen, setCreateModalOpen] = useState(false)
  const [createTitle, setCreateTitle] = useState('')
  const [createDescription, setCreateDescription] = useState('')
  const [createPriority, setCreatePriority] = useState('medium')
  const [createTags, setCreateTags] = useState<string[]>([])
  const [createEstimatorId, setCreateEstimatorId] = useState('')
  const [dueDate, setDueDate] = useState('')
  const [creating, setCreating] = useState(false)
  const [categoryTab, setCategoryTab] = useState<'all' | 'widget' | 'etl' | 'api' | 'docs' | 'proactive'>('all')

  useEffect(() => {
    api.get<CatalogItem[]>('/api/catalog').then(setCatalog).catch(() => setCatalog([]))
    api.get<User[]>('/api/users?role=teamlead').then(setTeamleads).catch(() => setTeamleads([]))
  }, [])

  useEffect(() => {
    if (teamleads.length > 0 && !createEstimatorId) setCreateEstimatorId(teamleads[0].id)
  }, [teamleads, createEstimatorId])

  const addToCart = (item: CatalogItem) => {
    setCart((prev) => {
      const i = prev.findIndex((r) => r.catalog.id === item.id)
      if (i >= 0) {
        const next = [...prev]
        next[i] = { ...next[i], quantity: Math.min(50, next[i].quantity + 1) }
        return next
      }
      return [...prev, { catalog: item, quantity: 1 }]
    })
    setEstimateResult(null)
    toast.success(`✅ ${item.name} добавлен — ${Number(item.base_cost_q).toFixed(1)} Q`, { duration: 2000 })
  }

  const setQuantity = (catalogId: string, quantity: number) => {
    setCart((prev) =>
      prev.map((r) =>
        r.catalog.id === catalogId ? { ...r, quantity } : r
      )
    )
    setEstimateResult(null)
  }

  const removeFromCart = (catalogId: string) => {
    setCart((prev) => prev.filter((r) => r.catalog.id !== catalogId))
    setEstimateResult(null)
  }

  const handleCalculate = async () => {
    if (cart.length === 0) return
    setLoading(true)
    try {
      const res = await api.post<EstimateResponse>('/api/calculator/estimate', {
        items: cart.map((r) => ({ catalog_id: r.catalog.id, quantity: r.quantity })),
      })
      setEstimateResult(res)
      toast.success('Расчёт выполнен')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка расчёта')
    } finally {
      setLoading(false)
    }
  }

  const openCreateModal = () => {
    setCreateTitle('')
    setCreateDescription('')
    setCreatePriority('medium')
    setCreateTags([])
    setCreateEstimatorId(teamleads[0]?.id ?? '')
    setDueDate('')
    setCreateModalOpen(true)
  }

  const handleCreateTask = async () => {
    if (!createTitle.trim() || createTitle.length < 5) {
      toast.error('Название задачи не менее 5 символов')
      return
    }
    if (cart.length === 0) return
    const hasProactive = cart.some((r) => r.catalog.category === 'proactive')
    const priorityToSend = hasProactive && (createPriority === 'critical' || createPriority === 'high') ? 'medium' : createPriority
    setCreating(true)
    try {
      const task = await api.post<{ id: string; title: string; estimated_q: number }>(
        '/api/calculator/create-task',
        {
          title: createTitle.trim(),
          description: createDescription.trim(),
          priority: priorityToSend,
          estimator_id: createEstimatorId,
          items: cart.map((r) => ({ catalog_id: r.catalog.id, quantity: r.quantity })),
          tags: createTags,
          due_date: dueDate ? new Date(dueDate).toISOString() : undefined,
        }
      )
      toast.success(`Задача создана, ${task.estimated_q} Q, в очереди`)
      setCreateModalOpen(false)
      navigate('/queue')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка создания задачи')
    } finally {
      setCreating(false)
    }
  }

  const filteredCatalog =
    categoryTab === 'all'
      ? catalog
      : catalog.filter((item) => item.category === categoryTab)

  const tabs: Array<{ key: typeof categoryTab; label: string }> = [
    { key: 'all', label: 'Все' },
    { key: 'widget', label: 'Виджеты' },
    { key: 'etl', label: 'ETL' },
    { key: 'api', label: 'API' },
    { key: 'docs', label: 'Документация' },
    { key: 'proactive', label: 'Проактивные' },
  ]

  const handleDownloadCalculation = () => {
    const sumRaw = cart.reduce((s, r) => s + r.catalog.base_cost_q * r.quantity, 0)
    const totalQ = Math.round(sumRaw * 10) / 10
    const header = 'Операция,Категория,Сложность,Стоимость (Q),Количество,Итого (Q)\n'
    const body = cart
      .map((r) =>
        [
          `"${r.catalog.name.replace(/"/g, '""')}"`,
          r.catalog.category,
          r.catalog.complexity,
          Number(r.catalog.base_cost_q).toFixed(1),
          r.quantity,
          Number(r.catalog.base_cost_q * r.quantity).toFixed(1),
        ].join(',')
      )
      .join('\n')
    const footer = `---\nИТОГО,,,,,${Number(totalQ).toFixed(1)}\n`
    const blob = new Blob(['\ufeff' + header + body + '\n' + footer], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'dpms-estimate.csv'
    a.click()
    URL.revokeObjectURL(url)
  }

  const priorityHint: Record<string, string> = {
    critical: 'Блокирует совещание/релиз в ближайшие 24ч',
    high: 'Нужно на этой неделе, есть внешний заказчик',
    medium: 'Плановая задача текущего месяца',
    low: 'Техдолг, исследования, можно отложить',
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold text-slate-900">Калькулятор задач</h1>
      <div className="flex flex-col gap-6 md:flex-row">
        <div className="w-full md:w-[620px] md:flex-shrink-0 overflow-y-auto max-h-[60vh] md:max-h-[calc(100vh-180px)] rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="mb-3 flex flex-wrap gap-1 border-b border-slate-200 pb-2">
            {tabs.map(({ key, label }) => (
              <button
                key={key}
                type="button"
                onClick={() => setCategoryTab(key)}
                className={`rounded-md px-3 py-1.5 text-sm font-medium ${
                  categoryTab === key
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          <CatalogPicker catalog={filteredCatalog} onAdd={addToCart} />
        </div>
        <div className="w-full md:flex-1 md:sticky md:top-4 md:self-start md:max-h-[calc(100vh-180px)] overflow-y-auto rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <EstimateCart
            rows={cart}
            onQuantity={setQuantity}
            onRemove={removeFromCart}
            onCalculate={handleCalculate}
            onCreateTask={openCreateModal}
            onDownloadCalculation={handleDownloadCalculation}
            calculated={!!estimateResult}
            loading={loading}
          />
        </div>
      </div>

      {createModalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          role="dialog"
          aria-modal="true"
          onKeyDown={(e) => e.key === 'Escape' && setCreateModalOpen(false)}
        >
          <div
            className="w-full max-w-md rounded-xl bg-white p-6 shadow-lg"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-semibold text-slate-900">
              Создать задачу и отправить в очередь
            </h3>
            <div className="mt-4 space-y-3">
              <label className="block text-sm font-medium text-slate-700">
                Название задачи *
              </label>
              <input
                type="text"
                value={createTitle}
                onChange={(e) => setCreateTitle(e.target.value)}
                placeholder="Не менее 5 символов"
                className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
                minLength={5}
                maxLength={500}
              />
              <label className="block text-sm font-medium text-slate-700">
                Описание
              </label>
              <textarea
                value={createDescription}
                onChange={(e) => setCreateDescription(e.target.value)}
                rows={3}
                className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
              />
              <label className="block text-sm font-medium text-slate-700">
                Приоритет
              </label>
              {(() => {
                const hasProactive = cart.some((r) => r.catalog.category === 'proactive')
                const effectivePriority = hasProactive && (createPriority === 'critical' || createPriority === 'high') ? 'medium' : createPriority
                const priorityOptions = hasProactive
                  ? [
                      { value: 'medium', label: '🟡 Средний' },
                      { value: 'low', label: '🟢 Низкий' },
                    ]
                  : [
                      { value: 'critical', label: '🔴 Критический' },
                      { value: 'high', label: '🟠 Высокий' },
                      { value: 'medium', label: '🟡 Средний' },
                      { value: 'low', label: '🟢 Низкий' },
                    ]
                return (
                  <>
                    <select
                      value={effectivePriority}
                      onChange={(e) => setCreatePriority(e.target.value)}
                      className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
                    >
                      {priorityOptions.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                    {hasProactive && (
                      <p className="mt-1 text-xs text-slate-500">
                        Проактивные задачи: максимальный приоритет — средний.
                      </p>
                    )}
                    {!hasProactive && (
                      <p className="mt-1 text-xs text-slate-400">
                        {priorityHint[createPriority] ?? ''}
                      </p>
                    )}
                  </>
                )
              })()}
              <div>
                <label className="block text-sm font-medium text-slate-700">
                  Крайний срок <span className="text-slate-400">(необязательно)</span>
                </label>
                <input
                  type="datetime-local"
                  value={dueDate}
                  onChange={(e) => setDueDate(e.target.value)}
                  className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                />
              </div>
              <label className="block text-sm font-medium text-slate-700">
                Теги
              </label>
              <TagInput tags={createTags} onChange={setCreateTags} className="mt-1" />
              <label className="block text-sm font-medium text-slate-700">
                Оценщик (тимлид)
              </label>
              <select
                value={createEstimatorId}
                onChange={(e) => setCreateEstimatorId(e.target.value)}
                className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
              >
                {teamleads.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.full_name}
                  </option>
                ))}
              </select>
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setCreateModalOpen(false)}
                className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Отмена
              </button>
              <button
                type="button"
                onClick={handleCreateTask}
                disabled={creating || createTitle.trim().length < 5}
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
              >
                {creating ? '...' : 'Создать и отправить в очередь'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
