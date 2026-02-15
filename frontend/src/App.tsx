import { Routes, Route, Navigate } from 'react-router-dom'
import { Layout } from '@/components/Layout'
import { ProtectedRoute } from '@/components/ProtectedRoute'
import { LoginPage } from '@/pages/LoginPage'
import { DashboardPage } from '@/pages/DashboardPage'
import { QueuePage } from '@/pages/QueuePage'
import { MyTasksPage } from '@/pages/MyTasksPage'
import { CalculatorPage } from '@/pages/CalculatorPage'
import { ProfilePage } from '@/pages/ProfilePage'
import { ShopPage } from '@/pages/ShopPage'
import { AdminUsersPage } from '@/pages/AdminUsersPage'
import { CatalogPage } from '@/pages/CatalogPage'
import { CalibrationPage } from '@/pages/CalibrationPage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { ReportsPage } from '@/pages/ReportsPage'

function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="calibration" element={<CalibrationPage />} />
        <Route path="queue" element={<QueuePage />} />
        <Route path="my-tasks" element={<MyTasksPage />} />
        <Route path="calculator" element={<CalculatorPage />} />
        <Route path="profile" element={<ProfilePage />} />
        <Route path="shop" element={<ShopPage />} />
        <Route path="admin/users" element={<AdminUsersPage />} />
        <Route path="catalog" element={<CatalogPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}

export default App
