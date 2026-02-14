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
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useUser } from '@/contexts/UserContext'

const nav = [
  { to: '/', label: 'Дашборд', icon: LayoutDashboard },
  { to: '/calibration', label: 'Калибровка', icon: Scale, roles: ['teamlead', 'admin'] as const },
  { to: '/queue', label: 'Очередь', icon: ListTodo },
  { to: '/my-tasks', label: 'Мои задачи', icon: ClipboardList },
  { to: '/calculator', label: 'Калькулятор', icon: Calculator },
  { to: '/profile', label: 'Профиль', icon: User },
  { to: '/shop', label: 'Магазин', icon: ShoppingBag },
  { to: '/admin/users', label: 'Сотрудники', icon: Users },
  { to: '/catalog', label: 'Справочник', icon: BookOpen },
]

export function Sidebar() {
  const { users, currentUserId, setCurrentUserId, currentUser } = useUser()
  const visibleNav = nav.filter(
    (item) => !('roles' in item && item.roles) || (currentUser && item.roles.includes(currentUser.role as 'teamlead' | 'admin'))
  )

  return (
    <aside className="w-56 border-r border-slate-200 bg-white flex flex-col">
      <div className="p-4 border-b border-slate-200">
        <h1 className="font-semibold text-slate-800">DPMS</h1>
        <p className="text-xs text-slate-500">Production Management</p>
      </div>
      {users.length > 0 && (
        <div className="px-4 py-2 border-b border-slate-100">
          <label className="text-xs text-slate-500 block mb-1">Текущий пользователь</label>
          <select
            value={currentUserId}
            onChange={(e) => setCurrentUserId(e.target.value)}
            className="w-full rounded border border-slate-200 bg-white px-2 py-1.5 text-sm text-slate-700"
          >
            {users.map((u) => (
              <option key={u.id} value={u.id}>{u.full_name}</option>
            ))}
          </select>
        </div>
      )}
      <nav className="p-2 flex-1">
        {visibleNav.map((item) => {
          const { to, label, icon: Icon } = item
          return (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors',
                isActive
                  ? 'bg-primary text-primary-foreground'
                  : 'text-slate-600 hover:bg-slate-100'
              )
            }
          >
            <Icon className="h-4 w-4 shrink-0" />
            {label}
          </NavLink>
          )
        })}
      </nav>
    </aside>
  )
}
