import { expect, test, type Page, type Route } from '@playwright/test'

const userId = '11111111-1111-4111-8111-111111111111'
const peerId = '22222222-2222-4222-8222-222222222222'
const threadId = '33333333-3333-4333-8333-333333333333'
const noteId = '44444444-4444-4444-8444-444444444444'
const directId = '55555555-5555-4555-8555-555555555555'
const importantId = '66666666-6666-4666-8666-666666666666'

const testUser = {
  id: userId,
  full_name: 'Тестовый пользователь',
  email: 'owner@example.com',
  league: 'A',
  role: 'admin',
  mpw: 0,
  wip_limit: 5,
  wallet_main: 0,
  wallet_karma: 0,
  quality_score: 1,
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
  created_at: '2026-08-13T08:00:00Z',
  updated_at: '2026-08-13T08:00:00Z',
}

const participant = {
  user_id: peerId,
  full_name: 'Анна Петрова',
  email: 'anna@example.com',
}

const ownerParticipant = {
  user_id: userId,
  full_name: testUser.full_name,
  email: testUser.email,
}

const thread = {
  id: threadId,
  subject: 'Согласование материалов',
  created_by_id: peerId,
  participants: [ownerParticipant, participant],
  last_post_preview: 'Посмотрите, пожалуйста, итоговый вариант.',
  last_post_at: '2026-08-13T09:20:00Z',
  unread_count: 1,
  created_at: '2026-08-13T09:00:00Z',
  updated_at: '2026-08-13T09:20:00Z',
}

const threadDetail = {
  ...thread,
  posts: [
    {
      id: '77777777-7777-4777-8777-777777777777',
      thread_id: threadId,
      author_id: peerId,
      author_name: participant.full_name,
      author_email: participant.email,
      body: 'Посмотрите, пожалуйста, итоговый вариант.',
      quick_note_id: null,
      quick_note_title: null,
      quick_note_available: false,
      created_at: '2026-08-13T09:20:00Z',
    },
  ],
}

const directItem = {
  id: directId,
  kind: 'direct',
  event_type: 'contact.request.received',
  title: 'Новая заявка в контакты',
  body: 'Коллега предлагает добавить контакт.',
  link: null,
  source_type: 'contact',
  source_key: '88888888-8888-4888-8888-888888888888',
  actor_id: peerId,
  actor_name: participant.full_name,
  actor_email: participant.email,
  is_read: false,
  created_at: '2026-08-13T09:30:00Z',
  updated_at: '2026-08-13T09:30:00Z',
}

const importantItem = {
  id: importantId,
  kind: 'important',
  event_type: 'task_rejected',
  title: 'Результат задачи возвращён',
  body: 'Требуется уточнить приложенный результат.',
  link: null,
  source_type: 'notification',
  source_key: '99999999-9999-4999-8999-999999999999',
  actor_id: null,
  actor_name: null,
  actor_email: null,
  is_read: false,
  created_at: '2026-08-13T09:40:00Z',
  updated_at: '2026-08-13T09:40:00Z',
}

const contact = {
  id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  requester_id: userId,
  recipient_id: peerId,
  requester_name: testUser.full_name,
  requester_email: testUser.email,
  recipient_name: participant.full_name,
  recipient_email: participant.email,
  status: 'accepted',
  direction: 'outgoing',
  created_at: '2026-08-13T08:00:00Z',
  updated_at: '2026-08-13T08:00:00Z',
}

const note = {
  id: noteId,
  owner_id: userId,
  title: 'Итоги проектного комитета',
  body: 'Рабочая заметка',
  context: null,
  status: 'draft',
  tags: [],
  revision: 1,
  created_at: '2026-08-13T08:00:00Z',
  updated_at: '2026-08-13T08:00:00Z',
}

type MockState = {
  directUnread: boolean
  importantUnread: boolean
  threadUnread: number
  createCalls: number
  createdPayload: Record<string, unknown> | null
  remoteReplyBody: string | null
}

async function installWebSocketMock(page: Page) {
  await page.addInitScript(`
    class MockWebSocket {
      static OPEN = 1;
      constructor(url) {
        this.url = url;
        this.readyState = 0;
        this.onopen = null; this.onmessage = null; this.onclose = null; this.onerror = null;
        window.__dpmsMessageSockets = window.__dpmsMessageSockets || [];
        window.__dpmsMessageSockets.push(this);
        window.setTimeout(() => { this.readyState = 1; if (this.onopen) this.onopen(); }, 0);
      }
      send(data) {
        try {
          const value = JSON.parse(data);
          if (value.type === 'auth' && this.onmessage) {
            window.setTimeout(() => this.onmessage({ data: JSON.stringify({ type: 'ready' }) }), 0);
          }
          if (value.type === 'ping' && this.onmessage) {
            this.onmessage({ data: JSON.stringify({ type: 'pong' }) });
          }
        } catch (error) {}
      }
      close() { this.readyState = 3; if (this.onclose) this.onclose({ code: 1000 }); }
    }
    window.__emitDpmsMessageEvent = (event) => {
      for (const socket of window.__dpmsMessageSockets || []) {
        if (socket.readyState === MockWebSocket.OPEN && socket.onmessage) {
          socket.onmessage({ data: JSON.stringify(event) });
        }
      }
    };
    window.WebSocket = MockWebSocket;
  `)
}

async function installApiMock(page: Page, state: MockState) {
  await page.addInitScript(() => localStorage.setItem('dpms_token', 'messages-test-token'))
  await installWebSocketMock(page)
  await page.route('**/api/**', async (route: Route) => {
    const request = route.request()
    const method = request.method()
    const url = new URL(request.url())
    const path = url.pathname

    const respond = async (body: unknown, status = 200) => {
      await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    }

    if (path === '/api/auth/me') return respond(testUser)
    if (path === '/api/users') return respond([])
    if (path === '/api/messages/summary') {
      return respond({
        direct_count: (state.directUnread ? 1 : 0) + (state.threadUnread > 0 ? 1 : 0),
        important_count: state.importantUnread ? 1 : 0,
      })
    }
    if (path === '/api/messages/attention' && method === 'GET') {
      const kind = url.searchParams.get('kind')
      if (kind === 'direct') return respond(state.directUnread ? [directItem] : [])
      return respond(state.importantUnread ? [importantItem] : [])
    }
    if (path === `/api/messages/attention/${directId}/read` && method === 'POST') {
      state.directUnread = false
      return respond({ read: true, item_id: directId })
    }
    if (path === `/api/messages/attention/${importantId}/read` && method === 'POST') {
      state.importantUnread = false
      return respond({ read: true, item_id: importantId })
    }
    if (path === '/api/messages/threads' && method === 'GET') {
      return respond([{ ...thread, unread_count: state.threadUnread }])
    }
    if (path === `/api/messages/threads/${threadId}` && method === 'GET') {
      const posts = state.remoteReplyBody
        ? [
            ...threadDetail.posts,
            {
              id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
              thread_id: threadId,
              author_id: peerId,
              author_name: participant.full_name,
              author_email: participant.email,
              body: state.remoteReplyBody,
              quick_note_id: null,
              quick_note_title: null,
              quick_note_available: false,
              created_at: '2026-08-13T09:25:00Z',
            },
          ]
        : threadDetail.posts
      return respond({ ...threadDetail, posts, unread_count: state.threadUnread })
    }
    if (path === `/api/messages/threads/${threadId}/read` && method === 'POST') {
      state.threadUnread = 0
      return respond({ read: true, thread_id: threadId })
    }
    if (path === '/api/messages/threads' && method === 'POST') {
      state.createCalls += 1
      state.createdPayload = JSON.parse(request.postData() || '{}')
      await new Promise((resolve) => setTimeout(resolve, 120))
      return respond({ ...threadDetail, created_by_id: userId, unread_count: 0 }, 201)
    }
    if (path === '/api/contacts' && method === 'GET') return respond([contact])
    if (path === '/api/quick-notes' && method === 'GET') return respond([note])
    if (path.startsWith('/api/client-events')) return respond({})
    return respond(method === 'GET' ? [] : {})
  })
}

async function noHorizontalOverflow(page: Page) {
  const size = await page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
  }))
  expect(size.document).toBeLessThanOrEqual(size.viewport + 1)
}

test('desktop inbox, exact read and protected compose', async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.startsWith('desktop-'))
  const state: MockState = {
    directUnread: true,
    importantUnread: true,
    threadUnread: 1,
    createCalls: 0,
    createdPayload: null,
    remoteReplyBody: null,
  }
  await installApiMock(page, state)
  await page.goto('/messages')

  await expect(page.getByRole('heading', { name: 'Сообщения' })).toBeVisible()
  await expect(page.getByRole('tab', { name: /Обращения/ })).toBeVisible()
  await expect(page.getByRole('tab', { name: /Важное/ })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Прочитать всё' })).toHaveCount(0)
  await expect(page.locator('[title*="новых обращений"]:visible').first()).toBeVisible()
  await expect(page.locator('[title*="важных событий"]:visible').first()).toBeVisible()
  await expect(page.getByText('Новая заявка в контакты').first()).toBeVisible()
  await expect(page.getByText('Согласование материалов').first()).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('messages-overview.png'), fullPage: true })

  await page.getByRole('tab', { name: /Важное/ }).click()
  await page.getByRole('button', { name: /Результат задачи возвращён/ }).click()
  expect(state.importantUnread).toBe(false)

  await page.getByRole('tab', { name: /Обращения/ }).click()
  await page.getByRole('link', { name: /Согласование материалов/ }).click()
  await expect(page.getByRole('heading', { name: 'Согласование материалов' })).toBeVisible()
  await expect(page.getByText('Посмотрите, пожалуйста, итоговый вариант.').last()).toBeVisible()
  expect(state.threadUnread).toBe(0)

  await page.getByRole('button', { name: 'Новое письмо' }).click()
  const dialog = page.getByRole('dialog', { name: 'Новое письмо' })
  await expect(dialog).toBeVisible()
  await page.mouse.click(2, 2)
  await expect(dialog).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialog).toBeVisible()

  await dialog.getByLabel('Получатель').selectOption(peerId)
  await dialog.getByLabel('Тема').fill('Письмо с заметкой')
  await dialog.getByLabel('Текст').fill('Прошу посмотреть материалы.')
  await dialog.getByLabel('Заметка').selectOption(noteId)
  await dialog.getByRole('button', { name: 'Отправить' }).dblclick()
  await expect(dialog).toBeHidden()
  expect(state.createCalls).toBe(1)
  expect(state.createdPayload).toMatchObject({
    recipient_id: peerId,
    subject: 'Письмо с заметкой',
    body: 'Прошу посмотреть материалы.',
    quick_note_id: noteId,
  })
  await noHorizontalOverflow(page)
})

test('mobile list, detail and back navigation', async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.startsWith('iphone-'))
  const state: MockState = {
    directUnread: true,
    importantUnread: true,
    threadUnread: 1,
    createCalls: 0,
    createdPayload: null,
    remoteReplyBody: null,
  }
  await installApiMock(page, state)
  await page.goto('/messages')

  await expect(page.getByRole('heading', { name: 'Сообщения' })).toBeVisible()
  await expect(page.getByText('Согласование материалов').first()).toBeVisible()
  await noHorizontalOverflow(page)
  await page.screenshot({ path: testInfo.outputPath('messages-mobile-list.png'), fullPage: true })

  await page.getByRole('link', { name: /Согласование материалов/ }).click()
  await expect(page.getByRole('heading', { name: 'Согласование материалов' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Назад к списку сообщений' })).toBeVisible()
  await noHorizontalOverflow(page)

  await page.getByRole('link', { name: 'Назад к списку сообщений' }).click()
  await expect(page).toHaveURL(/\/messages$/)
  await expect(page.getByText('Согласование материалов').first()).toBeVisible()
})

test('open thread resyncs when a colleague replies', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-light-messages')
  const state: MockState = {
    directUnread: false,
    importantUnread: false,
    threadUnread: 0,
    createCalls: 0,
    createdPayload: null,
    remoteReplyBody: null,
  }
  await installApiMock(page, state)
  await page.goto(`/messages/${threadId}`)
  await expect(page.getByText('Посмотрите, пожалуйста, итоговый вариант.').last()).toBeVisible()

  const remoteReply = 'Ответ коллеги появился без перезагрузки страницы.'
  state.remoteReplyBody = remoteReply
  await page.evaluate((activeThreadId) => {
    const emit = (window as Window & {
      __emitDpmsMessageEvent?: (event: Record<string, string>) => void
    }).__emitDpmsMessageEvent
    emit?.({ type: 'thread.changed', thread_id: activeThreadId })
  }, threadId)

  await expect(page.getByText(remoteReply)).toBeVisible()
})
