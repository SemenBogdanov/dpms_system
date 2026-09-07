import { fileURLToPath } from 'node:url'
import { defineConfig, devices } from '@playwright/test'

const baseURL = 'http://127.0.0.1:4189'

export default defineConfig({
  testDir: '.',
  testMatch: 'audit-legacy-history.spec.ts',
  outputDir: '/tmp/dpms-a19-history-playwright',
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 8_000 },
  use: { baseURL, screenshot: 'only-on-failure', trace: 'retain-on-failure', timezoneId: 'America/Los_Angeles' },
  webServer: {
    cwd: fileURLToPath(new URL('..', import.meta.url)),
    command: 'npm run preview -- --outDir /tmp/dpms-a19-history-build --host 127.0.0.1 --port 4189 --strictPort',
    url: `${baseURL}/login`,
    reuseExistingServer: false,
  },
  projects: [
    { name: 'desktop-light', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
    { name: 'mobile-dark', use: { ...devices['iPhone 13'], browserName: 'chromium' } },
  ],
})
