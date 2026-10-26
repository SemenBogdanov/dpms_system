import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  testMatch: ['graphs-integration.spec.ts', 'graphs-*-20260924.spec.ts'],
  fullyParallel: false,
  timeout: 30_000,
  expect: {
    timeout: 8_000,
  },
  use: {
    baseURL: 'http://localhost:55177',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  // Checklist 1: exercise the rebuilt local Docker candidate, never a second preview URL.
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
