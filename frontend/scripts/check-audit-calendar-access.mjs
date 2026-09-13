import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const require = createRequire(import.meta.url)
function loadModule(path, overrides = {}) {
  const source = readFileSync(resolve(root, path), 'utf8')
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const mod = { exports: {} }
  new Function('require', 'module', 'exports', compiled)(
    (id) => overrides[id] ?? require(id), mod, mod.exports,
  )
  return mod.exports
}
const access = loadModule('src/lib/access.ts')
const nav = loadModule('src/lib/sidebarNavigation.ts', { '@/lib/access': access })
for (const role of ['executor', 'teamlead', 'admin']) {
  for (const audit of [false, true]) {
    for (const enabled of [false, true]) {
      const user = { role, audit_enabled: audit, audit_calendar_enabled: enabled }
      assert.equal(access.hasAuditCalendarAccess(user), enabled)
      assert.equal(nav.visibleSidebarNav(user).some((item) => item.id === 'audit-calendar'), enabled)
      assert.equal(access.firstAvailablePath(user), '/messages')
    }
  }
}
assert.equal(access.hasAuditCalendarAccess(null), false)
assert.equal(access.hasAuditCalendarAccess({ role: 'admin' }), false)
for (let version = 1; version <= 8; version += 1) {
  const layout = nav.normalizeSidebarOrder({
    version,
    groups: [{ id: 'mine', label: 'Мое меню', item_ids: ['messages', 'quick-notes'] }],
  })
  assert.equal(layout.version, 9)
  assert.equal(layout.groups.flatMap((g) => g.itemIds).filter((id) => id === 'audit-calendar').length, 1)
  assert.equal(layout.groups[0].label, 'Мое меню')
  assert.ok(layout.groups[0].itemIds.includes('quick-notes'))
  assert.deepEqual(nav.normalizeSidebarOrder(nav.sidebarOrderPayload(layout)), layout)
}
const deliberatelyHidden = nav.normalizeSidebarOrder({
  version: 9, groups: [{ id: 'mine', item_ids: ['messages'] }],
})
assert.equal(deliberatelyHidden.groups.flatMap((g) => g.itemIds).includes('audit-calendar'), false)
assert.equal(nav.visibleSidebarNav({ role: 'executor', audit_calendar_enabled: true })
  .some((item) => item.id === 'audit-calendar'), true)
console.log('Audit calendar access OK: 12 role/grant combinations, old-menu migration, custom-menu preservation, Messages default.')
