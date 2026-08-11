import { defineConfig, devices, type Project } from '@playwright/test'

const baseURL = 'http://127.0.0.1:4174'

function storageState(theme: 'light' | 'dark' | 'rose') {
  return {
    cookies: [],
    origins: [
      {
        origin: baseURL,
        localStorage: [{ name: 'dpms-theme', value: theme }],
      },
    ],
  }
}

const projects: Project[] = [
  {
    name: 'chromium-1440-light',
    use: { browserName: 'chromium', viewport: { width: 1440, height: 900 }, storageState: storageState('light') },
  },
  {
    name: 'webkit-1440-light',
    use: { browserName: 'webkit', viewport: { width: 1440, height: 900 }, storageState: storageState('light') },
  },
  {
    name: 'chromium-1024-rose',
    use: { browserName: 'chromium', viewport: { width: 1024, height: 768 }, storageState: storageState('rose') },
  },
  {
    name: 'webkit-1024-rose',
    use: { browserName: 'webkit', viewport: { width: 1024, height: 768 }, storageState: storageState('rose') },
  },
  {
    name: 'chromium-390-dark',
    use: { ...devices['iPhone 13'], browserName: 'chromium', storageState: storageState('dark') },
  },
  {
    name: 'webkit-390-dark',
    use: { ...devices['iPhone 13'], browserName: 'webkit', storageState: storageState('dark') },
  },
  {
    name: 'chromium-320-light',
    use: {
      ...devices['iPhone 13'],
      browserName: 'chromium',
      viewport: { width: 320, height: 700 },
      storageState: storageState('light'),
    },
  },
  {
    name: 'webkit-320-light',
    use: {
      ...devices['iPhone 13'],
      browserName: 'webkit',
      viewport: { width: 320, height: 700 },
      storageState: storageState('light'),
    },
  },
]

export default defineConfig({
  testDir: './tests/mobile',
  grep: /delegated Q execution|acceptance draft|acceptance loading|acceptance stale|acceptance revision/,
  fullyParallel: false,
  timeout: 30_000,
  expect: { timeout: 8_000 },
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'npm run preview -- --host 127.0.0.1 --port 4174',
    url: `${baseURL}/login`,
    reuseExistingServer: true,
    timeout: 30_000,
  },
  projects,
})
