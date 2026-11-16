import { defineConfig, devices } from '@playwright/test'

// The spec fulfills the entire synthetic origin in memory; no listener or app build.
export default defineConfig({
  testDir: './tests',
  testMatch: 'outlook-connector.spec.ts',
  outputDir: '/tmp/dpms-outlook-connector-results',
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 8_000 },
  reporter: 'line',
  use: {
    baseURL: 'https://outlook-fixture.test',
    serviceWorkers: 'block',
    trace: 'off',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
    { name: 'iphone', use: { ...devices['iPhone 13'], colorScheme: 'dark' } },
    { name: 'narrow', use: { ...devices['Desktop Chrome'], viewport: { width: 320, height: 700 } } },
  ],
})
