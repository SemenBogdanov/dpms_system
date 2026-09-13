import { defineConfig } from '@playwright/test'

// Isolated Vite transform server, no env files, proxy, auth state, or backend.
const command = `node --input-type=module -e 'import {createServer} from "vite"; import path from "node:path"; const s = await createServer({configFile:false,envDir:false,optimizeDeps:{include:["react","react-dom/client","react-router-dom"]},resolve:{alias:{"@":path.resolve("src")}},esbuild:{jsx:"automatic"},server:{host:"127.0.0.1",port:4198,strictPort:true}}); await s.listen();'`
export default defineConfig({
  testDir: './tests', testMatch: 'audit-calendar*.spec.ts',
  outputDir: '../artifacts/audit-calendar/isolated',
  reporter: 'list', fullyParallel: false, workers: 2, timeout: 30000,
  use: { baseURL: 'http://127.0.0.1:4198', locale: 'ru-RU', timezoneId: 'Europe/Moscow', screenshot: 'only-on-failure' },
  webServer: { command, url: 'http://127.0.0.1:4198', reuseExistingServer: false, timeout: 30000 },
  projects: [
    { name: 'chromium', use: { browserName: 'chromium', viewport: { width: 1440, height: 900 } } },
    { name: 'webkit', use: { browserName: 'webkit', viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
  ],
})
