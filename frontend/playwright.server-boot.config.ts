import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  testMatch: 'server-boot-admin.spec.ts',
  outputDir: '/tmp/dpms-server-boot-playwright',
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 8_000 },
  reporter: 'list',
  use: {
    baseURL: 'http://localhost:55177',
    timezoneId: 'America/Los_Angeles',
    serviceWorkers: 'block',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  // The main session prepares the local candidate. Never start another server here.
  projects: [
    { name: 'chromium-desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
    { name: 'webkit-mobile', use: { ...devices['iPhone 13'], browserName: 'webkit' } },
  ],
})
