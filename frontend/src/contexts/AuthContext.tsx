/**
 * Контекст аутентификации: user из JWT, login, logout.
 * При монтировании: если есть токен — GET /api/auth/me.
 */
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
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
  const profileRevision = useRef(0)

  const loadUser = useCallback(async (silent = false) => {
    const revision = ++profileRevision.current
    if (!silent) setLoading(true)
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
      // Focus, visibility and polling can overlap; never restore stale grants.
      if (revision !== profileRevision.current || getToken() !== t) return
      setUser(u)
    } catch (error) {
      if (revision !== profileRevision.current) return
      const remainingToken = getToken()
      if (remainingToken && remainingToken !== t) return
      setUser(null)
      if (remainingToken) {
        setTokenState(remainingToken)
        setAuthError(error instanceof Error ? error.message : 'Не удалось проверить сессию')
      } else {
        setTokenState(null)
      }
    } finally {
      if (revision === profileRevision.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadUser()
    return () => { profileRevision.current += 1 }
  }, [loadUser])

  useEffect(() => {
    const refreshAccess = () => {
      if (document.visibilityState === 'visible' && getToken()) void loadUser(true)
    }
    window.addEventListener('focus', refreshAccess)
    document.addEventListener('visibilitychange', refreshAccess)
    const timer = window.setInterval(refreshAccess, 60_000)
    return () => {
      window.removeEventListener('focus', refreshAccess)
      document.removeEventListener('visibilitychange', refreshAccess)
      window.clearInterval(timer)
    }
  }, [loadUser])

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await api.post<{ access_token: string; user: AuthenticatedUser }>('/api/auth/login', {
        email: email.trim().toLowerCase(),
        password,
      })
      profileRevision.current += 1
      setToken(res.access_token)
      setTokenState(res.access_token)
      setUser(res.user)
      setAuthError(null)
      setLoading(false)
    },
    []
  )

  const updateUser = useCallback((updatedUser: AuthenticatedUser) => {
    profileRevision.current += 1
    setUser(updatedUser)
    setLoading(false)
  }, [])

  const logout = useCallback(() => {
    profileRevision.current += 1
    clearToken()
    setTokenState(null)
    setUser(null)
    setAuthError(null)
    setLoading(false)
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
        retryAuth: () => loadUser(false),
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
