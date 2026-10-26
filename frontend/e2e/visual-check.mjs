import { chromium, expect } from '@playwright/test'

const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1500, height: 1000 }, deviceScaleFactor: 1 })
const errors = []
page.on('pageerror', error => errors.push(error.message))
await page.goto('http://127.0.0.1:8000')
await page.getByRole('heading', { name: '不止回答，也能帮你处理。' }).waitFor()
await page.screenshot({ path: '../docs/screenshots/desktop.png', fullPage: true })
await page.getByRole('button', { name: /帮我取消订单/ }).click()
await page.getByTestId('approval-card').waitFor()
await page.screenshot({ path: '../docs/screenshots/confirmation.png', fullPage: true })
await page.getByRole('button', { name: '工具轨迹' }).click()
await page.screenshot({ path: '../docs/screenshots/tools.png', fullPage: true })
await page.getByRole('button', { name: '取消操作', exact: true }).click()
await expect(page.getByRole('textbox', { name: '输入咨询内容' })).toBeEnabled()
await page.setViewportSize({ width: 390, height: 844 })
await page.screenshot({ path: '../docs/screenshots/mobile.png', fullPage: true })
console.log(JSON.stringify({ browserErrors: errors, title: await page.title() }))
await browser.close()
if (errors.length) process.exitCode = 1
