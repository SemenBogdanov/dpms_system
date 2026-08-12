import { expect, test, type Page, type Route } from '@playwright/test'

const ownerId = '11111111-1111-4111-8111-111111111111'
const recipientId = '22222222-2222-4222-8222-222222222222'
const noteId = '33333333-3333-4333-8333-333333333333'
const shareId = '44444444-4444-4444-8444-444444444444'
const commentId = '55555555-5555-4555-8555-555555555555'

const testUser = {
  id: ownerId,
  full_name: 'Владелец',
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
  created_at: '2026-08-12T00:00:00Z',
  updated_at: '2026-08-12T00:00:00Z',
}

const baseNote = {
  id: noteId,
  owner_id: ownerId,
  title: 'Заметка реального времени',
  body: 'Исходный текст',
  context: '',
  status: 'draft' as const,
  tags: [],
  revision: 1,
  created_at: '2026-08-12T00:00:00Z',
  updated_at: '2026-08-12T00:00:00Z',
}

const sharedNote = {
  share: {
    id: shareId,
    note_id: noteId,
    owner_id: ownerId,
    owner_name: 'Владелец',
    owner_email: 'owner@example.com',
    recipient_id: recipientId,
    recipient_name: 'Коллега',
    recipient_email: 'peer@example.com',
    status: 'active' as const,
    created_at: '2026-08-12T00:00:00Z',
    updated_at: '2026-08-12T00:00:00Z',
  },
  note: baseNote,
}

const contact = {
  id: '66666666-6666-4666-8666-666666666666',
  requester_id: ownerId,
  recipient_id: recipientId,
  requester_name: 'Владелец',
  requester_email: 'owner@example.com',
  recipient_name: 'Коллега',
  recipient_email: 'peer@example.com',
  status: 'accepted' as const,
  direction: 'outgoing' as const,
  created_at: '2026-08-12T00:00:00Z',
  updated_at: '2026-08-12T00:00:00Z',
}

interface MockState {
  note: typeof baseNote
  comments: Array<Record<string, unknown>>
  shares: Array<Record<string, unknown>>
  patchStatus: number
  patchResponse: Record<string, unknown>
  wsEvents: Array<Record<string, unknown>>
}

type LiveSocketProbe = {
  url: string
  readyState: number
  _sent: string[]
  onclose: ((event: { code?: number }) => void) | null
}

type LiveTestWindow = Window & {
  __liveSockets: LiveSocketProbe[]
  __pushLiveEvent: (event: Record<string, unknown>) => void
}

async function pushLiveEvent(page: Page, event: Record<string, unknown>) {
  await page.evaluate((payload) => {
    const liveWindow = window as LiveTestWindow
    liveWindow.__pushLiveEvent(payload)
  }, event)
}

function makeNote(updated: Partial<typeof baseNote> = {}) {
  return { ...baseNote, ...updated }
}

/**
 * Live-WS mock: перехватывает window.WebSocket и кладёт события в очередь,
 * которая отправляется при onopen. Тесты двигают wsEvents.
 */
async function installLiveMock(page: Page) {
  await page.addInitScript(`
    window.__liveSockets = [];
    window.__liveEvents = window.__liveEvents || [];
    class MockWebSocket {
      static instances() { return window.__liveSockets }
      constructor(url) {
        this.url = url;
        this.readyState = 0;
        this.onopen = null; this.onmessage = null; this.onclose = null; this.onerror = null;
        this._sent = [];
        window.__liveSockets.push(this);
        window.setTimeout(() => { this.readyState = 1; if (this.onopen) this.onopen(); }, 0);
      }
      send(data) {
        this._sent.push(data);
        window.dispatchEvent(new CustomEvent('ws:sent',{detail:data}));
        try {
          const payload = JSON.parse(data);
          if (payload.type === 'auth') {
            const noteId = this.url.split('/').slice(-2, -1)[0];
            window.setTimeout(() => this.emit({ type: 'ready', note_id: noteId, active_users: 1 }), 0);
          }
        } catch (e) {}
      }
      close() { this.readyState = 3; if (this.onclose) this.onclose({}); }
      emit(event) { if (this.onmessage) this.onmessage({ data: JSON.stringify(event) }); }
    }
    window.WebSocket = MockWebSocket;
    window.__pushLiveEvent = (event) => {
      window.__liveEvents.push(event);
      window.__liveSockets.forEach(s => { try { s.emit(event); } catch(e){} });
    };
    window.__resetLiveEvents = () => { window.__liveEvents = []; };
  `)
  return {
    pushEvent: (event: Record<string, unknown>) => pushLiveEvent(page, event),
    lastAuth: () => page.evaluate(() => {
      const sockets = (window as LiveTestWindow).__liveSockets
      if (!sockets.length) return null
      const sent = sockets[sockets.length - 1]._sent
      return sent.length ? JSON.parse(sent[sent.length - 1]) : null
    }),
    closeLast: () => page.evaluate(() => {
      const sockets = (window as LiveTestWindow).__liveSockets
      if (!sockets.length) return
      const s = sockets[sockets.length - 1]
      s.readyState = 3
      if (s.onclose) s.onclose({})
    }),
    terminateAndReopen: () => page.evaluate(() => {
      const sockets = (window as LiveTestWindow).__liveSockets
      if (!sockets.length) return
      const s = sockets[sockets.length - 1]
      s.readyState = 3
      if (s.onclose) s.onclose({})
    }),
  }
}

async function installRoutes(
  page: Page,
  getState: () => MockState,
  setState: (next: MockState) => void,
  asShared = false,
) {
  await page.route('**/api/**', async (route: Route) => {
    const request = route.request()
    const method = request.method()
    const url = new URL(request.url())
    const pathname = url.pathname

    if (pathname === '/api/auth/me') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(testUser) })
      return
    }

    const state = getState()

    if (pathname === '/api/quick-notes' && method === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
      return
    }
    if (pathname === '/api/quick-notes/shared' && method === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(asShared ? [{ ...sharedNote, note: state.note }] : []),
      })
      return
    }
    if (pathname === '/api/contacts' && method === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([contact]) })
      return
    }
    if (pathname === `/api/quick-notes/${noteId}` && method === 'GET') {
      if (asShared) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ ...sharedNote, note: state.note }),
        })
        return
      }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(state.note) })
      return
    }
    if (pathname === `/api/quick-notes/${noteId}` && method === 'PATCH') {
      if (state.patchStatus !== 200) {
        await route.fulfill({
          status: state.patchStatus,
          contentType: 'application/json',
          body: JSON.stringify(state.patchResponse),
        })
        return
      }
      let body: Record<string, unknown> = {}
      try { body = JSON.parse(request.postData() ?? '{}') } catch { /* ignore */ }
      const next = makeNote({
        ...state.note,
        title: (body.title as string | null | undefined) ?? state.note.title,
        body: (body.body as string | undefined) ?? state.note.body,
        context: (body.context as string | null | undefined) ?? state.note.context,
        tags: (body.tags as string[] | undefined) ?? state.note.tags,
        revision: state.note.revision + 1,
        updated_at: '2026-08-12T01:00:00Z',
      })
      setState({ ...state, note: next })
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(next) })
      return
    }
    if (pathname === `/api/quick-notes/${noteId}/comments` && method === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(state.comments) })
      return
    }
    if (pathname === `/api/quick-notes/${noteId}/comments` && method === 'POST') {
      let body: Record<string, unknown> = {}
      try { body = JSON.parse(request.postData() ?? '{}') } catch { /* ignore */ }
      const comment = {
        id: commentId,
        note_id: noteId,
        author_id: ownerId,
        author_name: 'Владелец',
        author_email: 'owner@example.com',
        parent_id: body.parent_id ?? null,
        body: body.body ?? '',
        created_at: '2026-08-12T01:00:00Z',
      }
      setState({ ...state, comments: [...state.comments, comment] })
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(comment) })
      return
    }
    if (pathname === `/api/quick-notes/${noteId}/attachments` && method === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
      return
    }
    if (pathname === `/api/quick-notes/${noteId}/shares` && method === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(state.shares) })
      return
    }
    if (pathname === '/api/work-entities/links/by-target' && method === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
      return
    }
    if (pathname === '/api/work-entities' && method === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
      return
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(method === 'GET' ? [] : {}) })
  })
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('dpms_token', 'realtime-test-token'))
})

test.describe('Realtime notes v1', () => {
  test('live comment propagation', async ({ page }) => {
    let state: MockState = {
      note: makeNote(),
      comments: [
        { id: commentId, note_id: noteId, author_id: recipientId, author_name: 'Коллега', author_email: 'peer@example.com', parent_id: null, body: 'Первый комментарий', created_at: '2026-08-12T00:30:00Z' },
      ],
      shares: [],
      patchStatus: 200,
      patchResponse: {},
      wsEvents: [],
    }
    const setState = (next: MockState) => { state = next }
    const getState = () => state
    await installRoutes(page, getState, setState)
    await installLiveMock(page)

    await page.goto('/quick-notes/' + noteId)
    await expect(page.getByText('Первый комментарий')).toBeVisible()

    setState({ ...state, comments: [
      ...(state.comments),
      { id: 'c2', note_id: noteId, author_id: recipientId, author_name: 'Коллега', author_email: 'peer@example.com', parent_id: null, body: 'Новый комментарий из эфира', created_at: '2026-08-12T00:40:00Z' },
    ] })
    await pushLiveEvent(page, {
      type: 'comment.created',
      note_id: noteId,
    })
    // coalesced resync: single batch reload fetches comments
    await expect(page.getByText('Новый комментарий из эфира')).toBeVisible()

    const auth = await page.evaluate(() => {
      const sockets = (window as LiveTestWindow).__liveSockets
      const sent = sockets.length ? sockets[0]._sent : []
      return sent.length ? JSON.parse(sent[0]) : null
    })
    expect(auth).toEqual({ type: 'auth', token: 'realtime-test-token' })

    const socketUrl = await page.evaluate(
      () => (window as LiveTestWindow).__liveSockets[0]?.url ?? '',
    )
    expect(socketUrl).not.toContain('realtime-test-token')

    await expect(page.getByRole('status')).toContainText('В эфире')
  })

  test('editor is owner-only for shared recipient', async ({ page }) => {
    let state: MockState = {
      note: makeNote(),
      comments: [],
      shares: [],
      patchStatus: 200,
      patchResponse: {},
      wsEvents: [],
    }
    const setState = (next: MockState) => { state = next }
    const getState = () => state
    await installRoutes(page, getState, setState, /* asShared */ true)
    await installLiveMock(page)

    await page.goto('/quick-notes/' + noteId)
    await page.getByRole('button', { name: 'Редактировать заметку' }).waitFor({ state: 'hidden' })

    await expect(page.getByRole('button', { name: 'Редактировать заметку' })).toBeHidden()
    await expect(page.getByRole('button', { name: 'Удалить заметку' })).toBeHidden()
    await expect(page.getByRole('button', { name: 'Настроить доступ к заметке' })).toBeHidden()
    await expect(page.getByText('от Владелец')).toBeVisible()
    await expect(page.getByPlaceholder('Комментарий к заметке')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Добавить в проект или цель' })).toBeHidden()
  })

  test('shared recipient receives saved owner text without an editor', async ({ page }) => {
    let state: MockState = {
      note: makeNote({ body: 'Текст до сохранения' }),
      comments: [],
      shares: [],
      patchStatus: 200,
      patchResponse: {},
      wsEvents: [],
    }
    const setState = (next: MockState) => { state = next }
    const getState = () => state
    await installRoutes(page, getState, setState, true)
    await installLiveMock(page)

    await page.goto('/quick-notes/' + noteId)
    await expect(page.getByText('Текст до сохранения')).toBeVisible()

    setState({
      ...state,
      note: makeNote({
        body: 'Сохранённая правка владельца',
        revision: 2,
        updated_at: '2026-08-12T00:45:00Z',
      }),
    })
    await pushLiveEvent(page, {
      type: 'note.updated',
      note_id: noteId,
      revision: 2,
    })

    await expect(page.getByText('Сохранённая правка владельца')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Редактировать заметку' })).toBeHidden()
    await expect(page.getByPlaceholder('Комментарий к заметке')).toBeVisible()
  })

  test('dirty remote conflict surfaces 409 and keeps local text', async ({ page }) => {
    let state: MockState = {
      note: makeNote({ body: 'Исходный текст' }),
      comments: [],
      shares: [],
      patchStatus: 200,
      patchResponse: {},
      wsEvents: [],
    }
    const setState = (next: MockState) => { state = next }
    const getState = () => state
    await installRoutes(page, getState, setState)
    await installLiveMock(page)

    await page.goto('/quick-notes/' + noteId)
    await page.getByRole('button', { name: 'Редактировать заметку' }).click()
    const bodyField = page.getByPlaceholder('Текст заметки')
    await bodyField.fill('Локальная правка')

    // remote update arrives while editor is dirty
    setState({ ...state, note: makeNote({ body: 'Удалённая правка', revision: 2, updated_at: '2026-08-12T00:50:00Z' }) })
    await pushLiveEvent(page, { type: 'note.updated', note_id: noteId })
    await expect(page.getByText('Заметка обновлена с другого устройства')).toBeVisible()
    await expect(page.getByPlaceholder('Текст заметки')).toHaveValue('Локальная правка')

    // making the next PATCH return 409
    setState({ ...getState(), patchStatus: 409, patchResponse: { detail: 'Версия заметки устарела. Загрузите актуальную версию.' } })
    await page.getByRole('button', { name: 'Сохранить' }).click()
    await expect(page.getByText('Версия устарела', { exact: true })).toBeVisible()
    await expect(page.getByPlaceholder('Текст заметки')).toHaveValue('Локальная правка')
    await expect(page.getByRole('button', { name: 'Загрузить актуальную версию' })).toBeVisible()

    // accept fresh version loads remote text
    setState({ ...getState(), patchStatus: 200 })
    page.once('dialog', (d) => d.accept())
    await page.getByRole('button', { name: 'Загрузить актуальную версию' }).click()
    await expect(page.getByPlaceholder('Текст заметки')).toHaveValue('Удалённая правка')
  })

  test('reconnect triggers resync after closure', async ({ page }) => {
    let state: MockState = {
      note: makeNote({ body: 'До реконнекта' }),
      comments: [],
      shares: [],
      patchStatus: 200,
      patchResponse: {},
      wsEvents: [],
    }
    const setState = (next: MockState) => { state = next }
    const getState = () => state
    await installRoutes(page, getState, setState)
    const live = await installLiveMock(page)

    await page.goto('/quick-notes/' + noteId)
    await expect(page.getByText('До реконнекта')).toBeVisible()

    await live.closeLast()
    await expect(page.getByRole('status')).toContainText('Переподключение')
    await page.waitForTimeout(1100)
    // backend changed while disconnected
    setState({ ...state, note: makeNote({ body: 'После реконнекта', revision: 3, updated_at: '2026-08-12T02:00:00Z' }) })
    // ready event after reconnect should trigger full resync
    await pushLiveEvent(page, { type: 'ready', note_id: noteId, active_users: 1 })
    await expect(page.getByText('После реконнекта')).toBeVisible()
    await expect(page.getByRole('status')).toContainText('В эфире')
  })

  test('access revoked navigates back with toast', async ({ page }) => {
    let state: MockState = {
      note: makeNote(),
      comments: [],
      shares: [],
      patchStatus: 200,
      patchResponse: {},
      wsEvents: [],
    }
    const setState = (next: MockState) => { state = next }
    const getState = () => state
    await installRoutes(page, getState, setState, /* asShared */ true)
    await installLiveMock(page)

    await page.goto('/quick-notes/' + noteId)
    await expect(page.getByText('от Владелец')).toBeVisible()

    await pushLiveEvent(page, { type: 'access.revoked', note_id: noteId })
    await expect(page).toHaveURL(/\/quick-notes$/, { timeout: 10_000 })
    await expect(page.getByText('Доступ к заметке закрыт')).toBeVisible()
  })
})
