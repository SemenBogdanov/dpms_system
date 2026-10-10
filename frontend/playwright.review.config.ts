import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  testMatch: ['review-*.spec.ts', 'usage-navigation.spec.ts', 'graphs-acceptance-20260924.spec.ts'],
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 2,
  use: {
    baseURL: 'http://localhost:55177',
    locale: 'ru-RU',
    serviceWorkers: 'block',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium-review', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
    { name: 'webkit-review', use: { ...devices['iPhone 13'], browserName: 'webkit' } },
    { name: 'webkit-desktop-review', testMatch: 'graphs-acceptance-20260924.spec.ts', use: { ...devices['Desktop Safari'], viewport: { width: 1440, height: 1000 } } },
  ],
})
