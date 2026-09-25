import { expect, test, type Page } from '@playwright/test'
import { readFile } from 'node:fs/promises'

type Theme = 'light' | 'dark' | 'rose'
type Role = 'admin' | 'teamlead' | 'executor'
const timestamp = '2026-09-25T08:00:00Z'
const testUser = {
  id: '11111111-1111-4111-8111-111111111111',
  full_name: 'Проверка базы знаний', email: 'knowledge@example.invalid',
  league: 'A', mpw: 0, wip_limit: 5, wallet_main: 0, wallet_karma: 0, quality_score: 100,
  is_active: true, is_new_employee: false, needs_password_change: false,
  task_workspace_enabled: true, can_link_queue_tasks_to_projects: false,
  feedback_enabled: false, audit_enabled: false, audit_calendar_enabled: false,
  competency_development_enabled: false, competency_constructor_enabled: false,
  plan_started_at: null, onboarding_started_at: null, onboarding_until: null,
  sidebar_menu_order: null, created_at: timestamp, updated_at: timestamp,
}

const python = [
  'import json',
  '',
  'def record_boot():',
  '\tpayload = {"reason": "unknown"}  ',
  '\tif payload:',
  '        print(json.dumps(payload))',
  '',
  'record_boot()',
  '',
].join('\n')
const systemd = '[Unit]\nDescription=Boot journal fixture\n\n[Service]\nType=oneshot\nExecStart=/usr/bin/true\n\n[Install]\nWantedBy=multi-user.target\n'
const articleBody = `## Запись загрузки\n\nВводный абзац\nна второй строке.\n\n- До скрипта\n\n\`\`\`python\n${python}\`\`\`\n\n1. После скрипта\n\n\`\`\`systemd\n${systemd}\`\`\`\n\n## Проверка\n\nЗавершающий абзац.`

async function fixture(page: Page, body: string, options: { theme?: Theme; role?: Role } = {}) {
  const state = { writes: [] as string[], pageErrors: [] as string[] }
  page.on('pageerror', (error) => state.pageErrors.push(error.message))
  await page.addInitScript((theme) => {
    // Synthetic marker in a disposable context, never a saved browser session.
    window.localStorage.setItem('dpms_token', 'knowledge-code-fixture-only')
    window.localStorage.setItem('dpms-theme', theme)
  }, options.theme ?? 'light')
  await page.route('**/*', async (route) => {
    if (new URL(route.request().url()).origin !== 'http://localhost:55177') {
      await route.abort()
      return
    }
    await route.continue()
  })
  await page.routeWebSocket('**/api/messages/live', (socket) => {
    socket.onMessage(() => socket.send(JSON.stringify({ type: 'ready' })))
  })
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const pathname = new URL(request.url()).pathname
    if (request.method() !== 'GET') {
      state.writes.push(`${request.method()} ${pathname}`)
      await route.fulfill({ status: 405, json: { detail: 'Read-only fixture' } })
      return
    }
    let json: unknown = []
    if (pathname === '/api/auth/me') json = { ...testUser, role: options.role ?? 'admin' }
    if (pathname === '/api/messages/summary') json = { direct_count: 0, important_count: 0, revision: 0 }
    if (pathname === '/api/knowledge') json = [{
      id: '22222222-2222-4222-8222-222222222222', slug: 'boot-code-fixture',
      title: 'Журнал загрузок сервера', summary: 'Тестовая статья', section: 'general',
      body, status: 'published', sort_order: 1,
      created_by_id: testUser.id, updated_by_id: testUser.id,
      created_at: timestamp, updated_at: timestamp, published_at: timestamp,
    }]
    await route.fulfill({ status: 200, json })
  })
  await page.goto('/knowledge')
  await expect(page.locator('#knowledge-article-reader').getByRole('heading', { name: 'Журнал загрузок сервера', exact: true })).toBeVisible()
  return state
}

function codeBlock(page: Page, index = 1) {
  return page.getByRole('region', { name: `Блок кода ${index}`, exact: true })
}

test('real boot journal guide preserves every complete listing', async ({ page }) => {
  const body = await readFile(new URL('../../docs/stability/BOOT-JOURNAL-GUIDE.md', import.meta.url), 'utf8')
  const listings = [...body.matchAll(/^```(python|ini|bash|text)\r?\n([\s\S]*?)^```[\t ]*$/gm)]
  expect(listings.map((match) => match[1])).toEqual(expect.arrayContaining(['python', 'ini', 'bash']))
  const state = await fixture(page, body)
  await expect(page.locator('#knowledge-article-reader pre code')).toHaveCount(listings.length)
  for (const [index, listing] of listings.entries()) {
    expect(await codeBlock(page, index + 1).locator('code').textContent()).toBe(listing[2])
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  expect(state.writes).toEqual([])
  expect(state.pageErrors).toEqual([])
})

test('Python and systemd preserve exact whitespace and surrounding prose', async ({ page }) => {
  const state = await fixture(page, articleBody)
  await expect(page.locator('#knowledge-article-reader pre code')).toHaveCount(2)
  expect(await codeBlock(page).locator('code').textContent()).toBe(python)
  expect(await codeBlock(page, 2).locator('code').textContent()).toBe(systemd)
  const reader = page.locator('#knowledge-article-reader')
  await expect(reader.getByText('Вводный абзац на второй строке.', { exact: true })).toBeVisible()
  await expect(reader.locator('ul li')).toHaveText(['До скрипта'])
  await expect(reader.locator('ol li')).toHaveText(['После скрипта'])
  await expect(reader.getByRole('heading', { name: 'Проверка', exact: true })).toBeVisible()
  await expect(reader.getByText('Завершающий абзац.', { exact: true })).toBeVisible()
  expect(state.writes).toEqual([])
  expect(state.pageErrors).toEqual([])
})

test('only the matching fence length closes code, including embedded Markdown', async ({ page }) => {
  const content = '## Not a heading\n- Not a list\n1. Still code\n```\n`````\n````suffix\n\tlast line\n'
  await fixture(page, `Before\n\n\`\`\`\`python\n${content}\`\`\`\`\n\nAfter`)
  expect(await codeBlock(page).locator('code').textContent()).toBe(content)
  const reader = page.locator('#knowledge-article-reader')
  await expect(reader.locator('pre')).toHaveCount(1)
  await expect(reader.getByText('After', { exact: true })).toBeVisible()
  await expect(reader.locator('ul, ol')).toHaveCount(0)
  await expect(reader.getByRole('heading', { name: 'Not a heading' })).toHaveCount(0)
})

for (const [name, body, expected] of [
  ['unclosed without final newline', '```python\n\n\tvalue = 1  \n\nlast', '\n\tvalue = 1  \n\nlast'],
  ['unclosed with final newline', '```python\n\tvalue = 1\n', '\tvalue = 1\n'],
  ['empty unclosed', '```', ''],
  ['empty closed', '```\n```', ''],
  ['CRLF and indented fences', '  ```python\r\n\tvalue = 1  \r\n\r\n  ``` \t\r\n', '\tvalue = 1  \r\n\r\n'],
] as const) {
  test(`preserves ${name}`, async ({ page }) => {
    await fixture(page, body)
    await expect(codeBlock(page)).toBeVisible()
    expect(await codeBlock(page).locator('code').textContent()).toBe(expected)
  })
}

test('HTML, entities and info strings remain inert React text', async ({ page }) => {
  const html = '<script>document.documentElement.dataset.codeExecuted = "yes"</script>\n<img src="/code-fixture-image" onerror="document.documentElement.dataset.codeExecuted = \'yes\'">\n</code></pre><div>not markup</div>\n&lt;literal&gt; & value < other\n'
  const state = await fixture(page, `\`\`\`<img src=/code-info-image>\n${html}\`\`\`\n\n<strong>Plain prose</strong>`)
  expect(await codeBlock(page).locator('code').textContent()).toBe(html)
  const reader = page.locator('#knowledge-article-reader')
  await expect(reader.locator('script, img, strong')).toHaveCount(0)
  await expect(reader.getByText('<strong>Plain prose</strong>', { exact: true })).toBeVisible()
  expect(await page.locator('html').getAttribute('data-code-executed')).toBeNull()
  expect(state.pageErrors).toEqual([])
})

test('short backticks and inline backticks keep existing prose behavior', async ({ page }) => {
  await fixture(page, '``\nplain text\n\nInline `value` remains text.\n\n## Heading\n\n- One\n- Two\n\n1. First\n2. Second')
  const reader = page.locator('#knowledge-article-reader')
  await expect(reader.locator('pre')).toHaveCount(0)
  await expect(reader.getByText('`` plain text', { exact: true })).toBeVisible()
  await expect(reader.getByText('Inline `value` remains text.', { exact: true })).toBeVisible()
  await expect(reader.locator('ul li')).toHaveText(['One', 'Two'])
  await expect(reader.locator('ol li')).toHaveText(['First', 'Second'])
})

for (const theme of ['light', 'dark', 'rose'] as const) {
  test(`${theme}: bounded scrollable code on desktop and mobile`, async ({ page, isMobile, browserName }, info) => {
    const longLine = `result = "${'long_line_'.repeat(120)}"\n`
    const state = await fixture(page, `\`\`\`python\n${longLine}\tprint(result)\n\`\`\``, { theme })
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
    const block = codeBlock(page)
    await block.scrollIntoViewIfNeeded()
    await page.evaluate(() => document.fonts.ready)
    await expect(block).toHaveAttribute('tabindex', '0')
    await expect(block).toHaveCSS('white-space', 'pre')
    await expect(block).toHaveCSS('overflow-x', 'auto')
    await expect(block).toHaveCSS('tab-size', '4')
    expect(await block.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    expect(await block.evaluate((element) => {
      const bounds = element.getBoundingClientRect()
      return bounds.left >= 0 && bounds.right <= innerWidth
    })).toBe(true)
    await block.focus()
    await expect(block).toBeFocused()
    if (isMobile) {
      info.annotations.push({
        type: 'coverage',
        description: 'Mobile WebKit: geometry, focus and DOM scroll only. Native touch scrolling requires a device check; wheel input is unsupported by Playwright.',
      })
      await test.step('mobile overflow can reveal offscreen code (not a touch gesture)', async () => {
        await block.evaluate((element) => element.scrollTo({ left: 240, behavior: 'instant' }))
        await expect.poll(() => block.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0)
      })
    } else if (browserName === 'webkit') {
      await block.hover()
      await page.mouse.wheel(240, 0)
      await expect.poll(() => block.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0)
    } else {
      await page.keyboard.press('ArrowRight')
      await expect.poll(() => block.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0)
    }
    expect(await block.evaluate((element) => {
      const probe = document.createElement('span')
      probe.style.color = 'hsl(var(--foreground))'
      probe.style.backgroundColor = 'hsl(var(--surface-soft))'
      element.append(probe)
      const matches = getComputedStyle(element).color === getComputedStyle(probe).color
        && getComputedStyle(element).backgroundColor === getComputedStyle(probe).backgroundColor
      probe.remove()
      return matches
    })).toBe(true)
    await info.attach(`${theme}-code`, { body: await block.screenshot({ animations: 'disabled' }), contentType: 'image/png' })
    await info.attach(`${theme}-page`, { body: await page.screenshot({ animations: 'disabled' }), contentType: 'image/png' })
    await page.setViewportSize({ width: 320, height: 700 })
    await block.scrollIntoViewIfNeeded()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    expect(state.writes).toEqual([])
    expect(state.pageErrors).toEqual([])
  })
}

for (const role of ['admin', 'teamlead', 'executor'] as const) {
  test(`${role}: existing management guards stay unchanged`, async ({ page }) => {
    const state = await fixture(page, articleBody, { role })
    await expect(codeBlock(page)).toBeVisible()
    const add = page.getByRole('button', { name: 'Добавить статью', exact: true })
    const edit = page.getByRole('button', { name: 'Редактировать', exact: true })
    const status = page.getByRole('complementary', { name: 'Список статей', exact: true })
      .getByRole('combobox', { name: 'Статус', exact: true })
    if (role === 'executor') {
      await expect(add).toHaveCount(0)
      await expect(edit).toHaveCount(0)
      await expect(status).toHaveCount(0)
    } else {
      await expect(add).toBeVisible()
      await expect(edit).toBeVisible()
      await expect(status).toBeVisible()
    }
    expect(state.writes).toEqual([])
  })
}
