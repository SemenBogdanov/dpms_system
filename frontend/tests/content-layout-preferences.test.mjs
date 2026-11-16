import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import ts from 'typescript'

function loadSource(path, dependencies = {}, browser) {
  const source = readFileSync(new URL(`../${path}`, import.meta.url), 'utf8')
  const compiled = ts.transpileModule(source, {
    fileName: path,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    reportDiagnostics: true,
  })
  assert.deepEqual(compiled.diagnostics, [])
  const module = { exports: {} }
  const require = (name) => {
    assert.ok(Object.hasOwn(dependencies, name), `Unexpected dependency: ${name}`)
    return dependencies[name]
  }
  new Function('require', 'module', 'exports', 'window', compiled.outputText)(
    require, module, module.exports, browser,
  )
  return module.exports
}

const access = loadSource('src/lib/access.ts')
const nav = loadSource('src/lib/sidebarNavigation.ts', {
  '@/lib/access': access,
  'lucide-react': new Proxy({}, { get: (_target, name) => name }),
})
const modelDependencies = { '@/lib/access': access, '@/lib/sidebarNavigation': nav }
const model = loadSource('src/lib/contentLayout.ts', modelDependencies)
const preference = (marginPercent, fullWidth = false) => ({ fullWidth, marginPercent })
const encode = (sections) => JSON.stringify({ version: 1, sections })
const sectionKeysFor = (...userIds) => new Set(userIds.flatMap((userId) =>
  model.contentLayoutSections.map(({ id }) => model.contentLayoutStorageKey(userId, id))))

function createBrowser(data = new Map()) {
  const browser = new EventTarget()
  const reads = []
  const writes = []
  const listeners = new Set()
  const failures = { getter: false, read: false, write: false }
  const storage = {
    getItem(key) {
      reads.push(key)
      if (failures.read) throw new Error('Synthetic read denial')
      return data.get(key) ?? null
    },
    setItem(key, value) {
      writes.push([key, value])
      if (failures.write) throw new Error('Synthetic quota denial')
      data.set(key, value)
    },
  }
  Object.defineProperty(browser, 'localStorage', { get() {
    if (failures.getter) throw new Error('Synthetic storage access denial')
    return storage
  } })
  const addEventListener = browser.addEventListener.bind(browser)
  const removeEventListener = browser.removeEventListener.bind(browser)
  browser.addEventListener = (type, listener) => {
    assert.equal(type, 'storage')
    listeners.add(listener)
    addEventListener(type, listener)
  }
  browser.removeEventListener = (type, listener) => {
    listeners.delete(listener)
    removeEventListener(type, listener)
  }
  return {
    browser, data, reads, writes, failures, listeners,
    dispatch(key, newValue = data.get(key) ?? null, storageArea = storage) {
      const event = new Event('storage')
      Object.defineProperties(event, {
        key: { value: key }, newValue: { value: newValue }, storageArea: { value: storageArea },
      })
      browser.dispatchEvent(event)
    },
  }
}

function createRuntime(browser) {
  let active
  const hooks = {
    useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot) {
      const instance = active
      if (instance.subscribe !== subscribe) {
        instance.cleanup?.()
        instance.subscribe = subscribe
        instance.cleanup = subscribe(() => { instance.notifications += 1 })
      }
      instance.getSnapshot = getSnapshot
      instance.getServerSnapshot = getServerSnapshot
      assert.equal(getSnapshot(), getSnapshot(), 'Snapshots must have stable identity')
      assert.equal(getServerSnapshot(), getServerSnapshot(), 'Server snapshots must be stable')
      return getSnapshot()
    },
  }
  const storage = loadSource('src/lib/preferenceStorage.ts', {}, browser)
  const { useContentLayoutPreferences } = loadSource('src/hooks/useContentLayoutPreferences.ts', {
    react: hooks, '@/lib/contentLayout': model, '@/lib/preferenceStorage': storage,
  }, browser)
  return {
    mount(initialUserId) {
      let userId = initialUserId
      const instance = {
        notifications: 0,
        value() {
          active = instance
          try { return useContentLayoutPreferences(userId) } finally { active = undefined }
        },
        switchUser(nextUserId) { userId = nextUserId; return instance.value() },
        unmount() { instance.cleanup?.(); instance.subscribe = undefined },
      }
      instance.value()
      return instance
    },
  }
}

function setup(data) {
  const browser = createBrowser(data)
  return { ...browser, ...createRuntime(browser.browser) }
}

test('registry contains the 23 sidebar routes and all three extra routes with exact widths', () => {
  assert.equal(nav.sidebarNav.length, 23)
  assert.equal(model.contentLayoutSections.length, 26)
  assert.equal(new Set(model.contentLayoutSections.map((item) => item.id)).size, 26)
  const widths = {
    queue: 1440, reports: 1440, 'work-entities': 1440, audit: 1440,
    'admin-users': 1440, 'audit-calendar': 1440, calculator: 1120,
    knowledge: 1100, competencies: 1100,
  }
  for (const item of model.contentLayoutSections) {
    const sidebar = nav.sidebarNav.find((entry) => entry.id === item.id)
    assert.equal(item.minWidth, widths[item.id] ?? 960, item.id)
    assert.ok(item.label.trim())
    if (sidebar) {
      assert.equal(item.pathname, sidebar.to)
      assert.equal(item.label, sidebar.label)
    }
  }
  assert.deepEqual(model.contentLayoutSections.slice(23).map(({ id, pathname }) => [id, pathname]), [
    ['profile', '/profile'], ['admin-integrations', '/admin/integrations'], ['admin-usage', '/admin/usage'],
  ])
})

test('all routes match nested paths and ignore query/hash without accepting false prefixes', () => {
  for (const section of model.contentLayoutSections) {
    for (const suffix of ['', '/', '/nested/item', '?q=/unknown', '#/unknown', '/nested?q=1#hash']) {
      assert.equal(model.getSectionForPath(section.pathname + suffix), section)
    }
    assert.equal(model.getSectionForPath(`${section.pathname}-unknown`), undefined)
    assert.equal(model.getSectionForPath(`${section.pathname}other`), undefined)
  }
  for (const path of ['', '/', '/unknown', '/admin', '/Graphs', '/unknown?next=/graphs', '/unknown#/audit']) {
    assert.equal(model.getSectionForPath(path), undefined)
  }
  assert.equal(model.getSectionForPath('/audit-calendar/day').id, 'audit-calendar')
})

test('matching prefers the longest base route independently of registry order', () => {
  const nested = { ...nav.sidebarNav[0], id: 'nested-fixture', to: '/graphs/nested' }
  const extended = loadSource('src/lib/contentLayout.ts', {
    ...modelDependencies, '@/lib/sidebarNavigation': { ...nav, sidebarNav: [...nav.sidebarNav, nested] },
  })
  assert.equal(extended.getSectionForPath('/graphs/nested/item?x=1').id, 'nested-fixture')
  assert.equal(extended.getSectionForPath('/graphs/nested-other').id, 'graphs')
})

test('access exactly follows existing sidebar gates plus profile and admin extras', () => {
  const users = [null]
  for (const role of ['executor', 'teamlead', 'admin']) {
    for (let mask = 0; mask < 64; mask += 1) {
      users.push({
        role,
        task_workspace_enabled: Boolean(mask & 1),
        feedback_enabled: Boolean(mask & 2),
        audit_enabled: Boolean(mask & 4),
        audit_calendar_enabled: Boolean(mask & 8),
        competency_development_enabled: Boolean(mask & 16),
        competency_constructor_enabled: Boolean(mask & 32),
      })
    }
  }
  for (const user of users) {
    const expected = nav.visibleSidebarNav(user).map((item) => item.id)
    if (access.hasTaskWorkspaceAccess(user)) expected.push('profile')
    if (user?.role === 'admin') expected.push('admin-integrations', 'admin-usage')
    assert.deepEqual(model.getContentLayoutSections(user).map((item) => item.id), expected)
  }
})

test('defaults are for presentation only; missing records remain absent', () => {
  assert.deepEqual(model.DEFAULT_CONTENT_LAYOUT_PREFERENCE, { fullWidth: true, marginPercent: 10 })
  assert.equal(model.MAX_CONTENT_MARGIN, 40)
  assert.deepEqual(model.normalizeContentLayoutPreferences({}), {})
  assert.deepEqual(model.parseContentLayoutPreferences(null), {})
  assert.deepEqual(model.parseContentLayoutPreferences(encode({})), {})
  assert.equal(model.contentLayoutStorageKey('synthetic-user'), 'dpms.contentLayout.v1:synthetic-user')
  assert.equal(model.contentLayoutStorageKey('synthetic-user', 'graphs'), 'dpms.contentLayout.v1:synthetic-user:graphs')
  assert.equal(model.contentLayoutStorageKey('synthetic-user', undefined), 'dpms.contentLayout.v1:synthetic-user')
})

test('finite numeric margins clamp before rounding, retaining one decimal', () => {
  for (const [input, expected] of [
    [50, 40], [-12, 0], [-0, 0], [0, 0], [40, 40], [39.99, 40],
    [10.1, 10.1], [10.14, 10.1], [10.16, 10.2], [Number.MAX_VALUE, 40], [-Number.MAX_VALUE, 0],
  ]) {
    for (const fullWidth of [true, false]) {
      assert.deepEqual(model.normalizeContentLayoutPreference(preference(input, fullWidth)), preference(expected, fullWidth))
    }
  }
})

test('malformed records, coercible types and nonfinite margins are ignored, not defaulted', () => {
  const invalid = [null, undefined, [], 'record', true, 1, {}, { fullWidth: true }, { marginPercent: 10 }]
  for (const margin of [NaN, Infinity, -Infinity, '10', null, undefined, {}, []]) invalid.push(preference(margin))
  for (const fullWidth of [0, 1, 'true', 'false', null, undefined, [], {}]) invalid.push({ fullWidth, marginPercent: 10 })
  invalid.push(Object.create(preference(10)))
  for (const record of invalid) {
    assert.equal(model.normalizeContentLayoutPreference(record), undefined)
    assert.deepEqual(model.normalizeContentLayoutPreferences({ graphs: record, queue: preference(12) }), {
      queue: preference(12),
    })
  }
  const inherited = Object.create({ graphs: preference(10) })
  inherited.queue = preference(12)
  assert.deepEqual(model.normalizeContentLayoutPreferences(inherited), { queue: preference(12) })
})

test('unknown and prototype-like ids are discarded and inputs are not mutated', () => {
  const raw = JSON.parse('{"graphs":{"fullWidth":false,"marginPercent":50,"extra":1},"unknown":{"fullWidth":false,"marginPercent":8},"__proto__":{"fullWidth":true,"marginPercent":2},"constructor":{"fullWidth":true,"marginPercent":3}}')
  Object.freeze(raw.graphs)
  Object.freeze(raw)
  const expected = { graphs: preference(40) }
  assert.deepEqual(model.normalizeContentLayoutPreferences(raw), expected)
  assert.equal(raw.graphs.marginPercent, 50)
  assert.deepEqual(JSON.parse(model.serializeContentLayoutPreferences(raw)), { version: 1, sections: expected })
  assert.deepEqual(model.parseContentLayoutPreferences(model.serializeContentLayoutPreferences(raw)), expected)
})

test('malformed, unsupported-version and oversized storage safely produce an empty record', () => {
  for (const raw of [
    undefined, null, '', '{', 'null', 'true', '[]', '{}',
    JSON.stringify({ version: '1', sections: { graphs: preference(10) } }),
    JSON.stringify({ version: 2, sections: { graphs: preference(10) } }),
    JSON.stringify({ sections: { graphs: preference(10) } }),
    encode(null), encode([]), encode('invalid'),
    '{"version":1,"sections":{"graphs":{"fullWidth":true,"marginPercent":1e400}}}',
    JSON.stringify({ version: 1, sections: { graphs: preference(10) }, padding: 'x'.repeat(16_384) }),
  ]) assert.deepEqual(model.parseContentLayoutPreferences(raw), {})
  const all = Object.fromEntries(model.contentLayoutSections.map(({ id }) => [id, preference(40)]))
  assert.deepEqual(model.parseContentLayoutPreferences(encode(all)), all)
})

test('mount does not persist defaults and snapshots/callbacks are stable', () => {
  const h = setup()
  const first = h.mount('a')
  const before = first.value()
  assert.deepEqual(before.preferences, {})
  assert.equal(first.value().preferences, before.preferences)
  assert.equal(first.value().setPreference, before.setPreference)
  assert.equal(first.value().resetPreference, before.resetPreference)
  assert.deepEqual(first.getServerSnapshot(), {})
  assert.deepEqual(h.writes, [])
  assert.deepEqual(new Set(h.reads), sectionKeysFor('a'))
  first.unmount()
  assert.equal(h.listeners.size, 0)
})

test('missing users cannot read or write storage, even via reset', () => {
  const h = setup()
  const hook = h.mount(undefined)
  for (const user of [undefined, null, '']) {
    const value = hook.switchUser(user)
    assert.deepEqual(value.preferences, {})
    assert.equal(value.setPreference('graphs', preference(10)), false)
    assert.equal(value.resetPreference('graphs'), false)
  }
  assert.deepEqual(h.reads, [])
  assert.deepEqual(h.writes, [])
  assert.equal(h.listeners.size, 0)
})

test('same-tab instances share updates, immutable snapshots and durable write outcomes', () => {
  const h = setup()
  const first = h.mount('a')
  const second = h.mount('a')
  const initial = first.value().preferences
  const input = preference(50)
  assert.equal(first.value().setPreference('graphs', input), true)
  assert.equal(first.notifications, 1)
  assert.equal(second.notifications, 1)
  const snapshot = second.value().preferences
  assert.notEqual(snapshot, initial)
  assert.equal(snapshot, first.value().preferences)
  assert.deepEqual(snapshot, { graphs: preference(40) })
  input.marginPercent = 1
  assert.equal(snapshot.graphs.marginPercent, 40)
  assert.ok(Object.isFrozen(snapshot))
  assert.ok(Object.isFrozen(snapshot.graphs))
  assert.throws(() => { snapshot.graphs.marginPercent = 2 }, TypeError)
  assert.deepEqual(JSON.parse(h.data.get(model.contentLayoutStorageKey('a', 'graphs'))), {
    version: 1, sections: { graphs: preference(40) },
  })
  assert.equal(h.data.has(model.contentLayoutStorageKey('a')), false)
  assert.equal(second.value().setPreference('graphs', preference(40)), true)
  assert.equal(second.value().preferences, snapshot)
  assert.equal(second.notifications, 1)
  first.unmount()
  assert.equal(h.listeners.size, 1)
  second.unmount()
  assert.equal(h.listeners.size, 0)
})

test('reset deletes just the selected override and the result survives a new runtime', () => {
  const h = setup()
  const hook = h.mount('a')
  hook.value().setPreference('graphs', preference(10))
  hook.value().setPreference('queue', preference(15, true))
  assert.equal(hook.value().resetPreference('graphs'), true)
  assert.deepEqual(hook.value().preferences, { queue: preference(15, true) })
  assert.equal(h.data.get(model.contentLayoutStorageKey('a', 'graphs')), encode({}))
  assert.equal(h.data.get(model.contentLayoutStorageKey('a', 'queue')), encode({ queue: preference(15, true) }))
  const reloaded = createRuntime(h.browser).mount('a')
  assert.deepEqual(reloaded.value().preferences, { queue: preference(15, true) })
  assert.equal(hook.value().resetPreference('queue'), true)
  assert.deepEqual(hook.value().preferences, {})
  assert.equal(h.data.get(model.contentLayoutStorageKey('a', 'queue')), encode({}))
  assert.equal(h.data.get(model.contentLayoutStorageKey('a', 'graphs')), encode({}))
  assert.equal(h.data.has(model.contentLayoutStorageKey('a')), false)
})

test('user changes immediately isolate snapshots, writes and reset operations', () => {
  const h = setup(new Map([
    [model.contentLayoutStorageKey('a', 'graphs'), encode({ graphs: preference(11) })],
    [model.contentLayoutStorageKey('b', 'queue'), encode({ queue: preference(22) })],
  ]))
  const hook = h.mount('a')
  const a = hook.value()
  assert.deepEqual(hook.switchUser('b').preferences, { queue: preference(22) })
  assert.equal(hook.value().setPreference('graphs', preference(3)), true)
  assert.deepEqual(JSON.parse(h.data.get(model.contentLayoutStorageKey('a', 'graphs'))).sections, { graphs: preference(11) })
  assert.equal(a.setPreference('graphs', preference(17)), true)
  assert.deepEqual(hook.value().preferences, { queue: preference(22), graphs: preference(3) })
  assert.deepEqual(hook.switchUser(null).preferences, {})
  const writes = h.writes.length
  assert.equal(hook.value().setPreference('graphs', preference(7)), false)
  assert.equal(h.writes.length, writes)
  assert.deepEqual(hook.switchUser('a').preferences, { graphs: preference(17) })
  hook.value().resetPreference('graphs')
  assert.deepEqual(hook.switchUser('b').preferences, { queue: preference(22), graphs: preference(3) })
  assert.ok(h.reads.every((key) => sectionKeysFor('a', 'b').has(key)))
  assert.ok(h.writes.every(([key]) => sectionKeysFor('a', 'b').has(key)))
})

test('cross-tab changes sync only the matching user and never echo writes', () => {
  const h = setup()
  const otherTab = setup(h.data)
  const hook = h.mount('a')
  const anotherUser = h.mount('b')
  const remote = otherTab.mount('a')
  remote.value().setPreference('graphs', preference(13))
  h.dispatch(model.contentLayoutStorageKey('a', 'graphs'))
  assert.deepEqual(hook.value().preferences, { graphs: preference(13) })
  assert.deepEqual(anotherUser.value().preferences, {})
  assert.equal(hook.notifications, 1)
  assert.equal(anotherUser.notifications, 0)
  assert.deepEqual(h.writes, [])
  const reads = h.reads.length
  h.dispatch('unrelated-preference')
  h.dispatch(model.contentLayoutStorageKey('other-user', 'graphs'))
  h.dispatch(model.contentLayoutStorageKey('a', 'unknown'))
  h.dispatch(model.contentLayoutStorageKey('a'))
  h.dispatch(model.contentLayoutStorageKey('a', 'graphs'), encode({}), {})
  assert.equal(h.reads.length, reads)
  assert.equal(hook.notifications, 1)
})

test('queued storage events read current data; removal and clear discard overrides', () => {
  const h = setup(new Map([[model.contentLayoutStorageKey('a', 'queue'), encode({ queue: preference(9) })]]))
  const hook = h.mount('a')
  const key = model.contentLayoutStorageKey('a', 'graphs')
  h.data.set(key, encode({ graphs: preference(20) }))
  h.dispatch(key, encode({ graphs: preference(5) }))
  assert.deepEqual(hook.value().preferences, { graphs: preference(20), queue: preference(9) })
  const snapshot = hook.value().preferences
  h.dispatch(key)
  assert.equal(hook.value().preferences, snapshot)
  assert.equal(hook.notifications, 1)
  h.data.delete(key)
  h.dispatch(key)
  assert.deepEqual(hook.value().preferences, { queue: preference(9) })
  hook.value().setPreference('graphs', preference(7))
  h.data.clear()
  h.dispatch(null)
  assert.deepEqual(hook.value().preferences, {})
})

test('edits merge the latest persisted sections even before a remote event arrives', () => {
  const h = setup()
  const hook = h.mount('a')
  h.data.set(model.contentLayoutStorageKey('a', 'graphs'), encode({ graphs: preference(21) }))
  hook.value().setPreference('queue', preference(5))
  assert.deepEqual(hook.value().preferences, { graphs: preference(21), queue: preference(5) })
})

test('resubscription reloads inactive users and removes storage listeners on cleanup', () => {
  const h = setup()
  const hook = h.mount('a')
  hook.unmount()
  assert.equal(h.listeners.size, 0)
  h.data.set(model.contentLayoutStorageKey('a', 'graphs'), encode({ graphs: preference(17) }))
  h.dispatch(model.contentLayoutStorageKey('a', 'graphs'))
  assert.equal(hook.notifications, 0)
  assert.deepEqual(hook.value().preferences, { graphs: preference(17) })
  assert.equal(h.listeners.size, 1)
  hook.unmount()
  assert.equal(h.listeners.size, 0)
})

for (const failure of ['getter', 'read', 'write']) {
  test(`storage ${failure} denial preserves same-tab memory, reports false and can recover`, () => {
    const h = setup()
    h.failures[failure] = true
    const first = h.mount('a')
    const second = h.mount('a')
    assert.equal(first.value().setPreference('graphs', preference(12)), false)
    assert.deepEqual(second.value().preferences, { graphs: preference(12) })
    assert.equal(first.notifications, 1)
    assert.equal(first.value().setPreference('queue', preference(8)), false)
    assert.equal(second.value().resetPreference('graphs'), false)
    assert.deepEqual(first.value().preferences, { queue: preference(8) })
    first.unmount()
    assert.deepEqual(first.value().preferences, { queue: preference(8) })
    const queueKey = model.contentLayoutStorageKey('a', 'queue')
    const queueBeforeRecovery = h.data.get(queueKey)
    h.failures[failure] = false
    assert.equal(first.value().setPreference('graphs', preference(14)), true)
    assert.deepEqual(first.value().preferences, { queue: preference(8), graphs: preference(14) })
    assert.deepEqual(h.writes.at(-1), [model.contentLayoutStorageKey('a', 'graphs'), encode({ graphs: preference(14) })])
    assert.equal(h.data.get(queueKey), queueBeforeRecovery, 'Saving graphs must not rewrite a pending queue record')
    assert.equal(first.value().setPreference('queue', preference(8)), true)
    assert.equal(h.data.get(queueKey), encode({ queue: preference(8) }))
    assert.equal(h.data.get(model.contentLayoutStorageKey('a', 'graphs')), encode({ graphs: preference(14) }))
    assert.equal(h.data.has(model.contentLayoutStorageKey('a')), false)
  })
}

test('failed writes take precedence over old durable values and remain isolated by user', () => {
  const h = setup(new Map([[model.contentLayoutStorageKey('a', 'graphs'), encode({ graphs: preference(10) })]]))
  const hook = h.mount('a')
  h.failures.write = true
  assert.equal(hook.value().setPreference('graphs', preference(20)), false)
  assert.equal(hook.value().preferences.graphs.marginPercent, 20)
  assert.deepEqual(hook.switchUser('b').preferences, {})
  assert.deepEqual(hook.switchUser('a').preferences, { graphs: preference(20) })
  assert.equal(hook.value().resetPreference('graphs'), false)
  assert.deepEqual(hook.value().preferences, {})
  assert.deepEqual(JSON.parse(h.data.get(model.contentLayoutStorageKey('a', 'graphs'))).sections, { graphs: preference(10) })
})

test('remote durable updates supersede memory fallback without stale helper cache on remount', () => {
  const h = setup()
  const hook = h.mount('a')
  h.failures.write = true
  hook.value().setPreference('graphs', preference(20))
  h.data.set(model.contentLayoutStorageKey('a', 'graphs'), encode({ graphs: preference(30) }))
  h.dispatch(model.contentLayoutStorageKey('a', 'graphs'))
  assert.deepEqual(hook.value().preferences, { graphs: preference(30) })
  hook.unmount()
  assert.deepEqual(hook.value().preferences, { graphs: preference(30) })
})

test('invalid setter input and unknown reset ids never read or write storage', () => {
  const h = setup()
  const hook = h.mount('a')
  const reads = h.reads.length
  for (const id of ['unknown', '__proto__', 'constructor', '']) {
    assert.equal(hook.value().setPreference(id, preference(10)), false)
    assert.equal(hook.value().resetPreference(id), false)
  }
  for (const value of [null, {}, preference(NaN), preference(Infinity), preference('10'), preference(10, 'false')]) {
    assert.equal(hook.value().setPreference('graphs', value), false)
  }
  assert.deepEqual(hook.value().preferences, {})
  assert.equal(h.reads.length, reads)
  assert.deepEqual(h.writes, [])
})

test('malformed stored data and oversized envelopes are ignored without automatic repair writes', () => {
  for (const value of ['{', encode({ graphs: { fullWidth: 'true', marginPercent: 10 } }), ' '.repeat(16_385)]) {
    const h = setup(new Map([[model.contentLayoutStorageKey('a', 'graphs'), value]]))
    const hook = h.mount('a')
    assert.deepEqual(hook.value().preferences, {})
    assert.deepEqual(h.writes, [])
    assert.equal(hook.value().setPreference('graphs', preference(9.8)), true)
    assert.deepEqual(hook.value().preferences, { graphs: preference(9.8) })
  }
})

test('without a browser, edits remain memory-only and the server snapshot stays empty', () => {
  const h = createRuntime(undefined)
  const first = h.mount('a')
  const second = h.mount('b')
  assert.equal(first.value().setPreference('graphs', preference(10)), false)
  assert.deepEqual(first.value().preferences, { graphs: preference(10) })
  assert.deepEqual(second.value().preferences, {})
  assert.deepEqual(first.getServerSnapshot(), {})
  first.unmount()
  second.unmount()
})

for (const [outerId, innerId] of [['graphs', 'queue'], ['queue', 'graphs']]) {
  test(`interleaving tabs saving ${outerId} and ${innerId} preserves both independent records`, () => {
    const outerKey = model.contentLayoutStorageKey('a', outerId)
    const innerKey = model.contentLayoutStorageKey('a', innerId)
    const reportsKey = model.contentLayoutStorageKey('a', 'reports')
    const firstTab = setup(new Map([[reportsKey, encode({ reports: preference(9) })]]))
    const secondTab = setup(firstTab.data)
    const first = firstTab.mount('a')
    const second = secondTab.mount('a')
    const order = []
    let innerResult
    const storage = firstTab.browser.localStorage
    const commit = storage.setItem
    storage.setItem = (key, value) => {
      storage.setItem = commit
      order.push('outer-refreshed-and-ready-to-write')
      innerResult = second.value().setPreference(innerId, preference(12))
      order.push('inner-committed')
      commit(key, value)
      order.push('outer-committed')
    }

    assert.equal(first.value().setPreference(outerId, preference(30)), true)
    assert.equal(innerResult, true)
    assert.deepEqual(order, ['outer-refreshed-and-ready-to-write', 'inner-committed', 'outer-committed'])
    assert.equal(firstTab.data.get(outerKey), encode({ [outerId]: preference(30) }))
    assert.equal(firstTab.data.get(innerKey), encode({ [innerId]: preference(12) }))
    assert.equal(firstTab.data.get(reportsKey), encode({ reports: preference(9) }))
    assert.deepEqual(firstTab.writes, [[outerKey, encode({ [outerId]: preference(30) })]])
    assert.deepEqual(secondTab.writes, [[innerKey, encode({ [innerId]: preference(12) })]])
    assert.equal(firstTab.data.has(model.contentLayoutStorageKey('a')), false)

    firstTab.dispatch(innerKey)
    secondTab.dispatch(outerKey)
    const expected = { reports: preference(9), [outerId]: preference(30), [innerId]: preference(12) }
    assert.deepEqual(first.value().preferences, expected)
    assert.deepEqual(second.value().preferences, expected)
    const reloaded = setup(firstTab.data).mount('a')
    assert.deepEqual(reloaded.value().preferences, expected)
    first.unmount()
    second.unmount()
    reloaded.unmount()
  })
}

test('interleaving a section reset with another section save preserves the save and the reset', () => {
  const graphsKey = model.contentLayoutStorageKey('a', 'graphs')
  const queueKey = model.contentLayoutStorageKey('a', 'queue')
  const firstTab = setup(new Map([
    [graphsKey, encode({ graphs: preference(10) })],
    [queueKey, encode({ queue: preference(8) })],
  ]))
  const secondTab = setup(firstTab.data)
  const first = firstTab.mount('a')
  const second = secondTab.mount('a')
  let innerResult
  const storage = firstTab.browser.localStorage
  const commit = storage.setItem
  storage.setItem = (key, value) => {
    storage.setItem = commit
    innerResult = second.value().setPreference('queue', preference(25))
    commit(key, value)
  }
  assert.equal(first.value().resetPreference('graphs'), true)
  assert.equal(innerResult, true)
  assert.deepEqual(firstTab.writes, [[graphsKey, encode({})]])
  assert.deepEqual(secondTab.writes, [[queueKey, encode({ queue: preference(25) })]])
  assert.equal(firstTab.data.get(graphsKey), encode({}))
  assert.equal(firstTab.data.get(queueKey), encode({ queue: preference(25) }))
  firstTab.dispatch(queueKey)
  secondTab.dispatch(graphsKey)
  assert.deepEqual(first.value().preferences, { queue: preference(25) })
  assert.deepEqual(second.value().preferences, { queue: preference(25) })
  assert.deepEqual(setup(firstTab.data).mount('a').value().preferences, { queue: preference(25) })
})

test('interleaving writes to the same section converge to the last committed value', () => {
  const key = model.contentLayoutStorageKey('a', 'graphs')
  const firstTab = setup()
  const secondTab = setup(firstTab.data)
  const first = firstTab.mount('a')
  const second = secondTab.mount('a')
  let innerResult
  const storage = firstTab.browser.localStorage
  const commit = storage.setItem
  storage.setItem = (storageKey, value) => {
    storage.setItem = commit
    innerResult = second.value().setPreference('graphs', preference(31))
    commit(storageKey, value)
  }
  assert.equal(first.value().setPreference('graphs', preference(23)), true)
  assert.equal(innerResult, true)
  assert.equal(firstTab.data.get(key), encode({ graphs: preference(23) }))
  firstTab.dispatch(key, encode({ graphs: preference(31) }))
  secondTab.dispatch(key)
  assert.deepEqual(first.value().preferences, { graphs: preference(23) })
  assert.deepEqual(second.value().preferences, { graphs: preference(23) })
  assert.deepEqual(setup(firstTab.data).mount('a').value().preferences, { graphs: preference(23) })
})

test('a successful save elsewhere does not clear or falsely persist a section memory fallback', () => {
  const graphsKey = model.contentLayoutStorageKey('a', 'graphs')
  const h = setup(new Map([[graphsKey, encode({ graphs: preference(10) })]]))
  const hook = h.mount('a')
  h.failures.write = true
  assert.equal(hook.value().setPreference('graphs', preference(20)), false)
  h.failures.write = false
  assert.equal(hook.value().setPreference('queue', preference(8)), true)
  assert.equal(h.data.get(graphsKey), encode({ graphs: preference(10) }))
  assert.deepEqual(hook.value().preferences, { graphs: preference(20), queue: preference(8) })

  h.data.set(model.contentLayoutStorageKey('a', 'reports'), encode({ reports: preference(23) }))
  assert.equal(hook.value().setPreference('knowledge', preference(15)), true)
  assert.deepEqual(hook.value().preferences, {
    graphs: preference(20), queue: preference(8), reports: preference(23), knowledge: preference(15),
  })
  assert.equal(h.data.get(graphsKey), encode({ graphs: preference(10) }))
  assert.equal(setup(h.data).mount('a').value().preferences.graphs.marginPercent, 10)
  assert.equal(hook.value().setPreference('graphs', preference(20)), true)
  assert.equal(h.data.get(graphsKey), encode({ graphs: preference(20) }))
})

test('section events touch only that section; clear refreshes all including memory-only overrides', () => {
  const graphsKey = model.contentLayoutStorageKey('a', 'graphs')
  const queueKey = model.contentLayoutStorageKey('a', 'queue')
  const h = setup(new Map([
    [graphsKey, encode({ graphs: preference(11) })],
    [queueKey, encode({ queue: preference(7) })],
  ]))
  const hook = h.mount('a')
  h.failures.write = true
  assert.equal(hook.value().setPreference('graphs', preference(25)), false)
  const pending = hook.value().preferences.graphs
  h.data.set(queueKey, encode({ queue: preference(31) }))
  const reads = h.reads.length
  h.dispatch(queueKey)
  assert.deepEqual(h.reads.slice(reads), [queueKey])
  assert.equal(hook.value().preferences.graphs, pending)
  assert.deepEqual(hook.value().preferences, { graphs: preference(25), queue: preference(31) })
  const beforeClear = h.reads.length
  h.data.clear()
  h.dispatch(null)
  assert.deepEqual(new Set(h.reads.slice(beforeClear)), sectionKeysFor('a'))
  assert.deepEqual(hook.value().preferences, {})
  assert.deepEqual(h.writes, [[graphsKey, encode({ graphs: preference(25) })]])
})

test('an envelope can only affect the section named by its storage key', () => {
  const graphsKey = model.contentLayoutStorageKey('a', 'graphs')
  const queueKey = model.contentLayoutStorageKey('a', 'queue')
  const h = setup(new Map([
    [graphsKey, encode({ graphs: preference(11), queue: preference(40) })],
    [queueKey, encode({ queue: preference(7), graphs: preference(30) })],
  ]))
  const hook = h.mount('a')
  assert.deepEqual(hook.value().preferences, { graphs: preference(11), queue: preference(7) })
  h.data.set(graphsKey, encode({ queue: preference(6) }))
  h.dispatch(graphsKey)
  assert.deepEqual(hook.value().preferences, { queue: preference(7) })
  assert.deepEqual(h.writes, [])
})

test('unshipped aggregate records are neither read, migrated nor overwritten', () => {
  const base = model.contentLayoutStorageKey('a')
  const graphsKey = model.contentLayoutStorageKey('a', 'graphs')
  const queueKey = model.contentLayoutStorageKey('a', 'queue')
  const oldEnvelope = encode({ graphs: preference(20) })
  const h = setup(new Map([
    [base, oldEnvelope], [queueKey, encode({ queue: preference(10) })],
  ]))
  const hook = h.mount('a')
  assert.deepEqual(hook.value().preferences, { queue: preference(10) })
  assert.equal(hook.value().setPreference('graphs', preference(9)), true)
  assert.equal(hook.value().resetPreference('queue'), true)
  assert.deepEqual(hook.value().preferences, { graphs: preference(9) })
  assert.equal(h.reads.includes(base), false)
  assert.deepEqual(h.writes, [[graphsKey, encode({ graphs: preference(9) })], [queueKey, encode({})]])
  assert.equal(h.data.get(base), oldEnvelope)
  const reads = h.reads.length
  h.dispatch(base)
  assert.equal(h.reads.length, reads)
  assert.deepEqual(hook.value().preferences, { graphs: preference(9) })
})
