import { defineConfig, devices } from '@playwright/test'

const baseURL = 'http://127.0.0.1:4179'

export default defineConfig({
  testDir: './tests',
  testMatch: 'account-continuity.spec.ts',
  fullyParallel: false,
  timeout: 30_000,
  expect: { timeout: 8_000 },
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'npm run build && npm run preview -- --host 127.0.0.1 --port 4179',
    url: `${baseURL}/login`,
    reuseExistingServer: true,
    timeout: 120_000,
  },
  projects: [
    {
      name: 'desktop-light-account-continuity',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
      },
    },
    {
      name: 'iphone-dark-account-continuity',
      use: {
        ...devices['iPhone 13 Pro'],
        storageState: {
          cookies: [],
          origins: [{
            origin: baseURL,
            localStorage: [{ name: 'dpms-theme', value: 'dark' }],
          }],
        },
      },
    },
  ],
})
