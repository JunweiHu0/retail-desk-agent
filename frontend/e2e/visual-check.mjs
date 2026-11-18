import { mkdir } from 'node:fs/promises'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium, expect } from '@playwright/test'

const output = fileURLToPath(new URL('../test-results/visual/', import.meta.url))
await mkdir(output, { recursive: true })
const browser = await chromium.launch()
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto(process.env.BASE_URL || 'http://127.0.0.1:8000')
  await expect(page.locator('.availability')).toHaveText('在线')
  await page.screenshot({ path: join(output, 'desktop.png'), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: join(output, 'mobile.png'), fullPage: true })
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.getByRole('button', { name: /^取消订单/ }).click()
  await page.getByRole('button', { name: '填入示例订单' }).click()
  await page.getByRole('button', { name: '查看变更预览' }).click()
  await expect(page.getByTestId('approval-card')).toBeVisible()
  await page.screenshot({ path: join(output, 'confirmation.png'), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: join(output, 'mobile-confirmation.png'), fullPage: true })
  await page.getByRole('button', { name: '取消操作', exact: true }).click()
  await expect(page.getByRole('textbox', { name: '输入咨询内容' })).toBeEnabled()
  expect(errors).toEqual([])
} finally { await browser.close() }
