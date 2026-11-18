// Explicit opt-in: this checks the running live service and incurs model usage.
import { mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { chromium, expect } from '@playwright/test'

if (!process.argv.includes('--run-live')) throw new Error('Pass --run-live to allow paid model calls')
const base = process.env.BASE_URL || 'http://127.0.0.1:8000'
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL })
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  const errors = []
  page.on('pageerror', err => errors.push(err.message))
  await page.goto(base)
  const health = await (await page.request.get(new URL('api/health', base.endsWith('/') ? base : base + '/').href)).json()
  if (health.mode !== 'live' || !health.model.startsWith('deepseek')) throw new Error('Live DeepSeek service required')
  await page.getByRole('button', { name: '填入演示账户 李明' }).click()
  await page.getByRole('button', { name: '登录', exact: true }).click()
  const input = page.getByRole('textbox', { name: '输入咨询内容' })
  await input.fill('请查询我的订单状态。')
  await page.getByRole('button', { name: '发送消息' }).click()
  await expect(page.locator('.assistant .bubble').first()).toBeVisible({ timeout: 180000 })
  await expect(input).toBeEnabled({ timeout: 10000 })
  const nav = page.getByRole('navigation', { name: '账户导航' })
  await nav.getByRole('link', { name: '我的订单' }).click()
  await expect(page.locator('.listed-order').first()).toBeVisible()
  await nav.getByRole('link', { name: '客户资料' }).click()
  await expect(page.getByText('li.ming@retail-demo.example.com', { exact: true })).toBeVisible()
  await nav.getByRole('link', { name: '客服助手' }).click()
  const output = new URL('../test-results/', import.meta.url)
  await mkdir(fileURLToPath(output), { recursive: true })
  await page.screenshot({ path: fileURLToPath(new URL('deepseek-live.png', output)), fullPage: true })
  expect(errors).toEqual([])
  console.log(JSON.stringify({ status: 'passed', model: health.model }))
} finally { await browser.close() }
