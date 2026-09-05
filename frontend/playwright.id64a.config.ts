import { defineConfig, devices, type Project } from '@playwright/test'

const baseURL = 'http://127.0.0.1:4178'

const projects: Project[] = [
  {
    name: 'chromium-1440-id64a',
    use: { browserName: 'chromium', viewport: { width: 1440, height: 900 } },
  },
  {
    name: 'webkit-1440-id64a',
    use: { browserName: 'webkit', viewport: { width: 1440, height: 900 } },
  },
  {
    name: 'chromium-iphone-id64a',
    use: { ...devices['iPhone 13'], browserName: 'chromium' },
  },
  {
    name: 'webkit-iphone-id64a',
    use: { ...devices['iPhone 13'], browserName: 'webkit' },
  },
]

export default defineConfig({
  testDir: './tests',
  testMatch: 'id64a.spec.ts',
  fullyParallel: false,
  timeout: 30_000,
  expect: { timeout: 8_000 },
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'npm run build && npm run preview -- --host 127.0.0.1 --port 4178',
    url: `${baseURL}/login`,
    reuseExistingServer: true,
    timeout: 120_000,
  },
  projects,
})
