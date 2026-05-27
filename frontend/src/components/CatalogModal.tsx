import { useEffect, useState } from 'react'
import type { CatalogItem } from '@/api/types'
import type { CatalogCategory, Complexity, League } from '@/api/types'

interface CatalogModalProps {
  item: CatalogItem | null
  onClose: () => void
  onSave: (payload: CreateEditPayload) => void
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

  useEffect(() => {
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
  }, [item, isOpen])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const cost = parseFloat(base_cost_q)
    const order = Number.parseInt(sortOrder, 10)
    if (!name.trim()) return
    if (Number.isNaN(cost) || cost <= 0) return
    if (Number.isNaN(order) || order < 0) return
    onSave({
      name: name.trim(),
      category,
      complexity,
      base_cost_q: cost,
      min_league,
      sort_order: order,
      description: description.trim() || '',
    })
    onClose()
  }

  if (!isOpen) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      role="dialog"
      aria-modal="true"
      onKeyDown={(e) => e.key === 'Escape' && onClose()}
    >
      <div
        className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-semibold text-slate-900">
          {item ? 'Редактировать операцию' : 'Добавить операцию'}
        </h2>
        <form onSubmit={handleSubmit} className="mt-4 space-y-3">
          <div>
            <label className="block text-sm font-medium text-slate-700">Название *</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700">Категория</label>
            <select
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
            <label className="block text-sm font-medium text-slate-700">Сложность</label>
            <select
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
            <label className="block text-sm font-medium text-slate-700">Стоимость (Q) *</label>
            <input
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
            <label className="block text-sm font-medium text-slate-700">Мин. лига</label>
            <select
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
            <label className="block text-sm font-medium text-slate-700">Порядковый номер</label>
            <input
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
            <label className="block text-sm font-medium text-slate-700">Описание</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              Отмена
            </button>
            <button
              type="submit"
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
            >
              Сохранить
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
