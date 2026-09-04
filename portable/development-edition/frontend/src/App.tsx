import { useState } from 'react'
import { LogOut, Users } from 'lucide-react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { AdminUsersDialog } from '@/components/AdminUsersDialog'
import { useAuth } from '@/contexts/AuthContext'
import { CompetenciesPage } from '@/pages/CompetenciesPage'
import { LoginPage } from '@/pages/LoginPage'
import { SetupPage } from '@/pages/SetupPage'

function Loading() {
  return <div className="flex min-h-screen items-center justify-center bg-slate-50 text-sm text-slate-500">Загрузка...</div>
}

function Workspace() {
  const { user, logout } = useAuth()
  const [usersOpen, setUsersOpen] = useState(false)
  if (!user) return <Navigate to="/login" replace />

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-[1560px] items-center justify-between px-4 sm:px-6">
          <div className="flex min-w-0 items-center gap-4">
            <img src="/logo_prosto_sdelal.png" alt="ПРОСТО СДЕЛАЛ.РФ" className="h-9 w-auto" />
            <span className="hidden h-6 w-px bg-slate-200 sm:block" />
            <span className="truncate text-sm font-semibold text-slate-800">Развитие</span>
          </div>
          <div className="flex items-center gap-2">
            {user.role === 'admin' && (
              <button type="button" onClick={() => setUsersOpen(true)} aria-label="Сотрудники" title="Сотрудники" className="inline-flex h-9 items-center gap-2 rounded-md border border-slate-200 px-3 text-sm font-medium text-slate-700 hover:bg-slate-50">
                <Users className="h-4 w-4" />
                <span className="hidden sm:inline">Сотрудники</span>
              </button>
            )}
            <button type="button" onClick={logout} aria-label="Выйти" title="Выйти" className="flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 text-slate-500 hover:bg-slate-50 hover:text-slate-800">
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-[1560px] px-4 py-5 sm:px-6">
        <Routes>
          <Route path="/competencies/assignments/:assignmentId" element={<CompetenciesPage />} />
          <Route path="*" element={<CompetenciesPage />} />
        </Routes>
      </main>
      <AdminUsersDialog open={usersOpen} currentUserId={user.id} onClose={() => setUsersOpen(false)} />
    </div>
  )
}

export default function App() {
  const { user, setup, loading } = useAuth()
  if (loading || !setup) return <Loading />
  if (setup.setup_required) return <SetupPage />
  if (!user) return <LoginPage />
  return <Workspace />
}
