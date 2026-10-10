import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import * as React from 'react'
import ts from 'typescript'
import type { Page, Route } from '@playwright/test'

export const shellUser = {
  id: '11111111-1111-4111-8111-111111111106',
  full_name: 'Проверка оболочки', email: 'shell@example.test', role: 'admin', league: 'A',
  mpw: 0, wip_limit: 5, wallet_main: 0, wallet_karma: 0, quality_score: 100,
  is_active: true, is_new_employee: false, needs_password_change: false,
  task_workspace_enabled: true, can_link_queue_tasks_to_projects: true,
  competency_development_enabled: true, competency_constructor_enabled: true,
  feedback_enabled: true, audit_enabled: true, audit_calendar_enabled: true,
  sidebar_menu_order: null, created_at: '2026-10-01T12:00:00Z', updated_at: '2026-10-01T12:00:00Z',
}

export const catalogItem = {
  id: '22222222-2222-4222-8222-222222222206', name: 'Синтетическая операция',
  category: 'widget', complexity: 'M', base_cost_q: 5, min_league: 'C',
  sort_order: 1, description: '', is_active: true,
}

export function deferred<T = void>() {
  let resolve!: (value: T | PromiseLike<T>) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}

export async function shellFixture(page: Page, options: {
  theme?: 'light' | 'dark' | 'rose'
  pinned?: boolean
  storageFailure?: 'read' | 'write'
  summary?: { direct_count: number; important_count: number }
  tags?: string[]
  write?: (route: Route) => Promise<void>
} = {}) {
  const writes: Array<{ path: string; method: string }> = []
  await page.routeWebSocket('**/*', () => {})
  // This is a new in-memory fixture, never a read of the browser's storage.
  await page.addInitScript(({ theme, pinned, failure }) => {
    const values = new Map<string, string>([
      ['dpms_token', 'synthetic-shell-only'], ['dpms-theme', theme], ['dpms.sidebarPinned', String(pinned)],
    ])
    const preference = (name: string) => name === 'dpms-theme' || name === 'dpms.sidebarPinned'
    Object.defineProperty(window, 'localStorage', { configurable: true, value: {
      getItem(name: string) {
        if (failure === 'read' && preference(name)) throw new DOMException('Synthetic read refusal', 'SecurityError')
        return values.get(name) ?? null
      },
      setItem(name: string, value: string) {
        if (failure === 'write' && preference(name)) throw new DOMException('Synthetic write refusal', 'QuotaExceededError')
        values.set(name, String(value))
      },
      removeItem: (name: string) => values.delete(name), clear: () => values.clear(),
      key: (index: number) => [...values.keys()][index] ?? null,
      get length() { return values.size },
    } })
  }, { theme: options.theme ?? 'light', pinned: options.pinned ?? true, failure: options.storageFailure })
  await page.route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const respond = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (url.origin !== 'http://localhost:55177') return route.abort()
    if (!url.pathname.startsWith('/api/')) {
      return request.method() === 'GET' || request.method() === 'HEAD' ? route.continue() : route.abort()
    }
    if (request.method() !== 'GET') {
      writes.push({ path: url.pathname, method: request.method() })
      if (url.pathname.startsWith('/api/usage/') || url.pathname.startsWith('/api/client-events')) return respond({})
      if (url.pathname === '/api/calculator/estimate') return respond({ total_q: 5, items: [], min_league: 'C' })
      if (options.write) return options.write(route)
      return respond({ detail: 'Unexpected synthetic write' }, 409)
    }
    if (url.pathname === '/api/auth/me') return respond(shellUser)
    if (url.pathname === '/api/web-push/config') return respond({ available: false })
    if (url.pathname === '/api/messages/summary') return respond(options.summary ?? { direct_count: 0, important_count: 0 })
    if (url.pathname === '/api/catalog') return respond([catalogItem])
    if (url.pathname === '/api/users' || url.pathname === '/api/users/admin') return respond([shellUser])
    if (url.pathname === '/api/admin/server-boots') return respond({
      period_days: 0, total: 0, all_time_count: 0, last_7_days_count: 0, first_imported_at: null, items: [],
      import_status: { state: 'waiting', last_attempt_at: null, last_success_at: null, invalid_files: 0, conflicting_files: 0, checked_files: 0, error_code: null },
    })
    if (url.pathname === '/api/tasks/tags/suggestions') return respond((options.tags ?? []).map((tag) => ({ tag, count: 1 })))
    return respond([])
  })
  return writes
}

// Address-only transpilation follows the existing calendar-access-harness pattern.
// No imported project module is opened: all dependencies must be supplied explicitly.
export function loadBoundary<T>(file: 'CatalogModal' | 'UserModal' | 'preferenceStorage', dependencies: Record<string, unknown> = {}, globals: Record<string, unknown> = {}): T {
  const path = file === 'preferenceStorage' ? 'lib/preferenceStorage.ts' : `components/${file}.tsx`
  const url = new URL(`../src/${path}`, import.meta.url)
  const output = ts.transpileModule(readFileSync(url, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
    fileName: fileURLToPath(url),
  }).outputText
  const require = createRequire(import.meta.url)
  const module = { exports: {} }
  new Function('require', 'module', 'exports', ...Object.keys(globals), output)(
    (name: string) => {
      if (name in dependencies) return dependencies[name]
      if (name === 'react/jsx-runtime') return require(name)
      throw new Error(`Unmocked dependency: ${name}`)
    }, module, module.exports, ...Object.values(globals),
  )
  return module.exports as T
}

export function modalBoundary(kind: 'CatalogModal' | 'UserModal') {
  type Slot = { value?: unknown; deps?: React.DependencyList; cleanup?: void | (() => void) }
  const slots: Slot[] = []
  let cursor = 0
  let effects: Array<() => void> = []
  const hooks = {
    useState<T>(initial: T | (() => T)) {
      const index = cursor++
      slots[index] ??= { value: typeof initial === 'function' ? (initial as () => T)() : initial }
      return [slots[index].value as T, (next: T | ((before: T) => T)) => {
        slots[index].value = typeof next === 'function' ? (next as (before: T) => T)(slots[index].value as T) : next
      }]
    },
    useRef<T>(initial: T) {
      const index = cursor++
      slots[index] ??= { value: { current: initial } }
      return slots[index].value
    },
    useId() {
      const index = cursor++
      slots[index] ??= { value: `fixture-${index}` }
      return slots[index].value
    },
    useLayoutEffect(effect: () => void | (() => void), deps: React.DependencyList) {
      const index = cursor++
      if (!slots[index]?.deps || deps.some((value, i) => !Object.is(value, slots[index].deps?.[i]))) {
        effects.push(() => {
          slots[index]?.cleanup?.()
          slots[index] = { deps, cleanup: effect() }
        })
      }
    },
  }
  const exports = loadBoundary<Record<string, (props: Record<string, unknown>) => React.ReactNode>>(kind, {
    react: hooks,
    '@/hooks/useProtectedModal': { useProtectedModal: () => ({ current: null }), preventBackdropDismiss: () => {} },
    '@/lib/utils': { cn: (...values: unknown[]) => values.filter((value) => typeof value === 'string').join(' ') },
    // Forbidden dependencies are replaced, not resolved/read. These tests use edit mode.
    '@/lib/passwordValidation': { validatePassword: () => [] },
    '@/components/PasswordRevealButton': { PasswordRevealButton: 'button' },
  })
  return {
    render(props: Record<string, unknown>) {
      cursor = 0
      exports[kind](props)
      const pendingEffects = effects
      effects = []
      pendingEffects.forEach((effect) => effect())
      cursor = 0
      return exports[kind](props)
    },
    unmount() { slots.forEach((slot) => slot.cleanup?.()) },
  }
}

export function nodes(tree: React.ReactNode): React.ReactElement<Record<string, unknown>>[] {
  if (Array.isArray(tree)) return tree.flatMap(nodes)
  if (!React.isValidElement<Record<string, unknown>>(tree)) return []
  return [tree, ...nodes(tree.props.children as React.ReactNode)]
}
