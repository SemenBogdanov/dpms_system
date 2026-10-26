import { readFileSync } from 'node:fs'
import { expect, test, type Page } from '@playwright/test'
import type { KnowledgeArticle } from '../src/api/types'

const hierarchyBody = readFileSync(
  new URL('../../backend/app/content/graphs_hierarchy.md', import.meta.url),
  'utf8'
)
const articleSlug = 'graphs-hierarchy-guide'
const articleTitle = 'Графы: мастер иерархий и работа со структурой'
const articlePath = `/knowledge?article=${articleSlug}`
const frameSelector = 'iframe[title="Рабочее пространство графов"]'
const timestamp = '2026-09-24T00:00:00Z'

// Synthetic identity follows graphs-integration.spec.ts; no real session or API is used.
const testUser = {
  id: '11111111-1111-4111-8111-111111111111',
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
  task_workspace_enabled: true,
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
  created_at: timestamp,
  updated_at: timestamp,
}

const startArticle: KnowledgeArticle = {
  id: '22222222-2222-4222-8222-222222222222',
  slug: 'synthetic-start-article',
  title: 'Начальная статья для проверки выбора',
  summary: 'Первый материал списка, но не цель ссылки из мастера.',
  section: 'start',
  body: 'SYNTHETIC_START_BODY_MUST_NOT_REPLACE_HIERARCHY_GUIDE',
  status: 'published',
  sort_order: 1,
  created_by_id: null,
  updated_by_id: null,
  created_at: timestamp,
  updated_at: timestamp,
  published_at: timestamp,
}

const hierarchyArticle: KnowledgeArticle = {
  ...startArticle,
  id: '33333333-3333-4333-8333-333333333333',
  slug: articleSlug,
  title: articleTitle,
  summary: 'Правила текстовой иерархии, горячие клавиши, дочерние и соседние элементы, отмена, сохранение и ограничения графов.',
  section: 'general',
  body: hierarchyBody,
  sort_order: 100,
}

async function installKnowledgeFixture(page: Page) {
  const stats = { knowledgeGets: 0, writes: [] as string[] }
  let releaseKnowledge!: () => void
  const knowledgeGate = new Promise<void>((resolve) => { releaseKnowledge = resolve })
  await page.addInitScript(() => {
    if (window.parent !== window) return
    window.localStorage.setItem('dpms_token', 'graphs-smoke-token')
    window.localStorage.setItem('dpms-theme', 'light')
  })
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
    if (method !== 'GET') {
      stats.writes.push(`${method} ${pathname}`)
      status = 405
      body = { detail: 'This knowledge navigation fixture is read-only' }
    } else if (pathname === '/api/auth/me') {
      body = testUser
    } else if (pathname === '/api/messages/summary') {
      body = { direct_count: 0, important_count: 0, revision: 0 }
    } else if (pathname === '/api/knowledge') {
      stats.knowledgeGets += 1
      await knowledgeGate
      body = [startArticle, hierarchyArticle]
    }
    await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
  })
  return { stats, releaseKnowledge }
}

function normalizeWhitespace(value: string) {
  return value.replace(/\s+/g, ' ').trim()
}

const expectedHeadings = Array.from(hierarchyBody.matchAll(/^## (.+)$/gm), (match) => match[1].trim())
// Compare all content, ignoring only the document's heading/list markers and whitespace.
const expectedBodyText = normalizeWhitespace(hierarchyBody
  .split(/\r?\n/)
  .map((line) => line.trim().replace(/^(?:##\s+|-\s+|\d+\.\s+)/, ''))
  .join(' '))

const profiles = [
  { name: 'desktop', viewport: { width: 1440, height: 900 }, isMobile: false, hasTouch: false },
  { name: 'mobile-touch', viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true },
]

for (const { name, ...options } of profiles) {
  test.describe(`2.3 hierarchy knowledge deep link: ${name}`, () => {
    test.use({ baseURL: 'http://localhost:55177', ...options })

    test('wizard opens the full hierarchy article after loading, not the first start article', async ({ page }, testInfo) => {
      expect(hierarchyBody.length, 'Use the full published Markdown, not a shortened fixture').toBeGreaterThan(16_000)
      const { stats, releaseKnowledge } = await installKnowledgeFixture(page)
      try {
        await page.goto('/graphs')
        const frame = page.frameLocator(frameSelector)
        await expect(frame.locator('.app')).toBeVisible()
        await expect(page.getByRole('status')).toBeHidden()
        await frame.getByRole('button', { name: 'Мастер иерархий', exact: true }).click()
        const wizard = frame.getByRole('dialog', { name: 'Мастер иерархий', exact: true })
        await expect(wizard).toBeVisible()
        const link = wizard.getByRole('link', { name: 'База знаний', exact: true })
        await expect(link).toHaveAttribute('href', articlePath)
        await expect(link).toHaveAttribute('target', '_top')
        expect(stats.knowledgeGets).toBe(0)

        await link.click()
        await expect(page).toHaveURL((url) => url.pathname === '/knowledge'
          && url.searchParams.get('article') === articleSlug)
        await expect(page.locator(frameSelector)).toHaveCount(0)
        const list = page.locator('#knowledge-article-list')
        await expect(list.getByText('Загрузка...', { exact: true })).toBeVisible()
        await expect.poll(() => stats.knowledgeGets).toBeGreaterThan(0)
        releaseKnowledge()
        await expect(list.getByText('Загрузка...', { exact: true })).toBeHidden()

        await expect(list.getByRole('button')).toHaveCount(2)
        await expect(list.getByRole('button').first()).toContainText(startArticle.title)
        const reader = page.locator('#knowledge-article-reader')
        const heading = reader.getByRole('heading', { name: articleTitle, exact: true, level: 2 })
        await expect(heading).toBeVisible()
        await expect(reader.getByRole('heading', { name: startArticle.title, exact: true })).toHaveCount(0)
        await expect(reader).not.toContainText(startArticle.body)
        const body = reader.locator('article > div')
        await expect(body.getByRole('heading', { level: 2 })).toHaveText(expectedHeadings)
        await expect.poll(async () => normalizeWhitespace(
          (await body.locator('h2, p, li').allTextContents()).join(' ')
        ), { message: 'Every section and paragraph of the source Markdown must reach the reader' }).toBe(expectedBodyText)

        await page.evaluate(() => document.fonts.ready.then(() => undefined))
        await heading.evaluate((element) => element.scrollIntoView({ block: 'start', behavior: 'instant' }))
        await expect(heading).toBeInViewport({ ratio: 1 })
        const widths = await page.evaluate(() => [
          { name: 'document', element: document.documentElement },
          { name: 'main', element: document.querySelector('main.app-main') },
          { name: 'reader', element: document.getElementById('knowledge-article-reader') },
          { name: 'body', element: document.querySelector('#knowledge-article-reader article > div') },
        ].map(({ name, element }) => ({
          name,
          client: element?.clientWidth ?? 0,
          scroll: element?.scrollWidth ?? 0,
        })))
        for (const width of widths) {
          expect(width.client, `${width.name} must be measurable`).toBeGreaterThan(0)
          expect(width.scroll, `${width.name} must not overflow horizontally`).toBeLessThanOrEqual(width.client + 1)
        }
        expect(stats.writes).toEqual([])

        const screenshotName = `graphs-knowledge-${name}.png`
        const screenshotPath = testInfo.outputPath(screenshotName)
        await page.screenshot({ path: screenshotPath, fullPage: false, animations: 'disabled' })
        await testInfo.attach(screenshotName, { path: screenshotPath, contentType: 'image/png' })
      } finally {
        releaseKnowledge()
      }
    })
  })
}
