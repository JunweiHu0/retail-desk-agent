import { mkdir } from 'node:fs/promises'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium, expect } from '@playwright/test'

const output = fileURLToPath(new URL('../test-results/visual/', import.meta.url))
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL })
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto(process.env.BASE_URL || 'http://127.0.0.1:8000')
  await expect(page.getByRole('heading', { name: '登录账户' })).toBeVisible()
  await page.screenshot({ path: join(output, 'login.png'), fullPage: true })
  await page.getByRole('button', { name: '填入演示账户 李明' }).click()
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.locator('.availability')).toHaveText('在线')
  await page.screenshot({ path: join(output, 'assistant.png'), fullPage: true })
  const nav = page.getByRole('navigation', { name: '账户导航' })
  await nav.getByRole('link', { name: '我的订单' }).click()
  await expect(page.locator('.listed-order').first()).toBeVisible()
  await page.screenshot({ path: join(output, 'orders.png'), fullPage: true })
  await nav.getByRole('link', { name: '客户资料' }).click()
  await expect(page.getByRole('heading', { name: '客户资料' })).toBeVisible()
  await page.screenshot({ path: join(output, 'profile.png'), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: join(output, 'profile-mobile.png'), fullPage: true })
  expect(errors).toEqual([])
} finally { await browser.close() }
