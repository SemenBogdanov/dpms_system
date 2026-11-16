import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  testMatch: 'content-layout.spec.ts',
  timeout: 45_000,
  expect: { timeout: 8_000 },
  workers: 2,
  use: {
    baseURL: 'http://localhost:55177',
    locale: 'ru-RU',
    serviceWorkers: 'block',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'node --input-type=module -e \'import { preview } from "vite"; await preview({ configFile: false, envFile: false, preview: { host: "127.0.0.1", port: 55177, strictPort: true } });\'',
    url: 'http://localhost:55177/login',
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
  projects: [
    { name: 'chromium-layout', use: { ...devices['Desktop Chrome'], viewport: { width: 1920, height: 1080 } } },
    { name: 'webkit-layout', use: { ...devices['Desktop Safari'], viewport: { width: 1920, height: 1080 } } },
    { name: 'webkit-mobile-layout', use: { ...devices['iPhone 13'], browserName: 'webkit' } },
  ],
})
