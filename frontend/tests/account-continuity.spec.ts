import { expect, test, type Page, type Route } from '@playwright/test'

const adminId = '11111111-1111-4111-8111-111111111111'
const employeeId = '22222222-2222-4222-8222-222222222222'
const requestId = '33333333-3333-4333-8333-333333333333'

const admin = {
  id: adminId,
  full_name: 'Тестовый администратор',
  email: 'admin@example.com',
  league: 'A',
  role: 'admin',
  mpw: 0,
  wip_limit: 2,
  wallet_main: 0,
  wallet_karma: 0,
  quality_score: 100,
  is_active: true,
  is_new_employee: false,
  task_workspace_enabled: true,
  can_link_queue_tasks_to_projects: true,
  feedback_enabled: true,
  competency_development_enabled: true,
  competency_constructor_enabled: true,
  plan_started_at: null,
  onboarding_started_at: null,
  onboarding_until: null,
  sidebar_menu_order: null,
  needs_password_change: false,
  temporary_password_expires_at: null,
  created_at: '2026-08-14T08:00:00Z',
  updated_at: '2026-08-14T08:00:00Z',
}

const employee = {
  ...admin,
  id: employeeId,
  full_name: 'Иван Петров',
  email: 'employee@example.com',
  league: 'C',
  role: 'executor',
  task_workspace_enabled: false,
  can_link_queue_tasks_to_projects: false,
  feedback_enabled: false,
  competency_constructor_enabled: false,
}

function pendingRequest(newEmail: string, kind: 'self' | 'admin_assisted') {
  return {
    id: requestId,
    user_id: kind === 'self' ? adminId : employeeId,
    requested_by_id: adminId,
    request_kind: kind,
    old_email: kind === 'self' ? admin.email : employee.email,
    new_email: newEmail,
    status: 'pending',
    reason: kind === 'self' ? null : 'Смена рабочего адреса',
    expires_at: '2026-08-15T08:00:00Z',
    confirmed_at: null,
    cancelled_at: null,
    created_at: '2026-08-14T08:00:00Z',
    updated_at: '2026-08-14T08:00:00Z',
  }
}

async function installApiMock(page: Page) {
  let pending: ReturnType<typeof pendingRequest> | null = null
  await page.addInitScript(() => localStorage.setItem('dpms_token', 'account-continuity-test-token'))
  await page.route('**/api/**', async (route: Route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const method = request.method()
    const respond = (body: unknown, status = 200) => route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(body),
    })

    if (path === '/api/auth/me') return respond(admin)
    if (path === '/api/auth/email-change' && method === 'GET') return respond({ request: pending })
    if (path === '/api/auth/email-change/request' && method === 'POST') {
      const body = request.postDataJSON() as { new_email: string; current_password: string }
      expect(body.current_password).toBeTruthy()
      pending = pendingRequest(body.new_email, 'self')
      return respond(pending)
    }
    if (path === `/api/users/${employeeId}/email-change-request` && method === 'POST') {
      const body = request.postDataJSON() as { new_email: string; reason: string }
      expect(body.reason).toBe('Смена рабочего адреса')
      pending = pendingRequest(body.new_email, 'admin_assisted')
      return respond(pending)
    }
    if (path === '/api/auth/email-change/confirm' && method === 'POST') {
      return respond({ message: 'Email изменён. Войдите с новым адресом.', reauth_required: true })
    }
    if (path === '/api/users/admin') return respond([admin, employee])
    if (path === '/api/admin/period-history') return respond([])
    if (path === '/api/messages/summary') return respond({ direct_count: 0, important_count: 0 })
    if (path === '/api/users') return respond([])
    return respond([])
  })
}

test('self-service email request is protected from accidental modal dismissal', async ({ page }) => {
  await installApiMock(page)
  await page.goto('/settings')

  await page.getByRole('button', { name: 'Изменить email' }).click()
  const dialog = page.getByRole('dialog', { name: 'Изменить email-логин' })
  await expect(dialog).toBeVisible()
  await page.mouse.click(4, 4)
  await expect(dialog).toBeVisible()

  await dialog.getByLabel('Новый email').fill('new-admin@example.com')
  await dialog.getByLabel('Текущий пароль').fill('CurrentPassword123')
  await dialog.getByRole('button', { name: 'Отправить подтверждение' }).click()

  await expect(page.getByText('Ожидает подтверждения')).toBeVisible()
  await expect(page.getByText('new-admin@example.com')).toBeVisible()
})

test('administrator uses a separate reasoned flow and cannot edit login inline', async ({ page }) => {
  await installApiMock(page)
  await page.goto('/admin/users')

  const editButton = page.locator(`button[aria-label="Редактировать ${employee.full_name}"]:visible`)
  await editButton.click()
  const editDialog = page.getByRole('dialog', { name: 'Редактировать сотрудника' })
  await expect(editDialog.getByLabel('Email-логин *')).toHaveAttribute('readonly', '')
  await editDialog.getByRole('button', { name: 'Отмена' }).click()

  await page.locator(`button[aria-label="Изменить email для ${employee.full_name}"]:visible`).click()
  const emailDialog = page.getByRole('dialog', { name: 'Смена email сотрудника' })
  await emailDialog.getByLabel('Новый email').fill('employee.personal@example.com')
  await emailDialog.getByLabel('Причина изменения').fill('Смена рабочего адреса')
  await emailDialog.getByRole('button', { name: 'Запустить подтверждение' }).click()
  await expect(emailDialog).toBeHidden()
})

test('email link strips its fragment and mutates state only after explicit confirmation', async ({ page }) => {
  await installApiMock(page)
  const fakeToken = 'signed-email-change-token-with-safe-length'
  await page.goto(`/email-change#action=confirm&token=${fakeToken}`)

  await expect(page).toHaveURL(/\/email-change$/)
  await expect(page.getByRole('heading', { name: 'Подтвердить новый email?' })).toBeVisible()
  await page.getByRole('button', { name: 'Подтвердить email' }).click()
  await expect(page.getByRole('heading', { name: 'Готово' })).toBeVisible()
})
