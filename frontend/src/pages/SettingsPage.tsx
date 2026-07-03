import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowDown,
  ArrowUp,
  ArrowUpRight,
  Gauge,
  GripVertical,
  KeyRound,
  PanelLeft,
  Plus,
  RotateCcw,
  Save,
  ShieldCheck,
  Trash2,
  UserRound,
  WalletCards,
  X,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '@/api/client'
import type { User } from '@/api/types'
import { useAuth } from '@/contexts/AuthContext'
import { ChangePasswordModal } from '@/components/ChangePasswordModal'
import { LeagueBadge } from '@/components/LeagueBadge'
import { hasTaskWorkspaceAccess } from '@/lib/access'
import {
  applySidebarItemLabels,
  defaultSidebarOrder,
  normalizeSidebarOrder,
  sidebarOrderPayload,
  type SidebarMenuButton,
  type SidebarNavItem,
  type SidebarOrder,
  visibleSidebarNav,
} from '@/lib/sidebarNavigation'

type MenuDragPayload =
  | { type: 'button'; id: string }
  | { type: 'available-item'; itemId: string }
  | { type: 'selected-item'; buttonId: string; itemId: string }

function moveItem<T>(items: T[], from: number, to: number) {
  const next = [...items]
  const [item] = next.splice(from, 1)
  next.splice(to, 0, item)
  return next
}

export function SettingsPage() {
  const { user, updateUser } = useAuth()
  const [changePasswordOpen, setChangePasswordOpen] = useState(false)
  const [sidebarOrder, setSidebarOrder] = useState(() => normalizeSidebarOrder(user?.sidebar_menu_order))
  const [selectedButtonId, setSelectedButtonId] = useState(() => sidebarOrder.groups[0]?.id || '')
  const [savingMenu, setSavingMenu] = useState(false)
  const [dragPayload, setDragPayload] = useState<MenuDragPayload | null>(null)
  const canOpenDetailedProfile = hasTaskWorkspaceAccess(user)

  useEffect(() => {
    const nextOrder = normalizeSidebarOrder(user?.sidebar_menu_order)
    setSidebarOrder(nextOrder)
    setSelectedButtonId((current) =>
      nextOrder.groups.some((button) => button.id === current) ? current : nextOrder.groups[0]?.id || ''
    )
  }, [user?.sidebar_menu_order])

  const baseAvailableNav = useMemo(() => {
    return visibleSidebarNav(user).filter((item) => item.section !== 'settings' && item.section !== 'admin')
  }, [user])
  const availableNav = useMemo(
    () => applySidebarItemLabels(baseAvailableNav, sidebarOrder),
    [baseAvailableNav, sidebarOrder]
  )

  const savedSidebarOrder = useMemo(() => normalizeSidebarOrder(user?.sidebar_menu_order), [user?.sidebar_menu_order])
  const hasUnsavedMenuChanges = useMemo(() => {
    return JSON.stringify(sidebarOrderPayload(sidebarOrder)) !== JSON.stringify(sidebarOrderPayload(savedSidebarOrder))
  }, [savedSidebarOrder, sidebarOrder])

  const selectedButton = sidebarOrder.groups.find((button) => button.id === selectedButtonId) || sidebarOrder.groups[0]

  const selectedItems = useMemo(() => {
    if (!selectedButton) return []
    const visibleById = new Map(availableNav.map((item) => [item.id, item]))
    return selectedButton.itemIds.map((itemId) => visibleById.get(itemId)).filter((item): item is SidebarNavItem => Boolean(item))
  }, [availableNav, selectedButton])

  const assignedTo = useMemo(() => {
    const result = new Map<string, SidebarMenuButton>()
    sidebarOrder.groups.forEach((button) => {
      button.itemIds.forEach((itemId) => result.set(itemId, button))
    })
    return result
  }, [sidebarOrder.groups])

  const updateSidebarDraft = (updater: (current: SidebarOrder) => SidebarOrder) => {
    setSidebarOrder((current) => normalizeSidebarOrder(updater(current)))
  }

  const persistSidebarOrder = async () => {
    if (!user) return
    const normalized = normalizeSidebarOrder(sidebarOrder)
    if (!normalized.groups.some((button) => button.itemIds.length > 0)) {
      toast.error('Добавьте хотя бы один раздел в меню')
      return
    }
    setSavingMenu(true)
    try {
      const updatedUser = await api.patch<User>('/api/auth/me/sidebar-menu', {
        sidebar_menu_order: sidebarOrderPayload(normalized),
      })
      updateUser(updatedUser)
      toast.success('Меню сохранено')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось сохранить меню')
    } finally {
      setSavingMenu(false)
    }
  }

  const createMenuButton = () => {
    const id = `custom-${Date.now().toString(36)}`
    updateSidebarDraft((current) => ({
      ...current,
      groups: [...current.groups, { id, label: 'Новая кнопка', itemIds: [] }],
    }))
    setSelectedButtonId(id)
  }

  const updateMenuButtonLabel = (label: string) => {
    if (!selectedButton) return
    updateSidebarDraft((current) => ({
      ...current,
      groups: current.groups.map((button) =>
        button.id === selectedButton.id ? { ...button, label } : button
      ),
    }))
  }

  const updateSectionLabel = (itemId: string, label: string) => {
    updateSidebarDraft((current) => ({
      ...current,
      itemLabels: { ...current.itemLabels, [itemId]: label },
    }))
  }

  const deleteMenuButton = (buttonId: string) => {
    if (sidebarOrder.groups.length <= 1) {
      toast.error('В меню должна остаться хотя бы одна кнопка')
      return
    }
    const currentIndex = sidebarOrder.groups.findIndex((button) => button.id === buttonId)
    const nextGroups = sidebarOrder.groups.filter((button) => button.id !== buttonId)
    updateSidebarDraft((current) => ({
      ...current,
      groups: current.groups.filter((button) => button.id !== buttonId),
    }))
    if (selectedButtonId === buttonId) {
      setSelectedButtonId(nextGroups[Math.max(0, currentIndex - 1)]?.id || nextGroups[0]?.id || '')
    }
  }

  const moveButton = (buttonId: string, direction: -1 | 1) => {
    const index = sidebarOrder.groups.findIndex((button) => button.id === buttonId)
    const targetIndex = index + direction
    if (index < 0 || targetIndex < 0 || targetIndex >= sidebarOrder.groups.length) return
    updateSidebarDraft((current) => ({ ...current, groups: moveItem(current.groups, index, targetIndex) }))
  }

  const dropButton = (targetId: string) => {
    if (!dragPayload || dragPayload.type !== 'button' || dragPayload.id === targetId) return
    const from = sidebarOrder.groups.findIndex((button) => button.id === dragPayload.id)
    const to = sidebarOrder.groups.findIndex((button) => button.id === targetId)
    if (from < 0 || to < 0) return
    updateSidebarDraft((current) => ({ ...current, groups: moveItem(current.groups, from, to) }))
  }

  const assignItemToSelectedButton = (itemId: string) => {
    if (!selectedButton) return
    updateSidebarDraft((current) => ({
      ...current,
      groups: current.groups.map((button) => {
        const withoutItem = button.itemIds.filter((id) => id !== itemId)
        if (button.id !== selectedButton.id) return { ...button, itemIds: withoutItem }
        return { ...button, itemIds: [...withoutItem, itemId] }
      }),
    }))
  }

  const removeItemFromSelectedButton = (itemId: string) => {
    if (!selectedButton) return
    updateSidebarDraft((current) => ({
      ...current,
      groups: current.groups.map((button) =>
        button.id === selectedButton.id
          ? { ...button, itemIds: button.itemIds.filter((id) => id !== itemId) }
          : button
      ),
    }))
  }

  const moveSelectedItem = (itemId: string, direction: -1 | 1) => {
    if (!selectedButton) return
    const currentItems = selectedButton.itemIds
    const index = currentItems.indexOf(itemId)
    const targetIndex = index + direction
    if (index < 0 || targetIndex < 0 || targetIndex >= currentItems.length) return
    updateSidebarDraft((current) => ({
      ...current,
      groups: current.groups.map((button) =>
        button.id === selectedButton.id
          ? { ...button, itemIds: moveItem(button.itemIds, index, targetIndex) }
          : button
      ),
    }))
  }

  const dropSelectedItem = (targetId: string) => {
    if (!selectedButton || !dragPayload) return
    if (dragPayload.type === 'available-item') {
      assignItemToSelectedButton(dragPayload.itemId)
      return
    }
    if (dragPayload.type !== 'selected-item' || dragPayload.buttonId !== selectedButton.id || dragPayload.itemId === targetId) return
    const currentItems = selectedButton.itemIds
    const from = currentItems.indexOf(dragPayload.itemId)
    const to = currentItems.indexOf(targetId)
    if (from < 0 || to < 0) return
    updateSidebarDraft((current) => ({
      ...current,
      groups: current.groups.map((button) =>
        button.id === selectedButton.id
          ? { ...button, itemIds: moveItem(button.itemIds, from, to) }
          : button
      ),
    }))
  }

  const dropIntoSelectedButton = () => {
    if (!dragPayload || dragPayload.type !== 'available-item') return
    assignItemToSelectedButton(dragPayload.itemId)
  }

  const resetSidebarOrder = () => {
    const nextOrder = normalizeSidebarOrder(defaultSidebarOrder)
    setSidebarOrder(nextOrder)
    setSelectedButtonId(nextOrder.groups[0]?.id || '')
  }

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">Настройки</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Аккаунт, профиль пользователя и сервисные действия.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.45fr)_minmax(280px,0.55fr)]">
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-900">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="flex min-w-0 items-start gap-3">
              <span className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <UserRound className="h-5 w-5" />
              </span>
              <div className="min-w-0">
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">Профиль</p>
                <h2 className="mt-1 truncate text-lg font-semibold text-slate-900 dark:text-slate-100">
                  {user?.full_name ?? 'Пользователь'}
                </h2>
                <p className="mt-1 truncate text-sm text-slate-500 dark:text-slate-400">{user?.email}</p>
                {user && (
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <LeagueBadge league={user.league} />
                    <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                      {user.role}
                    </span>
                  </div>
                )}
              </div>
            </div>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-200">
              <ShieldCheck className="h-3.5 w-3.5" />
              Активен
            </span>
          </div>
          {canOpenDetailedProfile && (
            <div className="mt-5 border-t border-slate-100 pt-4 dark:border-slate-800">
              <Link
                to="/profile"
                className="inline-flex items-center gap-2 text-sm font-medium text-primary hover:underline"
              >
                Открыть подробный профиль
                <ArrowUpRight className="h-4 w-4" />
              </Link>
            </div>
          )}
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-900">
          <div className="flex items-start gap-3">
            <span className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <KeyRound className="h-5 w-5" />
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">Безопасность</p>
              <h2 className="mt-1 font-semibold text-slate-900 dark:text-slate-100">Пароль</h2>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">Обновление пароля учетной записи.</p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setChangePasswordOpen(true)}
            className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            <KeyRound className="h-4 w-4" />
            Сменить пароль
          </button>
        </section>
      </div>

      {user && (
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-900">
          <div className="mb-4 flex items-center gap-3">
            <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
              <WalletCards className="h-5 w-5" />
            </span>
            <div>
              <h2 className="font-semibold text-slate-900 dark:text-slate-100">Q-профиль</h2>
              <p className="text-sm text-slate-500 dark:text-slate-400">Баланс, план и качество в задачном контуре.</p>
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-lg border border-slate-200 px-4 py-3 dark:border-slate-700">
              <p className="text-xs font-medium text-slate-500 dark:text-slate-400">Main / план</p>
              <p className="mt-1 text-lg font-semibold text-slate-900 dark:text-slate-100">
                {Number(user.wallet_main).toFixed(1)} / {Number(user.mpw).toFixed(1)} Q
              </p>
            </div>
            <div className="rounded-lg border border-slate-200 px-4 py-3 dark:border-slate-700">
              <p className="text-xs font-medium text-slate-500 dark:text-slate-400">Karma</p>
              <p className="mt-1 text-lg font-semibold text-slate-900 dark:text-slate-100">
                {Number(user.wallet_karma).toFixed(1)} Q
              </p>
            </div>
            <div className="rounded-lg border border-slate-200 px-4 py-3 dark:border-slate-700">
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400">Quality Score</p>
                <Gauge className="h-4 w-4 text-slate-400" />
              </div>
              <p className="mt-1 text-lg font-semibold text-slate-900 dark:text-slate-100">
                {Number(user.quality_score).toFixed(1)}%
              </p>
            </div>
          </div>
        </section>
      )}

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-900">
        <div className="flex items-center gap-3">
          <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
            <ShieldCheck className="h-5 w-5" />
          </span>
          <div>
            <h2 className="font-medium text-slate-900 dark:text-slate-100">Доступы</h2>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              Разделы системы открывает администратор. Смена пароля доступна независимо от рабочих разделов.
            </p>
          </div>
        </div>
      </section>

      {user && (
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-900">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="flex items-start gap-3">
              <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <PanelLeft className="h-5 w-5" />
              </span>
              <div>
                <h2 className="font-semibold text-slate-900 dark:text-slate-100">Меню</h2>
                <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                  Конструктор левой панели. Конфигурация хранится в профиле пользователя.
                </p>
              </div>
            </div>
            <div className="flex flex-wrap items-center justify-end gap-2">
              {hasUnsavedMenuChanges && (
                <span className="rounded-full bg-amber-50 px-3 py-1 text-xs font-medium text-amber-700 dark:bg-amber-950/40 dark:text-amber-200">
                  Есть изменения
                </span>
              )}
              <button
                type="button"
                onClick={resetSidebarOrder}
                disabled={savingMenu}
                className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-50 disabled:opacity-60 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
              >
                <RotateCcw className="h-4 w-4" />
                Сбросить
              </button>
              <button
                type="button"
                onClick={() => void persistSidebarOrder()}
                disabled={savingMenu || !hasUnsavedMenuChanges}
                className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-60"
              >
                <Save className="h-4 w-4" />
                {savingMenu ? 'Сохранение' : 'Сохранить'}
              </button>
            </div>
          </div>

          <div className="mt-5 grid gap-4 xl:grid-cols-[320px_minmax(0,1fr)_300px]">
            <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Основные кнопки</h3>
                <button
                  type="button"
                  onClick={createMenuButton}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md bg-primary text-primary-foreground transition-colors hover:bg-primary/90"
                  aria-label="Создать кнопку меню"
                  title="Создать кнопку меню"
                >
                  <Plus className="h-4 w-4" />
                </button>
              </div>
              <div className="space-y-2">
                {sidebarOrder.groups.map((button, index) => {
                  const firstItem = availableNav.find((item) => button.itemIds.includes(item.id))
                  const Icon = firstItem?.icon || PanelLeft
                  const isSelected = button.id === selectedButton?.id
                  return (
                    <div
                      key={button.id}
                      draggable={!savingMenu}
                      onDragStart={() => setDragPayload({ type: 'button', id: button.id })}
                      onDragEnd={() => setDragPayload(null)}
                      onDragOver={(event) => event.preventDefault()}
                      onDrop={() => dropButton(button.id)}
                      className={[
                        'rounded-lg border px-3 py-3 text-sm transition-colors',
                        isSelected
                          ? 'border-primary/40 bg-primary/10 text-slate-900 dark:bg-primary/15 dark:text-slate-100'
                          : 'border-slate-200 bg-slate-50 text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-800/70 dark:text-slate-200 dark:hover:bg-slate-800',
                      ].join(' ')}
                    >
                      <div className="flex items-start gap-2">
                        <GripVertical className="mt-1 h-4 w-4 shrink-0 text-slate-400" />
                        <Icon className="mt-1 h-4 w-4 shrink-0 text-primary" />
                        <button
                          type="button"
                          onClick={() => setSelectedButtonId(button.id)}
                          className="min-w-0 flex-1 text-left"
                        >
                          <span className="block break-words text-sm font-semibold leading-5 text-slate-900 dark:text-slate-100">
                            {button.label}
                          </span>
                          <span className="mt-1 block text-xs leading-4 text-slate-500 dark:text-slate-400">
                            {button.itemIds.length} разделов
                            {firstItem ? ` · ${firstItem.label}` : ''}
                          </span>
                        </button>
                        <span className="shrink-0 rounded bg-white/70 px-1.5 py-0.5 text-[11px] text-slate-500 dark:bg-slate-900/70 dark:text-slate-400">
                          {button.itemIds.length}
                        </span>
                      </div>
                      <div className="mt-2 flex items-center justify-end gap-1">
                        <button
                          type="button"
                          onClick={() => moveButton(button.id, -1)}
                          disabled={savingMenu || index === 0}
                          className="inline-flex h-8 w-8 items-center justify-center rounded-md text-slate-500 hover:bg-white disabled:opacity-35 dark:text-slate-300 dark:hover:bg-slate-900"
                          aria-label="Поднять раздел"
                        >
                          <ArrowUp className="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          onClick={() => moveButton(button.id, 1)}
                          disabled={savingMenu || index === sidebarOrder.groups.length - 1}
                          className="inline-flex h-8 w-8 items-center justify-center rounded-md text-slate-500 hover:bg-white disabled:opacity-35 dark:text-slate-300 dark:hover:bg-slate-900"
                          aria-label="Опустить раздел"
                        >
                          <ArrowDown className="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          onClick={() => deleteMenuButton(button.id)}
                          disabled={savingMenu || sidebarOrder.groups.length <= 1}
                          className="inline-flex h-8 w-8 items-center justify-center rounded-md text-rose-500 hover:bg-rose-50 disabled:opacity-35 dark:text-rose-300 dark:hover:bg-rose-950/30"
                          aria-label="Удалить кнопку"
                          title="Удалить кнопку"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </div>
                  )
                })}
              </div>
              <p className="mt-3 text-xs text-slate-400">
                Настройки и админ-раздел закреплены внизу панели над выходом.
              </p>
            </div>

            <div
              className="rounded-lg border border-slate-200 p-4 dark:border-slate-700"
              onDragOver={(event) => event.preventDefault()}
              onDrop={dropIntoSelectedButton}
            >
              {selectedButton ? (
                <>
                  <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
                    <label className="block">
                      <span className="text-xs font-medium uppercase tracking-[0.12em] text-slate-400">
                        Редактирование
                      </span>
                      <input
                        value={selectedButton.label}
                        onChange={(event) => updateMenuButtonLabel(event.target.value)}
                        className="mt-2 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-900 outline-none transition-colors focus:border-primary dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                        maxLength={80}
                      />
                    </label>
                    <button
                      type="button"
                      onClick={() => deleteMenuButton(selectedButton.id)}
                      disabled={savingMenu || sidebarOrder.groups.length <= 1}
                      className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-rose-200 px-3 py-2 text-sm font-medium text-rose-600 transition-colors hover:bg-rose-50 disabled:opacity-50 dark:border-rose-900/70 dark:text-rose-300 dark:hover:bg-rose-950/30"
                    >
                      <Trash2 className="h-4 w-4" />
                      Удалить
                    </button>
                  </div>

                  <div className="mt-5">
                    <div className="mb-3 flex items-center justify-between gap-3">
                      <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Состав кнопки</h3>
                      <span className="text-xs text-slate-400">{selectedItems.length} разделов</span>
                    </div>
                    {selectedItems.length > 0 ? (
                      <div className="space-y-2">
                        {selectedItems.map((item, index) => {
                          const Icon = item.icon
                          return (
                            <div
                              key={item.id}
                              draggable={!savingMenu}
                              onDragStart={() =>
                                setDragPayload({ type: 'selected-item', buttonId: selectedButton.id, itemId: item.id })
                              }
                              onDragEnd={() => setDragPayload(null)}
                              onDragOver={(event) => event.preventDefault()}
                              onDrop={() => dropSelectedItem(item.id)}
                              className="flex min-h-11 items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700 dark:border-slate-700 dark:bg-slate-800/70 dark:text-slate-200"
                            >
                              <GripVertical className="h-4 w-4 shrink-0 text-slate-400" />
                              <Icon className="h-4 w-4 shrink-0 text-primary" />
                              <span className="min-w-0 flex-1 truncate">{item.label}</span>
                              <button
                                type="button"
                                onClick={() => moveSelectedItem(item.id, -1)}
                                disabled={savingMenu || index === 0}
                                className="inline-flex h-8 w-8 items-center justify-center rounded-md text-slate-500 hover:bg-white disabled:opacity-35 dark:text-slate-300 dark:hover:bg-slate-900"
                                aria-label="Поднять пункт"
                              >
                                <ArrowUp className="h-4 w-4" />
                              </button>
                              <button
                                type="button"
                                onClick={() => moveSelectedItem(item.id, 1)}
                                disabled={savingMenu || index === selectedItems.length - 1}
                                className="inline-flex h-8 w-8 items-center justify-center rounded-md text-slate-500 hover:bg-white disabled:opacity-35 dark:text-slate-300 dark:hover:bg-slate-900"
                                aria-label="Опустить пункт"
                              >
                                <ArrowDown className="h-4 w-4" />
                              </button>
                              <button
                                type="button"
                                onClick={() => removeItemFromSelectedButton(item.id)}
                                disabled={savingMenu}
                                className="inline-flex h-8 w-8 items-center justify-center rounded-md text-rose-500 hover:bg-rose-50 disabled:opacity-35 dark:text-rose-300 dark:hover:bg-rose-950/30"
                                aria-label="Убрать из кнопки"
                                title="Убрать из кнопки"
                              >
                                <X className="h-4 w-4" />
                              </button>
                            </div>
                          )
                        })}
                      </div>
                    ) : (
                      <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-800/50 dark:text-slate-400">
                        Нет разделов
                      </div>
                    )}
                  </div>
                </>
              ) : (
                <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-800/50 dark:text-slate-400">
                  Создайте кнопку меню
                </div>
              )}
            </div>

            <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Доступные разделы</h3>
                <span className="text-xs text-slate-400">{availableNav.length}</span>
              </div>
              <div className="space-y-2">
                {availableNav.map((item) => {
                  const Icon = item.icon
                  const owner = assignedTo.get(item.id)
                  const inSelected = owner?.id === selectedButton?.id
                  const sourceLabel = baseAvailableNav.find((baseItem) => baseItem.id === item.id)?.label || item.label
                  const draftLabel = sidebarOrder.itemLabels[item.id] ?? sourceLabel
                  return (
                    <div
                      key={item.id}
                      draggable={!savingMenu}
                      onDragStart={() => setDragPayload({ type: 'available-item', itemId: item.id })}
                      onDragEnd={() => setDragPayload(null)}
                      className="flex min-h-11 items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700 dark:border-slate-700 dark:bg-slate-800/70 dark:text-slate-200"
                    >
                      <Icon className="h-4 w-4 shrink-0 text-primary" />
                      <div className="min-w-0 flex-1">
                        <input
                          value={draftLabel}
                          onChange={(event) => updateSectionLabel(item.id, event.target.value)}
                          className="w-full rounded-md border border-transparent bg-transparent px-1 py-0.5 text-sm font-medium text-slate-800 outline-none transition-colors focus:border-primary focus:bg-white dark:text-slate-100 dark:focus:bg-slate-950"
                          maxLength={80}
                          aria-label={`Название раздела ${sourceLabel}`}
                        />
                        {owner && (
                          <p className="truncate text-xs text-slate-400">
                            {inSelected ? 'в выбранной кнопке' : `в ${owner.label}`}
                          </p>
                        )}
                        {draftLabel.trim() && draftLabel.trim() !== sourceLabel && (
                          <p className="truncate text-xs text-slate-400">исходно: {sourceLabel}</p>
                        )}
                      </div>
                      <button
                        type="button"
                        onClick={() => assignItemToSelectedButton(item.id)}
                        disabled={savingMenu || !selectedButton || inSelected}
                        className="inline-flex h-8 w-8 items-center justify-center rounded-md bg-primary text-primary-foreground transition-colors hover:bg-primary/90 disabled:bg-slate-200 disabled:text-slate-400 dark:disabled:bg-slate-700 dark:disabled:text-slate-500"
                        aria-label={inSelected ? 'Раздел уже добавлен' : 'Добавить раздел'}
                        title={inSelected ? 'Раздел уже добавлен' : 'Добавить раздел'}
                      >
                        <Plus className="h-4 w-4" />
                      </button>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        </section>
      )}

      <ChangePasswordModal
        open={changePasswordOpen}
        onClose={() => setChangePasswordOpen(false)}
      />
    </div>
  )
}
