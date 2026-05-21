import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { NotificationBell } from './NotificationBell'
import { ThemeToggle } from './ThemeToggle'
import { useAuth } from '@/contexts/AuthContext'

export function Layout() {
  const { user } = useAuth()
  return (
    <div className="flex h-screen overflow-hidden bg-background text-foreground transition-colors">
      <Sidebar />
      <div className="flex min-h-0 flex-1 flex-col min-w-0">
        <header className="sticky top-0 z-20 flex items-center justify-end gap-3 border-b border-gray-100 bg-white/80 backdrop-blur-sm px-4 py-2 lg:pl-6">
          <ThemeToggle />
          <NotificationBell />
          {user && (
            <span className="text-sm text-gray-400">
              {user.full_name}
            </span>
          )}
        </header>
        <main className="min-h-0 flex-1 overflow-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
