import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'
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
let combinations = 0
for (const role of ['executor', 'teamlead', 'admin']) {
  for (const audit of [false, true]) {
    for (const enabled of [false, true]) {
      for (const task of [false, true]) {
        for (const development of [false, true]) {
          for (const constructor of [false, true]) {
            for (const feedback of [false, true]) {
              const user = {
                role, audit_enabled: audit, audit_calendar_enabled: enabled,
                task_workspace_enabled: task, competency_development_enabled: development,
                competency_constructor_enabled: constructor, feedback_enabled: feedback,
              }
              const visible = nav.visibleSidebarNav(user)
              assert.equal(access.hasAuditCalendarAccess(user), enabled)
              assert.equal(visible.some((item) => item.id === 'audit-calendar'), enabled)
              assert.equal(access.hasAuditAccess(user), role === 'admin' || audit)
              assert.equal(visible.some((item) => item.id === 'audit'), role === 'admin' || audit)
              assert.equal(access.hasTaskWorkspaceAccess(user), role === 'admin' || task)
              assert.equal(access.firstAvailablePath(user), '/messages')
              const menuItems = nav.defaultSidebarOrder.groups.flatMap((group) => nav.visibleItemsForButton(group, visible))
              assert.equal(menuItems.some((item) => item.id === 'audit-calendar'), enabled)
              combinations += 1
            }
          }
        }
      }
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
const regressions = spawnSync(process.execPath, ['--test',
  resolve(root, 'tests/calendar-access-refresh.test.mjs'),
  resolve(root, 'tests/calendar-access-components.test.mjs'),
], { stdio: 'inherit' })
assert.equal(regressions.status, 0, 'Calendar access component/refresh regressions failed')
console.log(`Audit calendar access OK: ${combinations} role/grant combinations, old-menu migration, custom-menu preservation, Messages default.`)
