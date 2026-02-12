import { useEffect, useState } from 'react'
import { api } from '@/api/client'
import type { CatalogItem, CalculatorResponse } from '@/api/types'

export function CalculatorPage() {
  const [catalog, setCatalog] = useState<CatalogItem[]>([])
  const [selected, setSelected] = useState<Record<string, number>>({})
  const [result, setResult] = useState<CalculatorResponse | null>(null)
  const [complexityMult, setComplexityMult] = useState(1)
  const [urgencyMult, setUrgencyMult] = useState(1)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get<CatalogItem[]>('/api/catalog').then(setCatalog).finally(() => setLoading(false))
  }, [])

  const toggle = (id: string, qty: number) => {
    setSelected((prev) => {
      const next = { ...prev }
      if (qty <= 0) delete next[id]
      else next[id] = qty
      return next
    })
    setResult(null)
  }

  /** Формат Q: целое без десятичных, иначе один знак после запятой */
  const formatQ = (n: number) =>
    Number.isInteger(n) ? String(n) : Number(n).toFixed(1)

  const handleEstimate = async () => {
    const items = Object.entries(selected)
      .filter(([, q]) => q > 0)
      .map(([catalog_id, quantity]) => ({ catalog_id, quantity }))
    if (items.length === 0) return
    const res = await api.post<CalculatorResponse>('/api/calculator/estimate', {
      items,
      complexity_multiplier: complexityMult,
      urgency_multiplier: urgencyMult,
    })
    setResult(res)
  }

  if (loading) return <div className="text-slate-500">Загрузка каталога...</div>

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold text-slate-900">Калькулятор оценки</h1>
      <div className="grid gap-6 lg:grid-cols-2">
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <h2 className="font-medium text-slate-800">Позиции каталога</h2>
          <p className="mt-1 text-sm text-slate-500">
            Выберите операции и количество. Затем нажмите «Рассчитать».
          </p>
          <div className="mt-4 space-y-2 max-h-96 overflow-y-auto">
            {catalog.map((item) => (
              <div
                key={item.id}
                className="flex items-center justify-between rounded-lg border border-slate-100 p-2"
              >
                <span className="text-sm">{item.name}</span>
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    min={0}
                    value={selected[item.id] ?? 0}
                    onChange={(e) => toggle(item.id, e.target.valueAsNumber || 0)}
                    className="w-14 rounded border border-slate-300 px-2 py-1 text-sm"
                  />
                  <span className="text-xs text-slate-400">{formatQ(Number(item.base_cost_q))} Q</span>
                </div>
              </div>
            ))}
          </div>
          <div className="mt-4 flex gap-4">
            <label className="flex items-center gap-2 text-sm">
              Коэф. сложности:
              <input
                type="number"
                min={0.5}
                max={3}
                step={0.5}
                value={complexityMult}
                onChange={(e) => setComplexityMult(Number(e.target.value))}
                className="w-20 rounded border border-slate-300 px-2 py-1"
              />
            </label>
            <label className="flex items-center gap-2 text-sm">
              Срочность:
              <input
                type="number"
                min={1}
                max={2}
                step={0.5}
                value={urgencyMult}
                onChange={(e) => setUrgencyMult(Number(e.target.value))}
                className="w-20 rounded border border-slate-300 px-2 py-1"
              />
            </label>
          </div>
          <button
            type="button"
            onClick={handleEstimate}
            className="mt-4 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
          >
            Рассчитать
          </button>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <h2 className="font-medium text-slate-800">Результат</h2>
          {result ? (
            <div className="mt-4">
              <p className="text-2xl font-semibold text-slate-900">
                Итого: {formatQ(Number(result.total_q))} Q
              </p>
              <p className="text-sm text-slate-500">Минимальная лига: {result.min_league}</p>
              <ul className="mt-4 space-y-1 text-sm">
                {result.breakdown.map((b) => (
                  <li key={b.catalog_id}>
                    {b.name} × {b.quantity} = {formatQ(Number(b.subtotal_q))} Q
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="mt-4 text-slate-500">Выберите позиции и нажмите «Рассчитать».</p>
          )}
        </div>
      </div>
    </div>
  )
}
