import { Suspense, type CSSProperties } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { UsageTracker } from './UsageTracker'
import { SkeletonCard } from './Skeleton'
import { ThemeToggle } from './ThemeToggle'
import { AttentionProvider } from '@/contexts/AttentionContext'
import { useAuth } from '@/contexts/AuthContext'
import { cn } from '@/lib/utils'
import { getSectionForPath } from '@/lib/contentLayout'
import { useContentLayoutPreferences } from '@/hooks/useContentLayoutPreferences'

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
  const { preferences } = useContentLayoutPreferences(user?.id)
  const section = getSectionForPath(location.pathname)
  const preference = section ? preferences[section.id] : undefined
  const frameStyle = {
    '--content-margin': `${preference?.fullWidth ? 0 : preference?.marginPercent ?? 0}%`,
    '--content-min-width': `${section?.minWidth ?? 960}px`,
  } as CSSProperties
  const isGraphWorkspace = location.pathname === '/graphs' || location.pathname.startsWith('/graphs/')
  return (
    <AttentionProvider>
      <UsageTracker />
      <div className="app-shell flex overflow-hidden bg-background text-foreground transition-colors">
        <Sidebar />
        <div className="flex min-h-0 flex-1 flex-col min-w-0">
          <header className={cn(
            'app-header sticky top-0 z-20 flex min-h-[57px] items-center border-b border-border bg-surface/95 px-3 py-2 backdrop-blur-sm',
            isGraphWorkspace && 'hidden'
          )}>
            <div
              className="app-header-content flex items-center justify-end gap-2 lg:gap-3"
              data-layout-custom={Boolean(preference)}
              style={frameStyle}
            >
              <ThemeToggle />
              {user && (
                <span className="hidden max-w-[170px] truncate text-sm text-muted-foreground sm:inline">
                  {user.full_name}
                </span>
              )}
            </div>
          </header>
          <main className={cn(
            'app-main min-h-0 flex-1',
            isGraphWorkspace
              ? 'relative overflow-hidden !p-0'
              : 'overflow-auto pb-[calc(env(safe-area-inset-bottom)+92px)] pt-4 lg:p-6'
          )}>
            <div
              className={cn('app-content-frame', isGraphWorkspace && 'app-content-frame--canvas')}
              data-content-section={section?.id}
              data-layout-custom={Boolean(preference)}
              style={frameStyle}
            >
              <Suspense fallback={<RouteFallback />}>
                <Outlet />
              </Suspense>
            </div>
          </main>
        </div>
      </div>
    </AttentionProvider>
  )
}
