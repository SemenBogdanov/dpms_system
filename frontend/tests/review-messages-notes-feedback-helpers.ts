import { type Page, type Route } from '@playwright/test'
import { fixture, stamp, user } from './review-main-helpers'

export const peerId = '22222222-2222-4222-8222-222222222222'
export const ids = ['33333333-3333-4333-8333-333333333333', '44444444-4444-4444-8444-444444444444']
export const groupId = '55555555-5555-4555-8555-555555555555'
export const note = (id = ids[0], title = 'Заметка A') => ({
  id, title, owner_id: user.id, body: 'Исходный текст', context: '', tags: [],
  status: 'draft', revision: 1, group_id: null as string | null, created_at: stamp, updated_at: stamp,
})
export const thread = (id = ids[0], subject = 'Переписка A') => ({
  id, subject, created_by_id: user.id, participants: [
    { user_id: user.id, full_name: user.full_name, email: user.email },
    { user_id: peerId, full_name: 'Коллега', email: 'peer@example.invalid' },
  ], last_post_preview: subject, last_post_at: stamp, unread_count: 0,
  created_at: stamp, updated_at: stamp, posts: [],
})
export const feedback = (id = ids[0], title = 'Обращение A') => ({
  id, title, feedback_code: `FB-${id.slice(0, 4)}`, category: 'improvement', priority: 'medium',
  description: 'Описание обращения', status: 'new', object_type: 'other', object_ref: 'Контекст A',
  expected_result: 'Результат A', impact: 'Влияние A', evidence_links: ['https://example.invalid/a'],
  reviewer_id: user.id, reviewer_name: user.full_name, resolution: 'Решение A',
  decision_summary: 'Итог A', decision_reason: 'Причина A', next_action: 'Действие A', target_release: 'Релиз A',
  author_id: user.id, author_name: user.full_name, created_at: stamp, updated_at: stamp,
  reviewed_at: null, decided_at: null, closed_at: null, decided_by_name: null,
})

export function gate() {
  let release!: () => void
  const promise = new Promise<void>(resolve => { release = resolve })
  return { promise, release }
}

export type Seen = { method: string; path: string; body: Record<string, unknown> }
export async function workerFixture(page: Page, override?: (route: Route, url: URL) => Promise<boolean>) {
  const writes: Seen[] = []
  const notes = [note(), note(ids[1], 'Заметка B')]
  const threads = [thread(), thread(ids[1], 'Переписка B')]
  const requests = [feedback()]
  await fixture(page, async (route, url) => {
    const method = route.request().method(), path = url.pathname
    const body = method === 'GET' ? {} : (route.request().postDataJSON() ?? {}) as Record<string, unknown>
    if (method !== 'GET') writes.push({ method, path, body })
    if (override && await override(route, url)) return true
    const respond = async (json: unknown) => { await route.fulfill({ json }); return true }
    if (path === '/api/auth/me') return respond({ ...user, feedback_enabled: true })
    if (path === '/api/contacts') return respond([{
      id: 'contact', requester_id: user.id, recipient_id: peerId, requester_name: user.full_name,
      requester_email: user.email, recipient_name: 'Коллега', recipient_email: 'peer@example.invalid',
      status: 'accepted', direction: 'outgoing', created_at: stamp, updated_at: stamp,
    }])
    if (path === '/api/messages/threads') {
      if (method === 'POST') return respond({ ...threads[1], subject: body.subject })
      return respond(threads)
    }
    const selectedThread = threads.find(item => path === `/api/messages/threads/${item.id}`)
    if (selectedThread) return respond(selectedThread)
    if (path.endsWith('/posts') || path.endsWith('/read')) return respond({})
    if (path === '/api/quick-notes') {
      if (method === 'POST') { const created = { ...note('new-note'), ...body }; notes.push(created); return respond(created) }
      return respond(notes.filter(item => {
        if (url.searchParams.has('group_id') && item.group_id !== url.searchParams.get('group_id')) return false
        if (url.searchParams.has('ungrouped') && item.group_id) return false
        const search = url.searchParams.get('search')
        return !search || item.title.includes(search)
      }))
    }
    const selectedNote = notes.find(item => path === `/api/quick-notes/${item.id}`)
    if (selectedNote) {
      if (method === 'PATCH') Object.assign(selectedNote, body, { revision: selectedNote.revision + 1 })
      return respond(selectedNote)
    }
    if (path.endsWith('/comments') && method === 'POST') return respond({ id: 'comment', ...body })
    if (path === '/api/personal-tasks' && method === 'POST') return respond({ id: 'task', ...body })
    if (path === '/api/note-groups') return respond([{
      id: groupId, title: 'Группа', position: 0, collapsed: false, archived: false, revision: 1, note_count: 0,
    }])
    if (path === '/api/note-groups/share/recipients') return respond([{ id: peerId, name: 'Коллега' }])
    if (path === '/api/feedback') {
      if (method === 'POST') {
        const created = { ...feedback(ids[1], String(body.title)), ...body, reviewer_id: '', resolution: '',
          decision_summary: '', decision_reason: '', next_action: '', target_release: '' }
        requests.push(created)
        return respond(created)
      }
      return respond({ items: requests, total: requests.length })
    }
    if (path.startsWith('/api/feedback/') && method === 'PATCH') {
      const item = requests.find(value => path.endsWith(value.id))!
      Object.assign(item, body)
      return respond(item)
    }
    return false
  })
  // All sockets terminate here, including attention and note realtime channels.
  await page.routeWebSocket('**', socket => {
    socket.onMessage(message => {
      const event = JSON.parse(String(message)) as { type?: string }
      if (event.type === 'auth') socket.send(JSON.stringify({ type: 'ready' }))
      if (event.type === 'ping') socket.send(JSON.stringify({ type: 'pong' }))
    })
  })
  return { writes, notes, threads, requests }
}

export async function navigateWithinApp(page: Page, path: string) {
  await page.evaluate(next => {
    window.history.pushState({}, '', next)
    window.dispatchEvent(new PopStateEvent('popstate'))
  }, path)
}
