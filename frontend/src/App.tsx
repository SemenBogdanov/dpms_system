import { lazy } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import type { ComponentType, ReactElement } from 'react'
import { Layout } from '@/components/Layout'
import { ProtectedRoute } from '@/components/ProtectedRoute'
import { useAuth } from '@/contexts/AuthContext'
import {
  firstAvailablePath,
  hasAuditAccess,
  hasDevelopmentAccess,
  hasFeedbackAccess,
  hasTaskWorkspaceAccess,
} from '@/lib/access'
import { reportClientEvent } from '@/lib/clientDiagnostics'
import { LoginPage } from '@/pages/LoginPage'
import { SetPasswordPage } from '@/pages/SetPasswordPage'

const CHUNK_RELOAD_WINDOW_MS = 45_000

function isModuleLoadFailure(message: string) {
  return /failed to fetch dynamically imported module|importing a module script failed|error loading dynamically imported module|unable to preload css|chunkloaderror|load failed/i.test(message)
}

function lazyPage<T extends ComponentType<object>>(loader: () => Promise<Record<string, T>>, exportName: string) {
  return lazy(async () => {
    const reloadKey = `dpms:chunk-reload:${exportName}`
    try {
      const mod = await loader()
      try {
        sessionStorage.removeItem(reloadKey)
      } catch {
        // Storage can be unavailable in restrictive browser modes.
      }
      return { default: mod[exportName] }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      if (isModuleLoadFailure(message)) {
        reportClientEvent({
          event_type: 'route_module_load_failed',
          message,
          name: exportName,
          stack: error instanceof Error ? error.stack : undefined,
        })
        try {
          const lastReload = Number(sessionStorage.getItem(reloadKey) || 0)
          if (!lastReload || Date.now() - lastReload > CHUNK_RELOAD_WINDOW_MS) {
            sessionStorage.setItem(reloadKey, String(Date.now()))
            const nextUrl = new URL(window.location.href)
            nextUrl.searchParams.set('dpms_reload', String(Date.now()))
            window.location.replace(nextUrl.toString())
            return await new Promise<never>((_, reject) => {
              window.setTimeout(() => reject(error), 4_000)
            })
          }
        } catch {
          // Avoid an uncontrolled reload loop when sessionStorage is unavailable.
        }
        throw new Error(`Не удалось загрузить раздел «${exportName}». Обновите страницу и повторите попытку.`)
      }

      throw error
    }
  })
}

const DashboardPage = lazyPage(() => import('@/pages/DashboardPage'), 'DashboardPage')
const QueuePage = lazyPage(() => import('@/pages/QueuePage'), 'QueuePage')
const MyTasksPage = lazyPage(() => import('@/pages/MyTasksPage'), 'MyTasksPage')
const CalculatorPage = lazyPage(() => import('@/pages/CalculatorPage'), 'CalculatorPage')
const ProfilePage = lazyPage(() => import('@/pages/ProfilePage'), 'ProfilePage')
const ShopPage = lazyPage(() => import('@/pages/ShopPage'), 'ShopPage')
const AdminUsersPage = lazyPage(() => import('@/pages/AdminUsersPage'), 'AdminUsersPage')
const AdminIntegrationsPage = lazyPage(() => import('@/pages/AdminIntegrationsPage'), 'AdminIntegrationsPage')
const CatalogPage = lazyPage(() => import('@/pages/CatalogPage'), 'CatalogPage')
const KnowledgePage = lazyPage(() => import('@/pages/KnowledgePage'), 'KnowledgePage')
const AbsencesPage = lazyPage(() => import('@/pages/AbsencesPage'), 'AbsencesPage')
const CalibrationPage = lazyPage(() => import('@/pages/CalibrationPage'), 'CalibrationPage')
const NotFoundPage = lazyPage(() => import('@/pages/NotFoundPage'), 'NotFoundPage')
const ReportsPage = lazyPage(() => import('@/pages/ReportsPage'), 'ReportsPage')
const FeedbackPage = lazyPage(() => import('@/pages/FeedbackPage'), 'FeedbackPage')
const CompetenciesPage = lazyPage(() => import('@/pages/CompetenciesPage'), 'CompetenciesPage')
const SettingsPage = lazyPage(() => import('@/pages/SettingsPage'), 'SettingsPage')
const WorkEntitiesPage = lazyPage(() => import('@/pages/WorkEntitiesPage'), 'WorkEntitiesPage')
const AuditPage = lazyPage(() => import('@/pages/AuditPage'), 'AuditPage')
const ContactsPage = lazyPage(() => import('@/pages/ContactsPage'), 'ContactsPage')
const MessagesPage = lazyPage(() => import('@/pages/MessagesPage'), 'MessagesPage')
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

function AuditAccessRoute({ children }: { children: ReactElement }) {
  const { user } = useAuth()
  if (!hasAuditAccess(user)) {
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
        <Route path="settings" element={<SettingsPage />} />
        <Route path="contacts" element={<ContactsPage />} />
        <Route path="messages" element={<MessagesPage />} />
        <Route path="messages/:threadId" element={<MessagesPage />} />
        <Route path="quick-notes" element={<QuickNotesPage />} />
        <Route path="quick-notes/:noteId" element={<QuickNotesPage />} />
        <Route path="personal-tasks" element={<PersonalTasksPage />} />
        <Route path="deadline-trackers" element={<DeadlineTrackersPage />} />
        <Route path="work-entities" element={<TaskWorkspaceRoute><WorkEntitiesPage /></TaskWorkspaceRoute>} />
        <Route path="audit" element={<AuditAccessRoute><AuditPage /></AuditAccessRoute>} />
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
          path="admin/integrations"
          element={
            <AdminRoute>
              <AdminIntegrationsPage />
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
