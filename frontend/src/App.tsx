import { Suspense, lazy } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import type { ComponentType, ReactElement } from 'react'
import { Layout } from '@/components/Layout'
import { ProtectedRoute } from '@/components/ProtectedRoute'
import { SkeletonCard } from '@/components/Skeleton'
import { useAuth } from '@/contexts/AuthContext'
import {
  firstAvailablePath,
  hasDevelopmentAccess,
  hasFeedbackAccess,
  hasTaskWorkspaceAccess,
} from '@/lib/access'

function lazyPage<T extends ComponentType<object>>(loader: () => Promise<Record<string, T>>, exportName: string) {
  return lazy(async () => {
    const mod = await loader()
    return { default: mod[exportName] }
  })
}

const LoginPage = lazyPage(() => import('@/pages/LoginPage'), 'LoginPage')
const DashboardPage = lazyPage(() => import('@/pages/DashboardPage'), 'DashboardPage')
const QueuePage = lazyPage(() => import('@/pages/QueuePage'), 'QueuePage')
const MyTasksPage = lazyPage(() => import('@/pages/MyTasksPage'), 'MyTasksPage')
const CalculatorPage = lazyPage(() => import('@/pages/CalculatorPage'), 'CalculatorPage')
const ProfilePage = lazyPage(() => import('@/pages/ProfilePage'), 'ProfilePage')
const ShopPage = lazyPage(() => import('@/pages/ShopPage'), 'ShopPage')
const AdminUsersPage = lazyPage(() => import('@/pages/AdminUsersPage'), 'AdminUsersPage')
const CatalogPage = lazyPage(() => import('@/pages/CatalogPage'), 'CatalogPage')
const KnowledgePage = lazyPage(() => import('@/pages/KnowledgePage'), 'KnowledgePage')
const AbsencesPage = lazyPage(() => import('@/pages/AbsencesPage'), 'AbsencesPage')
const CalibrationPage = lazyPage(() => import('@/pages/CalibrationPage'), 'CalibrationPage')
const NotFoundPage = lazyPage(() => import('@/pages/NotFoundPage'), 'NotFoundPage')
const ReportsPage = lazyPage(() => import('@/pages/ReportsPage'), 'ReportsPage')
const SetPasswordPage = lazyPage(() => import('@/pages/SetPasswordPage'), 'SetPasswordPage')
const FeedbackPage = lazyPage(() => import('@/pages/FeedbackPage'), 'FeedbackPage')
const CompetenciesPage = lazyPage(() => import('@/pages/CompetenciesPage'), 'CompetenciesPage')
const SettingsPage = lazyPage(() => import('@/pages/SettingsPage'), 'SettingsPage')
const QuickNotesPage = lazyPage(() => import('@/pages/QuickNotesPage'), 'QuickNotesPage')
const PersonalTasksPage = lazyPage(() => import('@/pages/PersonalTasksPage'), 'PersonalTasksPage')
const DeadlineTrackersPage = lazyPage(() => import('@/pages/DeadlineTrackersPage'), 'DeadlineTrackersPage')

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

function RouteFallback() {
  return (
    <div className="mx-auto w-full max-w-5xl space-y-3 p-4">
      <SkeletonCard />
      <SkeletonCard />
    </div>
  )
}

function App() {
  return (
    <Suspense fallback={<RouteFallback />}>
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
        <Route path="settings" element={<SettingsPage />} />
        <Route path="quick-notes" element={<QuickNotesPage />} />
        <Route path="personal-tasks" element={<PersonalTasksPage />} />
        <Route path="deadline-trackers" element={<DeadlineTrackersPage />} />
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
    </Suspense>
  )
}

export default App
