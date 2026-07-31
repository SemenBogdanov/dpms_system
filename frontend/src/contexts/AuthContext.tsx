/**
 * Контекст аутентификации: user из JWT, login, logout.
 * При монтировании: если есть токен — GET /api/auth/me.
 */
import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api } from '@/api/client'
import type { AuthenticatedUser } from '@/api/types'
import { getToken, setToken, clearToken } from '@/lib/auth'

type AuthContextValue = {
  user: AuthenticatedUser | null
  token: string | null
  login: (email: string, password: string) => Promise<void>
  logout: () => void
  updateUser: (user: AuthenticatedUser) => void
  retryAuth: () => Promise<void>
  authError: string | null
  loading: boolean
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthenticatedUser | null>(null)
  const [token, setTokenState] = useState<string | null>(null)
  const [authError, setAuthError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const loadUser = useCallback(async () => {
    setLoading(true)
    setAuthError(null)
    const t = getToken()
    if (!t) {
      setUser(null)
      setTokenState(null)
      setLoading(false)
      return
    }
    setTokenState(t)
    try {
      const u = await api.get<AuthenticatedUser>('/api/auth/me')
      setUser(u)
    } catch (error) {
      setUser(null)
      const remainingToken = getToken()
      if (remainingToken) {
        setTokenState(remainingToken)
        setAuthError(error instanceof Error ? error.message : 'Не удалось проверить сессию')
      } else {
        setTokenState(null)
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadUser()
  }, [loadUser])

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await api.post<{ access_token: string; user: AuthenticatedUser }>('/api/auth/login', {
        email: email.trim().toLowerCase(),
        password,
      })
      setToken(res.access_token)
      setTokenState(res.access_token)
      setUser(res.user)
      setAuthError(null)
    },
    []
  )

  const updateUser = useCallback((updatedUser: AuthenticatedUser) => {
    setUser(updatedUser)
  }, [])

  const logout = useCallback(() => {
    clearToken()
    setTokenState(null)
    setUser(null)
    setAuthError(null)
    window.location.href = '/login'
  }, [])

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        login,
        logout,
        updateUser,
        retryAuth: loadUser,
        authError,
        loading,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
