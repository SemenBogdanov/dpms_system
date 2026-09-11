import { fileURLToPath } from 'node:url'
import { defineConfig, devices } from '@playwright/test'

const baseURL = 'http://127.0.0.1:4196'
const regression = process.env.DPMS_AUDIT_REVIEW_REGRESSION === '1'
const dist = process.env.DPMS_AUDIT_TEST_DIST || 'dist'

export default defineConfig({
  testDir: '.',
  testMatch: regression ? 'audit-review.spec.ts' : 'audit-skills-provenance.spec.ts',
  outputDir: regression ? '/tmp/dpms-id64a-review-regression' : '/tmp/dpms-id64a-provenance-playwright',
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 8_000 },
  use: { baseURL, screenshot: 'only-on-failure', trace: 'retain-on-failure' },
  webServer: {
    cwd: fileURLToPath(new URL('..', import.meta.url)),
    command: `node --input-type=module -e "import {preview} from 'vite'; await preview({envDir:'/tmp/dpms-id64a-no-env',build:{outDir:process.env.DPMS_AUDIT_TEST_DIST || 'dist'},preview:{host:'127.0.0.1',port:4196,strictPort:true,proxy:{'/api':{target:'http://127.0.0.1:1'}}}})"`,
    env: { DPMS_AUDIT_TEST_DIST: dist },
    url: `${baseURL}/login`,
    reuseExistingServer: false,
  },
  projects: [
    { name: 'desktop-light', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
    { name: 'iphone-dark', use: { ...devices['iPhone 13'], browserName: 'webkit' } },
    { name: 'desktop-rose', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
    { name: 'wide-light', use: { ...devices['Desktop Chrome'], viewport: { width: 1920, height: 1080 } } },
    { name: 'tablet-light', use: { ...devices['Desktop Chrome'], viewport: { width: 1024, height: 768 } } },
    { name: 'narrow-dark', use: { ...devices['Desktop Chrome'], viewport: { width: 320, height: 700 } } },
  ],
})
