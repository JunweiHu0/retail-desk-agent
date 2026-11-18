export type Message = { id: string; role: 'user' | 'assistant'; content: string }
export type Address = { address1: string; address2: string; city: string; state: string; country: string; zip: string }
export type Item = { name: string; product_id: string; item_id: string; price: number; options: Record<string, string> }
export type PaymentMethod = { source: string; last_four?: string; brand?: string; balance?: number }
export type Transaction = { transaction_type: string; amount: number; payment_method_id: string }
export type Order = {
  order_id: string
  status: string
  items: Item[]
  address: Address
  fulfillments: { tracking_id: string[]; item_ids: string[] }[]
  payment_history: Transaction[]
  cancel_reason?: string | null
  return_items?: string[] | null
  return_payment_method_id?: string | null
  exchange_items?: string[] | null
  exchange_new_items?: string[] | null
  exchange_payment_method_id?: string | null
  exchange_price_difference?: number | null
}
export type Customer = {
  user_id: string
  name: { first_name: string; last_name: string }
  email: string
  address: Address
  payment_methods: Record<string, PaymentMethod>
  orders: string[]
}
export type Snapshot = { user: Customer; order?: Order }
export type Pending = {
  id: string
  tool: string
  args: Record<string, unknown>
  item_details?: Record<string, Item>
  before: Snapshot
  after: Snapshot
}
export type AuditEvent =
  | { kind: 'decision'; created_at: string; data: ({ approved: true } & Pending) | { id: string; approved: false } }
  | { kind: 'tool' | 'error'; created_at: string; data: unknown }
export type Session = {
  id: string
  title: string
  messages: Message[]
  transferred: boolean
  context: { user: Customer | null; orders: Order[]; pending: Pending | null }
  events: AuditEvent[]
}
export type SessionRef = { id: string; token: string; title: string }
export type Sample = { name: string; email: string; order_id: string; status: string; items: number }
export type Health = { mode: 'demo' | 'live'; model_ready: boolean }
export type Service = 'query' | 'return' | 'cancel'
