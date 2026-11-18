import { expect, test, type Page } from '@playwright/test'

async function sampleRequest(page: Page, title: '查询订单' | '申请退货' | '取消订单') {
  await page.getByRole('button', { name: new RegExp('^' + title) }).click()
  const dialog = page.getByRole('dialog', { name: title })
  await dialog.getByRole('button', { name: '填入示例订单' }).click()
  const orderId = await dialog.getByLabel('订单号', { exact: false }).inputValue()
  await dialog.getByRole('button', { name: title === '查询订单' ? title : '查看变更预览' }).click()
  return orderId
}

test('cancellation changes the reviewed order once and restores its receipt', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: /需要什么帮助/ })).toBeVisible()
  const id = await sampleRequest(page, '取消订单')
  const approval = page.getByTestId('approval-card')
  const order = page.locator('.order-card').filter({ hasText: id })
  await expect(approval).toContainText(id)
  await expect(approval).toContainText('付款与退款记录')
  await expect(order.locator('.status-tag')).toHaveText('待处理')
  await page.reload()
  await expect(approval).toContainText('待你确认')
  await expect(page.getByRole('textbox', { name: '输入咨询内容' })).toHaveCount(0)
  await page.getByRole('group', { name: '确认本次变更' }).getByRole('button', { name: '确认执行' }).click()
  await expect(order.locator('.status-tag')).toHaveText('已取消')
  const receipt = page.getByTestId('receipt-card')
  await expect(receipt).toContainText(id)
  await page.reload()
  await expect(order.locator('.status-tag')).toHaveText('已取消')
  await receipt.getByText('查看办理明细').click()
  await expect(receipt.getByRole('cell', { name: '已取消', exact: true })).toBeVisible()
  await expect(page.getByText(/工具轨迹|benchmark|已持久化|cancel_pending_order|本地开发环境/i)).toHaveCount(0)
})

test('mobile return rejection preserves the order and history remains reachable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  const id = await sampleRequest(page, '申请退货')
  const approval = page.getByTestId('approval-card')
  await expect(approval).toContainText('退款方式')
  await page.getByRole('button', { name: '取消操作' }).click()
  await expect(page.getByText('已撤回本次申请，原有信息保持不变。')).toBeVisible()
  await page.getByRole('link', { name: '我的订单' }).click()
  await expect(page.locator('.order-card').filter({ hasText: id }).locator('.status-tag')).toHaveText('已送达')
  await page.getByRole('button', { name: '新咨询', exact: true }).click()
  await expect(page.getByRole('heading', { name: /需要什么帮助/ })).toBeVisible()
  await page.getByRole('button', { name: '咨询记录' }).click()
  await page.getByRole('dialog', { name: '咨询记录' }).getByRole('button', { name: new RegExp(id) }).click()
  await expect(page.getByText('已撤回本次申请，原有信息保持不变。')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('Chinese input confirmation and rapid Enter presses send only one message', async ({ page }) => {
  let created = 0, sent = 0
  page.on('request', req => {
    if (req.method() !== 'POST') return
    if (req.url().endsWith('/api/sessions')) created++
    if (req.url().endsWith('/messages')) sent++
  })
  await page.goto('/')
  const input = page.getByRole('textbox', { name: '输入咨询内容' })
  await input.fill('你好')
  await input.dispatchEvent('keydown', { key: 'Enter', isComposing: true, bubbles: true })
  await expect(input).toHaveValue('你好')
  await input.press('Shift+Enter')
  await expect(input).toHaveValue('你好\n')
  expect(sent).toBe(0)
  await input.evaluate(el => {
    const enter = () => new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })
    el.dispatchEvent(enter())
    el.dispatchEvent(enter())
  })
  await expect(page.locator('.assistant .bubble')).toContainText('邮箱')
  await expect(page.locator('.message.user')).toHaveCount(1)
  expect(created).toBe(1)
  expect(sent).toBe(1)
})

test('a missing eligible sample cannot turn a delivered order into a cancellation shortcut', async ({ page }) => {
  await page.route('**/api/samples', route => route.fulfill({ json: { samples: [
    { name: 'Sample Customer', email: 'sample@example.test', order_id: '#W1234567', status: 'delivered', items: 1 },
  ] } }))
  await page.goto('/')
  await expect(page.locator('.availability')).toHaveText('在线')
  await Promise.all([
    page.waitForResponse('**/api/samples'),
    page.getByRole('button', { name: /^取消订单/ }).click(),
  ])
  const dialog = page.getByRole('dialog', { name: '取消订单' })
  await expect(dialog.getByRole('button', { name: '填入示例订单' })).toHaveCount(0)
  await expect(dialog.getByLabel('下单邮箱')).toBeEditable()
  await dialog.getByRole('button', { name: '关闭服务窗口' }).click()
  await page.getByRole('button', { name: /^申请退货/ }).click()
  await page.getByRole('button', { name: '填入示例订单' }).click()
  await expect(page.getByLabel('订单号')).toHaveValue('#W1234567')
})

test('live service never uses a sample identity; an expired saved session can start again', async ({ page }) => {
  let samples = 0
  page.on('request', req => { if (req.url().endsWith('/api/samples')) samples++ })
  await page.route('**/api/health', route => route.fulfill({ json: { mode: 'live', model_ready: true } }))
  await page.addInitScript(() => {
    localStorage.setItem('retail.sessions.v1', JSON.stringify([{ id: 'expired', token: 'old', title: '旧咨询' }]))
    localStorage.setItem('retail.active.v1', 'expired')
  })
  await page.goto('/')
  await page.getByRole('button', { name: /^查询订单/ }).click()
  await expect(page.getByLabel('下单邮箱')).toHaveValue('')
  await expect(page.getByRole('button', { name: '填入示例订单' })).toHaveCount(0)
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('retail.sessions.v1')!))).toEqual([])
  expect(samples).toBe(0)
})

test('a lost decision response reconciles the receipt without sending the decision again', async ({ page }) => {
  let submissions = 0
  await page.route('**/decisions', async route => {
    submissions++
    const result = await route.fetch()
    expect(result.ok()).toBe(true)
    await route.abort('failed')
  })
  await page.goto('/')
  const id = await sampleRequest(page, '取消订单')
  await page.getByRole('button', { name: '确认执行' }).click()
  await expect(page.getByTestId('receipt-card')).toContainText(id)
  await expect(page.getByTestId('approval-card')).toHaveCount(0)
  expect(submissions).toBe(1)
})

test('order lookup accepts CRLF streams and a final unterminated event', async ({ page }) => {
  let snapshotReads = 0
  page.on('request', req => { if (req.method() === 'GET' && /\/api\/sessions\/[^/]+$/.test(req.url())) snapshotReads++ })
  await page.route('**/messages', async route => {
    const response = await route.fetch()
    const body = (await response.text()).trimEnd().replaceAll('data: ', 'data:').replaceAll('\n', '\r\n')
    await route.fulfill({ status: response.status(), contentType: 'text/event-stream', body })
  })
  await page.goto('/')
  const id = await sampleRequest(page, '查询订单')
  await expect(page.locator('.assistant .bubble')).toContainText(id)
  await expect(page.locator('.order-card').filter({ hasText: id })).toBeVisible()
  expect(snapshotReads).toBe(0)
})

test('a stale approval can be withdrawn after another consultation changes the same order', async ({ page, browser, baseURL }) => {
  const other = await browser.newPage({ baseURL })
  try {
    await page.goto('/')
    await other.goto('/')
    const firstId = await sampleRequest(page, '取消订单')
    expect(await sampleRequest(other, '取消订单')).toBe(firstId)
    await expect(other.getByTestId('approval-card')).toBeVisible()
    await page.getByRole('button', { name: '确认执行' }).click()
    await expect(page.getByTestId('receipt-card')).toBeVisible()
    await other.getByRole('button', { name: '确认执行' }).click()
    await expect(other.getByTestId('approval-card')).toContainText('需重新申请')
    await expect(other.getByRole('button', { name: '确认执行' })).toBeDisabled()
    await other.getByRole('button', { name: '取消操作' }).click()
    await expect(other.getByTestId('approval-card')).toHaveCount(0)
    await expect(other.getByTestId('receipt-card')).toHaveCount(0)
  } finally { await other.close() }
})

test('a failed send keeps the draft available for a deliberate retry', async ({ page }) => {
  await page.route('**/api/sessions', route => route.fulfill({ status: 503, json: { detail: 'backend unavailable' } }), { times: 1 })
  await page.goto('/')
  const input = page.getByRole('textbox', { name: '输入咨询内容' })
  await input.fill('我想查询订单')
  await page.getByRole('button', { name: '发送消息' }).click()
  await expect(input).toHaveValue('我想查询订单')
  await expect(page.getByRole('alert')).toContainText('请稍后重试')
  await page.getByRole('button', { name: '发送消息' }).click()
  await expect(page.locator('.assistant .bubble')).toContainText('邮箱')
  await expect(page.locator('.message.user')).toHaveCount(1)
})

test('restoring an in-flight conversation fetches its final reply', async ({ page, request }) => {
  const created = await (await request.post('/api/sessions')).json()
  const first = { id: 'first', role: 'user', content: '我的订单到哪了？' }
  const last = { id: 'second', role: 'assistant', content: '请提供下单邮箱。' }
  const state = { id: created.id, title: first.content, transferred: false, context: { user: null, orders: [], pending: null }, events: [] }
  let reads = 0
  await page.route('**/api/sessions/' + created.id, route => route.fulfill({
    json: { ...state, messages: ++reads === 1 ? [first] : [first, last] },
  }))
  await page.addInitScript(item => {
    localStorage.setItem('retail.sessions.v1', JSON.stringify([item]))
    localStorage.setItem('retail.active.v1', item.id)
  }, created)
  await page.goto('/')
  await expect(page.getByRole('status')).toHaveText('正在准备回复')
  await expect(page.getByRole('textbox', { name: '输入咨询内容' })).toBeDisabled()
  await expect(page.locator('.assistant .bubble')).toHaveText(last.content)
  await expect(page.getByRole('textbox', { name: '输入咨询内容' })).toBeEnabled()
})
