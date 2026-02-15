/**
 * Контекст аутентификации: user из JWT, login, logout.
 * При монтировании: если есть токен — GET /api/auth/me.
 */
import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api } from '@/api/client'
import type { User } from '@/api/types'
import { getToken, setToken, clearToken } from '@/lib/auth'

type AuthContextValue = {
  user: User | null
  token: string | null
  login: (email: string, password: string) => Promise<void>
  logout: () => void
  loading: boolean
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [token, setTokenState] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const loadUser = useCallback(async () => {
    const t = getToken()
    if (!t) {
      setUser(null)
      setTokenState(null)
      setLoading(false)
      return
    }
    setTokenState(t)
    try {
      const u = await api.get<User>('/api/auth/me')
      setUser(u)
    } catch {
      clearToken()
      setTokenState(null)
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadUser()
  }, [loadUser])

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await api.post<{ access_token: string; user: User }>('/api/auth/login', {
        email,
        password,
      })
      setToken(res.access_token)
      setTokenState(res.access_token)
      setUser(res.user)
    },
    []
  )

  const logout = useCallback(() => {
    clearToken()
    setTokenState(null)
    setUser(null)
    window.location.href = '/login'
  }, [])

  return (
    <AuthContext.Provider value={{ user, token, login, logout, loading }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
