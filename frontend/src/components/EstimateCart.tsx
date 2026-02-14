import type { CatalogItem } from '@/api/types'
// import { QBadge } from './QBadge'
import { LeagueBadge } from './LeagueBadge'
import { cn } from '@/lib/utils'

export interface CartRow {
  catalog: CatalogItem
  quantity: number
}

const complexityOptions = [
  { value: 1, label: 'Стандартная (×1.0)' },
  { value: 1.5, label: 'Повышенная (×1.5)' },
  { value: 2, label: 'Высокая (×2.0)' },
]
const urgencyOptions = [
  { value: 1, label: 'Обычная (×1.0)' },
  { value: 1.5, label: 'Срочная (×1.5)' },
]

interface EstimateCartProps {
  rows: CartRow[]
  complexityMult: number
  urgencyMult: number
  onQuantity: (catalogId: string, quantity: number) => void
  onRemove: (catalogId: string) => void
  onComplexity: (v: number) => void
  onUrgency: (v: number) => void
  onCalculate: () => void
  onCreateTask: () => void
  calculated: boolean
  loading?: boolean
  className?: string
}

function formatQ(n: number) {
  return Number.isInteger(n) ? String(n) : Number(n).toFixed(1)
}

export function EstimateCart({
  rows,
  complexityMult,
  urgencyMult,
  onQuantity,
  onRemove,
  onComplexity,
  onUrgency,
  onCalculate,
  onCreateTask,
  calculated,
  loading,
  className,
}: EstimateCartProps) {
  const sumRaw = rows.reduce((s, r) => s + r.catalog.base_cost_q * r.quantity, 0)
  const totalQ = Math.round(sumRaw * complexityMult * urgencyMult * 10) / 10
  const maxLeague = rows.length
    ? rows.reduce((max, r) => {
        const order = { C: 0, B: 1, A: 2 }
        return order[r.catalog.min_league] > order[max as keyof typeof order]
          ? r.catalog.min_league
          : max
      }, rows[0].catalog.min_league)
    : 'C'
  const isEmpty = rows.length === 0

  return (
    <div className={cn('flex flex-col', className)}>
      <h2 className="font-medium text-slate-800">Корзина</h2>
      {isEmpty ? (
        <p className="mt-2 text-sm text-slate-500">Добавьте операции из каталога слева.</p>
      ) : (
        <>
          <div className="mt-2 max-h-64 overflow-y-auto rounded border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50">
                <tr>
                  <th className="px-2 py-1.5 text-left font-medium text-slate-600">
                    Название
                  </th>
                  <th className="px-2 py-1.5 text-right font-medium text-slate-600">Q</th>
                  <th className="w-16 px-2 py-1.5 text-center font-medium text-slate-600">Кол.</th>
                  <th className="px-2 py-1.5 text-right font-medium text-slate-600">Подитог</th>
                  <th className="w-8" />
                </tr>
              </thead>
              <tbody>
                {rows.map(({ catalog, quantity }) => (
                  <tr key={catalog.id} className="border-t border-slate-100">
                    <td className="px-2 py-1.5 truncate">{catalog.name}</td>
                    <td className="px-2 py-1.5 text-right">
                      {formatQ(catalog.base_cost_q)}
                    </td>
                    <td className="px-2 py-1.5 text-center">
                      <input
                        type="number"
                        min={1}
                        max={50}
                        value={quantity}
                        onChange={(e) =>
                          onQuantity(catalog.id, Math.min(50, Math.max(1, e.target.valueAsNumber || 1)))
                        }
                        className="w-12 rounded border border-slate-300 px-1 py-0.5 text-center text-sm"
                      />
                    </td>
                    <td className="px-2 py-1.5 text-right">
                      {formatQ(catalog.base_cost_q * quantity)}
                    </td>
                    <td className="px-2 py-1.5">
                      <button
                        type="button"
                        onClick={() => onRemove(catalog.id)}
                        className="text-slate-400 hover:text-red-600"
                        aria-label="Удалить"
                      >
                        ✕
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-4 space-y-2">
            <label className="block text-sm font-medium text-slate-700">
              Сложность
            </label>
            <select
              value={complexityMult}
              onChange={(e) => onComplexity(Number(e.target.value))}
              className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
            >
              {complexityOptions.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            <label className="block text-sm font-medium text-slate-700">
              Срочность
            </label>
            <select
              value={urgencyMult}
              onChange={(e) => onUrgency(Number(e.target.value))}
              className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
            >
              {urgencyOptions.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
          <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-3">
            <p className="text-sm text-slate-600">
              Сумма без множителей: {formatQ(sumRaw)} Q
            </p>
            <p className="text-sm text-slate-600">
              Множители: ×{complexityMult} × ×{urgencyMult}
            </p>
            <p className="mt-2 text-xl font-semibold text-slate-900">
              Итого: {formatQ(totalQ)} Q
            </p>
            <div className="mt-1">
              <LeagueBadge league={maxLeague} />
            </div>
          </div>
          <div className="mt-4 flex gap-2">
            <button
              type="button"
              onClick={onCalculate}
              disabled={isEmpty || loading}
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
            >
              {loading ? '...' : 'Рассчитать'}
            </button>
            <button
              type="button"
              onClick={onCreateTask}
              disabled={!calculated || isEmpty}
              className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              Создать задачу
            </button>
          </div>
        </>
      )}
    </div>
  )
}
