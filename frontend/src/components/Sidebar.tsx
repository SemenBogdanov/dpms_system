import { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  ListTodo,
  ClipboardList,
  Calculator,
  Scale,
  User,
  Users,
  CalendarDays,
  BookOpenCheck,
  BookOpen,
  Library,
  ShoppingBag,
  BarChart3,
  MessageSquare,
  Settings,
  LogOut,
  Menu,
  Paperclip,
  X,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useAuth } from '@/contexts/AuthContext'
import { LeagueBadge } from '@/components/LeagueBadge'
import { hasDevelopmentAccess, hasFeedbackAccess, hasTaskWorkspaceAccess } from '@/lib/access'

const nav: Array<
  {
    to: string
    label: string
    icon: typeof LayoutDashboard
    section: 'task' | 'feedback' | 'development' | 'settings' | 'admin'
    roles?: readonly ('executor' | 'teamlead' | 'admin')[]
  }
> = [
  { to: '/', label: 'Дашборд', icon: LayoutDashboard, section: 'task', roles: ['teamlead', 'admin'] as const },
  { to: '/calibration', label: 'Калибровка', icon: Scale, section: 'task', roles: ['admin'] },
  { to: '/queue', label: 'Очередь', icon: ListTodo, section: 'task' },
  { to: '/my-tasks', label: 'Мои задачи', icon: ClipboardList, section: 'task' },
  { to: '/calculator', label: 'Калькулятор', icon: Calculator, section: 'task', roles: ['teamlead', 'admin'] },
  { to: '/profile', label: 'Профиль', icon: User, section: 'task' },
  { to: '/shop', label: 'Магазин', icon: ShoppingBag, section: 'task' },
  { to: '/feedback', label: 'Обратная связь', icon: MessageSquare, section: 'feedback' },
  { to: '/competencies', label: 'Развитие', icon: BookOpenCheck, section: 'development' },
  { to: '/settings', label: 'Настройки', icon: Settings, section: 'settings' },
  { to: '/reports', label: 'Отчёты', icon: BarChart3, section: 'task', roles: ['teamlead', 'admin'] },
  { to: '/absences', label: 'Отсутствия', icon: CalendarDays, section: 'task', roles: ['teamlead', 'admin'] },
  { to: '/admin/users', label: 'Админ', icon: Users, section: 'admin', roles: ['admin'] },
  { to: '/catalog', label: 'Каталог операций', icon: Library, section: 'task' },
  { to: '/knowledge', label: 'База знаний', icon: BookOpen, section: 'task' },
]

export function Sidebar() {
  const { user, logout } = useAuth()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [desktopPinned, setDesktopPinned] = useState(() => {
    if (typeof window === 'undefined') return true
    return window.localStorage.getItem('dpms.sidebarPinned') !== 'false'
  })
  const [desktopHoverOpen, setDesktopHoverOpen] = useState(false)

  useEffect(() => {
    window.localStorage.setItem('dpms.sidebarPinned', String(desktopPinned))
  }, [desktopPinned])

  const visibleNav = nav.filter((item) => {
    if (item.section === 'task' && !hasTaskWorkspaceAccess(user)) return false
    if (item.section === 'feedback' && !hasFeedbackAccess(user)) return false
    if (item.section === 'development' && !hasDevelopmentAccess(user)) return false
    if (item.section === 'settings') return true
    if (item.section === 'admin' && user?.role !== 'admin') return false
    if (!item.roles) return true
    return user && item.roles.includes(user.role)
  })

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
          {visibleNav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              onClick={() => setMobileOpen(false)}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-2.5 rounded-xl px-3 py-2 text-sm transition-all',
                  isActive
                    ? 'bg-accent-lighter text-accent-dark font-medium'
                    : 'text-gray-500 hover:bg-gray-50 hover:text-gray-700'
                )
              }
            >
              <item.icon className="h-4 w-4 shrink-0" />
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-gray-100 p-2">
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
