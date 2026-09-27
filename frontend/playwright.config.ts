import { defineConfig, devices } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const E2E_DB_DIR = path.resolve(__dirname, '.e2e-db')

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: process.env.CI ? [['github'], ['list']] : 'list',
  timeout: 90_000,
  expect: { timeout: 15_000 },
  globalSetup: path.join(__dirname, 'e2e', 'global-setup.ts'),
  use: {
    baseURL: 'http://127.0.0.1:5188',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'frontend',
      testMatch: /consent-workflow\.spec\.ts/,
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'marketing',
      testMatch: /marketing-demo\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], baseURL: 'http://localhost:3100' },
    },
  ],
  webServer: [
    {
      command: 'npm run dev -- --port 5188 --strictPort',
      cwd: __dirname,
      url: 'http://127.0.0.1:5188',
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      command:
        'if [ -f .venv/bin/python ]; then .venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000; else python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000; fi',
      cwd: path.resolve(__dirname, '..'),
      url: 'http://127.0.0.1:8000/docs',
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        MINDGUARD_DB_DIR: E2E_DB_DIR,
        JWT_SECRET: 'e2e-jwt-secret-do-not-use-in-prod',
        ENCRYPTION_KEY: 'e'.repeat(64),
        ENFORCE_CONSENT_ANALYSIS: 'true',
        HF_TOKEN: '',
        RESEND_API_KEY: '',
        RESEND_WEBHOOK_SECRET: '',
        CORS_ORIGINS: 'http://127.0.0.1:5188,http://localhost:5188,http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:3000,http://localhost:3000',
      },
    },
    {
      command: 'npm run dev -- --port 3100',
      cwd: path.resolve(__dirname, '..', 'marketing'),
      url: 'http://localhost:3100',
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        MINDGUARD_API_URL: 'http://127.0.0.1:8000',
      },
    },
  ],
})
