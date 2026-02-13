import { useCallback, useEffect, useState } from 'react'
import { api } from '@/api/client'
import type { User, ShopItem, Purchase } from '@/api/types'
import { ShopCard } from '@/components/ShopCard'
import toast from 'react-hot-toast'

const FALLBACK_USER_ID = ''

export function ShopPage() {
  const [users, setUsers] = useState<User[]>([])
  const [currentUserId, setCurrentUserId] = useState(FALLBACK_USER_ID)
  const [items, setItems] = useState<ShopItem[]>([])
  const [purchases, setPurchases] = useState<Purchase[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [userList, itemList] = await Promise.all([
        api.get<User[]>('/api/users'),
        api.get<ShopItem[]>('/api/shop'),
      ])
      setUsers(userList)
      if (userList.length && !currentUserId) setCurrentUserId(userList[0].id)
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
    if (!currentUserId) return
    api.get<Purchase[]>(`/api/shop/purchases/${currentUserId}`).then(setPurchases).catch(() => setPurchases([]))
  }, [currentUserId])

  const currentUser = users.find((u) => u.id === currentUserId)
  const karmaBalance = currentUser ? currentUser.wallet_karma : 0

  const now = new Date()
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1).toISOString()
  const purchasedThisMonthByItem: Record<string, number> = {}
  items.forEach((item) => {
    purchasedThisMonthByItem[item.id] = purchases.filter(
      (p) => p.shop_item_id === item.id && p.created_at >= monthStart
    ).length
  })

  const handlePurchase = (item: ShopItem) => {
    if (!currentUserId) return
    if (!window.confirm(`Купить "${item.name}" за ${item.cost_q} Q кармы?`)) return
    api
      .post<Purchase>('/api/shop/purchase', { user_id: currentUserId, shop_item_id: item.id })
      .then(() => {
        toast.success('Покупка оформлена! Ожидает подтверждения тимлида.')
        return Promise.all([
          api.get<Purchase[]>(`/api/shop/purchases/${currentUserId}`),
          api.get<User[]>('/api/users'),
        ])
      })
      .then(([newPurchases, newUsers]) => {
        setPurchases(newPurchases)
        setUsers(newUsers)
      })
      .catch((e) => toast.error(e instanceof Error ? e.message : 'Ошибка покупки'))
  }

  const statusIcon = (status: string) => {
    if (status === 'pending') return '🕐'
    if (status === 'approved') return '✅'
    return '❌'
  }

  if (loading) return <div className="text-slate-500">Загрузка...</div>
  if (error) return <div className="text-red-600">{error}</div>

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-900">Магазин</h1>
        {users.length > 0 && (
          <select
            value={currentUserId}
            onChange={(e) => setCurrentUserId(e.target.value)}
            className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
          >
            {users.map((u) => (
              <option key={u.id} value={u.id}>{u.full_name}</option>
            ))}
          </select>
        )}
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        {karmaBalance > 0 ? (
          <p className="text-xl font-semibold text-slate-900">
            Ваш баланс кармы: ⭐ {karmaBalance.toFixed(1)} Q
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
                  <td className="px-4 py-2">{p.cost_q.toFixed(1)} Q</td>
                  <td className="px-4 py-2">{statusIcon(p.status)} {p.status}</td>
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
