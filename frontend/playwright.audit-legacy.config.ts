import { defineConfig, devices } from '@playwright/test'

const baseURL = 'http://127.0.0.1:4187'
export default defineConfig({
  testDir: './tests',
  testMatch: 'audit-legacy-import.spec.ts',
  outputDir: './test-results/audit-legacy',
  fullyParallel: false,
  workers: 2,
  timeout: 35_000,
  expect: { timeout: 8_000 },
  use: { baseURL, trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 4187 --strictPort',
    url: baseURL + '/login',
    reuseExistingServer: false,
    timeout: 60_000,
  },
  projects: [
    { name: 'chromium-desktop-light', use: { browserName: 'chromium', viewport: { width: 1440, height: 900 } } },
    { name: 'webkit-desktop-dark', use: { browserName: 'webkit', viewport: { width: 1440, height: 900 } } },
    { name: 'chromium-mobile-rose', use: { ...devices['iPhone 13'], browserName: 'chromium', viewport: { width: 390, height: 844 } } },
    { name: 'webkit-mobile-dark', use: { ...devices['iPhone 13'], viewport: { width: 390, height: 844 } } },
  ],
})
