import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  testMatch: 'realtime-notes.spec.ts',
  fullyParallel: false,
  timeout: 30_000,
  expect: {
    timeout: 8_000,
  },
  use: {
    baseURL: 'http://127.0.0.1:4175',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'npm run build && npm run preview -- --host 127.0.0.1 --port 4175',
    url: 'http://127.0.0.1:4175/login',
    reuseExistingServer: true,
    timeout: 120_000,
  },
  projects: [
    {
      name: 'chromium-realtime',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1280, height: 900 },
      },
    },
    {
      name: 'webkit-realtime',
      use: {
        ...devices['Desktop Safari'],
        viewport: { width: 1280, height: 900 },
      },
    },
    {
      name: 'iphone-realtime',
      use: {
        ...devices['iPhone 13 Pro'],
      },
    },
  ],
})
