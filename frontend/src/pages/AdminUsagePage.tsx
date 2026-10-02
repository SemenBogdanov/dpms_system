import { BarChart3, PlugZap, Users } from 'lucide-react'
import { Link } from 'react-router-dom'
import { AdminUsagePanel } from '@/components/AdminUsagePanel'

export function AdminUsagePage() {
  return (
    <div className="min-w-0 space-y-5 px-3 text-foreground lg:px-0">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-primary">Администрирование</p>
          <h1 className="mt-1 text-2xl font-semibold">Использование системы</h1>
        </div>
        <nav className="flex max-w-full flex-wrap gap-1" aria-label="Разделы администрирования">
          <Link to="/admin/users" className="inline-flex min-h-11 items-center gap-2 rounded-md px-3 text-sm hover:bg-surface-muted focus-visible:ring-2 focus-visible:ring-primary"><Users className="h-4 w-4" aria-hidden="true" />Сотрудники</Link>
          <Link to="/admin/integrations" className="inline-flex min-h-11 items-center gap-2 rounded-md px-3 text-sm hover:bg-surface-muted focus-visible:ring-2 focus-visible:ring-primary"><PlugZap className="h-4 w-4" aria-hidden="true" />Интеграции</Link>
          <Link to="/admin/usage" aria-current="page" className="inline-flex min-h-11 items-center gap-2 rounded-md bg-primary px-3 text-sm text-primary-foreground focus-visible:ring-2 focus-visible:ring-primary"><BarChart3 className="h-4 w-4" aria-hidden="true" />Использование</Link>
        </nav>
      </header>
      <AdminUsagePanel />
    </div>
  )
}
