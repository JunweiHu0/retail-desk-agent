import type { Health, Sample, Session, SessionRef } from './types'

export class RequestError extends Error {
  constructor(readonly status: number, message: string) {
    super(message)
  }
}

async function checkResponse(response: Response) {
  if (response.ok) return
  const body = await response.json().catch(() => ({}))
  const messages: Record<number, string> = {
    403: '这段咨询已无法访问。',
    404: '这段咨询已失效。',
    409: '咨询状态已更新，请重新核对后继续。',
    422: '请检查输入的内容后重试。',
    503: '客服暂时无法接待，请稍后重试。',
  }
  // The decision endpoint explains stale approvals and simultaneous requests in customer terms.
  const detail = response.status === 409 && typeof body?.detail === 'string' ? body.detail : undefined
  throw new RequestError(response.status, detail || messages[response.status] || '服务暂时不可用，请稍后重试。')
}

async function request<T>(url: string, ref?: SessionRef, body?: unknown, method = 'GET'): Promise<T> {
  const headers = new Headers()
  if (ref) headers.set('Authorization', 'Bearer ' + ref.token)
  if (body !== undefined) headers.set('Content-Type', 'application/json')
  const response = await fetch(url, { method, headers, body: JSON.stringify(body) })
  await checkResponse(response)
  return response.json()
}

type ChatEvent =
  | { type: 'status' }
  | { type: 'tool_start'; name: string }
  | { type: 'tool_end' }
  | { type: 'done' | 'error'; session: Session }

async function chat(ref: SessionRef, message: string, onProgress: (tool?: string) => void) {
  const response = await fetch('/api/sessions/' + encodeURIComponent(ref.id) + '/messages', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + ref.token },
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
          if (event.session?.id !== ref.id) throw new Error('Missing session snapshot')
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
  health: () => request<Health>('/api/health'),
  samples: () => request<{ samples: Sample[] }>('/api/samples'),
  create: () => request<SessionRef>('/api/sessions', undefined, undefined, 'POST'),
  session: (ref: SessionRef) => request<Session>('/api/sessions/' + encodeURIComponent(ref.id), ref),
  decide: (ref: SessionRef, actionId: string, approve: boolean) =>
    request<{ session: Session }>('/api/sessions/' + encodeURIComponent(ref.id) + '/decisions', ref, { action_id: actionId, approve }, 'POST'),
  chat,
}
