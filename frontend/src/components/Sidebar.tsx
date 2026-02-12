import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  ListTodo,
  ClipboardList,
  Calculator,
  User,
  Users,
  BookOpen,
} from 'lucide-react'
import { cn } from '@/lib/utils'

const nav = [
  { to: '/', label: 'Дашборд', icon: LayoutDashboard },
  { to: '/queue', label: 'Очередь', icon: ListTodo },
  { to: '/my-tasks', label: 'Мои задачи', icon: ClipboardList },
  { to: '/calculator', label: 'Калькулятор', icon: Calculator },
  { to: '/profile', label: 'Профиль', icon: User },
  { to: '/admin/users', label: 'Сотрудники', icon: Users },
  { to: '/catalog', label: 'Справочник', icon: BookOpen },
]

export function Sidebar() {
  return (
    <aside className="w-56 border-r border-slate-200 bg-white flex flex-col">
      <div className="p-4 border-b border-slate-200">
        <h1 className="font-semibold text-slate-800">DPMS</h1>
        <p className="text-xs text-slate-500">Production Management</p>
      </div>
      <nav className="p-2 flex-1">
        {nav.map(({ to, label, icon: Icon }) => (
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
        ))}
      </nav>
    </aside>
  )
}
