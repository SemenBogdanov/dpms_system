import { defineConfig, devices } from '@playwright/test'

const baseURL = 'http://127.0.0.1:4176'

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
  testMatch: 'messages.spec.ts',
  fullyParallel: false,
  timeout: 30_000,
  expect: { timeout: 8_000 },
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'npm run build && npm run preview -- --host 127.0.0.1 --port 4176',
    url: 'http://127.0.0.1:4176/login',
    reuseExistingServer: true,
    timeout: 120_000,
  },
  projects: [
    {
      name: 'desktop-light-messages',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
        storageState: storageState('light'),
      },
    },
    {
      name: 'desktop-rose-messages',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1280, height: 800 },
        storageState: storageState('rose'),
      },
    },
    {
      name: 'iphone-dark-messages',
      use: {
        ...devices['iPhone 13 Pro'],
        storageState: storageState('dark'),
      },
    },
  ],
})
