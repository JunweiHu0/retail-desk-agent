import { locale, t } from './i18n'
import type { Address, Customer, Item, Message, Order, Pending, Service, Session, Transaction } from './types'

export const serviceKeys: Service[] = ['query', 'return', 'cancel']

export function serviceTitle(service: Service) {
  return {
    query: t('查询订单', 'Order status'),
    return: t('申请退货', 'Return items'),
    cancel: t('取消订单', 'Cancel order'),
  }[service]
}

export function serviceDetail(service: Service) {
  return {
    query: t('查看订单与物流', 'Track orders and delivery'),
    return: t('核对商品与退款方式', 'Review items and refund method'),
    cancel: t('核对取消原因', 'Review the cancellation reason'),
  }[service]
}

export const statusValues = [
  'pending', 'processed', 'delivered', 'cancelled', 'pending (item modified)',
  'return requested', 'exchange requested',
]

const actionLabels: Record<string, [string, string]> = {
  cancel_pending_order: ['取消订单', 'Cancel order'],
  modify_pending_order_address: ['修改收货地址', 'Change shipping address'],
  modify_pending_order_items: ['修改订单商品', 'Change order items'],
  modify_pending_order_payment: ['修改支付方式', 'Change payment method'],
  modify_user_address: ['修改默认地址', 'Change default address'],
  return_delivered_order_items: ['申请退货', 'Return items'],
  exchange_delivered_order_items: ['申请换货', 'Exchange items'],
}
const currency = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })
export const money = (amount: number) => currency.format(amount)
export const statusLabel = (status: string) => {
  const labels: Record<string, [string, string]> = {
    pending: ['待处理', 'Pending'],
    processed: ['处理中', 'Processing'],
    delivered: ['已送达', 'Delivered'],
    cancelled: ['已取消', 'Cancelled'],
    'pending (item modified)': ['商品已修改', 'Items modified'],
    'return requested': ['已申请退货', 'Return requested'],
    'exchange requested': ['已申请换货', 'Exchange requested'],
  }
  const pair = labels[status]
  return pair ? t(pair[0], pair[1]) : status
}
export const actionLabel = (tool: string) => {
  const pair = actionLabels[tool]
  return pair ? t(pair[0], pair[1]) : t('服务申请', 'Service request')
}
export const orderTotal = (order: Order) => order.items.reduce((sum, item) => sum + item.price, 0)
export const fullName = (user: Customer) => [user.name.first_name, user.name.last_name].filter(Boolean).join(' ')
export const addressText = (value: Address) =>
  [value.address1, value.address2, value.city, [value.state, value.zip].filter(Boolean).join(' '), value.country].filter(Boolean).join(', ')

export function paymentLabel(id: string, user: Customer) {
  const method = user.payment_methods[id]
  if (method?.source === 'paypal' || id.startsWith('paypal')) return 'PayPal · ' + id.slice(-4)
  if (method?.source === 'gift_card' || id.startsWith('gift_card')) return t('礼品卡', 'Gift card') + ' · ' + id.slice(-4)
  if (method?.source === 'credit_card' || id.startsWith('credit_card')) {
    return (method?.brand?.toUpperCase() || t('信用卡', 'Credit card')) + ' · ' + (method?.last_four || id.slice(-4))
  }
  return t('支付方式', 'Payment method') + ' · ' + id.slice(-4)
}

export function progressLabel(tool = '') {
  if (tool.startsWith('find_user') || tool === 'get_user_details') return t('正在核验账户', 'Verifying your account')
  if (tool === 'get_order_details') return t('正在查询订单', 'Looking up the order')
  if (tool === 'calculate') return t('正在核对金额', 'Checking the amount')
  if (tool.startsWith('get_') || tool.startsWith('list_')) return t('正在查找商品', 'Looking up products')
  if (tool in actionLabels) return t('正在准备变更明细', 'Preparing the change details')
  if (tool === 'transfer_to_human_agents') return t('正在记录转接请求', 'Recording the handoff')
  return t('正在处理你的咨询', 'Working on your request')
}

export const addressFieldKeys = ['address1', 'address2', 'city', 'state', 'zip', 'country'] as const
export function addressFieldLabel(key: string) {
  const labels: Record<string, [string, string]> = {
    address1: ['街道地址', 'Street address'],
    address2: ['详细地址', 'Address line 2'],
    city: ['城市', 'City'],
    state: ['州 / 省', 'State / province'],
    zip: ['邮编', 'ZIP / postal code'],
    country: ['国家', 'Country'],
  }
  const pair = labels[key]
  return pair ? t(pair[0], pair[1]) : key
}
const reasonLabels: Record<string, [string, string]> = {
  'no longer needed': ['不再需要', 'No longer needed'],
  'ordered by mistake': ['误下单', 'Ordered by mistake'],
}
const reasonLabel = (value: string) => {
  const pair = reasonLabels[value]
  return pair ? t(pair[0], pair[1]) : value
}
const priceDifference = (amount: number) => amount === 0
  ? t('无差价', 'No difference')
  : (amount > 0 ? t('需补付 ', 'Pay ') : t('应退回 ', 'Refund ')) + money(Math.abs(amount))
const transactionText = (entry: Transaction, user: Customer) =>
  (entry.transaction_type === 'refund' ? t('退款 ', 'Refund ') : t('付款 ', 'Payment '))
  + money(entry.amount) + ' · ' + paymentLabel(entry.payment_method_id, user)
const itemLine = (item: Item) =>
  [item.name, ...Object.values(item.options), t('货号 ', 'Item ') + item.item_id, money(item.price)].join(' · ')

export function paymentAndServiceFields(order: Order, user: Customer) {
  const items = (ids: string[]) => ids.map(id => {
    const item = order.items.find(candidate => candidate.item_id === id)
    return item ? itemLine(item) : t('货号 ', 'Item ') + id
  }).join('\n')
  return [
    { label: t('付款与退款记录', 'Payments and refunds'), value: order.payment_history.map(entry => transactionText(entry, user)).join('\n') },
    { label: t('取消原因', 'Cancellation reason'), value: order.cancel_reason && reasonLabel(order.cancel_reason) },
    { label: t('退货商品', 'Returned items'), value: order.return_items && items(order.return_items) },
    { label: t('退款方式', 'Refund method'), value: order.return_payment_method_id && paymentLabel(order.return_payment_method_id, user) },
    { label: t('换出商品', 'Exchanged from'), value: order.exchange_items && items(order.exchange_items) },
    { label: t('换入商品', 'Exchanged to'), value: order.exchange_new_items && items(order.exchange_new_items) },
    { label: t('换货差价', 'Exchange price difference'), value: order.exchange_price_difference != null && priceDifference(order.exchange_price_difference) },
    { label: t('差价支付或退款方式', 'Difference payment or refund method'), value: order.exchange_payment_method_id && paymentLabel(order.exchange_payment_method_id, user) },
  ].filter(row => row.value)
}

export function changeRows(change: Pending) {
  const rows: { label: string; before: string; after: string }[] = []
  function compare<T>(label: string, a: T | null | undefined, b: T | null | undefined, format: (v: T) => string = String) {
    if (JSON.stringify(a ?? null) === JSON.stringify(b ?? null)) return
    rows.push({ label, before: a == null ? '—' : format(a) || '—', after: b == null ? '—' : format(b) || '—' })
  }
  function address(label: string, a: Address, b: Address) {
    for (const key of addressFieldKeys as readonly (keyof Address)[]) {
      compare(label + ' · ' + addressFieldLabel(key), a[key], b[key])
    }
  }
  const before = change.before, after = change.after
  const a = before.order, b = after.order
  const payment = (id: string) => paymentLabel(id, after.user)
  function itemNames(ids: string[]) {
    return ids.map(id => {
      const item = change.item_details?.[id] || a?.items.find(i => i.item_id === id) || b?.items.find(i => i.item_id === id)
      return item ? itemLine(item) : t('货号 ', 'Item ') + id
    }).join('\n')
  }
  const payments = (entries: Transaction[]) => entries.map(entry => transactionText(entry, after.user)).join('\n')

  if (a && b) {
    compare(t('订单状态', 'Order status'), a.status, b.status, statusLabel)
    compare(t('取消原因', 'Cancellation reason'), a.cancel_reason, b.cancel_reason, reasonLabel)
    address(t('收货地址', 'Shipping address'), a.address, b.address)
    compare(t('订单商品', 'Order items'), a.items, b.items, items => items.map(itemLine).join('\n'))
    compare(t('退货商品', 'Returned items'), a.return_items, b.return_items, itemNames)
    compare(t('退款方式', 'Refund method'), a.return_payment_method_id, b.return_payment_method_id, payment)
    compare(t('换出商品', 'Exchanged from'), a.exchange_items, b.exchange_items, itemNames)
    compare(t('换入商品', 'Exchanged to'), a.exchange_new_items, b.exchange_new_items, itemNames)
    compare(t('换货差价', 'Exchange price difference'), a.exchange_price_difference, b.exchange_price_difference, priceDifference)
    compare(t('差价支付或退款方式', 'Difference payment or refund method'), a.exchange_payment_method_id, b.exchange_payment_method_id, payment)
    compare(t('付款与退款记录', 'Payments and refunds'), a.payment_history, b.payment_history, payments)
  }
  address(t('默认地址', 'Default address'), before.user.address, after.user.address)
  for (const id of new Set([...Object.keys(before.user.payment_methods), ...Object.keys(after.user.payment_methods)])) {
    compare(payment(id) + t(' 余额', ' balance'), before.user.payment_methods[id]?.balance, after.user.payment_methods[id]?.balance, money)
  }
  return rows
}

const assistantCopy: Record<string, string> = {
  '只有已送达（delivered）的订单可以申请退货。': '只有已送达的订单可以申请退货。',
  '暂时无法继续：User not found\n请检查信息后再试。': '未找到这个账户，请核对下单邮箱后重试。',
  '已生成变更预览，尚未执行。请核对下方操作、商品与支付或退款明细，再点击「确认执行」；也可以取消本次操作。':
    '已为你准备好变更明细。请核对下方信息，再决定是否办理。',
  '已生成变更预览，尚未执行。请核对操作、商品与支付或退款明细，再点击确认执行或取消。':
    '已为你准备好变更明细。请核对下方信息，再决定是否办理。',
  '你好，我是 Retail 客服助手。请提供账户邮箱，我会先核验身份，再查询或处理你的订单。也可以选择下方的模拟客户场景。':
    '请告诉我下单时使用的邮箱，我会先核验账户，再帮你查询或处理订单。',
  '演示模式请明确「全部商品退货，退回原支付方式」。真实模型模式支持逐项选择商品、退款方式和其他 Retail 操作。':
    '这项服务支持整单退货。如需办理，请确认要退回全部商品，并使用原支付方式接收退款。',
  '已查到你的账户和订单。当前为离线演示模式，支持查询、取消和整单退货；修改地址、支付方式、商品和换货请配置真实模型后使用。':
    '已查到你的账户和订单。你可以在「我的订单」办理售后，或在「客户资料」修改默认地址。',
  '查询到的订单不是 pending 状态，不能取消。你可以在右侧查看当前订单状态。':
    '只有待处理订单可以取消。你可以在「我的订单」中查看这笔订单的当前状态。',
  '已取消本次操作，数据未变更。': '已撤回本次申请，原有信息保持不变。',
  '模型请求未完成，请检查后端日志、API 配置或网络后重试。工具和已确认操作的结果仍保存在会话中。':
    '本次咨询暂未完成，请稍后重试。已经确认的办理结果仍可在这里查看。',
  'YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON.\n人工转接请求已记录在本次会话中。':
    '已记录人工转接请求，咨询和订单记录已保留。',
}

const assistantCopyEn: Record<string, string> = {
  '只有已送达（delivered）的订单可以申请退货。': 'Only delivered orders can be returned.',
  '暂时无法继续：User not found\n请检查信息后再试。': 'We could not find that account. Please check the email used for the order and try again.',
  '已生成变更预览，尚未执行。请核对下方操作、商品与支付或退款明细，再点击「确认执行」；也可以取消本次操作。':
    'Your change is ready for review. Check the details below, then confirm or cancel.',
  '已生成变更预览，尚未执行。请核对操作、商品与支付或退款明细，再点击确认执行或取消。':
    'A change preview is ready but not executed. Review the operation, items and payment or refund details, then approve or cancel.',
  '你好，我是 Retail 客服助手。请提供账户邮箱，我会先核验身份，再查询或处理你的订单。也可以选择下方的模拟客户场景。':
    'Tell me the email used for your order and I will verify the account before helping.',
  '演示模式请明确「全部商品退货，退回原支付方式」。真实模型模式支持逐项选择商品、退款方式和其他 Retail 操作。':
    'This service returns the whole order to the original payment method. Confirm that you want to return every item.',
  '已查到你的账户和订单。当前为离线演示模式，支持查询、取消和整单退货；修改地址、支付方式、商品和换货请配置真实模型后使用。':
    'I found your account and orders. Use My orders for after-sales help, or Profile to change your default address.',
  '查询到的订单不是 pending 状态，不能取消。你可以在右侧查看当前订单状态。':
    'Only pending orders can be cancelled. You can check the current status in My orders.',
  '已取消本次操作，数据未变更。': 'The request was withdrawn; nothing changed.',
  '模型请求未完成，请检查后端日志、API 配置或网络后重试。工具和已确认操作的结果仍保存在会话中。':
    'This request did not complete. Please try again; confirmed changes remain in the conversation.',
  'YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON.\n人工转接请求已记录在本次会话中。':
    'The handoff request has been recorded and the conversation and orders are preserved.',
}

export function messageText(message: Message) {
  if (message.role === 'user') return message.content
  if (locale.value === 'en' && assistantCopyEn[message.content]) return assistantCopyEn[message.content]
  if (assistantCopy[message.content]) return assistantCopy[message.content]
  if (message.content.startsWith('YOU ARE BEING TRANSFERRED TO A HUMAN AGENT.')) {
    return t('已记录人工转接请求，咨询和订单记录已保留。', 'The handoff request has been recorded and the conversation and orders are preserved.')
  }
  if (message.content.startsWith('操作已完成，变更已持久化。')) {
    const [, target] = message.content.split('\n')
    const [id, status] = (target || '').split(' · ')
    return [
      t('已按你的确认完成办理。', 'Completed as approved.'),
      [id, status && statusLabel(status)].filter(Boolean).join(' · '),
    ].filter(Boolean).join('\n')
  }
  return message.content.replace(
    '你可以查看右侧订单明细',
    t('你可以在「我的订单」中查看明细', 'You can review the details in My orders'),
  )
}

export function receiptsByMessage(session: Session | null) {
  const result = new Map<string, { change: Pending; time: string }>()
  if (!session) return result
  const receipts = session.events.flatMap(event =>
    event.kind === 'decision' && event.data.approved && event.data.before && event.data.after
      ? [{ change: event.data, time: event.created_at }] : [])
  // Pair only the server's confirmation message with a committed change to the same subject.
  session.messages.forEach((message, index) => {
    if (message.role !== 'assistant' || !message.content.startsWith('操作已完成，变更已持久化。')) return
    const previous = session.messages[index - 1]
    if (previous?.role !== 'user' || previous.content !== '确认执行') return
    const target = message.content.split('\n')[1]
    const match = receipts.findIndex(({ change }) => {
      const { order, user } = change.after
      return target === (order ? order.order_id + ' · ' + order.status : user.user_id + ' · 资料已更新')
    })
    if (match !== -1) result.set(message.id, receipts.splice(match, 1)[0])
  })
  return result
}
