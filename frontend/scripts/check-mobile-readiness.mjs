import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const repoRoot = resolve(frontendRoot, '..')

const sources = {
  api: readFileSync(resolve(frontendRoot, 'src/api/client.ts'), 'utf8'),
  app: readFileSync(resolve(frontendRoot, 'src/App.tsx'), 'utf8'),
  compose: readFileSync(resolve(repoRoot, 'docker-compose.yml'), 'utf8'),
  dockerfile: readFileSync(resolve(frontendRoot, 'Dockerfile'), 'utf8'),
  index: readFileSync(resolve(frontendRoot, 'index.html'), 'utf8'),
  layout: readFileSync(resolve(frontendRoot, 'src/components/Layout.tsx'), 'utf8'),
  nginx: readFileSync(resolve(repoRoot, 'deploy/nginx.conf'), 'utf8'),
  styles: readFileSync(resolve(frontendRoot, 'src/index.css'), 'utf8'),
  vite: readFileSync(resolve(frontendRoot, 'vite.config.ts'), 'utf8'),
}

const checks = [
  [
    'browser API is same-origin',
    !sources.compose.includes('VITE_API_URL') && !sources.dockerfile.includes('VITE_API_URL'),
  ],
  ['container proxy targets backend service', sources.compose.includes('VITE_API_PROXY_TARGET: http://backend:8000')],
  ['Vite uses server-only proxy target', sources.vite.includes('process.env.VITE_API_PROXY_TARGET')],
  ['API requests have a timeout', sources.api.includes('AbortController') && sources.api.includes('GET_TIMEOUT_MS')],
  ['idempotent reads retry once', sources.api.includes("requestMethod(options) === 'GET' ? 2 : 1")],
  ['route imports clear successful reload markers', sources.app.includes('sessionStorage.removeItem(reloadKey)')],
  ['mobile core pages remain route-split', ['ContactsPage', 'QuickNotesPage', 'PersonalTasksPage', 'DeadlineTrackersPage'].every(
    (page) => sources.app.includes(`lazyPage(() => import('@/pages/${page}')`)
  )],
  ['static boot watchdog exists', sources.index.includes('Не удалось загрузить систему') && sources.index.includes('dpms:ready')],
  ['mobile shell uses dynamic viewport', sources.layout.includes('app-shell') && sources.styles.includes('height: 100dvh')],
  ['iOS form zoom is prevented', sources.styles.includes('font-size: 16px !important')],
  ['missing JS returns a real 404', sources.nginx.includes('try_files $uri =404;')],
  ['fake stale module fallback is disabled', !sources.nginx.includes('/stale-module.js')],
]

const failed = checks.filter(([, passed]) => !passed)
if (failed.length > 0) {
  console.error('Mobile readiness smoke failed:')
  for (const [label] of failed) console.error(`- ${label}`)
  process.exit(1)
}

console.log(`Mobile readiness smoke OK: ${checks.length} reliability guards are present.`)
