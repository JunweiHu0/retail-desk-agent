import { computed, onMounted, ref, watchEffect } from 'vue'
import { api, RequestError } from './api'
import { progressLabel } from './retail'
import type { Health, Message, Session, SessionRef } from './types'

const historyKey = 'retail.sessions.v1'
const activeKey = 'retail.active.v1'

function stored(key: string) {
  try { return localStorage.getItem(key) } catch { return null }
}
function persist(key: string, value: string) {
  try { localStorage.setItem(key, value) } catch { /* The current tab can still serve the customer. */ }
}
function readHistory(): SessionRef[] {
  try {
    const value: unknown = JSON.parse(stored(historyKey) || '[]')
    if (!Array.isArray(value)) return []
    return value.filter(item => item && typeof item.id === 'string' && typeof item.token === 'string' && typeof item.title === 'string')
  } catch { return [] }
}
function expired(error: unknown) {
  return error instanceof RequestError && (error.status === 403 || error.status === 404)
}
function readable(error: unknown, fallback: string) {
  return error instanceof RequestError ? error.message : fallback
}

export function useDesk() {
  const history = ref(readHistory())
  const active = ref<SessionRef | null>(null)
  const session = ref<Session | null>(null)
  const draft = ref('')
  const drafts = new Map<string, string>()
  const phase = ref<'load' | 'send' | 'decide' | null>('load')
  const outgoing = ref<Message | null>(null)
  const progress = ref('')
  const error = ref('')
  const mustRefresh = ref(false)
  const staleAction = ref('')
  const health = ref<Health | null>(null)
  const availability = ref<'checking' | 'ready' | 'unavailable'>('checking')
  const pending = computed(() => session.value?.context.pending)
  const transferred = computed(() => Boolean(session.value?.transferred))
  const pausedReply = ref('')
  const lastMessage = computed(() => session.value?.messages.at(-1))
  const waitingForReply = computed(() => lastMessage.value?.role === 'user' && lastMessage.value.id !== pausedReply.value &&
    !pending.value && !transferred.value)
  const locked = computed(() => Boolean(phase.value || pending.value || transferred.value || waitingForReply.value ||
    mustRefresh.value || availability.value !== 'ready'))
  const messages = computed(() => outgoing.value ? [...(session.value?.messages || []), outgoing.value] : session.value?.messages || [])

  function remember() { persist(historyKey, JSON.stringify(history.value)) }
  function select(item: SessionRef | null, state: Session | null) {
    drafts.set(active.value?.id || '', draft.value)
    active.value = item
    session.value = state
    draft.value = drafts.get(item?.id || '') || ''
    persist(activeKey, item?.id || '')
    staleAction.value = ''
    mustRefresh.value = false
  }
  function applyState(state: Session) {
    session.value = state
    mustRefresh.value = false
    const item = history.value.find(entry => entry.id === state.id)
    if (item && state.messages.length) {
      const title = (state.messages[0].content || state.title).replace(/^我的邮箱是\s*\S+?，/, '').trim().slice(0, 45)
      if (title && title !== item.title) { item.title = title; remember() }
    }
  }
  function forget(item: SessionRef) {
    history.value = history.value.filter(entry => entry.id !== item.id)
    drafts.delete(item.id)
    remember()
    if (active.value?.id === item.id) select(null, null)
  }

  async function checkHealth() {
    try {
      health.value = await api.health()
      availability.value = health.value.model_ready ? 'ready' : 'unavailable'
    } catch { availability.value = 'unavailable' }
  }

  onMounted(async () => {
    void checkHealth()
    const saved = stored(activeKey)
    let current = saved === '' ? undefined : history.value.find(item => item.id === saved) || history.value[0]
    try {
      while (current) {
        try {
          const state = await api.session(current)
          select(current, state)
          applyState(state)
          break
        } catch (e) {
          if (!expired(e)) {
            select(current, null)
            mustRefresh.value = true
            error.value = readable(e, '咨询记录暂时无法载入，请刷新重试。')
            break
          }
          forget(current)
          current = history.value[0]
        }
      }
    } finally { phase.value = null }
  })

  function newChat() {
    if (phase.value) return
    error.value = ''
    select(null, null)
    draft.value = ''
    if (availability.value !== 'ready') void checkHealth()
  }

  async function open(item: SessionRef) {
    if (phase.value) return
    phase.value = 'load'
    error.value = ''
    try {
      const state = await api.session(item)
      if (active.value?.id !== item.id) select(item, state)
      applyState(state)
    } catch (e) {
      if (expired(e)) forget(item)
      error.value = readable(e, '咨询记录未能载入，请刷新重试。')
    } finally { phase.value = null }
  }

  async function refresh() {
    if (phase.value) return
    error.value = ''
    const status = checkHealth()
    if (active.value) await open(active.value)
    await status
  }

  async function send(text = draft.value) {
    const message = text.trim()
    if (!message || message.length > 8000 || locked.value) return
    const previousLength = session.value?.messages.length || 0
    let item = active.value
    phase.value = 'send'
    error.value = ''
    progress.value = progressLabel()
    outgoing.value = { id: 'outgoing', role: 'user', content: message }
    draft.value = ''
    try {
      if (!item) {
        item = await api.create()
        history.value.unshift(item)
        active.value = item
        persist(activeKey, item.id)
        remember()
      }
      const result = await api.chat(item, message, name => { progress.value = progressLabel(name) })
      applyState(result.session)
    } catch (e) {
      let received = false
      if (item) {
        try {
          const state = await api.session(item)
          applyState(state)
          received = state.messages.slice(previousLength).some(m => m.role === 'user' && m.content === message)
        } catch (syncError) {
          if (expired(syncError)) forget(item)
          else mustRefresh.value = true
        }
      }
      if (!received) {
        draft.value = message
        error.value = readable(e, mustRefresh.value ? '连接中断，请刷新咨询以核对发送结果。' : '消息未能发送，内容已保留，请重试。')
      }
    } finally {
      outgoing.value = null
      progress.value = ''
      phase.value = null
    }
  }

  async function decide(approve: boolean) {
    const item = active.value, action = pending.value
    if (!item || !action || phase.value || mustRefresh.value || (approve && staleAction.value === action.id)) return
    phase.value = 'decide'
    error.value = ''
    try {
      const result = await api.decide(item, action.id, approve)
      applyState(result.session)
    } catch (e) {
      // A dropped response can follow a successful write. Only the server can settle its outcome.
      try {
        const state = await api.session(item)
        applyState(state)
        if (state.context.pending?.id !== action.id) return
        if (e instanceof RequestError && e.message.includes('确认已失效')) staleAction.value = action.id
        else error.value = readable(e, '操作仍待确认，请重新核对后重试。')
      } catch (syncError) {
        if (expired(syncError)) forget(item)
        else mustRefresh.value = true
        error.value = readable(syncError, '暂时无法核对办理结果，请刷新咨询。')
      }
    } finally { phase.value = null }
  }

  // Reloading or losing an SSE connection need not lose the reply still being prepared.
  let polledMessage = '', polls = 0
  watchEffect(onCleanup => {
    const item = active.value, message = lastMessage.value
    if (!item || !message || !waitingForReply.value || phase.value || mustRefresh.value) return
    if (message.id !== polledMessage) { polledMessage = message.id; polls = 0 }
    if (polls >= 10) {
      pausedReply.value = message.id
      error.value = '暂未收到回复。你可以刷新咨询查看进度，或继续留言。'
      return
    }
    let current = true
    const timer = window.setTimeout(async () => {
      try {
        const next = await api.session(item)
        if (current) { polls++; applyState(next) }
      } catch (e) {
        if (current) {
          if (expired(e)) forget(item)
          else mustRefresh.value = true
          error.value = readable(e, '进度暂时无法同步，请刷新咨询。')
        }
      }
    }, Math.min(1800 * (polls + 1), 10000))
    onCleanup(() => { current = false; window.clearTimeout(timer) })
  })

  return { history, active, session, draft, phase, error, pending, transferred, locked, health, availability,
    messages, progress, waitingForReply, mustRefresh, staleAction, newChat, open, refresh, send, decide }
}
