// Explicit opt-in: this checks the actual running live service and incurs model usage.
import { chromium, expect } from '@playwright/test'

if (!process.argv.includes('--run-live')) throw new Error('Pass --run-live to allow paid model calls')
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } })
const errors = []
page.on('pageerror', e => errors.push(e.message))
await page.goto('http://127.0.0.1:8000')
await page.getByRole('button', { name: 'li.ming ↗', exact: true }).click()
await page.getByRole('button', { name: '登录工作台 →', exact: true }).click()
const health = await (await page.request.get('http://127.0.0.1:8000/api/health')).json()
if (health.mode !== 'live' || !health.model.startsWith('deepseek')) throw new Error('Live DeepSeek service required')
await expect(page.locator('.mode-tag')).toHaveText('真实模型')
await page.getByRole('button', { name: /我的订单到哪了/ }).click()
await expect(page.locator('.messages .assistant .bubble').first()).toBeVisible({ timeout: 180000 })
await expect(page.getByRole('textbox', { name: '输入咨询内容' })).toBeEnabled({ timeout: 10000 })
await expect(page.locator('.verified')).toBeVisible()
await expect(page.locator('.order-card').first()).toBeVisible()
await expect(page.locator('.error-banner')).toHaveCount(0)
await page.getByRole('button', { name: '订单管理', exact: true }).click()
await expect(page.locator('.order-tile').first()).toBeVisible()
await page.getByRole('button', { name: '个人信息', exact: true }).click()
await expect(page.getByText('li.ming@retail-demo.example.com', { exact: true })).toBeVisible()
await page.getByRole('button', { name: '客服助手', exact: true }).click()
await page.screenshot({ path: '../docs/screenshots/deepseek-live.png', fullPage: true })
console.log(JSON.stringify({ status: 'passed', model: health.model,
  verifiedCustomer: await page.locator('.customer-top h3').innerText(),
  orderCards: await page.locator('.order-card').count(), browserErrors: errors }))
await browser.close()
if (errors.length) process.exitCode = 1
