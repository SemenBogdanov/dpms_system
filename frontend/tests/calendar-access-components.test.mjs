import assert from 'node:assert/strict'
import test from 'node:test'
import { hookHarness, loadSource, nodes } from './calendar-access-harness.mjs'

const access = loadSource('src/lib/access.ts')
const nav = loadSource('src/lib/sidebarNavigation.ts', { '@/lib/access': access })
const calendarLabel = nav.sidebarNav.find((item) => item.id === 'audit-calendar').label
const auditLabel = nav.sidebarNav.find((item) => item.id === 'audit').label
const userFor = (role, enabled, development = false) => ({
  id: 'synthetic-user', full_name: 'Calendar access', email: 'calendar@example.com',
  role, league: 'C', mpw: 0,
  audit_enabled: false, task_workspace_enabled: false,
  audit_calendar_enabled: enabled, competency_development_enabled: development,
  competency_constructor_enabled: false,
})

test('real App route uses only the independent calendar gate for every account combination', () => {
  let user
  const App = loadSource('src/App.tsx', {
    '@/contexts/AuthContext': { useAuth: () => ({ user }) },
    '@/components/Layout': { Layout: 'Layout' },
    '@/components/ProtectedRoute': { ProtectedRoute: 'ProtectedRoute' },
    '@/lib/access': access,
    '@/lib/clientDiagnostics': { reportClientEvent: () => {} },
    '@/pages/LoginPage': { LoginPage: 'LoginPage' },
    '@/pages/SetPasswordPage': { SetPasswordPage: 'SetPasswordPage' },
    'react-router-dom': { Routes: 'Routes', Route: 'Route', Navigate: 'Navigate' },
  }).default
  const routes = nodes(App())
  const route = routes.find((node) => node.props.path === 'audit-calendar').props.element
  const audit = routes.find((node) => node.props.path === 'audit').props.element
  for (const role of ['executor', 'teamlead', 'admin']) {
    for (let mask = 0; mask < 64; mask += 1) {
      const flags = Array.from({ length: 6 }, (_, i) => Boolean(mask & (1 << i)))
      user = {
        role, audit_calendar_enabled: flags[0], audit_enabled: flags[1],
        task_workspace_enabled: flags[2], competency_development_enabled: flags[3],
        competency_constructor_enabled: flags[4], feedback_enabled: flags[5],
      }
      const result = route.type(route.props)
      assert.equal(result === route.props.children, flags[0])
      if (!flags[0]) assert.equal(result.props.to, '/messages')
      assert.equal(audit.type(audit.props) === audit.props.children, role === 'admin' || flags[1])
    }
  }
})

for (const role of ['executor', 'teamlead', 'admin']) {
  for (const development of [false, true]) {
    test(`menu configurator and admin grant: ${role}, development=${development}, Audit/Q off`, async () => {
      let user = userFor(role, true, development)
      user.sidebar_menu_order = { version: 9, groups: [{ id: 'mine', label: 'Custom', item_ids: ['messages'] }] }
      const runtime = hookHarness()
      let saved
      const { SettingsPage } = loadSource('src/pages/SettingsPage.tsx', {
        react: runtime.hooks,
        '@/contexts/AuthContext': { useAuth: () => ({ user, updateUser: (next) => { user = next } }) },
        '@/lib/access': access, '@/lib/sidebarNavigation': nav,
        '@/api/client': { api: { patch: async (_path, payload) => {
          saved = payload
          return { ...user, ...payload }
        } } },
        'react-router-dom': { Link: 'Link' },
        'react-hot-toast': { success: () => {}, error: (message) => assert.fail(message) },
        '@/components/ChangePasswordModal': { ChangePasswordModal: 'ChangePasswordModal' },
        '@/components/LeagueBadge': { LeagueBadge: 'LeagueBadge' },
        '@/components/StorageQuotaSettingsPanel': { StorageQuotaSettingsPanel: 'StorageQuotaSettingsPanel' },
      })
      runtime.render(SettingsPage)
      runtime.flushEffects()
      const availableCalendar = () => nodes(runtime.render(SettingsPage)).find((node) =>
        node.key === 'audit-calendar' && nodes(node).some((child) => child.type === 'input' && child.props.value === calendarLabel))
      const entry = availableCalendar()
      assert.ok(entry, 'A deliberately hidden calendar remains available in the configurator')
      const add = nodes(entry).find((node) => node.type === 'button')
      assert.equal(add.props.disabled, false)
      add.props.onClick()
      const tree = runtime.render(SettingsPage)
      const save = nodes(tree).find((node) => node.type === 'button'
        && nodes(node).some((child) => child.type?.displayName === 'Save'))
      assert.ok(save)
      assert.equal(save.props.disabled, false)
      save.props.onClick()
      await Promise.resolve()
      assert.deepEqual(saved.sidebar_menu_order.groups[0].item_ids, ['messages', 'audit-calendar'])
      assert.equal(user.audit_enabled, false)
      assert.equal(user.task_workspace_enabled, false)
      assert.equal(user.role, role)
      user = { ...user, audit_calendar_enabled: false }
      assert.equal(availableCalendar(), undefined, 'Revocation removes the configurator entry')
      user = { ...user, audit_calendar_enabled: true }
      assert.ok(availableCalendar(), 'A refreshed grant restores the configurator entry')

      const modalRuntime = hookHarness()
      let submitted
      const { UserModal } = loadSource('src/components/UserModal.tsx', {
        react: modalRuntime.hooks,
        '@/lib/passwordValidation': { validatePassword: () => [] },
        '@/lib/utils': { cn: (...values) => values.filter(Boolean).join(' ') },
        '@/components/PasswordRevealButton': { PasswordRevealButton: 'PasswordRevealButton' },
        '@/hooks/useProtectedModal': { preventBackdropDismiss: () => {}, useProtectedModal: () => ({ current: null }) },
      })
      const props = { open: true, mode: 'edit', initial: userFor(role, false, development),
        onClose: () => {}, onSubmit: async (payload) => { submitted = payload } }
      modalRuntime.render(UserModal, props)
      modalRuntime.flushEffects()
      const render = () => modalRuntime.render(UserModal, props)
      const checkbox = (label) => {
        const group = nodes(render()).find((node) => node.type === 'label'
          && nodes(node).some((child) => child.props.children === label))
        return nodes(group).find((node) => node.type === 'input')
      }
      assert.ok(!checkbox(calendarLabel).props.disabled)
      checkbox(calendarLabel).props.onChange({ target: { checked: true } })
      assert.equal(checkbox(auditLabel).props.checked, false)
      await nodes(render()).find((node) => node.type === 'form').props.onSubmit({ preventDefault() {} })
      assert.equal(submitted.audit_calendar_enabled, true)
      assert.equal(submitted.audit_enabled, false)
      assert.equal(submitted.task_workspace_enabled, false)
      assert.equal(submitted.role, role)
      checkbox(auditLabel).props.onChange({ target: { checked: true } })
      checkbox(auditLabel).props.onChange({ target: { checked: false } })
      assert.equal(checkbox(calendarLabel).props.checked, true)
    })
  }
}

function calendarPageHarness() {
  const runtime = hookHarness()
  const browser = new EventTarget()
  const document = new EventTarget()
  document.visibilityState = 'visible'
  const requests = []
  const params = new URLSearchParams({ from: '2026-09-14', to: '2026-09-20' })
  const setParams = () => assert.fail('The explicit test date range must remain unchanged')
  const componentModules = {
    CalendarGraph: ['CalendarGraph'],
    CalendarMeetingEditor: ['CalendarMeetingEditor'],
    CalendarAvailability: ['CalendarAvailability'],
    CalendarReadiness: ['CalendarReadiness'],
    CalendarWorkload: ['CalendarWorkload'],
    CalendarAvailabilityAction: ['CalendarAvailabilityAction'],
    CalendarManagement: ['CalendarActionEditor', 'CalendarDirectories', 'CalendarManagement', 'AbsenceList'],
    CalendarDataset: ['CalendarDataset'],
    CalendarHistory: ['CalendarHistory'],
    CalendarImports: ['CalendarImports', 'CalendarRestoreEditor'],
  }
  const { AuditCalendarPage } = loadSource('src/pages/AuditCalendarPage.tsx', {
    react: runtime.hooks,
    'react-router-dom': { Link: 'Link', useSearchParams: () => [params, setParams] },
    '@/api/auditCalendar': { auditCalendar: {
      state: () => new Promise((resolve, reject) => requests.push({ resolve, reject })),
    } },
    '@/api/client': { ApiError: class ApiError extends Error {} },
    '@/lib/auditCalendar': {
      moscowToday: () => '2026-09-14',
      addDays: (day, count) => new Date(Date.parse(`${day}T00:00:00Z`) + count * 86400000).toISOString().slice(0, 10),
      clampDay: (day) => day,
      periodError: () => '', readinessEnd: (_from, to) => to,
      errorText: (error) => error.message, numberLabel: String,
      calendarTargetScopes: { all: 'All groups' }, MIN_DATE: '2000-01-01', MAX_DATE: '2100-12-31',
    },
    '@/components/audit-calendar/audit-calendar.css': {},
    ...Object.fromEntries(Object.entries(componentModules).map(([file, exports]) => [
      `@/components/audit-calendar/${file}`, Object.fromEntries(exports.map((name) => [name, name])),
    ])),
  }, { window: browser, document })
  const render = () => {
    const tree = runtime.render(AuditCalendarPage)
    runtime.flushEffects()
    return nodes(tree)
  }
  render()
  return {
    runtime, browser, requests, render,
    state: {
      scope: { name: 'Synthetic calendar', today: '2026-09-14', archived: false },
      actor: { user_id: 'synthetic-user', can_manage: true, can_archive: false },
      stats: { plan: 0, fact: 0, attention: 0, target: 0, target_scope: 'all' },
      groups: [], members: [],
    },
  }
}

for (const alreadyLoaded of [false, true]) {
  for (const outcome of ['success', 'failure']) {
    test(`calendar revoke invalidates pending state ${outcome}, alreadyLoaded=${alreadyLoaded}`, async () => {
      const h = calendarPageHarness()
      if (alreadyLoaded) {
        h.requests[0].resolve(h.state)
        await Promise.resolve()
        const graph = h.render().find((node) => node.type === 'CalendarGraph')
        assert.ok(graph)
        graph.props.onOpen('2026-09-14', 600)
        const editor = h.render().find((node) => node.type === 'CalendarMeetingEditor')
        assert.ok(editor)
        void editor.props.onRefresh().catch(() => undefined)
      }
      assert.equal(h.render().find((node) => node.type === 'main').props['aria-busy'], true)
      h.browser.dispatchEvent(new Event('audit-calendar:access-revoked'))
      const revoked = h.render()
      const revocationAlert = revoked.find((node) => node.props.role === 'alert')
      assert.ok(revocationAlert)
      assert.equal(revoked.some((node) => node.type === 'CalendarMeetingEditor'), false)
      const busyAfterRevoke = revoked.find((node) => node.type === 'main').props['aria-busy']

      const pending = h.requests.at(-1)
      if (outcome === 'success') pending.resolve(h.state)
      else pending.reject(new Error('Synthetic late refresh failure'))
      await Promise.resolve()
      await Promise.resolve()
      const after = h.render()
      assert.equal(after.some((node) => node.type === 'CalendarGraph'), false,
        'A late state response must not restore revoked calendar data')
      assert.equal(after.some((node) => node.props.className === 'ac-bound-content'), false)
      assert.equal(after.some((node) => node.type === 'CalendarMeetingEditor'), false)
      const alertText = (alert) => nodes(alert)
        .filter((node) => node.type === 'strong' || node.type === 'p').map((node) => node.props.children)
      assert.deepEqual(alertText(after.find((node) => node.props.role === 'alert')), alertText(revocationAlert),
        'A stale success or error must preserve the access-revoked message')
      assert.equal(busyAfterRevoke, false, 'Revocation must end loading immediately')
      assert.equal(after.find((node) => node.type === 'main').props['aria-busy'], false)

      const refresh = after.find((node) => node.type === 'button'
        && nodes(node).some((child) => child.type?.displayName === 'RefreshCw'))
      assert.equal(refresh.props.disabled, false)
      refresh.props.onClick()
      h.requests.at(-1).resolve(h.state)
      await Promise.resolve()
      const retried = h.render()
      assert.ok(retried.find((node) => node.type === 'CalendarGraph'),
        'A new explicit refresh may restore access after a fresh successful response')
      assert.equal(retried.some((node) => node.type === 'CalendarMeetingEditor'), false)
      h.runtime.unmount()
    })
  }
}
