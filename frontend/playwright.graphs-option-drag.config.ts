import { defineConfig, devices } from '@playwright/test'

if (process.env.DPMS_REVIEW_GRAPH_SOURCE === '1') {
  throw new Error('Option-drag acceptance requires the served candidate, not source injection')
}

export default defineConfig({
  testDir: './tests',
  testMatch: 'graphs-option-drag-20261020.spec.ts',
  outputDir: '../../dpms-release-artifacts/graphs-option-drag-20261020/browser',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: 'list',
  use: {
    baseURL: 'http://localhost:55177',
    locale: 'ru-RU',
    serviceWorkers: 'block',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium-option-drag', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
    { name: 'webkit-option-drag', use: { ...devices['Desktop Safari'], viewport: { width: 1440, height: 900 } } },
  ],
})
