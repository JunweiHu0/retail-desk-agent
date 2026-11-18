import type { Health, Sample, Session, SessionInput, SessionRef, StreamEvent } from './types'

async function request<T>(url: string, ref?: SessionRef, init: RequestInit = {}): Promise<T> {
  const response = await fetch(url, { ...init, headers: {
    'Content-Type': 'application/json', ...(ref ? { Authorization: `Bearer ${ref.token}` } : {}), ...init.headers,
  } })
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new Error(typeof data.detail === 'string' ? data.detail : `请求失败 (${response.status})`)
  }
  return response.json()
}

async function stream(ref: SessionRef, route: 'messages' | 'decisions', body: object, onEvent: (event: StreamEvent) => void) {
  const response = await fetch(`/api/sessions/${ref.id}/${route}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${ref.token}` },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new Error(typeof data.detail === 'string' ? data.detail : `请求失败 (${response.status})`)
  }
  if (!response.body) throw new Error('浏览器不支持流式响应')
  const reader = response.body.getReader(), decoder = new TextDecoder()
  let buffer = '', completed = false
  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const frames = buffer.split(/\r?\n\r?\n/)
    buffer = frames.pop() || ''
    for (const frame of frames) {
      const data = frame.split(/\r?\n/).filter(line => line.startsWith('data:')).map(line => line.slice(5).replace(/^ /, '')).join('\n')
      if (data) {
        const event = JSON.parse(data) as StreamEvent
        if (event.type === 'done' || event.type === 'error') completed = true
        onEvent(event)
      }
    }
    if (done) break
  }
  if (!completed) throw new Error('连接中断。请刷新会话检查处理结果。')
}

export const api = {
  health: () => request<Health>('/api/health'),
  samples: () => request<{ samples: Sample[] }>('/api/samples'),
  create: (input: SessionInput) => request<SessionRef>('/api/sessions', undefined, { method: 'POST', body: JSON.stringify(input) }),
  session: (ref: SessionRef) => request<Session>(`/api/sessions/${ref.id}`, ref),
  decide: (ref: SessionRef, action_id: string, approve: boolean, onEvent: (event: StreamEvent) => void) =>
    stream(ref, 'decisions', { action_id, approve }, onEvent),
  chat: (ref: SessionRef, message: string, onEvent: (event: StreamEvent) => void) =>
    stream(ref, 'messages', { message }, onEvent),
}
