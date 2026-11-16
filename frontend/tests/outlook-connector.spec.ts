import { expect, test, type Page, type Route } from '@playwright/test'
import { build } from 'esbuild'
import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { createHash } from 'node:crypto'
import type { ImportedMailItem, MailImportDevice } from '../src/api/mailImport'

const require = createRequire(import.meta.url)
const origin = 'https://outlook-fixture.test'
const fixedNow = new Date('2026-11-16T12:00:00Z')
const pairingCode = 'synthetic-one-use-pairing-code-for-tests-only'
const deviceId = '11111111-1111-4111-8111-111111111111'
const mailId = '22222222-2222-4222-8222-222222222222'
const meetingId = '33333333-3333-4333-8333-333333333333'
const updatedId = '44444444-4444-4444-8444-444444444444'
const attachmentId = '55555555-5555-4555-8555-555555555555'
const attachmentBytes = Buffer.from('<html><script>window.attachmentExecuted=true</script>Test attachment</html>')
const attachmentPath = `/api/mail-import/items/${mailId}/attachments/${attachmentId}`
const plainBody = '<img src="https://blocked.invalid/pixel" onerror="window.mailExecuted=true">\n<script>window.mailExecuted=true</script>\nОбычный текст & подробности.'

function device(overrides: Partial<MailImportDevice> = {}): MailImportDevice {
  return {
    id: deviceId, name: 'Рабочий Outlook', status: 'pending', include_body: true, include_attachments: true,
    mailbox_label: null, created_at: fixedNow.toISOString(), last_sync_at: null,
    source_state: null, expires_at: '2026-11-16T12:10:00Z',
    last_scan_complete: null, last_skipped_items: 0, ...overrides,
  }
}

function item(overrides: Partial<ImportedMailItem> = {}): ImportedMailItem {
  return {
    id: mailId, source_id: 'a'.repeat(64), kind: 'mail', subject: 'Отчёт за неделю',
    sender_name: 'Ирина Тестовая', sender_address: 'irina@example.test',
    to_recipients: 'Получатель <recipient@example.test>', cc_recipients: 'Копия <copy@example.test>',
    body_html: '<img src="https://blocked.invalid/html-pixel"><script>window.mailExecuted=true</script>HTML_ONLY_SHOULD_NOT_RENDER',
    attachments: [{ id: attachmentId, filename: 'Отчёт.html', content_type: 'text/html', byte_length: attachmentBytes.length, sha256: createHash('sha256').update(attachmentBytes).digest('hex'), is_inline: true, content_id: 'synthetic-inline-id' }],
    received_at: fixedNow.toISOString(), source_modified_at: fixedNow.toISOString(),
    body_text: plainBody, source_is_read: true, is_read: false,
    mailbox_label: 'Тестовый ящик', meeting_status: null, starts_at: null, ends_at: null,
    all_day: false, location: '', meeting_key: null, is_recurring: false,
    created_at: fixedNow.toISOString(), updated_at: fixedNow.toISOString(), ...overrides,
  }
}

type Call = { method: string; path: string; query: URLSearchParams; body: unknown }
type State = {
  devices: MailImportDevice[]
  items: ImportedMailItem[]
  calls: Call[]
  unexpected: string[]
  failures: Set<string>
  waits: Map<string, Promise<void>>
  statuses: Map<string, number>
  fileBytes: Buffer
}

function fixtures(): State {
  return {
    devices: [],
    items: [item(), item({ id: meetingId, kind: 'meeting', subject: 'Отмена планёрки', meeting_status: 'cancelled', is_recurring: true, body_text: null, starts_at: '2026-11-17T09:00:00Z', ends_at: '2026-11-17T10:00:00Z', location: 'Переговорная 2' }), item({ id: updatedId, kind: 'meeting', subject: 'Перенос комитета', meeting_status: 'updated', body_text: '' })],
    calls: [], unexpected: [], failures: new Set(), waits: new Map(), statuses: new Map(), fileBytes: attachmentBytes,
  }
}

let bundle = ''
let styles = ''
const runtimeErrors = new WeakMap<Page, string[]>()

test.afterEach(async ({ page }) => {
  expect(runtimeErrors.get(page) || []).toEqual([])
})

test.beforeAll(async () => {
  const root = fileURLToPath(new URL('..', import.meta.url))
  // Resolve protected modules to synthetic stubs before esbuild can read them.
  const stubs: Record<string, string> = {
    '@/lib/auth': 'export const getToken = () => "outlook-owner-fixture"; export const clearToken = () => {};',
    '@/contexts/AuthContext': `const user = { id: 'fixture-owner', full_name: 'Тестовый владелец', email: 'owner@example.test', role: 'employee', league: 'A', wallet_main: 0, wallet_karma: 0, quality_score: 1, mpw: 0, sidebar_menu_order: null, task_workspace_enabled: true }; export const useAuth = () => ({ user, updateUser() {} });`,
    '@/contexts/attentionState': `const state = { summary: { direct_count: 2, important_count: 3 }, revision: 'fixture', refresh: async () => {} }; export const useAttention = () => state;`,
    '@/components/WebPushControl': 'export const WebPushControl = () => null;',
    '@/components/StorageQuotaSettingsPanel': 'export const StorageQuotaSettingsPanel = () => null;',
    '@/components/ContentLayoutSettingsPanel': 'export const ContentLayoutSettingsPanel = () => null;',
    '@/components/ChangePasswordModal': 'export const ChangePasswordModal = () => null;',
  }
  const result = await build({
    absWorkingDir: root, write: false, bundle: true, format: 'iife', platform: 'browser',
    jsx: 'automatic', logLevel: 'silent', tsconfigRaw: {},
    define: { 'process.env.NODE_ENV': '"test"', 'import.meta.env': '{}' },
    stdin: {
      contents: `import React from 'react'; import { createRoot } from 'react-dom/client'; import { BrowserRouter, Routes, Route } from 'react-router-dom'; import { SettingsPage } from '@/pages/SettingsPage'; import { MessagesPage } from '@/pages/MessagesPage'; createRoot(document.getElementById('root')).render(<React.StrictMode><BrowserRouter><main className="p-4"><Routes><Route path="/settings" element={<SettingsPage />} /><Route path="/messages" element={<MessagesPage />} /><Route path="/messages/:threadId" element={<MessagesPage />} /></Routes></main></BrowserRouter></React.StrictMode>);`,
      resolveDir: root, loader: 'tsx',
    },
    plugins: [{ name: 'bounded-fixture', setup(builder) {
      builder.onResolve({ filter: /^@\// }, args => {
        if (stubs[args.path]) return { path: args.path, namespace: 'fixture' }
        if (/(?:auth|secret|credential|token|key|\.env)/i.test(args.path)) throw new Error('Protected module outside fixture scope')
        return { path: resolve(root, 'src', args.path.slice(2)) + (args.path.includes('/components/') || args.path.includes('/pages/') ? '.tsx' : '.ts') }
      })
      builder.onLoad({ filter: /.*/, namespace: 'fixture' }, args => ({ contents: stubs[args.path], loader: 'js' }))
    } }],
  })
  bundle = result.outputFiles[0].text
  const files = ['src/components/OutlookConnectorSettingsPanel.tsx', 'src/components/ImportedMailPanel.tsx', 'src/pages/SettingsPage.tsx', 'src/pages/MessagesPage.tsx']
  const raw = (await Promise.all(files.map(file => readFile(resolve(root, file), 'utf8')))).join('\n')
  const postcss = require('postcss')
  const tailwind = require('tailwindcss')
  const { default: theme } = await import('../tailwind.config.js')
  styles = (await postcss([tailwind({ ...theme, content: [{ raw, extension: 'tsx' }] })])
    .process(await readFile(resolve(root, 'src/index.css'), 'utf8'), { from: undefined })).css
})

async function open(page: Page, state: State, path = '/messages?tab=mail') {
  const errors: string[] = []
  runtimeErrors.set(page, errors)
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => {
    if (message.text().includes(pairingCode)) errors.push('Pairing code leaked to console')
  })
  await page.clock.install({ time: fixedNow })
  await page.route('**/*', async (route: Route) => {
    const req = route.request()
    const url = new URL(req.url())
    const respond = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (url.origin !== origin) { state.unexpected.push(url.origin); return route.abort() }
    if (url.pathname === '/fixture.js') return route.fulfill({ contentType: 'application/javascript', body: bundle })
    if (url.pathname === '/fixture.css') return route.fulfill({ contentType: 'text/css', body: styles })
    if (!url.pathname.startsWith('/api/')) {
      if (req.isNavigationRequest()) return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html lang="ru" data-theme="${test.info().project.name === 'iphone' ? 'dark' : 'light'}"><head><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="/fixture.css"></head><body><div id="root"></div><script src="/fixture.js"></script></body></html>` })
      state.unexpected.push(url.pathname)
      return route.abort()
    }
    const method = req.method()
    const path = url.pathname
    const body = req.postDataJSON()
    state.calls.push({ method, path, query: url.searchParams, body })
    const action = `${method} ${path}${url.searchParams.get('limit') === '1' ? ':count' : ''}`
    await state.waits.get(action)
    if (state.failures.has(`offline:${action}`)) return route.abort('internetdisconnected')
    if (state.failures.has(action)) return respond({ detail: 'Synthetic failure' }, 400)
    const status = state.statuses.get(action)
    if (status) return respond({ detail: 'Synthetic attachment failure' }, status)
    if (path === '/api/mail-import/devices') {
      if (method === 'GET') return respond(state.devices)
      if (method === 'POST') {
        expect(Object.keys(body).sort()).toEqual(['include_attachments', 'include_body', 'name'])
        const next = device({ name: body.name, include_body: body.include_body, include_attachments: body.include_attachments })
        state.devices.push(next)
        return respond({ device: next, pairing_code: pairingCode, expires_at: next.expires_at }, 201)
      }
    }
    if (path === `/api/mail-import/devices/${deviceId}/revoke` && method === 'POST') {
      expect(body).toEqual({})
      const next = state.devices.find(entry => entry.id === deviceId)!
      next.status = 'revoked'
      return respond(next)
    }
    if (path === '/api/mail-import/items' && method === 'GET') {
      let items = state.items
      const kind = url.searchParams.get('kind')
      if (kind) items = items.filter(entry => entry.kind === kind)
      const unreadCount = items.filter(entry => !entry.is_read).length
      if (url.searchParams.get('unread_only') === 'true') items = items.filter(entry => !entry.is_read)
      const offset = Number(url.searchParams.get('offset'))
      const limit = Number(url.searchParams.get('limit'))
      return respond({ items: items.slice(offset, offset + limit).map(entry => ({ ...entry, body_text: null, body_html: null })), total: items.length, unread_count: unreadCount })
    }
    if (path === attachmentPath && method === 'GET') {
      expect(req.headers().authorization).toBe('Bearer outlook-owner-fixture')
      return route.fulfill({ status: 200, contentType: 'text/html', body: state.fileBytes })
    }
    const match = path.match(/^\/api\/mail-import\/items\/([^/]+)(\/read)?$/)
    if (match) {
      const found = state.items.find(entry => entry.id === match[1])
      if (!found) return respond({ detail: 'Not found' }, 404)
      if (match[2] && method === 'POST') {
        expect(Object.keys(body)).toEqual(['is_read'])
        found.is_read = body.is_read
      } else if (method !== 'GET') { state.unexpected.push(action); return route.abort() }
      return respond(found)
    }
    if (path === '/api/messages/threads' && method === 'GET') return respond([])
    if (path === '/api/messages/attention' && method === 'GET') return respond([])
    if ((path === '/api/contacts' || path === '/api/quick-notes') && method === 'GET') return respond([])
    state.unexpected.push(action)
    return route.abort()
  })
  await page.goto(path)
}

async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
}

type DownloadAudit = { created: number; revoked: number; active: string[]; types: string[] }

async function installDownloadAudit(page: Page) {
  await page.addInitScript(() => {
    const audit = { created: 0, revoked: 0, active: [] as string[], types: [] as string[] }
    Object.defineProperty(window, 'outlookDownloadAudit', { value: audit })
    const create = URL.createObjectURL.bind(URL)
    const revoke = URL.revokeObjectURL.bind(URL)
    URL.createObjectURL = object => {
      const url = create(object)
      audit.created += 1
      audit.active.push(url)
      audit.types.push(object instanceof Blob ? object.type : 'non-blob')
      return url
    }
    URL.revokeObjectURL = url => {
      audit.revoked += 1
      audit.active = audit.active.filter(value => value !== url)
      revoke(url)
    }
  })
}

function downloadAudit(page: Page) {
  return page.evaluate(() => (window as unknown as { outlookDownloadAudit: DownloadAudit }).outlookDownloadAudit)
}

test('settings: full consent defaults, one-use code, clipboard failure and recovery, no persistence', async ({ page }) => {
  const state = fixtures()
  await page.addInitScript(() => {
    let attempts = 0
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async () => { if (++attempts === 1) throw new Error('Synthetic clipboard denied') } } })
  })
  await open(page, state, '/settings')
  const panel = page.getByRole('region', { name: 'Outlook Inbox' })
  await expect(panel.getByText('Подключений Outlook пока нет.')).toBeVisible()
  await expect(panel.getByLabel('Передавать текст писем')).toBeChecked()
  await expect(panel.getByLabel('Передавать вложения')).toBeChecked()
  await panel.getByLabel('Название устройства').fill('  Ноутбук Windows  ')
  await panel.getByRole('button', { name: 'Создать подключение', exact: true }).click()
  await expect(page.getByTestId('outlook-pairing-code')).toHaveText(pairingCode)
  expect(state.calls.find(call => call.method === 'POST')?.body).toEqual({ name: 'Ноутбук Windows', include_body: true, include_attachments: true })
  await panel.getByRole('button', { name: 'Копировать код' }).click()
  await expect(panel.getByRole('alert')).toContainText('Не удалось скопировать')
  await panel.getByRole('button', { name: 'Копировать код' }).click()
  await expect(panel.getByText('Код скопирован.')).toBeVisible()
  expect(await page.evaluate(() => JSON.stringify([localStorage, sessionStorage]))).not.toContain(pairingCode)
  await noOverflow(page)
  await panel.screenshot({ path: test.info().outputPath('settings-pairing.png') })
  state.devices[0].status = 'active'
  await panel.getByRole('button', { name: 'Обновить подключения' }).click()
  await expect(page.getByTestId('outlook-pairing-code')).toHaveCount(0)
  await expect(panel.getByText('Активно', { exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByTestId('outlook-pairing-code')).toHaveCount(0)
  expect(state.unexpected).toEqual([])
})

test('settings: explicit metadata opt-out, pending creation, expiry clears code', async ({ page }) => {
  const state = fixtures()
  let release!: () => void
  state.waits.set('POST /api/mail-import/devices', new Promise<void>(resolve => { release = resolve }))
  await open(page, state, '/settings')
  await page.getByLabel('Название устройства').fill('Рабочий Outlook')
  await page.getByLabel('Передавать текст писем').uncheck()
  await page.getByLabel('Передавать вложения').uncheck()
  await page.getByRole('button', { name: 'Создать подключение', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Создание…' })).toBeDisabled()
  release()
  await expect(page.getByTestId('outlook-pairing-code')).toBeVisible()
  expect(state.calls.find(call => call.method === 'POST')?.body).toEqual({ name: 'Рабочий Outlook', include_body: false, include_attachments: false })
  await page.clock.fastForward(601_000)
  await expect(page.getByTestId('outlook-pairing-code')).toHaveCount(0)
  await expect(page.getByText('Срок кода истёк.', { exact: false })).toBeVisible()
  await expect(page.getByText('Срок истёк', { exact: true })).toBeVisible()
  expect(state.unexpected).toEqual([])
})

test('settings: all device states, incomplete delivery, revoke confirmation and retry', async ({ page }) => {
  const state = fixtures()
  state.devices = [device({ status: 'active', expires_at: '2027-11-16T12:00:00Z', last_sync_at: fixedNow.toISOString(), source_state: 'cached', last_scan_complete: false, last_skipped_items: 4 }), device({ id: 'pending', name: 'Ожидающий' }), device({ id: 'expired', name: 'Старый', status: 'expired' }), device({ id: 'revoked', name: 'Отозванный', status: 'revoked' }), device({ id: 'offline', name: 'Без сети', status: 'active', source_state: 'offline', last_sync_at: fixedNow.toISOString() })]
  await open(page, state, '/settings')
  const panel = page.getByRole('region', { name: 'Outlook Inbox' })
  await expect(panel.getByText('Неполное сканирование. Пропущено записей: 4.')).toBeVisible()
  await expect(panel.getByText('Локальный кэш Outlook')).toBeVisible()
  await expect(panel.getByText('Outlook не в сети')).toBeVisible()
  await expect(panel.getByText('Ожидает привязки', { exact: true })).toBeVisible()
  await expect(panel.getByText('Срок истёк', { exact: true })).toBeVisible()
  await expect(panel.getByRole('button', { name: 'Отозвать Отозванный' })).toHaveCount(0)
  const trigger = panel.getByRole('button', { name: 'Отозвать Рабочий Outlook', exact: true })
  await trigger.click()
  await expect(page.getByRole('dialog')).toContainText('сохранятся')
  await noOverflow(page)
  await page.getByRole('dialog').screenshot({ path: test.info().outputPath('revoke-confirmation.png') })
  await page.getByRole('button', { name: 'Отмена', exact: true }).click()
  await expect(trigger).toBeFocused()
  expect(state.calls.filter(call => call.method === 'POST')).toHaveLength(0)
  await trigger.click()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await trigger.click()
  state.failures.add(`POST /api/mail-import/devices/${deviceId}/revoke`)
  await page.getByRole('button', { name: 'Отозвать подключение', exact: true }).click()
  await expect(page.getByRole('dialog').getByRole('alert')).toContainText('Не удалось отозвать')
  state.failures.clear()
  let release!: () => void
  state.waits.set(`POST /api/mail-import/devices/${deviceId}/revoke`, new Promise<void>(resolve => { release = resolve }))
  await page.getByRole('button', { name: 'Отозвать подключение', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Отзыв…' })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Отмена', exact: true })).toBeDisabled()
  release()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(panel.getByText('Подключение отозвано. Импортированные записи сохранены.')).toBeVisible()
  await expect(panel.getByRole('button', { name: 'Обновить подключения' })).toBeFocused()
  expect(state.items).toHaveLength(3)
  await noOverflow(page)
  expect(state.unexpected).toEqual([])
})

test('settings: loading, load/create errors preserve draft and reload', async ({ page }) => {
  const state = fixtures()
  let release!: () => void
  state.waits.set('GET /api/mail-import/devices', new Promise<void>(resolve => { release = resolve }))
  state.failures.add('GET /api/mail-import/devices')
  await open(page, state, '/settings')
  await expect(page.getByText('Загрузка подключений…')).toBeVisible()
  release()
  await expect(page.getByText('Не удалось загрузить подключения.', { exact: false })).toBeVisible()
  state.failures.clear()
  await page.getByRole('button', { name: 'Повторить загрузку' }).click()
  await expect(page.getByText('Подключений Outlook пока нет.')).toBeVisible()
  state.failures.add('POST /api/mail-import/devices')
  await page.getByLabel('Название устройства').fill('Черновик устройства')
  await page.getByRole('button', { name: 'Создать подключение', exact: true }).click()
  await expect(page.getByText('Не удалось создать подключение.', { exact: false })).toBeVisible()
  await expect(page.getByLabel('Название устройства')).toHaveValue('Черновик устройства')
  expect(state.unexpected).toEqual([])
})

test('mail integration: separate counts, safe plain text, explicit DPMS read, no source write', async ({ page }) => {
  const state = fixtures()
  await open(page, state, '/messages')
  await expect(page.getByRole('tab', { name: 'Обращения 2' })).toBeVisible()
  await expect(page.getByRole('tab', { name: 'Важное 3' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Новое письмо', exact: true })).toBeVisible()
  expect(state.calls.some(call => call.path.startsWith('/api/mail-import'))).toBe(false)
  await page.getByRole('tab', { name: 'Почта и встречи' }).click()
  await expect(page.getByLabel('Непрочитанных в DPMS: 3')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Новое письмо', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: /Отчёт за неделю/ }).click()
  const detail = page.getByRole('article', { name: 'Содержимое записи' })
  await expect(detail.getByText('Прочитано в Outlook', { exact: true })).toBeVisible()
  await expect(detail.getByText('Не прочитано в DPMS', { exact: true })).toBeVisible()
  await expect(page.getByTestId('imported-mail-body')).toHaveText(plainBody)
  await expect(detail.getByText('Получатель <recipient@example.test>', { exact: true })).toBeVisible()
  await expect(detail.getByText('Копия <copy@example.test>', { exact: true })).toBeVisible()
  if (page.viewportSize()!.width >= 640) {
    await page.evaluate(() => window.scrollTo(0, 0))
    await expect(page.getByTestId('imported-mail-body')).toBeInViewport({ ratio: 1 })
  }
  await expect(page.getByText('HTML_ONLY_SHOULD_NOT_RENDER', { exact: false })).toHaveCount(0)
  await expect(detail.locator('img,script,iframe')).toHaveCount(0)
  expect(state.calls.filter(call => call.method === 'POST')).toHaveLength(0)
  await detail.getByRole('button', { name: 'Отметить прочитанным в DPMS', exact: true }).click()
  await expect(detail.getByText('Прочитано в DPMS', { exact: true })).toBeVisible()
  await expect(page.getByLabel('Непрочитанных в DPMS: 2')).toBeVisible()
  expect(state.items[0].source_is_read).toBe(true)
  expect(state.calls.filter(call => call.method === 'POST').map(call => [call.path, call.body])).toEqual([[`/api/mail-import/items/${mailId}/read`, { is_read: true }]])
  await noOverflow(page)
  await page.screenshot({ path: test.info().outputPath('mail-detail.png'), fullPage: true })
  await detail.getByRole('button', { name: 'Отметить непрочитанным в DPMS', exact: true }).click()
  await expect(page.getByLabel('Непрочитанных в DPMS: 3')).toBeVisible()
  await page.getByRole('tab', { name: 'Важное 3' }).click()
  await expect(page.getByText('Важных непросмотренных событий нет.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Новое письмо', exact: true })).toBeVisible()
  await page.getByRole('tab', { name: 'Обращения 2' }).click()
  await expect(page.getByText('Новых обращений и переписок пока нет.')).toBeVisible()
  await page.getByRole('button', { name: 'Новое письмо', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  expect(state.unexpected).toEqual([])
})

test('mail: meeting filters, cancelled/updated series, metadata and missing schedule', async ({ page }) => {
  const state = fixtures()
  await open(page, state)
  await page.getByLabel('Тип записи', { exact: true }).selectOption('meeting')
  await expect(page.getByRole('button', { name: /Отчёт за неделю/ })).toHaveCount(0)
  await expect(page.getByLabel('Непрочитанных в DPMS: 3')).toBeVisible()
  await page.getByRole('button', { name: /Отмена планёрки/ }).click()
  const detail = page.getByRole('article')
  await expect(detail.getByText('Встреча отменена', { exact: true })).toBeVisible()
  await expect(detail.getByText('Серия встреч', { exact: true })).toBeVisible()
  await expect(detail.getByText('Переговорная 2')).toBeVisible()
  await expect(detail.getByText('Текст не передан.', { exact: false })).toBeVisible()
  await page.getByRole('button', { name: 'К списку' }).click()
  await page.getByRole('button', { name: /Перенос комитета/ }).click()
  await expect(detail.getByText('Встреча обновлена', { exact: true })).toBeVisible()
  await expect(detail.getByText('Пустой текст.')).toBeVisible()
  await expect(detail.getByText('Не указано', { exact: true })).toHaveCount(2)
  await page.reload()
  await expect(detail.getByText('Встреча обновлена', { exact: true })).toBeVisible()
  await expect(page.getByLabel('Тип записи', { exact: true })).toHaveValue('meeting')
  await noOverflow(page)
  expect(state.unexpected).toEqual([])
})

test('mail: stable pagination and last unread page clamps after read', async ({ page }) => {
  const state = fixtures()
  state.items = Array.from({ length: 51 }, (_, index) => item({ id: `synthetic-${index}`, subject: `Запись ${index}`, body_text: null }))
  await open(page, state)
  const unread = page.getByLabel('Непрочитанные в DPMS', { exact: true })
  // Router transitions commit asynchronously; assert the settled URL and control.
  await unread.click()
  await expect(page).toHaveURL(/mail_unread=true/)
  await expect(unread).toBeChecked()
  await page.getByRole('button', { name: 'Следующая страница' }).click()
  await expect(page.getByText('Страница 2 из 2 · 51 записей')).toBeVisible()
  await page.getByRole('button', { name: /Запись 50/ }).click()
  await page.getByRole('button', { name: 'Отметить прочитанным в DPMS', exact: true }).click()
  await expect(page.getByLabel('Непрочитанных в DPMS: 50')).toBeVisible()
  await page.getByRole('button', { name: 'К списку' }).click()
  await expect(page.getByText('Страница 1 из 1 · 50 записей')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Следующая страница' })).toBeDisabled()
  await expect(page.getByRole('button', { name: /Запись 50/ })).toHaveCount(0)
  expect(state.calls.filter(call => call.path === '/api/mail-import/items' && call.query.get('limit') !== '1').every(call => call.query.get('limit') === '50')).toBe(true)
  expect(state.unexpected).toEqual([])
})

test('mail: list, detail, read and count error recovery', async ({ page }) => {
  const state = fixtures()
  state.failures.add('GET /api/mail-import/items')
  state.failures.add('GET /api/mail-import/items:count')
  await open(page, state)
  await expect(page.getByText('Не удалось загрузить почту и встречи.', { exact: false })).toBeVisible()
  await expect(page.getByText('Счётчик непрочитанных недоступен.', { exact: false })).toBeVisible()
  state.failures.clear()
  await page.getByRole('button', { name: 'Повторить загрузку', exact: true }).click()
  state.failures.add(`GET /api/mail-import/items/${mailId}`)
  await page.getByRole('button', { name: /Отчёт за неделю/ }).click()
  await expect(page.getByText('Не удалось открыть запись.', { exact: false })).toBeVisible()
  state.failures.clear()
  await page.getByRole('button', { name: 'Повторить открытие' }).click()
  state.failures.add(`POST /api/mail-import/items/${mailId}/read`)
  await page.getByRole('button', { name: 'Отметить прочитанным в DPMS', exact: true }).click()
  await expect(page.getByText('Не удалось изменить статус DPMS.', { exact: false })).toBeVisible()
  await expect(page.getByRole('article').getByText('Не прочитано в DPMS', { exact: true })).toBeVisible()
  state.failures.clear()
  await page.getByRole('button', { name: 'Отметить прочитанным в DPMS', exact: true }).click()
  await expect(page.getByRole('article').getByText('Прочитано в DPMS', { exact: true })).toBeVisible()
  expect(state.unexpected).toEqual([])
})

test('mail: late detail does not replace current selection; long text stays within mobile', async ({ page }) => {
  const state = fixtures()
  state.items[1].subject = 'ДлиннаяТемаБезПробелов'.repeat(30)
  state.items[1].sender_address = `${'address'.repeat(30)}@example.test`
  let release!: () => void
  state.waits.set(`GET /api/mail-import/items/${mailId}`, new Promise<void>(resolve => { release = resolve }))
  await open(page, state)
  await page.getByRole('button', { name: /Отчёт за неделю/ }).click()
  await expect(page.getByText('Загрузка записи…')).toBeVisible()
  await page.getByRole('button', { name: 'К списку' }).click()
  await page.getByRole('button', { name: /ДлиннаяТемаБезПробелов/ }).click()
  await expect(page.getByRole('article').getByText('Встреча отменена', { exact: true })).toBeVisible()
  release()
  await expect(page.getByTestId('imported-mail-body')).toHaveCount(0)
  await expect(page.getByRole('heading', { level: 2, name: state.items[1].subject })).toBeVisible()
  await noOverflow(page)
  await page.screenshot({ path: test.info().outputPath('long-meeting.png'), fullPage: true })
  expect(state.unexpected).toEqual([])
})

test('mail: empty list and filter reset page, no automatic read', async ({ page }) => {
  const state = fixtures()
  state.items = []
  await open(page, state, '/messages?tab=mail&mail_offset=50')
  await expect(page.getByText('Импортированных писем и встреч пока нет.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Предыдущая страница' })).toBeDisabled()
  await page.getByLabel('Тип записи', { exact: true }).selectOption('meeting')
  await expect(page.getByText('Нет записей по выбранным фильтрам.')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Подключения Outlook' })).toHaveAttribute('href', '/settings')
  expect(state.calls.filter(call => call.method === 'POST')).toHaveLength(0)
  expect(state.unexpected).toEqual([])
})

test('settings: slow pairing poll cannot overlap or hide its result', async ({ page }) => {
  const state = fixtures()
  await open(page, state, '/settings')
  await expect(page.getByText('Подключений Outlook пока нет.')).toBeVisible()
  await page.getByLabel('Название устройства').fill('Медленное подключение')
  await page.getByRole('button', { name: 'Создать подключение', exact: true }).click()
  await expect(page.getByTestId('outlook-pairing-code')).toBeVisible()
  const before = state.calls.filter(call => call.method === 'GET' && call.path === '/api/mail-import/devices').length
  let release!: () => void
  state.waits.set('GET /api/mail-import/devices', new Promise<void>(resolve => { release = resolve }))
  await page.clock.fastForward(5000)
  await expect.poll(() => state.calls.filter(call => call.method === 'GET' && call.path === '/api/mail-import/devices').length).toBe(before + 1)
  await page.clock.fastForward(5000)
  expect(state.calls.filter(call => call.method === 'GET' && call.path === '/api/mail-import/devices')).toHaveLength(before + 1)
  state.devices[0].status = 'active'
  release()
  await expect(page.getByTestId('outlook-pairing-code')).toHaveCount(0)
  await expect(page.getByText('Активно', { exact: true })).toBeVisible()
  expect(state.unexpected).toEqual([])
})

test('mail: offline list retries without losing selected filters', async ({ page }) => {
  const state = fixtures()
  state.failures.add('offline:GET /api/mail-import/items')
  await open(page, state, '/messages?tab=mail&mail_kind=meeting&mail_unread=true')
  await expect(page.getByText('Не удалось загрузить почту и встречи.', { exact: false })).toBeVisible()
  state.failures.clear()
  await page.getByRole('button', { name: 'Повторить загрузку', exact: true }).click()
  await expect(page.getByRole('button', { name: /Отмена планёрки/ })).toBeVisible()
  await expect(page.getByLabel('Тип записи', { exact: true })).toHaveValue('meeting')
  await expect(page.getByLabel('Непрочитанные в DPMS', { exact: true })).toBeChecked()
  expect(state.unexpected).toEqual([])
})

test('attachments: owner API download, inert HTML, manifest name and object URL cleanup', async ({ page }) => {
  const state = fixtures()
  await installDownloadAudit(page)
  await open(page, state)
  await page.getByRole('button', { name: /Отчёт за неделю/ }).click()
  const files = page.getByRole('region', { name: 'Вложения', exact: true })
  await expect(files.getByText('Отчёт.html', { exact: true })).toBeVisible()
  await expect(files.getByText(`${attachmentBytes.length} Б · Встроенное вложение`, { exact: true })).toBeVisible()
  const downloadEvent = page.waitForEvent('download')
  await files.getByRole('button', { name: 'Скачать Отчёт.html', exact: true }).click()
  const downloaded = await downloadEvent
  expect(downloaded.suggestedFilename().normalize('NFC')).toBe('Отчёт.html')
  expect(await downloaded.failure()).toBeNull()
  expect(await readFile((await downloaded.path())!)).toEqual(attachmentBytes)
  await expect(files.getByText('Файл передан браузеру.')).toBeVisible()
  expect(state.calls.filter(call => call.path === attachmentPath).map(call => call.method)).toEqual(['GET'])
  expect((await downloadAudit(page)).types).toEqual(['application/octet-stream'])
  await page.clock.fastForward(1100)
  await expect.poll(async () => (await downloadAudit(page)).active.length).toBe(0)
  expect((await downloadAudit(page)).revoked).toBe(1)
  await expect(page.getByRole('article').locator('img,iframe,script')).toHaveCount(0)
  expect(await page.evaluate(() => 'attachmentExecuted' in window || 'mailExecuted' in window)).toBe(false)
  await noOverflow(page)
  await page.screenshot({ path: test.info().outputPath('attachments-download.png'), fullPage: true })
  expect(state.unexpected).toEqual([])
})

test('attachments: denied, failed and corrupt files never report download success', async ({ page }) => {
  const state = fixtures()
  await installDownloadAudit(page)
  await open(page, state)
  await page.getByRole('button', { name: /Отчёт за неделю/ }).click()
  const files = page.getByRole('region', { name: 'Вложения', exact: true })
  const button = files.getByRole('button', { name: 'Скачать Отчёт.html', exact: true })
  state.statuses.set(`GET ${attachmentPath}`, 403)
  await button.click()
  await expect(files.getByRole('alert')).toHaveText('Нет доступа к вложению или файл недоступен.')
  state.statuses.set(`GET ${attachmentPath}`, 413)
  await button.click()
  await expect(files.getByRole('alert')).toHaveText('Превышен лимит размера вложения. Файл не скачан.')
  state.statuses.set(`GET ${attachmentPath}`, 400)
  await button.click()
  await expect(files.getByRole('alert')).toHaveText('Не удалось скачать вложение. Повторите загрузку.')
  state.statuses.clear()
  state.fileBytes = Buffer.from('incomplete')
  await button.click()
  await expect(files.getByRole('alert')).toHaveText('Размер вложения не совпадает. Файл не скачан.')
  state.fileBytes = Buffer.alloc(attachmentBytes.length, 'x')
  await button.click()
  await expect(files.getByRole('alert')).toHaveText('Контрольная сумма вложения не совпадает. Файл не скачан.')
  expect((await downloadAudit(page)).created).toBe(0)
  await expect(files.getByText('Файл передан браузеру.')).toHaveCount(0)
  await expect(page.getByTestId('imported-mail-body')).toHaveText(plainBody)
  state.fileBytes = attachmentBytes
  const downloadEvent = page.waitForEvent('download')
  await button.click()
  await downloadEvent
  await expect(files.getByRole('alert')).toHaveCount(0)
  await expect(files.getByText('Файл передан браузеру.')).toBeVisible()
  // Unmount must also release a URL before the delayed cleanup runs.
  await page.getByRole('tab', { name: 'Важное 3' }).click()
  await expect.poll(async () => (await downloadAudit(page)).active.length).toBe(0)
  expect(state.unexpected).toEqual([])
})

test('attachments: pending request cannot download after changing the selected item', async ({ page }) => {
  const state = fixtures()
  await installDownloadAudit(page)
  let release!: () => void
  state.waits.set(`GET ${attachmentPath}`, new Promise<void>(resolve => { release = resolve }))
  await open(page, state)
  await page.getByRole('button', { name: /Отчёт за неделю/ }).click()
  const button = page.getByRole('button', { name: 'Скачать Отчёт.html', exact: true })
  await button.click()
  await expect(button).toBeDisabled()
  await expect(page.getByText('Загрузка вложения…')).toBeVisible()
  await page.getByRole('button', { name: 'К списку' }).click()
  await page.getByRole('button', { name: /Отмена планёрки/ }).click()
  await expect(page.getByRole('article').getByText('Встреча отменена', { exact: true })).toBeVisible()
  const response = page.waitForResponse(url => url.url().endsWith(attachmentPath))
  release()
  await response
  expect((await downloadAudit(page)).created).toBe(0)
  await expect(page.getByText('Файл передан браузеру.')).toHaveCount(0)
  expect(state.unexpected).toEqual([])
})

test('attachments: manifest size limits warn instead of implying a complete transfer', async ({ page }) => {
  const state = fixtures()
  const attachment = state.items[0].attachments[0]
  state.items[0].attachments = [
    { ...attachment, filename: 'БольшойФайл'.repeat(20) + '.html', byte_length: 11 * 1024 * 1024 },
    { ...attachment, id: 'another-file', filename: '<img onerror=alert(1)>.txt', byte_length: 10 * 1024 * 1024 },
  ]
  await open(page, state)
  await page.getByRole('button', { name: /Отчёт за неделю/ }).click()
  const files = page.getByRole('region', { name: 'Вложения', exact: true })
  await expect(files.getByText('Превышен лимит 20 МиБ вложений на письмо.', { exact: false })).toBeVisible()
  await expect(files.getByText('Файл превышает лимит 10 МиБ.', { exact: false })).toBeVisible()
  await expect(files.getByRole('button', { name: /Скачать БольшойФайл/ })).toBeDisabled()
  await expect(files.getByText('<img onerror=alert(1)>.txt', { exact: true })).toBeVisible()
  await expect(files.locator('img')).toHaveCount(0)
  await noOverflow(page)
  await files.screenshot({ path: test.info().outputPath('attachments-limit-warning.png') })
  expect(state.calls.filter(call => call.path.includes('/attachments/'))).toHaveLength(0)
  expect(state.unexpected).toEqual([])
})

test('detail: responsive metadata columns and full-width long recipients', async ({ page }) => {
  const state = fixtures()
  state.items[0].to_recipients = `${'ПолучательБезПробелов'.repeat(30)} <recipient@example.test>`
  state.items[0].cc_recipients = `${'КопияБезПробелов'.repeat(30)} <copy@example.test>`
  await open(page, state)
  await page.getByRole('button', { name: /Отчёт за неделю/ }).click()
  const metadata = page.getByRole('article').locator('dl')
  await expect(metadata).toBeVisible()
  const layout = await metadata.evaluate(element => ({
    columns: getComputedStyle(element).gridTemplateColumns.split(' ').length,
    minWidths: Array.from(element.children, child => getComputedStyle(child).minWidth),
    recipientWidths: Array.from(element.children).filter(child => ['Кому', 'Копия'].includes(child.querySelector('dt')?.textContent || '')).map(child => child.getBoundingClientRect().width),
    width: element.getBoundingClientRect().width,
  }))
  expect(layout.columns).toBe(page.viewportSize()!.width >= 640 ? 2 : 1)
  expect(layout.minWidths.every(width => width === '0px')).toBe(true)
  for (const width of layout.recipientWidths) expect(width).toBeCloseTo(layout.width, 0)
  await noOverflow(page)
  await page.screenshot({ path: test.info().outputPath('metadata-long-recipients.png'), fullPage: true })
  expect(state.unexpected).toEqual([])
})
