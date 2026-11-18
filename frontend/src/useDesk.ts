import { computed, onMounted, onUnmounted, ref, watchEffect } from 'vue'
import { api, authExpired, errorText, RequestError } from './api'
import { progressLabel } from './retail'
import type { ChatTarget, Message, Session, SessionRef } from './types'

function stored(key: string) {
  try { return localStorage.getItem(key) } catch { return null }
}
function persist(key: string, value: string) {
  try { localStorage.setItem(key, value) } catch { /* The current tab can still serve the customer. */ }
}
function missingSession(error: unknown) {
  return error instanceof RequestError && (error.status === 403 || error.status === 404)
}

export function useDesk(userId: string, target: ChatTarget | undefined, onAuthExpired: () => void) {
  const activeKey = 'retail.active.v2:' + userId
  const history = ref<SessionRef[]>([])
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

  let mounted = true
  onUnmounted(() => { mounted = false })

  function needsLogin(reason: unknown) {
    if (!authExpired(reason)) return false
    if (mounted) onAuthExpired()
    return true
  }

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
      const title = state.title.replace(/^我的邮箱是\s*\S+?，/, '').trim().slice(0, 45)
      if (title) item.title = title
    }
  }
  function forget(item: SessionRef) {
    history.value = history.value.filter(entry => entry.id !== item.id)
    drafts.delete(item.id)
    if (active.value?.id === item.id) select(null, null)
  }

  async function checkHealth() {
    try {
      const status = await api.health()
      availability.value = status.model_ready ? 'ready' : 'unavailable'
    } catch { availability.value = 'unavailable' }
  }

  onMounted(async () => {
    void checkHealth()
    if (target?.draft !== undefined) {
      select(null, null)
      draft.value = target.draft
    }
    try {
      try {
        const { sessions } = await api.sessions()
        if (!mounted) return
        history.value = sessions
      } catch (e) {
        if (!target?.id || authExpired(e)) throw e
      }
      if (!mounted || target?.draft !== undefined) return
      const saved = stored(activeKey)
      const intended = target?.id && (history.value.find(item => item.id === target.id) ||
        { id: target.id, title: '待确认操作' })
      let current = intended || (saved === '' ? undefined : history.value.find(item => item.id === saved) || history.value[0])
      while (current) {
        try {
          const state = await api.session(current.id)
          if (!mounted) return
          select(current, state)
          applyState(state)
          break
        } catch (e) {
          if (needsLogin(e) || !mounted) return
          if (!missingSession(e)) {
            select(current, null)
            mustRefresh.value = true
            error.value = errorText(e, '咨询记录暂时无法载入，请刷新重试。')
            break
          }
          forget(current)
          if (intended) {
            error.value = '这段咨询已无法打开，请从咨询记录中选择。'
            break
          }
          current = history.value[0]
        }
      }
    } catch (e) {
      if (!needsLogin(e) && mounted) error.value = errorText(e, '咨询记录暂时无法载入。')
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
      const state = await api.session(item.id)
      if (!mounted) return
      if (active.value?.id !== item.id) select(item, state)
      applyState(state)
    } catch (e) {
      if (needsLogin(e) || !mounted) return
      if (missingSession(e)) forget(item)
      error.value = errorText(e, '咨询记录未能载入，请刷新重试。')
    } finally { phase.value = null }
  }

  async function refresh() {
    if (phase.value) return
    error.value = ''
    const status = checkHealth()
    if (active.value) await open(active.value)
    else {
      try { history.value = (await api.sessions()).sessions }
      catch (e) { if (!needsLogin(e)) error.value = errorText(e, '咨询记录暂时无法载入。') }
    }
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
        if (!mounted) return
        history.value.unshift(item)
        active.value = item
        persist(activeKey, item.id)
      }
      const result = await api.chat(item.id, message, name => { progress.value = progressLabel(name) })
      if (mounted) applyState(result.session)
    } catch (e) {
      if (needsLogin(e) || !mounted) return
      let received = false
      if (item) {
        try {
          const state = await api.session(item.id)
          if (!mounted) return
          applyState(state)
          received = state.messages.slice(previousLength).some(m => m.role === 'user' && m.content === message)
        } catch (syncError) {
          if (needsLogin(syncError) || !mounted) return
          if (missingSession(syncError)) forget(item)
          else mustRefresh.value = true
        }
      }
      if (!received) {
        draft.value = message
        error.value = errorText(e, mustRefresh.value ? '连接中断，请刷新咨询以核对发送结果。' : '消息未能发送，内容已保留，请重试。')
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
      const result = await api.decide(item.id, action.id, approve)
      if (mounted) applyState(result.session)
    } catch (e) {
      if (needsLogin(e) || !mounted) return
      // A dropped response can follow a successful write. Only the server can settle its outcome.
      try {
        const state = await api.session(item.id)
        if (!mounted) return
        applyState(state)
        if (state.context.pending?.id !== action.id) return
        if (e instanceof RequestError && e.message.includes('确认已失效')) staleAction.value = action.id
        else error.value = errorText(e, '操作仍待确认，请重新核对后重试。')
      } catch (syncError) {
        if (needsLogin(syncError) || !mounted) return
        if (missingSession(syncError)) forget(item)
        else mustRefresh.value = true
        error.value = errorText(syncError, '暂时无法核对办理结果，请刷新咨询。')
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
        const next = await api.session(item.id)
        if (current) { polls++; applyState(next) }
      } catch (e) {
        if (current) {
          if (needsLogin(e)) return
          if (missingSession(e)) forget(item)
          else mustRefresh.value = true
          error.value = errorText(e, '进度暂时无法同步，请刷新咨询。')
        }
      }
    }, Math.min(1800 * (polls + 1), 10000))
    onCleanup(() => { current = false; window.clearTimeout(timer) })
  })

  return { history, active, session, draft, phase, error, pending, transferred, locked, availability,
    messages, progress, waitingForReply, mustRefresh, staleAction, newChat, open, refresh, send, decide }
}
