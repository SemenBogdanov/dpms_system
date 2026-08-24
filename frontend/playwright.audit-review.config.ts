import { defineConfig, devices } from '@playwright/test'

const baseURL = 'http://127.0.0.1:4177'

function storageState(theme: 'light' | 'dark' | 'rose') {
  return {
    cookies: [],
    origins: [{
      origin: baseURL,
      localStorage: [{ name: 'dpms-theme', value: theme }],
    }],
  }
}

export default defineConfig({
  testDir: './tests',
  testMatch: 'audit-review.spec.ts',
  fullyParallel: false,
  timeout: 30_000,
  expect: { timeout: 8_000 },
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'npm run preview -- --host 127.0.0.1 --port 4177',
    url: `${baseURL}/login`,
    reuseExistingServer: true,
    timeout: 30_000,
  },
  projects: [
    {
      name: 'desktop-light-audit-review',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
        storageState: storageState('light'),
      },
    },
    {
      name: 'iphone-dark-audit-review',
      use: {
        ...devices['iPhone 13 Pro'],
        storageState: storageState('dark'),
      },
    },
    {
      name: 'desktop-rose-audit-review',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
        storageState: storageState('rose'),
      },
    },
  ],
})
