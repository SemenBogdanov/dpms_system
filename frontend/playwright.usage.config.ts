import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  testMatch: ['admin-usage.spec.ts', 'usage-navigation.spec.ts'],
  fullyParallel: false,
  workers: 2,
  timeout: 30_000,
  expect: { timeout: 8_000 },
  use: { baseURL: 'http://localhost:55177', trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  projects: [
    { name: 'chromium-desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
    { name: 'webkit-desktop', use: { ...devices['Desktop Safari'], viewport: { width: 1440, height: 900 } } },
    { name: 'webkit-iphone-13', use: { ...devices['iPhone 13'], browserName: 'webkit' } },
  ],
})
