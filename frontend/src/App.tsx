import { Routes, Route, Navigate } from 'react-router-dom'
import { Layout } from '@/components/Layout'
import { DashboardPage } from '@/pages/DashboardPage'
import { QueuePage } from '@/pages/QueuePage'
import { MyTasksPage } from '@/pages/MyTasksPage'
import { CalculatorPage } from '@/pages/CalculatorPage'
import { ProfilePage } from '@/pages/ProfilePage'
import { AdminUsersPage } from '@/pages/AdminUsersPage'
import { CatalogPage } from '@/pages/CatalogPage'

function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="queue" element={<QueuePage />} />
        <Route path="my-tasks" element={<MyTasksPage />} />
        <Route path="calculator" element={<CalculatorPage />} />
        <Route path="profile" element={<ProfilePage />} />
        <Route path="admin/users" element={<AdminUsersPage />} />
        <Route path="catalog" element={<CatalogPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}

export default App
