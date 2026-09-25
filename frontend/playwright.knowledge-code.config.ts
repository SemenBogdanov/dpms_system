import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  testMatch: 'knowledge-code-blocks.spec.ts',
  outputDir: '/tmp/dpms-knowledge-code-playwright',
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 8_000 },
  reporter: 'list',
  use: {
    baseURL: 'http://localhost:55177',
    serviceWorkers: 'block',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  // The integrator prepares the existing runtime; this suite starts no server.
  projects: [
    { name: 'chromium-desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
    { name: 'webkit-mobile', use: { ...devices['iPhone 13'], browserName: 'webkit' } },
    {
      name: 'webkit-desktop-input',
      grep: /bounded scrollable code/,
      use: { ...devices['Desktop Safari'], browserName: 'webkit', viewport: { width: 1440, height: 900 } },
    },
  ],
})
