import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  timeout: 60000,
  use: { baseURL: process.env.BASE_URL || 'http://127.0.0.1:8000', headless: true },
  reporter: 'list',
  workers: 1,
})
