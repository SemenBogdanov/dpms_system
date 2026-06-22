import { Routes, Route, Navigate } from 'react-router-dom'
import type { ReactElement } from 'react'
import { Layout } from '@/components/Layout'
import { ProtectedRoute } from '@/components/ProtectedRoute'
import { useAuth } from '@/contexts/AuthContext'
import { LoginPage } from '@/pages/LoginPage'
import { DashboardPage } from '@/pages/DashboardPage'
import { QueuePage } from '@/pages/QueuePage'
import { MyTasksPage } from '@/pages/MyTasksPage'
import { CalculatorPage } from '@/pages/CalculatorPage'
import { ProfilePage } from '@/pages/ProfilePage'
import { ShopPage } from '@/pages/ShopPage'
import { AdminUsersPage } from '@/pages/AdminUsersPage'
import { CatalogPage } from '@/pages/CatalogPage'
import { KnowledgePage } from '@/pages/KnowledgePage'
import { AbsencesPage } from '@/pages/AbsencesPage'
import { CalibrationPage } from '@/pages/CalibrationPage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { ReportsPage } from '@/pages/ReportsPage'
import { SetPasswordPage } from '@/pages/SetPasswordPage'
import { FeedbackPage } from '@/pages/FeedbackPage'
import { CompetenciesPage } from '@/pages/CompetenciesPage'
import {
  firstAvailablePath,
  hasDevelopmentAccess,
  hasFeedbackAccess,
  hasTaskWorkspaceAccess,
} from '@/lib/access'

function DashboardRoute() {
  const { user } = useAuth()
  if (!hasTaskWorkspaceAccess(user)) {
    return <Navigate to={firstAvailablePath(user)} replace />
  }
  if (user?.role === 'executor') {
    return <Navigate to="/my-tasks" replace />
  }
  return <DashboardPage />
}

function TaskWorkspaceRoute({ children }: { children: ReactElement }) {
  const { user } = useAuth()
  if (!hasTaskWorkspaceAccess(user)) {
    return <Navigate to={firstAvailablePath(user)} replace />
  }
  return children
}

function TeamleadAdminRoute({ children }: { children: ReactElement }) {
  const { user } = useAuth()
  if (!hasTaskWorkspaceAccess(user)) {
    return <Navigate to={firstAvailablePath(user)} replace />
  }
  if (user?.role !== 'teamlead' && user?.role !== 'admin') {
    return <Navigate to={firstAvailablePath(user)} replace />
  }
  return children
}

function AdminRoute({ children }: { children: ReactElement }) {
  const { user } = useAuth()
  if (user?.role !== 'admin') {
    return <Navigate to={firstAvailablePath(user)} replace />
  }
  return children
}

function FeedbackAccessRoute({ children }: { children: ReactElement }) {
  const { user } = useAuth()
  if (!hasFeedbackAccess(user)) {
    return <Navigate to={firstAvailablePath(user)} replace />
  }
  return children
}

function CompetenciesAccessRoute({ children }: { children: ReactElement }) {
  const { user } = useAuth()
  if (!hasDevelopmentAccess(user)) {
    return <Navigate to={firstAvailablePath(user)} replace />
  }
  return children
}

function NoAccessPage() {
  return (
    <div className="mx-auto flex min-h-[60vh] max-w-xl flex-col justify-center">
      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="text-xl font-semibold text-slate-900">Нет открытых разделов</h1>
        <p className="mt-2 text-sm text-slate-500">
          Доступ в систему создан, но администратор еще не включил для пользователя рабочие разделы.
        </p>
      </div>
    </div>
  )
}

function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/set-password" element={<SetPasswordPage />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route index element={<DashboardRoute />} />
        <Route
          path="calibration"
          element={
            <AdminRoute>
              <CalibrationPage />
            </AdminRoute>
          }
        />
        <Route path="queue" element={<TaskWorkspaceRoute><QueuePage /></TaskWorkspaceRoute>} />
        <Route path="my-tasks" element={<TaskWorkspaceRoute><MyTasksPage /></TaskWorkspaceRoute>} />
        <Route
          path="calculator"
          element={
            <TeamleadAdminRoute>
              <CalculatorPage />
            </TeamleadAdminRoute>
          }
        />
        <Route path="profile" element={<TaskWorkspaceRoute><ProfilePage /></TaskWorkspaceRoute>} />
        <Route path="shop" element={<TaskWorkspaceRoute><ShopPage /></TaskWorkspaceRoute>} />
        <Route
          path="feedback"
          element={
            <FeedbackAccessRoute>
              <FeedbackPage />
            </FeedbackAccessRoute>
          }
        />
        <Route
          path="competencies"
          element={
            <CompetenciesAccessRoute>
              <CompetenciesPage />
            </CompetenciesAccessRoute>
          }
        />
        <Route
          path="competencies/assignments/:assignmentId"
          element={
            <CompetenciesAccessRoute>
              <CompetenciesPage />
            </CompetenciesAccessRoute>
          }
        />
        <Route
          path="admin/users"
          element={
            <AdminRoute>
              <AdminUsersPage />
            </AdminRoute>
          }
        />
        <Route
          path="absences"
          element={
            <TeamleadAdminRoute>
              <AbsencesPage />
            </TeamleadAdminRoute>
          }
        />
        <Route path="catalog" element={<TaskWorkspaceRoute><CatalogPage /></TaskWorkspaceRoute>} />
        <Route path="knowledge" element={<TaskWorkspaceRoute><KnowledgePage /></TaskWorkspaceRoute>} />
        <Route
          path="reports"
          element={
            <TeamleadAdminRoute>
              <ReportsPage />
            </TeamleadAdminRoute>
          }
        />
        <Route path="no-access" element={<NoAccessPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}

export default App
