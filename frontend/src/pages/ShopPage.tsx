import { useCallback, useEffect, useState } from 'react'
import { api } from '@/api/client'
import type { ShopItem, Purchase } from '@/api/types'
import { useAuth } from '@/contexts/AuthContext'
import { ShopCard } from '@/components/ShopCard'
import toast from 'react-hot-toast'

export function ShopPage() {
  const { user: currentUser } = useAuth()
  const [items, setItems] = useState<ShopItem[]>([])
  const [purchases, setPurchases] = useState<Purchase[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const itemList = await api.get<ShopItem[]>('/api/shop')
      setItems(itemList)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    if (!currentUser) return
    api.get<Purchase[]>(`/api/shop/purchases/${currentUser.id}`).then(setPurchases).catch(() => setPurchases([]))
  }, [currentUser])

  const karmaBalance = currentUser ? Number(currentUser.wallet_karma) : 0

  const now = new Date()
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1).toISOString()
  const purchasedThisMonthByItem: Record<string, number> = {}
  items.forEach((item) => {
    purchasedThisMonthByItem[item.id] = purchases.filter(
      (p) => p.shop_item_id === item.id && p.created_at >= monthStart
    ).length
  })

  const handlePurchase = (item: ShopItem) => {
    if (!currentUser) return
    if (!window.confirm(`Купить "${item.name}" за ${Number(item.cost_q).toFixed(1)} Q кармы?`)) return
    api
      .post<Purchase>('/api/shop/purchase', { shop_item_id: item.id })
      .then((purchase) => {
        if (purchase.status === 'approved') {
          toast.success(`Куплено: ${item.name}! Списано ${Number(item.cost_q).toFixed(1)} кармы.`)
        } else {
          toast.success(`Заявка на «${item.name}» отправлена тимлиду на одобрение.`)
        }
        return api.get<Purchase[]>(`/api/shop/purchases/${currentUser.id}`)
      })
      .then(setPurchases)
      .catch((e) => toast.error(e instanceof Error ? e.message : 'Ошибка покупки'))
  }

  const statusIcon = (status: string) => {
    if (status === 'pending') return '🕐'
    if (status === 'approved') return '✅'
    return '❌'
  }

  const statusLabel = (status: string) => {
    if (status === 'pending') return 'Ожидает согласования'
    if (status === 'approved') return 'Согласовано'
    if (status === 'rejected') return 'Отклонено'
    return status
  }

  if (loading) return <div className="text-slate-500">Загрузка...</div>
  if (error) return <div className="text-red-600">{error}</div>

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-900">Магазин</h1>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        {karmaBalance > 0 ? (
          <p className="text-xl font-semibold text-slate-900">
            Ваш баланс кармы: ⭐ {Number(karmaBalance).toFixed(1)} Q
          </p>
        ) : (
          <p className="text-slate-600">Нет средств для покупок</p>
        )}
      </div>

      <div>
        <h2 className="mb-3 font-medium text-slate-800">Каталог товаров</h2>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((item) => (
            <ShopCard
              key={item.id}
              item={item}
              purchasedThisMonth={purchasedThisMonthByItem[item.id] ?? 0}
              karmaBalance={karmaBalance}
              onPurchase={handlePurchase}
            />
          ))}
        </div>
        {items.length === 0 && <p className="text-slate-500">Нет товаров</p>}
      </div>

      <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
        <h2 className="p-4 border-b border-slate-200 font-medium text-slate-800">Мои покупки</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50">
                <th className="px-4 py-2 text-left font-medium text-slate-700">Дата</th>
                <th className="px-4 py-2 text-left font-medium text-slate-700">Товар</th>
                <th className="px-4 py-2 text-left font-medium text-slate-700">Стоимость</th>
                <th className="px-4 py-2 text-left font-medium text-slate-700">Статус</th>
              </tr>
            </thead>
            <tbody>
              {purchases.map((p) => (
                <tr key={p.id} className="border-b border-slate-100">
                  <td className="px-4 py-2 text-slate-600">
                    {new Date(p.created_at).toLocaleString('ru')}
                  </td>
                  <td className="px-4 py-2">{p.item_name ?? p.shop_item_id}</td>
                  <td className="px-4 py-2">{Number(p.cost_q).toFixed(1)} Q</td>
                  <td className="px-4 py-2">{statusIcon(p.status)} {statusLabel(p.status)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {purchases.length === 0 && <p className="p-4 text-slate-500 text-center">Нет покупок</p>}
      </div>
    </div>
  )
}
