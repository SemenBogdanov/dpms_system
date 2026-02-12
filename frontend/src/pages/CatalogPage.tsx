import { useEffect, useState } from 'react'
import { api } from '@/api/client'
import type { CatalogItem } from '@/api/types'
import { QBadge } from '@/components/QBadge'

export function CatalogPage() {
  const [items, setItems] = useState<CatalogItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.get<CatalogItem[]>('/api/catalog')
      .then(setItems)
      .catch((e) => setError(e instanceof Error ? e.message : 'Ошибка'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="text-slate-500">Загрузка...</div>
  if (error) return <div className="text-red-600">{error}</div>

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold text-slate-900">Справочник операций</h1>
      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <table className="min-w-full divide-y divide-slate-200">
          <thead className="bg-slate-50">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-600">Категория</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-600">Название</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-600">Сложность</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-600">Базовая стоимость</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-600">Мин. лига</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200">
            {items.map((item) => (
              <tr key={item.id} className="bg-white">
                <td className="px-4 py-3 text-sm text-slate-600">{item.category}</td>
                <td className="px-4 py-3 text-sm text-slate-900">{item.name}</td>
                <td className="px-4 py-3 text-sm">{item.complexity}</td>
                <td className="px-4 py-3">
                  <QBadge q={item.base_cost_q} />
                </td>
                <td className="px-4 py-3 text-sm">{item.min_league}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
