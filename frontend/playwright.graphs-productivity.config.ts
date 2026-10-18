import { defineConfig, devices } from '@playwright/test'

// Served candidate only: no preview server, source override or alternate origin.
// Matrix: desktop Chromium/WebKit plus iPhone WebKit portrait/landscape.
export default defineConfig({
  testDir: './tests',
  testMatch: 'graphs-productivity-20261018.spec.ts',
  outputDir: '../../dpms-release-artifacts/graphs-productivity-20261018/browser-productivity',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 90_000,
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
    { name: 'chromium-productivity', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
    { name: 'webkit-productivity', use: { ...devices['Desktop Safari'], viewport: { width: 1440, height: 900 } } },
    { name: 'iphone-productivity', use: { ...devices['iPhone 13'], browserName: 'webkit' } },
    { name: 'iphone-landscape-productivity', use: { ...devices['iPhone 13 landscape'], browserName: 'webkit' } },
  ],
})
