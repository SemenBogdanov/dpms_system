import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests', testMatch: 'note-groups.spec.ts', fullyParallel: false, workers: 1,
  timeout: 30_000, expect: { timeout: 8_000 },
  outputDir: '/tmp/dpms-note-groups-results',
  use: { baseURL: 'http://127.0.0.1:4182', trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  webServer: {
    command: 'npm run build && npm run preview -- --host 127.0.0.1 --port 4182 --strictPort',
    url: 'http://127.0.0.1:4182/login', reuseExistingServer: false, timeout: 120_000,
  },
  projects: [
    { name: 'chromium-desktop', use: { browserName: 'chromium', viewport: { width: 1440, height: 900 } } },
    { name: 'webkit-desktop', use: { browserName: 'webkit', viewport: { width: 1440, height: 900 } } },
    { name: 'chromium-mobile', use: { ...devices['iPhone 13'], browserName: 'chromium' } },
    { name: 'webkit-mobile', use: { ...devices['iPhone 13'], browserName: 'webkit' } },
  ],
})
