import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { NotificationBell } from './NotificationBell'
import { useAuth } from '@/contexts/AuthContext'

export function Layout() {
  const { user } = useAuth()
  return (
    <div className="flex min-h-screen bg-[#f5f5f7]">
      <Sidebar />
      <div className="flex flex-1 flex-col min-w-0">
        <header className="sticky top-0 z-20 flex items-center justify-end gap-3 border-b border-gray-100 bg-white/80 backdrop-blur-sm px-4 py-2 lg:pl-6">
          <NotificationBell />
          {user && (
            <span className="text-sm text-gray-400">
              {user.full_name}
            </span>
          )}
        </header>
        <main className="flex-1 p-6 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
