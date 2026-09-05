import { defineConfig, devices } from '@playwright/test'

const baseURL = 'http://127.0.0.1:4181'

export default defineConfig({
  testDir: './tests',
  testMatch: 'trackers.spec.ts',
  fullyParallel: false,
  timeout: 30_000,
  expect: { timeout: 8_000 },
  use: { baseURL, trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  webServer: {
    command: 'npm run build && npm run preview -- --host 127.0.0.1 --port 4181 --strictPort',
    url: baseURL + '/login',
    reuseExistingServer: false,
    timeout: 120_000,
  },
  projects: [
    { name: 'chromium-1440-trackers', use: { browserName: 'chromium', viewport: { width: 1440, height: 900 } } },
    { name: 'webkit-1440-trackers', use: { browserName: 'webkit', viewport: { width: 1440, height: 900 } } },
    { name: 'chromium-iphone-trackers', use: { ...devices['iPhone 13'], browserName: 'chromium' } },
    { name: 'webkit-iphone-trackers', use: { ...devices['iPhone 13'], browserName: 'webkit' } },
  ],
})
