import { useCallback, useEffect, useState } from 'react'
import { api } from '@/api/client'
import type { CatalogItem } from '@/api/types'
import { useAuth } from '@/contexts/AuthContext'
import { QBadge } from '@/components/QBadge'
import { LeagueBadge } from '@/components/LeagueBadge'
import { CatalogModal, type CreateEditPayload } from '@/components/CatalogModal'
import toast from 'react-hot-toast'
import { cn } from '@/lib/utils'

export function CatalogPage() {
  const { user: currentUser } = useAuth()
  const [items, setItems] = useState<CatalogItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error] = useState<string | null>(null)

  const [categoryFilter, setCategoryFilter] = useState<string>('all')
  const [complexityFilter, setComplexityFilter] = useState<string>('all')
  const [activeFilter, setActiveFilter] = useState<string>('active')
  const [search, setSearch] = useState('')

  const [modalItem, setModalItem] = useState<CatalogItem | null>(null)
  const [modalOpen, setModalOpen] = useState(false)

  const loadItems = useCallback(() => {
    const params: Record<string, string> = {}
    if (categoryFilter !== 'all') params.category = categoryFilter
    if (complexityFilter !== 'all') params.complexity = complexityFilter
    if (activeFilter === 'active') params.is_active = 'true'
    else if (activeFilter === 'inactive') params.is_active = 'false'
    if (search.trim()) params.search = search.trim()
    api
      .get<CatalogItem[]>('/api/catalog', params)
      .then(setItems)
      .catch(() => setItems([]))
  }, [categoryFilter, complexityFilter, activeFilter, search])

  useEffect(() => {
    setLoading(true)
    loadItems()
    setLoading(false)
  }, [loadItems])

  const canEdit = currentUser?.role === 'admin'

  const handleCreate = () => {
    setModalItem(null)
    setModalOpen(true)
  }

  const handleEdit = (item: CatalogItem) => {
    setModalItem(item)
    setModalOpen(true)
  }

  const handleSave = (payload: CreateEditPayload) => {
    if (modalItem) {
      api
        .patch<CatalogItem>(`/api/catalog/${modalItem.id}`, payload)
        .then(() => {
          toast.success('Операция обновлена')
          loadItems()
        })
        .catch((e) => toast.error(e instanceof Error ? e.message : 'Ошибка'))
    } else {
      api
        .post<CatalogItem>('/api/catalog', { ...payload, is_active: true })
        .then(() => {
          toast.success('Операция добавлена')
          loadItems()
        })
        .catch((e) => toast.error(e instanceof Error ? e.message : 'Ошибка'))
    }
    setModalOpen(false)
  }

  const handleDeactivate = (item: CatalogItem) => {
    if (!window.confirm(`Деактивировать «${item.name}»?`)) return
    api
      .delete(`/api/catalog/${item.id}`)
      .then(() => {
        toast.success('Операция деактивирована')
        loadItems()
      })
      .catch((e) => toast.error(e instanceof Error ? e.message : 'Ошибка'))
  }

  const handleRestore = (item: CatalogItem) => {
    api
      .patch<CatalogItem>(`/api/catalog/${item.id}`, { is_active: true })
      .then(() => {
        toast.success('Операция восстановлена')
        loadItems()
      })
      .catch((e) => toast.error(e instanceof Error ? e.message : 'Ошибка'))
  }

  if (loading && items.length === 0)
    return <div className="text-slate-500">Загрузка...</div>
  if (error) return <div className="text-red-600">{error}</div>

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold text-slate-900">
          Каталог операций
        </h1>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <select
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value)}
          className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
        >
          <option value="all">Все категории</option>
          <option value="widget">widget</option>
          <option value="etl">etl</option>
          <option value="api">api</option>
          <option value="docs">docs</option>
          <option value="proactive">proactive</option>
        </select>

        <select
          value={complexityFilter}
          onChange={(e) => setComplexityFilter(e.target.value)}
          className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
        >
          <option value="all">Все сложности</option>
          <option value="S">S</option>
          <option value="M">M</option>
          <option value="L">L</option>
          <option value="XL">XL</option>
        </select>

        <select
          value={activeFilter}
          onChange={(e) => setActiveFilter(e.target.value)}
          className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
        >
          <option value="all">Все</option>
          <option value="active">Активные</option>
          <option value="inactive">Неактивные</option>
        </select>

        <input
          type="text"
          placeholder="Поиск по названию"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="rounded-md border border-slate-300 px-3 py-2 text-sm"
        />

        {canEdit && (
          <button
            type="button"
            onClick={handleCreate}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
          >
            + Добавить операцию
          </button>
        )}
      </div>

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <table className="min-w-full divide-y divide-slate-200">
          <thead className="bg-slate-50">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-600">
                №
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-600">
                Название
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-600">
                Категория
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-600">
                Сложность
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-600">
                Стоимость (Q)
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-600">
                Мин. лига
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-600">
                Статус
              </th>
              {canEdit && (
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-600">
                  Действия
                </th>
              )}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200">
            {items.map((item) => (
              <tr
                key={item.id}
                className={cn(
                  'bg-white',
                  !item.is_active && 'bg-slate-100 opacity-75'
                )}
              >
                <td className="whitespace-nowrap px-4 py-3 text-sm text-slate-500">
                  {item.sort_order ?? 100}
                </td>
                <td className="px-4 py-3 text-sm font-medium text-slate-900">
                  {item.name}
                </td>
                <td className="px-4 py-3 text-sm text-slate-600">
                  {item.category}
                </td>
                <td className="px-4 py-3 text-sm">{item.complexity}</td>
                <td className="px-4 py-3">
                  <QBadge q={item.base_cost_q} />
                </td>
                <td className="px-4 py-3">
                  <LeagueBadge league={item.min_league} />
                </td>
                <td className="px-4 py-3 text-sm">
                  {item.is_active ? 'Активна' : 'Неактивна'}
                </td>
                {canEdit && (
                  <td className="px-4 py-3 flex gap-2">
                    <button
                      type="button"
                      onClick={() => handleEdit(item)}
                      className="text-sm text-slate-600 hover:text-slate-900"
                      title="Редактировать"
                    >
                      ✏️ Редактировать
                    </button>
                    {item.is_active ? (
                      <button
                        type="button"
                        onClick={() => handleDeactivate(item)}
                        className="text-sm text-red-600 hover:text-red-800"
                        title="Деактивировать"
                      >
                        🗑️ Деактивировать
                      </button>
                    ) : (
                      <button
                        type="button"
                        onClick={() => handleRestore(item)}
                        className="text-sm text-emerald-600 hover:text-emerald-800"
                        title="Восстановить"
                      >
                        ♻️ Восстановить
                      </button>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        {items.length === 0 && (
          <p className="p-6 text-center text-slate-500">Нет операций</p>
        )}
      </div>

      <CatalogModal
        item={modalItem}
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        onSave={handleSave}
      />
    </div>
  )
}
