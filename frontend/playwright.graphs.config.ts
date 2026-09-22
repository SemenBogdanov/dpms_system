import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  testMatch: 'graphs-integration.spec.ts',
  fullyParallel: false,
  timeout: 30_000,
  expect: {
    timeout: 8_000,
  },
  use: {
    baseURL: 'http://127.0.0.1:4176',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'npm run preview -- --host 127.0.0.1 --port 4176',
    url: 'http://127.0.0.1:4176/login',
    reuseExistingServer: true,
    timeout: 30_000,
  },
  projects: [
    {
      name: 'chromium-desktop',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
      },
    },
    {
      name: 'webkit-iphone-13',
      use: {
        ...devices['iPhone 13'],
        browserName: 'webkit',
      },
    },
    {
      name: 'webkit-iphone-13-landscape',
      use: {
        ...devices['iPhone 13 landscape'],
        browserName: 'webkit',
      },
    },
  ],
})
