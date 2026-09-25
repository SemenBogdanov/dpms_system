import { expect, test, type Page } from '@playwright/test'

type HostTheme = 'light' | 'dark' | 'rose'

const themes: HostTheme[] = ['light', 'dark', 'rose']
const frameSelector = 'iframe[title="Рабочее пространство графов"]'
const userId = '11111111-1111-4111-8111-111111111111'
const workspaceKey = `dpms-graphs-workspace-v3:${userId}`
const themeLabels: Record<HostTheme, string> = {
  light: 'Светлая тема',
  dark: 'Темная тема',
  rose: 'Розовая тема',
}

// Synthetic user and API behavior follow graphs-integration.spec.ts.
const testUser = {
  id: userId,
  full_name: 'Проверка графов',
  email: 'graphs-test@example.com',
  league: 'A',
  role: 'executor',
  mpw: 0,
  wip_limit: 5,
  wallet_main: 0,
  wallet_karma: 0,
  quality_score: 100,
  is_active: true,
  is_new_employee: false,
  task_workspace_enabled: false,
  can_link_queue_tasks_to_projects: false,
  feedback_enabled: false,
  audit_enabled: false,
  audit_calendar_enabled: false,
  competency_development_enabled: false,
  competency_constructor_enabled: false,
  plan_started_at: null,
  onboarding_started_at: null,
  onboarding_until: null,
  sidebar_menu_order: null,
  needs_password_change: false,
  created_at: '2026-09-22T00:00:00Z',
  updated_at: '2026-09-22T00:00:00Z',
}

async function installThemeFixture(page: Page, theme: HostTheme) {
  const graphWrites: string[] = []
  await page.addInitScript((initialTheme) => {
    if (window.parent !== window) return
    window.localStorage.setItem('dpms_token', 'graphs-smoke-token')
    window.localStorage.setItem('dpms-theme', initialTheme)
    // A conflicting standalone preference must not override the host theme.
    window.localStorage.setItem('dpms-graphs-theme', initialTheme === 'dark' ? 'light' : 'dark')
  }, theme)
  await page.routeWebSocket('**/api/messages/live', (socket) => {
    socket.onMessage((message) => {
      try {
        const event = JSON.parse(String(message)) as { type?: string }
        socket.send(JSON.stringify({ type: event.type === 'ping' ? 'pong' : 'ready' }))
      } catch {
        socket.close({ code: 1003, reason: 'Malformed synthetic message' })
      }
    })
  })
  await page.route('**/api/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname
    const method = route.request().method()
    let body: unknown = []
    let status = 200
    if (pathname === '/api/auth/me') {
      body = testUser
    } else if (pathname === '/api/messages/summary') {
      body = { direct_count: 0, important_count: 0, revision: 0 }
    } else if (pathname === '/api/graphs' || pathname.startsWith('/api/graphs/')) {
      if (method !== 'GET') {
        graphWrites.push(`${method} ${pathname}`)
        status = 405
        body = { detail: 'Theme changes must not publish or delete graphs' }
      } else if (pathname !== '/api/graphs') {
        status = 404
        body = { detail: { code: 'graph_not_found', message: 'Synthetic graph not found' } }
      }
    }
    await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
  })
  return graphWrites
}

async function openWorkspace(page: Page) {
  await page.goto('/graphs')
  const frame = page.frameLocator(frameSelector)
  await expect(page.locator(frameSelector)).toBeVisible()
  await expect(frame.locator('.app')).toBeVisible()
  await expect(frame.locator('.graph-node')).toHaveCount(4)
  await expect(page.getByRole('status')).toBeHidden()
  return frame
}

async function expectInheritedTheme(page: Page, theme: HostTheme) {
  const frame = page.frameLocator(frameSelector)
  await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
  await expect(frame.locator('html')).toHaveAttribute('data-theme', theme)
  // The standalone control may remain in the DOM, but must not be available when embedded.
  await expect(frame.locator('#themeButton')).toBeHidden()
  await expect(frame.getByRole('button', { name: /Включить (?:светлую|тёмную) тему/ })).toHaveCount(0)
}

async function readPersistedGraph(page: Page) {
  return page.evaluate((key) => {
    const workspace = JSON.parse(window.localStorage.getItem(key) || '{}') as {
      activeGraphId?: string
      graphs?: Array<{ id: string; title: string }>
    }
    const graph = workspace.graphs?.find((item) => item.id === workspace.activeGraphId)
    return graph ? { id: graph.id, title: graph.title } : null
  }, workspaceKey)
}

const profiles = [
  { name: 'desktop', viewport: { width: 1440, height: 900 }, isMobile: false, hasTouch: false },
  { name: 'mobile-touch', viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true },
]

for (const { name, ...options } of profiles) {
  test.describe(`3.1 host theme contract: ${name}`, () => {
    test.use({ baseURL: 'http://localhost:55177', ...options })

    for (const theme of themes) {
      test(`inherits initial ${theme} instead of the standalone preference`, async ({ page }, testInfo) => {
        const graphWrites = await installThemeFixture(page, theme)
        await openWorkspace(page)
        await expectInheritedTheme(page, theme)

        const source = await page.locator(frameSelector).getAttribute('src')
        expect(source).not.toBeNull()
        expect(new URL(source!, page.url()).searchParams.get('theme')).toBe(theme)
        expect(graphWrites).toEqual([])

        const screenshotName = `graphs-theme-${name}-${theme}.png`
        const screenshotPath = testInfo.outputPath(screenshotName)
        await page.screenshot({ path: screenshotPath, fullPage: false, animations: 'disabled' })
        await testInfo.attach(screenshotName, { path: screenshotPath, contentType: 'image/png' })
      })
    }

    test('live DOM and native theme changes preserve the iframe and uncommitted graph title', async ({ page }) => {
      const graphWrites = await installThemeFixture(page, 'light')
      const frame = await openWorkspace(page)
      await expectInheritedTheme(page, 'light')
      // Mobile startup zoom saves asynchronously; let it finish before staging an unsaved title.
      await expect.poll(() => frame.locator('#world').evaluate((world, key) => {
        const workspace = JSON.parse(window.localStorage.getItem(key) || '{}') as {
          activeGraphId?: string
          graphs?: Array<{ id: string; viewport: { x: number; y: number; scale: number } }>
        }
        const viewport = workspace.graphs?.find((item) => item.id === workspace.activeGraphId)?.viewport
        if (!viewport) return false
        const transform = new DOMMatrixReadOnly((world as HTMLElement).style.transform)
        return [
          [viewport.x, transform.e],
          [viewport.y, transform.f],
          [viewport.scale, transform.a],
        ].every(([stored, displayed]) => Math.abs(stored - displayed) < 0.001)
      }, workspaceKey), { message: 'Startup viewport must be persisted before editing' }).toBe(true)
      await expect.poll(() => readPersistedGraph(page)).not.toBeNull()
      const persisted = await readPersistedGraph(page)
      const frameElement = page.locator(frameSelector)
      const source = await frameElement.getAttribute('src')
      expect(source).not.toBeNull()
      const identity = await frameElement.evaluateHandle((element) => {
        const iframe = element as HTMLIFrameElement
        return { element: iframe, window: iframe.contentWindow, document: iframe.contentDocument }
      })
      const title = frame.locator('#graphTitle')
      const draft = `Uncommitted theme draft ${name}`

      try {
        // Do not blur or press Enter: this edit must remain outside persisted graph state.
        await title.fill(draft)
        await expect(title).toBeFocused()
        expect(await readPersistedGraph(page)).toEqual(persisted)
        expect(persisted?.title).not.toBe(draft)

        for (const mode of ['DOM observer', 'native ThemeProvider'] as const) {
          for (const theme of ['dark', 'rose', 'light'] as const) {
            await test.step(`${mode}: ${theme}`, async () => {
              if (mode === 'DOM observer') {
                await page.evaluate((nextTheme) => {
                  document.documentElement.dataset.theme = nextTheme
                }, theme)
              } else {
                // DPMS hides its header on /graphs; dispatch the real control's event without blurring the draft.
                const button = page.getByRole('button', {
                  name: themeLabels[theme], exact: true, includeHidden: true,
                })
                await button.dispatchEvent('click')
                await expect(button).toHaveAttribute('aria-pressed', 'true')
              }

              await expectInheritedTheme(page, theme)
              await page.evaluate(() => new Promise<void>((resolve) => {
                requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
              }))
              await expect(frameElement).toHaveAttribute('src', source!)
              // WindowProxy alone survives navigation, so also compare the element and Document.
              expect(await identity.evaluate((saved, selector) => {
                const current = document.querySelector<HTMLIFrameElement>(selector)
                return {
                  sameElement: current === saved.element,
                  sameWindow: current?.contentWindow === saved.window,
                  sameDocument: current?.contentDocument === saved.document,
                }
              }, frameSelector)).toEqual({ sameElement: true, sameWindow: true, sameDocument: true })
              await expect(title).toHaveValue(draft)
              await expect(title).toBeFocused()
              expect(await readPersistedGraph(page)).toEqual(persisted)
              expect(graphWrites).toEqual([])
            })
          }
        }
      } finally {
        await identity.dispose()
      }
    })
  })
}
