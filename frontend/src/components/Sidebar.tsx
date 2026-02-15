import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  ListTodo,
  ClipboardList,
  Calculator,
  Scale,
  User,
  Users,
  BookOpen,
  ShoppingBag,
  BarChart3,
  LogOut,
  Menu,
  X,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useAuth } from '@/contexts/AuthContext'
import { LeagueBadge } from '@/components/LeagueBadge'

const nav: Array<
  { to: string; label: string; icon: typeof LayoutDashboard; roles?: readonly ('executor' | 'teamlead' | 'admin')[] }
> = [
  { to: '/', label: 'Дашборд', icon: LayoutDashboard },
  { to: '/calibration', label: 'Калибровка', icon: Scale, roles: ['teamlead', 'admin'] },
  { to: '/queue', label: 'Очередь', icon: ListTodo },
  { to: '/my-tasks', label: 'Мои задачи', icon: ClipboardList },
  { to: '/calculator', label: 'Калькулятор', icon: Calculator },
  { to: '/profile', label: 'Профиль', icon: User },
  { to: '/shop', label: 'Магазин', icon: ShoppingBag },
  { to: '/reports', label: 'Отчёты', icon: BarChart3, roles: ['teamlead', 'admin'] },
  { to: '/admin/users', label: 'Админ', icon: Users, roles: ['admin'] },
  { to: '/catalog', label: 'Справочник', icon: BookOpen },
]

export function Sidebar() {
  const { user, logout } = useAuth()
  const [mobileOpen, setMobileOpen] = useState(false)

  const visibleNav = nav.filter((item) => {
    if (!item.roles) return true
    return user && item.roles.includes(user.role)
  })

  return (
    <>
      {/* Кнопка бургера для мобильных (< 1024px) */}
      <button
        type="button"
        onClick={() => setMobileOpen((o) => !o)}
        className="fixed left-4 top-4 z-40 rounded-lg border border-slate-200 bg-white p-2 lg:hidden"
        aria-label="Меню"
      >
        {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
      </button>

      {/* Overlay при открытом сайдбаре на мобильных */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/50 lg:hidden"
          onClick={() => setMobileOpen(false)}
          aria-hidden
        />
      )}

      <aside
        className={cn(
          'fixed left-0 top-0 z-40 flex h-full w-56 flex-col border-r border-slate-200 bg-white transition-transform lg:static lg:translate-x-0',
          mobileOpen ? 'translate-x-0' : '-translate-x-full'
        )}
      >
        <div className="p-4 border-b border-slate-200">
          <h1 className="font-semibold text-slate-800">DPMS</h1>
          <p className="text-xs text-slate-500">Production Management</p>
        </div>
        {user && (
          <div className="border-b border-slate-100 px-4 py-3">
            <p className="truncate text-sm font-medium text-slate-900">{user.full_name}</p>
            <div className="mt-1 flex items-center gap-2">
              <LeagueBadge league={user.league} className="text-xs" />
              <span className="text-xs text-slate-500">{user.role}</span>
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
                  'flex items-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors',
                  isActive ? 'bg-primary text-primary-foreground' : 'text-slate-600 hover:bg-slate-100'
                )
              }
            >
              <item.icon className="h-4 w-4 shrink-0" />
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-slate-200 p-2">
          <button
            type="button"
            onClick={logout}
            className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-600 hover:bg-slate-100"
          >
            <LogOut className="h-4 w-4" />
            Выйти
          </button>
        </div>
      </aside>
    </>
  )
}
