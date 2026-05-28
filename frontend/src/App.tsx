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

function DashboardRoute() {
  const { user } = useAuth()
  if (user?.role === 'executor') {
    return <Navigate to="/my-tasks" replace />
  }
  return <DashboardPage />
}

function TeamleadAdminRoute({ children }: { children: ReactElement }) {
  const { user } = useAuth()
  if (user?.role !== 'teamlead' && user?.role !== 'admin') {
    return <Navigate to="/queue" replace />
  }
  return children
}

function AdminRoute({ children }: { children: ReactElement }) {
  const { user } = useAuth()
  if (user?.role !== 'admin') {
    return <Navigate to="/queue" replace />
  }
  return children
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
        <Route path="queue" element={<QueuePage />} />
        <Route path="my-tasks" element={<MyTasksPage />} />
        <Route
          path="calculator"
          element={
            <TeamleadAdminRoute>
              <CalculatorPage />
            </TeamleadAdminRoute>
          }
        />
        <Route path="profile" element={<ProfilePage />} />
        <Route path="shop" element={<ShopPage />} />
        <Route path="feedback" element={<FeedbackPage />} />
        <Route path="admin/users" element={<AdminUsersPage />} />
        <Route
          path="absences"
          element={
            <TeamleadAdminRoute>
              <AbsencesPage />
            </TeamleadAdminRoute>
          }
        />
        <Route path="catalog" element={<CatalogPage />} />
        <Route path="knowledge" element={<KnowledgePage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}

export default App
