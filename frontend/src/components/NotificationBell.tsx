import { useCallback, useEffect, useState } from 'react'
import { Bell } from 'lucide-react'
import { api } from '@/api/client'
import { NotificationPanel } from './NotificationPanel'

export function NotificationBell() {
  const [unreadCount, setUnreadCount] = useState(0)
  const [open, setOpen] = useState(false)

  const fetchCount = useCallback(() => {
    api.get<{ count: number }>('/api/notifications/unread-count').then(
      (r) => setUnreadCount(r.count),
      () => setUnreadCount(0)
    )
  }, [])

  useEffect(() => {
    fetchCount()
    const t = setInterval(fetchCount, 30000)
    return () => clearInterval(t)
  }, [fetchCount])

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="relative rounded-lg p-2 text-slate-600 hover:bg-slate-100"
        aria-label="Уведомления"
      >
        <Bell className="h-5 w-5" />
        {unreadCount > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-medium text-white">
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>
      {open && (
        <NotificationPanel
          onClose={() => setOpen(false)}
          onReadAll={fetchCount}
        />
      )}
    </div>
  )
}
