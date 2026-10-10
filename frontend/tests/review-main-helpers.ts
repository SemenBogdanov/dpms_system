import { type Page, type Route } from '@playwright/test'

export const user = {
  id: '11111111-1111-4111-8111-111111111111', full_name: 'Проверка пользователя', email: 'review@example.invalid',
  role: 'admin', league: 'A', mpw: 0, wip_limit: 5, wallet_main: 0, wallet_karma: 0, quality_score: 1,
  is_active: true, needs_password_change: false, task_workspace_enabled: true, audit_enabled: true,
  audit_calendar_enabled: true, sidebar_menu_order: null,
}
export const stamp = '2026-10-03T08:00:00Z'
export const article = (slug: string) => ({
  id: slug, slug, title: 'Статья ' + slug, summary: '', section: 'general', body: 'Текст статьи ' + slug,
  status: 'draft', sort_order: 1, created_by_id: user.id, updated_by_id: user.id,
  created_at: stamp, updated_at: stamp, published_at: null,
})
export async function fixture(page: Page, handler: (route: Route, url: URL) => Promise<boolean>) {
  await page.addInitScript(() => {
    localStorage.setItem('dpms_token', 'synthetic-review-remediation')
    localStorage.setItem('dpms-theme', 'light')
  })
  await page.routeWebSocket('**', (socket) => { socket.onMessage(() => socket.send(JSON.stringify({ type: 'ready' }))) })
  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url())
    if (url.origin !== 'http://localhost:55177') return route.abort()
    if (!url.pathname.startsWith('/api/')) return route.continue()
    if (await handler(route, url)) return
    const path = url.pathname
    if (path === '/api/auth/me') return route.fulfill({ json: user })
    if (path === '/api/users') return route.fulfill({ json: [user] })
    if (path === '/api/messages/summary') return route.fulfill({ json: { direct_count: 0, important_count: 0, revision: 0 } })
    if (path === '/api/web-push/config') return route.fulfill({ json: { available: false } })
    if (path.startsWith('/api/usage/') || path.startsWith('/api/client-events')) return route.fulfill({ json: {} })
    if (route.request().method() !== 'GET') return route.fulfill({ status: 405, json: { detail: 'Unexpected synthetic mutation' } })
    return route.fulfill({ json: [] })
  })
}
