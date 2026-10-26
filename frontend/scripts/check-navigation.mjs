import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const sidebarSource = readFileSync(resolve(root, 'src/lib/sidebarNavigation.ts'), 'utf8')
const appSource = readFileSync(resolve(root, 'src/App.tsx'), 'utf8')

const expectedItems = [
  ['personal-tasks', '/personal-tasks', 'Личные задачи', 'tasks'],
  ['work-tracks', '/work-tracks', 'Треки', 'tasks'],
  ['my-tasks', '/my-tasks', 'Q-план', 'tasks'],
  ['queue', '/queue', 'Очередь', 'tasks'],
  ['calculator', '/calculator', 'Калькулятор', 'tasks'],
  ['catalog', '/catalog', 'Каталог операций', 'tasks'],
  ['knowledge', '/knowledge', 'База знаний', 'tasks'],
  ['shop', '/shop', 'Магазин', 'tasks'],
  ['deadline-trackers', '/deadline-trackers', 'Трекер сроков', 'tasks'],
  ['quick-notes', '/quick-notes', 'Заметки', 'tasks'],
  ['contacts', '/contacts', 'Контакты', 'tasks'],
  ['dashboard', '/', 'Дашборд', 'management'],
  ['reports', '/reports', 'Отчёты', 'management'],
  ['calibration', '/calibration', 'Калибровка', 'management'],
  ['absences', '/absences', 'Отсутствия', 'management'],
  ['audit', '/audit', 'Аудит', 'audit'],
  ['competencies', '/competencies', 'Развитие', 'development'],
  ['feedback', '/feedback', 'Обратная связь', 'feedback'],
  ['settings', '/settings', 'Настройки', 'settings'],
  ['admin-users', '/admin/users', 'Админ', 'admin'],
]

const expectedInternalRoutes = [
  ['/admin/integrations', 'Админ: интеграции'],
]

const routePaths = new Set()
if (/<Route\s+index\b/.test(appSource)) routePaths.add('/')
for (const match of appSource.matchAll(/<Route\s+path="([^"]+)"/g)) {
  routePaths.add(`/${match[1]}`.replace(/\/+/g, '/'))
}

const errors = []

for (const [id, to, label, group] of expectedItems) {
  const itemPattern = new RegExp(
    String.raw`\{\s*id:\s*'${escapeRegex(id)}'[\s\S]*?to:\s*'${escapeRegex(to)}'[\s\S]*?label:\s*'${escapeRegex(label)}'[\s\S]*?group:\s*'${escapeRegex(group)}'[\s\S]*?\}`,
    'm'
  )
  if (!itemPattern.test(sidebarSource)) {
    errors.push(`sidebarNav missing or changed: ${id} -> ${to} (${label}, group ${group})`)
  }

  if (!routePaths.has(to)) {
    errors.push(`App route missing for sidebar item: ${id} -> ${to}`)
  }
}

for (const [path, label] of expectedInternalRoutes) {
  if (!routePaths.has(path)) {
    errors.push(`internal route missing: ${label} -> ${path}`)
  }
}

const payloadVersionMatch = sidebarSource.match(/sidebarOrderPayload[\s\S]*?return\s*\{\s*version:\s*(\d+)/)
const payloadVersion = payloadVersionMatch ? Number(payloadVersionMatch[1]) : 0
if (payloadVersion < 5) {
  errors.push(`sidebar menu payload version must be >= 5, got ${payloadVersion || 'unknown'}`)
}

if (errors.length > 0) {
  console.error('Navigation smoke failed:')
  for (const error of errors) console.error(`- ${error}`)
  process.exit(1)
}

console.log(`Navigation smoke OK: ${expectedItems.length} menu sections and ${expectedInternalRoutes.length} internal routes are present.`)

function escapeRegex(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
