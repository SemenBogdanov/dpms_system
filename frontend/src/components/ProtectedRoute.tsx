import { Navigate, useLocation } from 'react-router-dom'
import { AuthConnectionError } from '@/components/AuthConnectionError'
import { useAuth } from '@/contexts/AuthContext'

/**
 * Редирект на /login, если пользователь не авторизован.
 */
export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, token, authError, retryAuth, loading } = useAuth()
  const location = useLocation()

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50">
        <p className="text-slate-500">Загрузка...</p>
      </div>
    )
  }

  if (authError && token) {
    return <AuthConnectionError message={authError} onRetry={() => void retryAuth()} />
  }

  if (!user) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  if (user.needs_password_change) {
    return <Navigate to="/set-password" replace />
  }

  return <>{children}</>
}
