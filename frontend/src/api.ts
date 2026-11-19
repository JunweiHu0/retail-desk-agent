import type { Address, Customer, Health, Order, Session, SessionRef } from './types'

const endpoint = (path: string) => import.meta.env.BASE_URL.replace(/\/$/, '') + path
const sessionPath = (id: string) => '/api/sessions/' + encodeURIComponent(id)

export class RequestError extends Error {
  constructor(readonly status: number, message: string) {
    super(message)
  }
}

export const authExpired = (error: unknown) => error instanceof RequestError && error.status === 401
export const errorText = (error: unknown, fallback: string) => error instanceof RequestError ? error.message : fallback

async function checkResponse(response: Response) {
  if (response.ok) return
  const body = await response.json().catch(() => ({}))
  const messages: Record<number, string> = {
    401: '请先登录。',
    403: '当前账户无法执行这项操作。',
    404: '未找到相关记录。',
    409: '当前状态已更新，请重新核对。',
    422: '请检查填写的信息后重试。',
    429: '操作过于频繁，请稍后重试。',
    503: '客服暂时无法接待，请稍后重试。',
  }
  const detail = response.status < 500 && typeof body?.detail === 'string' ? body.detail : undefined
  throw new RequestError(response.status, detail || messages[response.status] || '服务暂时不可用，请稍后重试。')
}

async function request<T>(path: string, body?: unknown, method = 'GET'): Promise<T> {
  const response = await fetch(endpoint(path), {
    method,
    credentials: 'same-origin',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  await checkResponse(response)
  return response.json()
}

type ChatEvent =
  | { type: 'status' }
  | { type: 'tool_start'; name: string }
  | { type: 'tool_end' }
  | { type: 'done' | 'error'; session: Session }

async function chat(id: string, message: string, onProgress: (tool?: string) => void) {
  const response = await fetch(endpoint(sessionPath(id) + '/messages'), {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  })
  await checkResponse(response)
  if (!response.body) throw new Error('Missing response stream')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value, { stream: !done })
      const frames = buffer.split(/\r?\n\r?\n/)
      buffer = done ? '' : frames.pop()!
      for (const frame of frames) {
        const data = frame.split(/\r?\n/).filter(line => line.startsWith('data:'))
          .map(line => line.slice(5).replace(/^ /, '')).join('\n')
        if (!data) continue
        const event: ChatEvent = JSON.parse(data)
        if (event.type === 'tool_start') onProgress(event.name)
        if (event.type === 'status') onProgress()
        if (event.type === 'done' || event.type === 'error') {
          if (event.session?.id !== id) throw new Error('Missing session snapshot')
          return event
        }
      }
      if (done) throw new Error('Incomplete response stream')
    }
  } finally {
    reader.releaseLock()
  }
}

export const api = {
  me: () => request<Customer>('/api/me'),
  login: (email: string, password: string) => request<Customer>('/api/auth/login', { email, password }, 'POST'),
  register: (form: { email: string; password: string; first_name: string; last_name: string }) =>
    request<{ message: string }>('/api/auth/register', form, 'POST'),
  logout: () => request<{ message: string }>('/api/auth/logout', undefined, 'POST'),
  orders: () => request<{ orders: Order[] }>('/api/orders'),
  stageOrder: (id: string, tool: string, args: Record<string, unknown>) =>
    request<Session>('/api/orders/' + encodeURIComponent(id) + '/actions', { tool, args }, 'POST'),
  stageAddress: (address: Address) => request<Session>('/api/me/address', address, 'POST'),
  health: () => request<Health>('/api/health'),
  sessions: () => request<{ sessions: SessionRef[] }>('/api/sessions'),
  create: () => request<SessionRef>('/api/sessions', undefined, 'POST'),
  session: (id: string) => request<Session>(sessionPath(id)),
  decide: (id: string, actionId: string, approve: boolean) =>
    request<{ session: Session }>(sessionPath(id) + '/decisions', { action_id: actionId, approve }, 'POST'),
  chat,
}
