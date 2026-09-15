import assert from 'node:assert/strict'
import test from 'node:test'
import { hookHarness, loadSource } from './calendar-access-harness.mjs'

const access = loadSource('src/lib/access.ts')
const granted = { role: 'admin', audit_calendar_enabled: true, audit_enabled: false, task_workspace_enabled: false }
const revoked = { ...granted, role: 'executor', audit_calendar_enabled: false }

function setup() {
  const runtime = hookHarness()
  const requests = []
  let storedSession = 'synthetic-session'
  const browser = new EventTarget()
  const doc = new EventTarget()
  doc.visibilityState = 'visible'
  browser.location = { href: '/' }
  let interval
  browser.setInterval = (callback) => { interval = callback; return 1 }
  browser.clearInterval = () => { interval = undefined }
  const { AuthProvider } = loadSource('src/contexts/AuthContext.tsx', {
    react: runtime.hooks,
    '@/api/client': { api: {
      get: () => new Promise((resolve, reject) => requests.push({ resolve, reject })),
      post: async () => ({ user: revoked, access_token: 'synthetic-next-session' }),
    } },
    '@/lib/auth': {
      getToken: () => storedSession,
      setToken: (value) => { storedSession = value },
      clearToken: () => { storedSession = null },
    },
  }, { window: browser, document: doc })
  const value = () => runtime.render(AuthProvider).props.value
  value()
  runtime.flushEffects()
  return {
    requests, value, browser, doc, runtime,
    tick: () => interval?.(),
    clearSession: () => { storedSession = null },
  }
}

async function settle() { await Promise.resolve(); await Promise.resolve() }

test('focus/visibility refresh cannot restore a stale role or grant', async () => {
  const h = setup()
  h.requests[0].resolve(granted)
  await settle()
  h.browser.dispatchEvent(new Event('focus'))
  h.doc.dispatchEvent(new Event('visibilitychange'))
  h.requests[2].resolve(revoked)
  await settle()
  h.requests[1].resolve(granted)
  await settle()
  assert.equal(h.value().user.role, 'executor')
  assert.equal(access.hasAuditCalendarAccess(h.value().user), false)
})

test('stale denial cannot hide a newly granted calendar', async () => {
  const h = setup()
  h.requests[0].resolve(revoked)
  await settle()
  h.tick()
  h.browser.dispatchEvent(new Event('focus'))
  h.requests[2].resolve(granted)
  await settle()
  h.requests[1].resolve(revoked)
  await settle()
  assert.equal(access.hasAuditCalendarAccess(h.value().user), true)
})

test('obsolete refresh failure does not erase a newer profile', async () => {
  const h = setup()
  const newest = h.value().retryAuth()
  h.requests[1].resolve(granted)
  await newest
  h.requests[0].reject(new Error('synthetic unavailable'))
  await settle()
  assert.deepEqual(h.value().user, granted)
  assert.equal(h.value().authError, null)
  assert.equal(h.value().loading, false)
})

test('silent refresh superseding startup clears loading', async () => {
  const h = setup()
  h.tick()
  h.requests[1].resolve(granted)
  await settle()
  assert.equal(h.value().loading, false)
  h.requests[0].resolve(revoked)
  await settle()
  assert.deepEqual(h.value().user, granted)
})

for (const action of ['updateUser', 'login', 'logout']) {
  test(`${action} invalidates an in-flight profile refresh`, async () => {
    const h = setup()
    if (action === 'updateUser') h.value().updateUser(revoked)
    if (action === 'login') await h.value().login('synthetic@example.com', 'synthetic-only')
    if (action === 'logout') h.value().logout()
    h.requests[0].resolve(granted)
    await settle()
    assert.deepEqual(h.value().user, action === 'logout' ? null : revoked)
    assert.equal(access.hasAuditCalendarAccess(h.value().user), false)
    assert.equal(h.value().loading, false)
  })
}

test('a cleared session cannot be repopulated by an old successful refresh', async () => {
  const h = setup()
  h.clearSession()
  h.requests[0].resolve(granted)
  await settle()
  assert.equal(h.value().user, null)
  assert.equal(h.value().loading, false)
})

test('the latest session rejection still denies access', async () => {
  const h = setup()
  h.requests[0].resolve(granted)
  await settle()
  const retry = h.value().retryAuth()
  h.clearSession()
  h.requests[1].reject(new Error('synthetic session revoked'))
  await retry
  assert.equal(h.value().user, null)
  assert.equal(h.value().token, null)
  assert.equal(h.value().loading, false)
})

test('hidden tabs do not poll and unmount removes refresh listeners', async () => {
  const h = setup()
  h.doc.visibilityState = 'hidden'
  h.tick()
  h.browser.dispatchEvent(new Event('focus'))
  assert.equal(h.requests.length, 1)
  h.runtime.unmount()
  h.doc.visibilityState = 'visible'
  h.browser.dispatchEvent(new Event('focus'))
  h.doc.dispatchEvent(new Event('visibilitychange'))
  h.tick()
  assert.equal(h.requests.length, 1)
  h.requests[0].resolve(granted)
  await settle()
  assert.equal(h.value().user, null)
})
