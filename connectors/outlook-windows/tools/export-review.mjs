import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { copyFileSync, existsSync, lstatSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('../../../', import.meta.url))
const base = 'connectors/outlook-windows'
const revision = '01541ca4b0573fca8be276a8a106dbf0162d6d25'
const baseline = '839391deee0598a8718306ab23096c9c730adb60'
const output = join(root, base, 'artifacts/review-01541ca')
const verify = process.argv.slice(2).join(' ') === '--verify'
const refresh = process.argv.slice(2).join(' ') === '--refresh-docs'
if (process.argv.length > 2 && !verify && !refresh) throw new Error('Usage: export-review.mjs [--verify|--refresh-docs]')
const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex')
const git = (...args) => execFileSync('git', args, { cwd: root, maxBuffer: 16 * 1024 * 1024 })

const client = [
  '.gitignore', 'Core/Core.csproj', 'Core/DpmsClient.cs', 'Core/OutlookMapping.cs',
  'Core/Protocol.cs', 'Core/ScanSnapshot.cs', 'Core/SyncEngine.cs',
  'Desktop/AttachmentStaging.cs', 'Desktop/Desktop.csproj', 'Desktop/MainForm.cs',
  'Desktop/OutlookReader.cs', 'Desktop/Program.cs', 'Desktop/ProtectedState.cs',
  'Desktop/app.manifest', 'NuGet.Config', 'README.md', 'Tests/ProtocolTests.cs', 'Tests/Tests.csproj',
].map((path) => `${base}/${path}`)
const server = [
  'backend/alembic/versions/100_mail_import.py', 'backend/app/api/routes/mail_import.py',
  'backend/app/mail_import_gateway.py', 'backend/app/main.py', 'backend/app/models/__init__.py',
  'backend/app/models/mail_import.py', 'backend/app/schemas/mail_import.py',
  'backend/app/services/mail_import.py', 'backend/tests/test_mail_import.py',
  'backend/tests/test_mail_import_http.py',
]
const frontend = [
  'frontend/playwright.outlook-connector.config.ts', 'frontend/src/api/mailImport.ts',
  'frontend/src/components/ImportedMailPanel.tsx', 'frontend/src/components/OutlookConnectorSettingsPanel.tsx',
  'frontend/src/pages/MessagesPage.tsx', 'frontend/src/pages/SettingsPage.tsx',
  'frontend/tests/outlook-connector.spec.ts',
]
const groups = [
  ['WINDOWS CLIENT: application, build configuration, tests', client],
  ['SERVER: not compiled into the Windows EXE; feature scope only', server],
  ['WEB UI: not compiled into the Windows EXE; feature scope only', frontend],
  ['CONTRACT', ['docs/OUTLOOK-CONNECTOR-2026-11-16.md']],
]
const paths = groups.flatMap(([, files]) => files)
const delta = git('diff', '--name-only', '-z', baseline, revision).toString().split('\0').filter(Boolean)
if (JSON.stringify(delta.sort()) !== JSON.stringify([...paths].sort())) throw new Error('Unexpected snapshot scope')
const forbidden = /(^|\/)(\.env[^/]*|[^/]*(?:secret|credential|token|auth|key)[^/]*)$/i
if (paths.some((path) => forbidden.test(path))) throw new Error('Forbidden path in allowlist')

const exePath = join(root, base, 'artifacts/win-x64/DPMS.OutlookConnector.exe')
const expectedExe = 'c41f4d734cc17ae9934d535272933c6ba7954b9eb3b30b096fdb1d89d5a902f8'
if (sha256(readFileSync(exePath)) !== expectedExe) throw new Error('Original EXE hash mismatch')
const documents = new Map()
const manifest = { source_commit: revision, baseline_commit: baseline, exe_sha256: expectedExe, files: [] }
const listing = [
  'ЛИСТИНГ ИСХОДНОГО КОДА: DPMS Outlook Connector 0.1.0',
  `Source commit: ${revision}`, '',
  'Полный собственный Windows-клиент, конфигурация сборки и тесты.',
  'Далее: серверный/UI scope функции, не полный репозиторий DPMS.',
  'Это точный текст Git-объектов с добавленными номерами строк, не декомпиляция.',
  'Оригиналы без номеров строк: source/. Сторонний runtime не включён в листинг.',
  'См. SECURITY-AND-BUILD.md: листинг и hashes не являются гарантией безопасности.', '',
]
for (const [label, files] of groups) {
  listing.push(`===== ${label} =====`, '')
  for (const path of files) {
    const bytes = git('show', `${revision}:${path}`)
    const hash = sha256(bytes)
    documents.set(`source/${path}`, bytes)
    manifest.files.push({ path, sha256: hash, bytes: bytes.length })
    const lines = bytes.toString('utf8').split('\n')
    if (lines.at(-1) === '') lines.pop()
    listing.push(`FILE: ${path}`, `SHA256: ${hash}`, `LINES: ${lines.length}`)
    listing.push(...lines.map((line, index) => `${String(index + 1).padStart(5, ' ')} | ${line}`), '')
  }
}
documents.set('SOURCE-LISTING.txt', Buffer.from(listing.join('\n') + '\n'))
documents.set('SOURCE-MANIFEST.json', Buffer.from(JSON.stringify(manifest, null, 2) + '\n'))
documents.set('SECURITY-AND-BUILD.md', readFileSync(join(root, base, 'SECURITY-AND-BUILD.md')))
documents.set('QUICK-START.md', readFileSync(join(root, base, 'QUICK-START.md')))
documents.set('export-review.mjs', readFileSync(fileURLToPath(import.meta.url)))
const checksums = [...documents].map(([path, bytes]) => `${sha256(bytes)}  ${path}`)
checksums.push(`${expectedExe}  DPMS.OutlookConnector.exe`)
documents.set('SHA256SUMS.txt', Buffer.from(checksums.join('\n') + '\n'))

if (verify || refresh) {
  if (!lstatSync(output).isDirectory() || lstatSync(output).isSymbolicLink()) throw new Error('Invalid output directory')
  const editable = new Set(['SECURITY-AND-BUILD.md', 'QUICK-START.md', 'export-review.mjs', 'SHA256SUMS.txt'])
  for (const [path, bytes] of documents) {
    const file = join(output, path)
    if (refresh && editable.has(path)) {
      if (existsSync(file) && lstatSync(file).isSymbolicLink()) throw new Error(`Invalid document: ${path}`)
      continue
    }
    if (lstatSync(file).isSymbolicLink() || !readFileSync(file).equals(bytes)) throw new Error(`Mismatch: ${path}`)
  }
  if (sha256(readFileSync(join(output, 'DPMS.OutlookConnector.exe'))) !== expectedExe) throw new Error('Copied EXE mismatch')
  // Refresh only our generated documentation after verifying every immutable source and the EXE.
  if (refresh) for (const path of editable) writeFileSync(join(output, path), documents.get(path))
} else {
  if (existsSync(output)) throw new Error('Output already exists; use --verify or review it manually')
  mkdirSync(output)
  for (const [path, bytes] of documents) {
    const file = join(output, path)
    mkdirSync(dirname(file), { recursive: true })
    writeFileSync(file, bytes, { flag: 'wx' })
  }
  copyFileSync(exePath, join(output, 'DPMS.OutlookConnector.exe'))
}
console.log(JSON.stringify({ mode: verify ? 'verified' : refresh ? 'refreshed_docs' : 'exported', output, source_files: paths.length, source_commit: revision, exe_sha256: expectedExe }))
