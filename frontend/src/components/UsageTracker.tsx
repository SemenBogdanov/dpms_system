import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'
import { recordSectionVisit, usageSection } from '@/lib/usageTracking'

export function UsageTracker() {
  const { user } = useAuth()
  const { pathname } = useLocation()
  const section = user ? usageSection(pathname, user) : null
  const userId = user?.id
  useEffect(() => {
    if (!userId || !section) return
    const record = () => {
      if (document.visibilityState === 'visible') void recordSectionVisit(userId, section)
    }
    record()
    document.addEventListener('visibilitychange', record)
    return () => document.removeEventListener('visibilitychange', record)
  }, [userId, section])
  return null
}
