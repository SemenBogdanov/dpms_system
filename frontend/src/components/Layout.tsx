import { Suspense } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { SkeletonCard } from './Skeleton'
import { ThemeToggle } from './ThemeToggle'
import { AttentionProvider } from '@/contexts/AttentionContext'
import { useAuth } from '@/contexts/AuthContext'
import { cn } from '@/lib/utils'

function RouteFallback() {
  return (
    <div className="mx-auto w-full max-w-5xl space-y-3">
      <SkeletonCard />
      <SkeletonCard />
    </div>
  )
}

export function Layout() {
  const { user } = useAuth()
  const location = useLocation()
  const isGraphWorkspace = location.pathname === '/graphs' || location.pathname.startsWith('/graphs/')
  return (
    <AttentionProvider>
      <div className="app-shell flex overflow-hidden bg-background text-foreground transition-colors">
        <Sidebar />
        <div className="flex min-h-0 flex-1 flex-col min-w-0">
          <header className={cn(
            'app-header sticky top-0 z-20 flex min-h-[57px] items-center justify-end gap-2 border-b border-border bg-surface/95 px-3 py-2 backdrop-blur-sm lg:gap-3 lg:px-4 lg:pl-6',
            isGraphWorkspace && 'hidden'
          )}>
            <ThemeToggle />
            {user && (
              <span className="hidden max-w-[170px] truncate text-sm text-muted-foreground sm:inline">
                {user.full_name}
              </span>
            )}
          </header>
          <main className={cn(
            'app-main min-h-0 flex-1',
            isGraphWorkspace
              ? 'relative overflow-hidden !p-0'
              : 'overflow-auto pb-[calc(env(safe-area-inset-bottom)+92px)] pt-4 lg:p-6'
          )}>
            <Suspense fallback={<RouteFallback />}>
              <Outlet />
            </Suspense>
          </main>
        </div>
      </div>
    </AttentionProvider>
  )
}
