import { useEffect, useMemo, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import {
  ChevronDown,
  LogOut,
  Menu,
  Paperclip,
  X,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useAuth } from '@/contexts/AuthContext'
import { LeagueBadge } from '@/components/LeagueBadge'
import {
  applySidebarItemLabels,
  normalizeSidebarOrder,
  iconForMenuButton,
  sidebarGroups,
  type SidebarMenuButton,
  type SidebarNavItem,
  visibleItemsForButton,
  visibleSidebarNav,
} from '@/lib/sidebarNavigation'

export function Sidebar() {
  const { user, logout } = useAuth()
  const location = useLocation()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [desktopPinned, setDesktopPinned] = useState(() => {
    if (typeof window === 'undefined') return true
    return window.localStorage.getItem('dpms.sidebarPinned') !== 'false'
  })
  const [desktopHoverOpen, setDesktopHoverOpen] = useState(false)
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({})

  useEffect(() => {
    window.localStorage.setItem('dpms.sidebarPinned', String(desktopPinned))
  }, [desktopPinned])

  const sidebarOrder = useMemo(() => normalizeSidebarOrder(user?.sidebar_menu_order), [user?.sidebar_menu_order])
  const visibleNav = useMemo(
    () => applySidebarItemLabels(visibleSidebarNav(user), sidebarOrder),
    [sidebarOrder, user]
  )

  const orderedMainGroups = useMemo(() => {
    return sidebarOrder.groups
      .map((button) => ({ button, items: visibleItemsForButton(button, visibleNav) }))
      .filter(({ items }) => items.length > 0)
  }, [sidebarOrder, visibleNav])

  const orderedBottomGroups = useMemo(() => {
    const visibleByGroup = new Set(visibleNav.map((item) => item.group))
    return sidebarGroups.filter((group) => group.placement === 'bottom' && visibleByGroup.has(group.key))
  }, [visibleNav])

  const isItemActive = (item: SidebarNavItem) => {
    if (item.to === '/') return location.pathname === '/'
    return location.pathname === item.to || location.pathname.startsWith(`${item.to}/`)
  }

  const groupHasActiveItem = (items: SidebarNavItem[]) => {
    return items.some(isItemActive)
  }

  const toggleGroup = (groupId: string) => {
    setOpenGroups((current) => ({ ...current, [groupId]: !current[groupId] }))
  }

  const closeMobile = () => setMobileOpen(false)

  const renderNavLink = (item: SidebarNavItem, nested = false) => (
    <NavLink
      key={item.to}
      to={item.to}
      end={item.to === '/'}
      onClick={closeMobile}
      className={({ isActive }) =>
        cn(
          'flex items-center gap-2.5 rounded-xl text-sm transition-all',
          nested ? 'px-3 py-1.5 text-[13px]' : 'px-3 py-2',
          isActive
            ? 'bg-accent-lighter text-accent-dark font-medium'
            : 'text-gray-500 hover:bg-gray-50 hover:text-gray-700'
        )
      }
    >
      <item.icon className="h-4 w-4 shrink-0" />
      {item.label}
    </NavLink>
  )

  const renderMenuButton = (
    button: SidebarMenuButton,
    items: SidebarNavItem[],
  ) => {
    if (items.length === 0) return null
    if (items.length === 1) {
      const item = items[0]
      const Icon = iconForMenuButton(button, items)
      return renderNavLink({ ...item, label: button.label, icon: Icon })
    }
    const Icon = iconForMenuButton(button, items)
    const isOpen = openGroups[button.id]
    const isActive = groupHasActiveItem(items)
    return (
      <div>
        <button
          type="button"
          onClick={() => toggleGroup(button.id)}
          className={cn(
            'flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-sm transition-all',
            isActive
              ? 'bg-accent-lighter text-accent-dark font-medium'
              : 'text-gray-500 hover:bg-gray-50 hover:text-gray-700'
          )}
          aria-expanded={isOpen}
        >
          <Icon className="h-4 w-4 shrink-0" />
          <span className="min-w-0 flex-1 text-left">{button.label}</span>
          <ChevronDown className={cn('h-4 w-4 shrink-0 transition-transform', isOpen && 'rotate-180')} />
        </button>
        {isOpen && (
          <div className="mt-1 space-y-1 border-l border-slate-100 pl-3">
            {items.map((item) => renderNavLink(item, true))}
          </div>
        )}
      </div>
    )
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setMobileOpen((o) => !o)}
        className="fixed left-4 top-4 z-40 rounded-xl border border-gray-200 bg-white p-2 lg:hidden"
        aria-label="Меню"
      >
        {mobileOpen ? <X className="h-5 w-5 text-gray-600" /> : <Menu className="h-5 w-5 text-gray-600" />}
      </button>

      {mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/30 lg:hidden"
          onClick={() => setMobileOpen(false)}
          aria-hidden
        />
      )}

      {!desktopPinned && (
        <div
          className="fixed left-0 top-0 z-30 hidden h-screen w-3 lg:block"
          onMouseEnter={() => setDesktopHoverOpen(true)}
          aria-hidden
        />
      )}

      <aside
        onMouseEnter={() => {
          if (!desktopPinned) setDesktopHoverOpen(true)
        }}
        onMouseLeave={() => {
          if (!desktopPinned) setDesktopHoverOpen(false)
        }}
        className={cn(
          'fixed left-0 top-0 z-40 flex h-full w-56 flex-col border-r border-gray-200/50 bg-white shadow-sm transition-transform duration-200 ease-out',
          mobileOpen ? 'translate-x-0' : '-translate-x-full',
          desktopPinned && 'lg:static lg:translate-x-0 lg:shadow-none',
          !desktopPinned && (desktopHoverOpen ? 'lg:translate-x-0' : 'lg:-translate-x-full')
        )}
      >
        <div className="relative flex items-center justify-center border-b border-gray-100 px-4 py-5">
          <img src="/logo_prosto_sdelal.svg" alt="Просто Сделал" className="app-logo h-9" />
          <button
            type="button"
            onClick={() => setDesktopPinned((value) => !value)}
            className={cn(
              'absolute right-2 top-4 hidden h-8 w-8 items-center justify-center rounded-md border border-gray-200 text-gray-400 transition-colors hover:bg-gray-50 hover:text-gray-700 lg:inline-flex',
              desktopPinned && 'bg-gray-50 text-gray-700'
            )}
            title={desktopPinned ? 'Открепить боковую панель' : 'Закрепить боковую панель'}
            aria-label={desktopPinned ? 'Открепить боковую панель' : 'Закрепить боковую панель'}
          >
            <Paperclip className="h-4 w-4" />
          </button>
        </div>
        {user && (
          <div className="border-b border-gray-100 px-4 py-3">
            <p className="truncate text-sm font-medium text-gray-800">{user.full_name}</p>
            <div className="mt-1 flex items-center gap-2">
              <LeagueBadge league={user.league} className="text-xs" />
              <span className="text-xs text-gray-400">{user.role}</span>
            </div>
          </div>
        )}
        <nav className="flex-1 overflow-y-auto p-2">
          <div className="space-y-1">
            {orderedMainGroups.map(({ button, items }) => (
              <div key={button.id}>{renderMenuButton(button, items)}</div>
            ))}
          </div>
        </nav>
        <div className="border-t border-gray-100 p-2">
          <div className="mb-2 space-y-1">
            {orderedBottomGroups.map((group) =>
              visibleNav.filter((item) => item.group === group.key).map((item) => renderNavLink(item))
            )}
          </div>
          <button
            type="button"
            onClick={logout}
            className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-sm text-gray-400 hover:bg-gray-50 hover:text-gray-600 transition-colors"
          >
            <LogOut className="h-4 w-4" />
            Выйти
          </button>
        </div>
      </aside>
    </>
  )
}
