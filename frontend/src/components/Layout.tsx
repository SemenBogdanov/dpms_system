import { Suspense } from 'react'
import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { SkeletonCard } from './Skeleton'
import { ThemeToggle } from './ThemeToggle'
import { AttentionProvider } from '@/contexts/AttentionContext'
import { useAuth } from '@/contexts/AuthContext'

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
  return (
    <AttentionProvider>
      <div className="app-shell flex overflow-hidden bg-background text-foreground transition-colors">
        <Sidebar />
        <div className="flex min-h-0 flex-1 flex-col min-w-0">
          <header className="app-header sticky top-0 z-20 flex min-h-[57px] items-center justify-end gap-2 border-b border-border bg-surface/95 px-3 py-2 backdrop-blur-sm lg:gap-3 lg:px-4 lg:pl-6">
            <ThemeToggle />
            {user && (
              <span className="hidden max-w-[170px] truncate text-sm text-muted-foreground sm:inline">
                {user.full_name}
              </span>
            )}
          </header>
          <main className="app-main min-h-0 flex-1 overflow-auto pb-[calc(env(safe-area-inset-bottom)+92px)] pt-4 lg:p-6">
            <Suspense fallback={<RouteFallback />}>
              <Outlet />
            </Suspense>
          </main>
        </div>
      </div>
    </AttentionProvider>
  )
}
