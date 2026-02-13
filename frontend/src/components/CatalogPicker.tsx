import type { CatalogItem } from '@/api/types'
import { QBadge } from './QBadge'
import { LeagueBadge } from './LeagueBadge'
import { cn } from '@/lib/utils'

const categoryLabels: Record<string, string> = {
  widget: 'Виджеты',
  etl: 'ETL',
  api: 'API',
  docs: 'Документация',
}

const complexityStyles: Record<string, string> = {
  S: 'bg-slate-100 text-slate-700',
  M: 'bg-blue-100 text-blue-800',
  L: 'bg-orange-100 text-orange-800',
  XL: 'bg-red-100 text-red-800',
}

interface CatalogPickerProps {
  catalog: CatalogItem[]
  onAdd: (item: CatalogItem) => void
  className?: string
}

export function CatalogPicker({ catalog, onAdd, className }: CatalogPickerProps) {
  const byCategory = catalog.reduce<Record<string, CatalogItem[]>>((acc, item) => {
    const cat = item.category
    if (!acc[cat]) acc[cat] = []
    acc[cat].push(item)
    return acc
  }, {})
  const order = ['widget', 'etl', 'api', 'docs']

  return (
    <div className={cn('space-y-4', className)}>
      <h2 className="font-medium text-slate-800">Каталог операций</h2>
      {order.map(
        (cat) =>
          byCategory[cat]?.length > 0 && (
            <div key={cat}>
              <h3 className="mb-2 text-sm font-medium text-slate-600">
                {categoryLabels[cat] ?? cat}
              </h3>
              <ul className="space-y-1">
                {byCategory[cat].map((item) => (
                  <li
                    key={item.id}
                    className="flex items-center justify-between gap-2 rounded-lg border border-slate-100 bg-white p-2"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-slate-900">
                        {item.name}
                      </p>
                      <div className="mt-1 flex flex-wrap gap-1">
                        <span
                          className={cn(
                            'rounded px-1.5 py-0.5 text-xs',
                            complexityStyles[item.complexity] ?? 'bg-slate-100'
                          )}
                        >
                          {item.complexity}
                        </span>
                        <QBadge q={item.base_cost_q} />
                        <LeagueBadge league={item.min_league} />
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => onAdd(item)}
                      className="shrink-0 rounded border border-slate-300 bg-white px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50"
                    >
                      + Добавить
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )
      )}
    </div>
  )
}
