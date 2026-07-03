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
        <header className="sticky top-0 z-20 flex min-h-[57px] items-center justify-end gap-2 border-b border-border bg-surface/85 px-3 py-2 backdrop-blur-sm lg:gap-3 lg:px-4 lg:pl-6">
          <ThemeToggle />
          <NotificationBell />
          {user && (
            <span className="hidden max-w-[170px] truncate text-sm text-muted-foreground sm:inline">
              {user.full_name}
            </span>
          )}
        </header>
        <main className="min-h-0 flex-1 overflow-auto px-4 pb-[calc(env(safe-area-inset-bottom)+92px)] pt-4 lg:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
