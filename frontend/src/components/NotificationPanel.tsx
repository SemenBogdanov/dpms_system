import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '@/api/client'
import type { NotificationRead } from '@/api/types'
import { cn } from '@/lib/utils'

function formatRelative(dateStr: string): string {
  const d = new Date(dateStr)
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const diffM = Math.floor(diffMs / 60000)
  const diffH = Math.floor(diffMs / 3600000)
  const diffD = Math.floor(diffMs / 86400000)
  if (diffM < 1) return 'только что'
  if (diffM < 60) return `${diffM} мин назад`
  if (diffH < 24) return `${diffH} ч назад`
  if (diffD === 1) return 'вчера'
  if (diffD < 7) return `${diffD} дн. назад`
  return d.toLocaleDateString('ru')
}

function iconForType(type: string): string {
  if (type === 'task_validated') return '✅'
  if (type === 'task_rejected') return '❌'
  if (type === 'purchase_approved' || type === 'purchase_pending') return '🛒'
  if (type === 'rollover') return '🔄'
  if (type === 'league_change') return '⬆️'
  return '📌'
}

type Props = { onClose: () => void; onReadAll: () => void }

export function NotificationPanel({ onClose, onReadAll }: Props) {
  const [list, setList] = useState<NotificationRead[]>([])
  const navigate = useNavigate()

  useEffect(() => {
    api.get<NotificationRead[]>('/api/notifications', { limit: '20' }).then(setList).catch(() => setList([]))
  }, [])

  const handleReadAll = () => {
    api.post('/api/notifications/read-all', {}).then(() => onReadAll()).catch(() => {})
  }

  const handleClick = async (n: NotificationRead) => {
    if (!n.is_read) {
      try {
        await api.post(`/api/notifications/${n.id}/read`, {})
      } catch {
        // ignore
      }
    }
    onClose()
    if (n.link) navigate(n.link)
  }

  return (
    <div className="absolute right-0 top-full z-50 mt-2 w-80 rounded-xl border border-slate-200 bg-white shadow-lg">
      <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
        <span className="font-medium text-slate-800">Уведомления</span>
        <button
          type="button"
          onClick={handleReadAll}
          className="text-sm text-primary hover:underline"
        >
          Прочитать все
        </button>
      </div>
      <div className="max-h-96 overflow-y-auto">
        {list.length === 0 ? (
          <p className="p-4 text-center text-sm text-slate-500">Нет уведомлений</p>
        ) : (
          list.map((n) => (
            <button
              key={n.id}
              type="button"
              onClick={() => handleClick(n)}
              className={cn(
                'flex w-full gap-3 border-b border-slate-50 px-4 py-3 text-left last:border-0 hover:bg-slate-50',
                !n.is_read && 'bg-blue-50'
              )}
            >
              <span className="text-lg">{iconForType(n.type)}</span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-slate-900">{n.title}</p>
                <p className="truncate text-xs text-slate-600">{n.message}</p>
                <p className="mt-1 text-xs text-slate-400">{formatRelative(n.created_at)}</p>
              </div>
            </button>
          ))
        )}
      </div>
    </div>
  )
}
