import { useId, useLayoutEffect, useRef, useState } from 'react'
import { preventBackdropDismiss, useProtectedModal } from '@/hooks/useProtectedModal'
import type { CatalogItem } from '@/api/types'
import type { CatalogCategory, Complexity, League } from '@/api/types'

interface CatalogModalProps {
  item: CatalogItem | null
  onClose: () => void
  onSave: (payload: CreateEditPayload) => Promise<void>
  isOpen: boolean
}

export interface CreateEditPayload {
  name: string
  category: CatalogCategory
  complexity: Complexity
  base_cost_q: number
  min_league: League
  sort_order: number
  description: string
}

const CATEGORIES: CatalogCategory[] = ['widget', 'etl', 'api', 'docs', 'proactive']
const COMPLEXITIES: Complexity[] = ['S', 'M', 'L', 'XL']
const LEAGUES: League[] = ['C', 'B', 'A']

export function CatalogModal({ item, onClose, onSave, isOpen }: CatalogModalProps) {
  const [name, setName] = useState('')
  const [category, setCategory] = useState<CatalogCategory>('widget')
  const [complexity, setComplexity] = useState<Complexity>('S')
  const [base_cost_q, setBaseCostQ] = useState<string>('1')
  const [min_league, setMinLeague] = useState<League>('C')
  const [sortOrder, setSortOrder] = useState('100')
  const [description, setDescription] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const pending = useRef(false)
  const session = useRef(0)
  const id = useId()
  const panelRef = useProtectedModal<HTMLDivElement>(isOpen)

  useLayoutEffect(() => {
    session.current += 1
    pending.current = false
    setBusy(false)
    setError(null)
    if (item) {
      setName(item.name)
      setCategory(item.category)
      setComplexity(item.complexity)
      setBaseCostQ(String(item.base_cost_q))
      setMinLeague(item.min_league)
      setSortOrder(String(item.sort_order ?? 100))
      setDescription(item.description ?? '')
    } else {
      setName('')
      setCategory('widget')
      setComplexity('S')
      setBaseCostQ('1')
      setMinLeague('C')
      setSortOrder('100')
      setDescription('')
    }
    return () => { session.current += 1 }
  }, [item, isOpen])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (pending.current) return
    const cost = Number(base_cost_q)
    const order = Number(sortOrder)
    if (!name.trim()) {
      setError('Название обязательно')
      document.getElementById(`${id}-name`)?.focus()
      return
    }
    if (!Number.isFinite(cost) || cost <= 0 || !sortOrder.trim() || !Number.isInteger(order) || order < 0) {
      setError('Стоимость должна быть больше 0, порядок — целым числом не меньше 0')
      return
    }
    const revision = session.current
    pending.current = true
    setBusy(true)
    setError(null)
    try {
      await onSave({
      name: name.trim(),
      category,
      complexity,
      base_cost_q: cost,
      min_league,
      sort_order: order,
      description: description.trim() || '',
      })
      if (session.current === revision) onClose()
    } catch (err) {
      if (session.current === revision) setError(err instanceof Error ? err.message : 'Ошибка сохранения')
    } finally {
      if (session.current === revision) {
        pending.current = false
        setBusy(false)
      }
    }
  }

  if (!isOpen) return null

  return (
    <div
      className="protected-modal-overlay fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      role="dialog"
      aria-modal="true"
      aria-labelledby={`${id}-title`}
      onPointerDown={preventBackdropDismiss}
    >
      <div
        ref={panelRef}
        tabIndex={-1}
        className="protected-modal-panel w-full max-w-md rounded-lg bg-white p-4 shadow-xl sm:p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id={`${id}-title`} className="shrink-0 text-lg font-semibold text-slate-900">
          {item ? 'Редактировать операцию' : 'Добавить операцию'}
        </h2>
        <form onSubmit={handleSubmit} aria-busy={busy} className="mt-4 flex min-h-0 flex-1 flex-col">
          <div className="min-h-0 overflow-y-auto overscroll-contain">
          <fieldset disabled={busy} className="min-w-0 space-y-3">
          <div>
            <label htmlFor={`${id}-name`} className="block text-sm font-medium text-slate-700">Название *</label>
            <input
              id={`${id}-name`}
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              required
            />
          </div>
          <div>
            <label htmlFor={`${id}-category`} className="block text-sm font-medium text-slate-700">Категория</label>
            <select
              id={`${id}-category`}
              value={category}
              onChange={(e) => setCategory(e.target.value as CatalogCategory)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            >
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor={`${id}-complexity`} className="block text-sm font-medium text-slate-700">Сложность</label>
            <select
              id={`${id}-complexity`}
              value={complexity}
              onChange={(e) => setComplexity(e.target.value as Complexity)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            >
              {COMPLEXITIES.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor={`${id}-cost`} className="block text-sm font-medium text-slate-700">Стоимость (Q) *</label>
            <input
              id={`${id}-cost`}
              type="number"
              step="0.1"
              min="0.1"
              value={base_cost_q}
              onChange={(e) => setBaseCostQ(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              required
            />
          </div>
          <div>
            <label htmlFor={`${id}-league`} className="block text-sm font-medium text-slate-700">Мин. лига</label>
            <select
              id={`${id}-league`}
              value={min_league}
              onChange={(e) => setMinLeague(e.target.value as League)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            >
              {LEAGUES.map((l) => (
                <option key={l} value={l}>{l}</option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor={`${id}-order`} className="block text-sm font-medium text-slate-700">Порядковый номер</label>
            <input
              id={`${id}-order`}
              type="number"
              min="0"
              step="1"
              value={sortOrder}
              onChange={(e) => setSortOrder(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              required
            />
          </div>
          <div>
            <label htmlFor={`${id}-description`} className="block text-sm font-medium text-slate-700">Описание</label>
            <textarea
              id={`${id}-description`}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
          </fieldset>
          </div>
          {error && <p role="alert" className="max-h-24 shrink-0 overflow-y-auto break-words pt-2 text-sm text-red-600">{error}</p>}
          <div className="flex shrink-0 justify-end gap-2 pt-3">
            <button
              type="button"
              disabled={busy}
              onClick={onClose}
              className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              Отмена
            </button>
            <button
              type="submit"
              disabled={busy}
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
            >
              {busy ? 'Сохранение...' : 'Сохранить'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
