import { fileURLToPath } from 'node:url'
import { defineConfig, devices } from '@playwright/test'

const baseURL = 'http://127.0.0.1:4186'

export default defineConfig({
  testDir: '.',
  testMatch: 'personal-task-form.spec.ts',
  outputDir: '../test-results/personal-task-form',
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 8_000 },
  use: { baseURL, screenshot: 'only-on-failure', trace: 'retain-on-failure' },
  webServer: {
    cwd: fileURLToPath(new URL('..', import.meta.url)),
    command: 'npm run preview -- --host 127.0.0.1 --port 4186 --strictPort',
    url: `${baseURL}/login`,
    reuseExistingServer: false,
  },
  projects: [
    { name: 'chromium-desktop', use: { browserName: 'chromium', viewport: { width: 1440, height: 900 } } },
    { name: 'webkit-desktop', use: { browserName: 'webkit', viewport: { width: 1440, height: 900 } } },
    { name: 'chromium-wide', use: { browserName: 'chromium', viewport: { width: 1920, height: 1080 } } },
    { name: 'chromium-tablet-rose', use: { browserName: 'chromium', viewport: { width: 1024, height: 768 } } },
    { name: 'chromium-iphone-dark', use: { ...devices['iPhone 13'], browserName: 'chromium' } },
    { name: 'webkit-iphone-dark', use: { ...devices['iPhone 13'], browserName: 'webkit' } },
    { name: 'webkit-narrow', use: { ...devices['iPhone 13'], browserName: 'webkit', viewport: { width: 320, height: 700 } } },
  ],
})
