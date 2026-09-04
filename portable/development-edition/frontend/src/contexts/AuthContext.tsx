import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api } from '@/api/client'
import type { AuthenticatedUser, SetupStatus } from '@/api/types'
import { clearToken, getToken, setToken } from '@/lib/auth'

type Credentials = { email: string; password: string }
type Bootstrap = Credentials & { full_name: string }

type AuthContextValue = {
  user: AuthenticatedUser | null
  setup: SetupStatus | null
  loading: boolean
  login: (credentials: Credentials) => Promise<void>
  bootstrap: (payload: Bootstrap) => Promise<void>
  logout: () => void
  refreshUser: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthenticatedUser | null>(null)
  const [setup, setSetup] = useState<SetupStatus | null>(null)
  const [loading, setLoading] = useState(true)

  const initialize = useCallback(async () => {
    setLoading(true)
    try {
      const status = await api.get<SetupStatus>('/api/setup/status')
      setSetup(status)
      if (status.setup_required) {
        clearToken()
        setUser(null)
      } else if (getToken()) {
        try {
          setUser(await api.get<AuthenticatedUser>('/api/auth/me'))
        } catch {
          setUser(null)
        }
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void initialize()
  }, [initialize])

  const acceptSession = (response: { access_token: string; user: AuthenticatedUser }) => {
    setToken(response.access_token)
    setUser(response.user)
  }

  const login = async (credentials: Credentials) => {
    const response = await api.post<{ access_token: string; user: AuthenticatedUser }>('/api/auth/login', credentials)
    acceptSession(response)
  }

  const bootstrap = async (payload: Bootstrap) => {
    const response = await api.post<{ access_token: string; user: AuthenticatedUser }>('/api/setup/admin', payload)
    acceptSession(response)
    setSetup((current) => current ? { ...current, setup_required: false } : current)
  }

  const logout = () => {
    clearToken()
    setUser(null)
  }

  const refreshUser = async () => {
    setUser(await api.get<AuthenticatedUser>('/api/auth/me'))
  }

  return (
    <AuthContext.Provider value={{ user, setup, loading, login, bootstrap, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside AuthProvider')
  return value
}
