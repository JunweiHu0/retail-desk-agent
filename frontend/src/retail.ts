import type { Address, Customer, Item, Message, Order, Pending, Service, Session, Transaction } from './types'

export const services: Record<Service, { title: string; detail: string }> = {
  query: { title: '查询订单', detail: '查看订单与物流' },
  return: { title: '申请退货', detail: '核对商品与退款方式' },
  cancel: { title: '取消订单', detail: '核对取消原因' },
}

const statuses: Record<string, string> = {
  pending: '待处理', processed: '处理中', delivered: '已送达', cancelled: '已取消',
  'pending (item modified)': '商品已修改', 'return requested': '已申请退货', 'exchange requested': '已申请换货',
}
const actions: Record<string, string> = {
  cancel_pending_order: '取消订单', modify_pending_order_address: '修改收货地址',
  modify_pending_order_items: '修改订单商品', modify_pending_order_payment: '修改支付方式',
  modify_user_address: '修改默认地址', return_delivered_order_items: '申请退货',
  exchange_delivered_order_items: '申请换货',
}
const currency = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })
export const money = (amount: number) => currency.format(amount)
export const statusLabel = (status: string) => statuses[status] || status
export const actionLabel = (tool: string) => actions[tool] || '服务申请'
export const orderTotal = (order: Order) => order.items.reduce((sum, item) => sum + item.price, 0)
export const fullName = (user: Customer) => [user.name.first_name, user.name.last_name].filter(Boolean).join(' ')
export const addressText = (value: Address) =>
  [value.address1, value.address2, value.city, [value.state, value.zip].filter(Boolean).join(' '), value.country].filter(Boolean).join(', ')

export function paymentLabel(id: string, user: Customer) {
  const method = user.payment_methods[id]
  if (method?.source === 'paypal' || id.startsWith('paypal')) return 'PayPal · ' + id.slice(-4)
  if (method?.source === 'gift_card' || id.startsWith('gift_card')) return '礼品卡 · ' + id.slice(-4)
  if (method?.source === 'credit_card' || id.startsWith('credit_card')) {
    return (method?.brand?.toUpperCase() || '信用卡') + ' · ' + (method?.last_four || id.slice(-4))
  }
  return '支付方式 · ' + id.slice(-4)
}

export function progressLabel(tool = '') {
  if (tool.startsWith('find_user') || tool === 'get_user_details') return '正在核验账户'
  if (tool === 'get_order_details') return '正在查询订单'
  if (tool === 'calculate') return '正在核对金额'
  if (tool.startsWith('get_') || tool.startsWith('list_')) return '正在查找商品'
  if (tool in actions) return '正在准备变更明细'
  if (tool === 'transfer_to_human_agents') return '正在记录转接请求'
  return '正在处理你的咨询'
}

const addressFields = {
  address1: '街道地址', address2: '详细地址', city: '城市', state: '州 / 省', zip: '邮编', country: '国家',
}
const reasons: Record<string, string> = { 'no longer needed': '不再需要', 'ordered by mistake': '误下单' }
const reasonLabel = (value: string) => reasons[value] || value
const priceDifference = (amount: number) => amount === 0 ? '无差价' : (amount > 0 ? '需补付 ' : '应退回 ') + money(Math.abs(amount))
const transactionText = (t: Transaction, user: Customer) =>
  (t.transaction_type === 'refund' ? '退款 ' : '付款 ') + money(t.amount) + ' · ' + paymentLabel(t.payment_method_id, user)
const itemLine = (item: Item) => [item.name, ...Object.values(item.options), '货号 ' + item.item_id, money(item.price)].join(' · ')

export function paymentAndServiceFields(order: Order, user: Customer) {
  const items = (ids: string[]) => ids.map(id => {
    const item = order.items.find(candidate => candidate.item_id === id)
    return item ? itemLine(item) : '货号 ' + id
  }).join('\n')
  return [
    { label: '付款与退款记录', value: order.payment_history.map(entry => transactionText(entry, user)).join('\n') },
    { label: '取消原因', value: order.cancel_reason && reasonLabel(order.cancel_reason) },
    { label: '退货商品', value: order.return_items && items(order.return_items) },
    { label: '退款方式', value: order.return_payment_method_id && paymentLabel(order.return_payment_method_id, user) },
    { label: '换出商品', value: order.exchange_items && items(order.exchange_items) },
    { label: '换入商品', value: order.exchange_new_items && items(order.exchange_new_items) },
    { label: '换货差价', value: order.exchange_price_difference != null && priceDifference(order.exchange_price_difference) },
    { label: '差价支付或退款方式', value: order.exchange_payment_method_id && paymentLabel(order.exchange_payment_method_id, user) },
  ].filter(row => row.value)
}

export function changeRows(change: Pending) {
  const rows: { label: string; before: string; after: string }[] = []
  function compare<T>(label: string, a: T | null | undefined, b: T | null | undefined, format: (v: T) => string = String) {
    if (JSON.stringify(a ?? null) === JSON.stringify(b ?? null)) return
    rows.push({ label, before: a == null ? '—' : format(a) || '—', after: b == null ? '—' : format(b) || '—' })
  }
  function address(label: string, a: Address, b: Address) {
    for (const key of Object.keys(addressFields) as (keyof Address)[]) {
      compare(label + ' · ' + addressFields[key], a[key], b[key])
    }
  }
  const before = change.before, after = change.after
  const a = before.order, b = after.order
  const payment = (id: string) => paymentLabel(id, after.user)
  function itemNames(ids: string[]) {
    return ids.map(id => {
      const item = change.item_details?.[id] || a?.items.find(i => i.item_id === id) || b?.items.find(i => i.item_id === id)
      return item ? itemLine(item) : '货号 ' + id
    }).join('\n')
  }
  const payments = (entries: Transaction[]) => entries.map(entry => transactionText(entry, after.user)).join('\n')

  if (a && b) {
    compare('订单状态', a.status, b.status, statusLabel)
    compare('取消原因', a.cancel_reason, b.cancel_reason, reasonLabel)
    address('收货地址', a.address, b.address)
    compare('订单商品', a.items, b.items, items => items.map(itemLine).join('\n'))
    compare('退货商品', a.return_items, b.return_items, itemNames)
    compare('退款方式', a.return_payment_method_id, b.return_payment_method_id, payment)
    compare('换出商品', a.exchange_items, b.exchange_items, itemNames)
    compare('换入商品', a.exchange_new_items, b.exchange_new_items, itemNames)
    compare('换货差价', a.exchange_price_difference, b.exchange_price_difference, priceDifference)
    compare('差价支付或退款方式', a.exchange_payment_method_id, b.exchange_payment_method_id, payment)
    compare('付款与退款记录', a.payment_history, b.payment_history, payments)
  }
  address('默认地址', before.user.address, after.user.address)
  for (const id of new Set([...Object.keys(before.user.payment_methods), ...Object.keys(after.user.payment_methods)])) {
    compare(payment(id) + ' 余额', before.user.payment_methods[id]?.balance, after.user.payment_methods[id]?.balance, money)
  }
  return rows
}

const assistantCopy: Record<string, string> = {
  '只有已送达（delivered）的订单可以申请退货。': '只有已送达的订单可以申请退货。',
  '暂时无法继续：User not found\n请检查信息后再试。': '未找到这个账户，请核对下单邮箱后重试。',
  '已生成变更预览，尚未执行。请核对下方操作、商品与支付或退款明细，再点击「确认执行」；也可以取消本次操作。':
    '已为你准备好变更明细。请核对下方信息，再决定是否办理。',
  '你好，我是 Retail 客服助手。请提供账户邮箱，我会先核验身份，再查询或处理你的订单。也可以选择下方的模拟客户场景。':
    '请告诉我下单时使用的邮箱，我会先核验账户，再帮你查询或处理订单。',
  '演示模式请明确「全部商品退货，退回原支付方式」。真实模型模式支持逐项选择商品、退款方式和其他 Retail 操作。':
    '这项服务支持整单退货。如需办理，请确认要退回全部商品，并使用原支付方式接收退款。',
  '已查到你的账户和订单。当前为离线演示模式，支持查询、取消和整单退货；修改地址、支付方式、商品和换货请配置真实模型后使用。':
    '已查到你的账户和订单。当前可办理订单查询、取消和整单退货，暂时无法办理其他变更。',
  '查询到的订单不是 pending 状态，不能取消。你可以在右侧查看当前订单状态。':
    '只有待处理订单可以取消。你可以在「我的订单」中查看这笔订单的当前状态。',
  '已取消本次操作，数据未变更。': '已撤回本次申请，原有信息保持不变。',
  '模型请求未完成，请检查后端日志、API 配置或网络后重试。工具和已确认操作的结果仍保存在会话中。':
    '本次咨询暂未完成，请稍后重试。已经确认的办理结果仍可在这里查看。',
  'YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON.\n人工转接请求已记录在本次会话中。':
    '已记录人工转接请求，咨询和订单记录已保留。',
}

export function messageText(message: Message) {
  if (message.role === 'user') return message.content
  if (assistantCopy[message.content]) return assistantCopy[message.content]
  if (message.content.startsWith('YOU ARE BEING TRANSFERRED TO A HUMAN AGENT.')) return '已记录人工转接请求，咨询和订单记录已保留。'
  if (message.content.startsWith('操作已完成，变更已持久化。')) {
    const [, target] = message.content.split('\n')
    const [id, status] = (target || '').split(' · ')
    return ['已按你的确认完成办理。', [id, status && statusLabel(status)].filter(Boolean).join(' · ')].filter(Boolean).join('\n')
  }
  return message.content.replace('你可以查看右侧订单明细', '你可以在「我的订单」中查看明细')
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
