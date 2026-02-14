import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api } from '@/api/client'
import type { User } from '@/api/types'

const STORAGE_KEY = 'dpms_current_user_id'

type UserContextValue = {
  users: User[]
  currentUserId: string
  setCurrentUserId: (id: string) => void
  currentUser: User | null
}

const UserContext = createContext<UserContextValue | null>(null)

export function UserProvider({ children }: { children: React.ReactNode }) {
  const [users, setUsers] = useState<User[]>([])
  const [currentUserId, setCurrentUserIdState] = useState(() =>
    typeof window !== 'undefined' ? localStorage.getItem(STORAGE_KEY) || '' : ''
  )

  useEffect(() => {
    api.get<User[]>('/api/users').then(setUsers).catch(() => setUsers([]))
  }, [])

  const setCurrentUserId = useCallback((id: string) => {
    setCurrentUserIdState(id)
    try {
      localStorage.setItem(STORAGE_KEY, id)
    } catch {
      // ignore
    }
  }, [])

  useEffect(() => {
    if (users.length && !currentUserId) setCurrentUserId(users[0].id)
  }, [users, currentUserId, setCurrentUserId])

  const currentUser = users.find((u) => u.id === currentUserId) ?? null

  return (
    <UserContext.Provider
      value={{ users, currentUserId, setCurrentUserId, currentUser }}
    >
      {children}
    </UserContext.Provider>
  )
}

export function useUser() {
  const ctx = useContext(UserContext)
  if (!ctx) throw new Error('useUser must be used within UserProvider')
  return ctx
}
