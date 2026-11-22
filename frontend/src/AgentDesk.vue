<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import {
  ArrowDownRight, ArrowRight, ArrowUpRight, BookOpen, Check, ChevronDown, Clock3, Headset, History, LoaderCircle,
  MessageCircle, Package, PackageCheck, Plus, RefreshCw, RotateCcw, Send, ShieldCheck, SquareX, UserRound, X,
} from 'lucide-vue-next'
import ChangeCard from './components/ChangeCard.vue'
import ServiceDialog from './components/ServiceDialog.vue'
import { t } from './i18n'
import { renderMarkdown } from './markdown'
import { messageText, receiptsByMessage, serviceDetail, serviceTitle } from './retail'
import { useDesk } from './useDesk'
import type { ChatTarget, Message, Order, Service, SessionRef, ToolCall, ToolTurn } from './types'

const props = defineProps<{ userId: string; target?: ChatTarget; orders: Order[]; ordersLoading: boolean }>()
const emit = defineEmits<{ authExpired: []; busy: [busy: boolean]; openOrders: []; ordersChanged: [] }>()
const {
  history, active, session, draft, phase, error, pending, transferred, locked, availability,
  messages, progress, waitingForReply, mustRefresh, staleAction, newChat, open, refresh, send, decide,
} = useDesk(props.userId, props.target, () => emit('authExpired'))

// An evaluation replay link opens a finished session by id: /?session=<id>.
const replayTarget = new URLSearchParams(window.location.search).get('session')
let replayOpened = false
watch([history, phase], async ([items, current]) => {
  if (!replayTarget || replayOpened || current) return
  const item = items.find(entry => entry.id === replayTarget)
  if (!item) return
  replayOpened = true
  await open(item)
}, { immediate: true })

const toolEvents = computed(() =>
  (session.value?.events ?? [])
    .filter(event => event.kind === 'tool')
    .map(event => event.data as { name?: string; args?: unknown; ok?: boolean; duration_ms?: number })
    .filter(tool => typeof tool?.name === 'string'),
)

const toolTurns = computed(() => (session.value?.manifest?.tool_turns ?? []) as ToolTurn[])

function normalizedText(value: string) {
  return value.trim().replace(/\s+/g, ' ')
}

function messageTurn(message: Message): ToolTurn | undefined {
  if (message.role !== 'assistant') return undefined
  const key = normalizedText(message.content)
  return toolTurns.value.find(turn => normalizedText(turn.assistant) === key)
}

function messageTools(message: Message): ToolCall[] {
  return messageTurn(message)?.tools ?? []
}

function messageSummary(message: Message): string {
  const turn = messageTurn(message)
  if (!turn) return ''
  const count = turn.tools.length
  const noun = count === 1 ? 'tool' : 'tools'
  if (turn.seconds && turn.seconds >= 1) {
    return t(
      `思考 ${Math.round(turn.seconds)} 秒，调用 ${count} 个工具`,
      `Thought for ${Math.round(turn.seconds)}s, ran ${count} ${noun}`,
    )
  }
  return t(`调用 ${count} 个工具`, `Ran ${count} ${noun}`)
}

function toolArgs(value: unknown) {
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

watch(phase, phase => emit('busy', phase === 'send' || phase === 'decide'))
const chosen = ref<Service | null>(null)
const historyDialog = ref<HTMLDialogElement | null>(null)
const transcript = ref<HTMLElement | null>(null)
const approval = ref<HTMLElement | null>(null)
const composer = ref<HTMLTextAreaElement | null>(null)
const home = computed(() => !messages.value.length && !pending.value && !transferred.value)
const receipts = computed(() => receiptsByMessage(session.value))
const serviceIcons = { query: PackageCheck, return: RotateCcw, cancel: SquareX }
const serviceKeys: Service[] = ['query', 'return', 'cancel']
const status = computed(() => {
  if (mustRefresh.value) return t('待同步', 'Needs refresh')
  if (pending.value) return staleAction.value === pending.value.id ? t('需重新申请', 'Resubmit') : t('待你确认', 'Awaiting approval')
  if (transferred.value) return t('已记录转接', 'Transferred')
  if (availability.value === 'unavailable') return t('暂时离线', 'Offline')
  if (availability.value === 'checking' || phase.value === 'load') return t('连接中', 'Connecting')
  if (phase.value || waitingForReply.value) return t('处理中', 'Working')
  return t('在线', 'Online')
})

function scrollChat() {
  const area = transcript.value
  if (!area) return
  if (pending.value && approval.value) {
    area.scrollTop += approval.value.getBoundingClientRect().top - area.getBoundingClientRect().top - 16
  } else area.scrollTop = area.scrollHeight
}
watch([messages, pending, active], async () => { await nextTick(); scrollChat() }, { flush: 'post' })

function onEnter(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.isComposing || event.keyCode === 229 ||
      event.shiftKey || event.altKey || event.ctrlKey || event.metaKey) return
  event.preventDefault()
  void send()
}
function pickHistory(item: SessionRef) {
  historyDialog.value?.close()
  void open(item)
}
function startNew() {
  historyDialog.value?.close()
  newChat()
  window.scrollTo({ top: 0 })
}
async function onDecision(approve: boolean) {
  const id = session.value?.id
  await decide(approve)
  if (approve && id && session.value?.id === id && !pending.value) emit('ordersChanged')
}
</script>

<template>
  <main :class="['frame', 'main-content', { 'in-chat': !home }]">
    <section v-if="home" class="hero" aria-labelledby="welcome-title">
      <div class="hero-content">
        <h1 id="welcome-title">{{ t('你好，', 'Hello,') }}<span>{{ t('需要什么帮助？', 'how can we help?') }}</span></h1>
        <p>{{ t('查询订单进度，或告诉客服你想办理的售后。', 'Check an order or tell us what after-sales help you need.') }}</p>
        <button class="hero-link" :disabled="locked" @click="composer?.focus()">{{ t('开始咨询', 'Start a conversation') }}<ArrowDownRight :size="16" /></button>
      </div>
    </section>
    <div class="desk">
      <section class="surface conversation" aria-labelledby="chat-title">
        <header class="chat-heading">
          <span class="assistant-mark"><Headset :size="22" /></span>
          <component :is="home ? 'h2' : 'h1'" id="chat-title">{{ t('在线客服', 'Support') }}</component>
          <span :class="['availability', { idle: status !== t('在线', 'Online') }]"><i></i>{{ status }}</span>
          <div class="chat-actions">
            <button class="button history-button chat-history" :aria-label="t('咨询记录', 'Conversations')" :title="t('咨询记录', 'Conversations')" @click="historyDialog?.showModal()">
              <History :size="17" /><span>{{ t('咨询记录', 'Conversations') }}</span>
            </button>
            <button class="button new-button chat-new" :aria-label="t('新咨询', 'New chat')" :title="t('新咨询', 'New chat')" :disabled="!!phase" @click="startNew"><Plus :size="17" /><span>{{ t('新咨询', 'New chat') }}</span></button>
            <button v-if="!home" class="icon-button" :aria-label="t('刷新咨询', 'Refresh conversation')" :title="t('刷新咨询', 'Refresh conversation')" :disabled="!!phase" @click="refresh"><RefreshCw :size="16" /></button>
          </div>
        </header>

        <div v-if="home" class="start-area">
          <h3>{{ t('快捷服务', 'Quick services') }}</h3>
          <div class="service-grid">
            <button v-for="key in serviceKeys" :key="key" :class="['service-tile', 'tile-' + key]"
              :disabled="locked || ordersLoading" @click="chosen = key">
              <span class="tile-top"><component :is="serviceIcons[key]" :size="26" :stroke-width="1.7" /><ArrowUpRight class="tile-arrow" :size="16" /></span>
              <strong>{{ serviceTitle(key) }}</strong><small>{{ serviceDetail(key) }}</small>
            </button>
          </div>
        </div>
        <div v-else ref="transcript" class="transcript" role="log" :aria-label="t('咨询对话', 'Conversation')" aria-live="polite">
          <template v-for="message in messages" :key="message.id">
            <div v-if="receipts.has(message.id)" class="receipt-wrap">
              <ChangeCard :change="receipts.get(message.id)!.change" :receipt-time="receipts.get(message.id)!.time" />
            </div>
            <article v-else :class="['message', message.role]" :aria-label="message.role === 'user' ? t('你', 'You') : t('客服助手', 'Support agent')">
              <span v-if="message.role === 'assistant'" class="message-avatar"><Headset :size="16" /></span>
              <p v-if="message.role === 'user'" class="bubble">{{ messageText(message) }}</p>
              <div v-else class="message-body">
                <details v-if="messageTools(message).length" class="tool-drawer">
                  <summary>{{ messageSummary(message) }}</summary>
                  <ol class="tool-chain">
                    <li v-for="(tool, toolIndex) in messageTools(message)" :key="toolIndex">
                      <span class="tool-step">{{ toolIndex + 1 }}</span>
                      <div class="tool-line">
                        <span class="tool-name">{{ tool.name }}</span>
                        <span :class="['tool-status', { failed: tool.ok === false }]">{{ tool.ok === false ? t('失败', 'failed') : 'ok' }}</span>
                        <span v-if="tool.duration_ms" class="tool-ms">{{ tool.duration_ms }} ms</span>
                      </div>
                      <code class="tool-args">{{ toolArgs(tool.args) }}</code>
                      <div v-if="tool.result" class="tool-result">{{ tool.result }}</div>
                    </li>
                  </ol>
                </details>
                <div class="bubble markdown" v-html="renderMarkdown(messageText(message))"></div>
              </div>
            </article>
          </template>
          <div v-if="progress || waitingForReply" class="working" role="status"><LoaderCircle class="spin" :size="16" />{{ progress || t('正在准备回复', 'Preparing a reply') }}</div>
          <div v-if="pending" ref="approval" class="approval-wrap"><ChangeCard :change="pending" :stale="staleAction === pending.id" /></div>
          <details v-if="!toolTurns.length && toolEvents.length" class="tool-trace">
            <summary>{{ t('工具调用', 'Tool calls') }} · {{ toolEvents.length }}</summary>
            <ol>
              <li v-for="(tool, index) in toolEvents" :key="index">
                <span class="tool-name">{{ tool.name }}</span>
                <span :class="['tool-status', { failed: tool.ok === false }]">{{ tool.ok === false ? t('失败', 'failed') : 'ok' }}</span>
                <span v-if="tool.duration_ms" class="tool-ms">{{ tool.duration_ms }} ms</span>
                <code>{{ toolArgs(tool.args) }}</code>
              </li>
            </ol>
          </details>
        </div>

        <div class="composer-area">
          <div v-if="error || (availability === 'unavailable' && !pending)" class="notice" role="alert">
            <span>{{ error || t('客服暂时无法连接，请稍后重试。', 'Support is temporarily unavailable. Please try again later.') }}</span>
            <button v-if="mustRefresh || availability === 'unavailable'" type="button" :disabled="!!phase" @click="refresh">{{ mustRefresh ? t('同步咨询', 'Sync conversation') : t('重新连接', 'Reconnect') }}</button>
            <button v-else type="button" :aria-label="t('关闭提示', 'Dismiss')" @click="error = ''"><X :size="16" /></button>
          </div>
          <div v-if="pending" class="review-controls" role="group" :aria-label="t('确认本次变更', 'Confirm this change')">
            <button class="text-button" @click="scrollChat"><ShieldCheck :size="16" />{{ t('核对明细', 'Review details') }}</button>
            <button class="button secondary" :disabled="!!phase || mustRefresh" @click="onDecision(false)">{{ t('取消操作', 'Cancel') }}</button>
            <button class="button primary" :disabled="!!phase || mustRefresh || staleAction === pending.id" @click="onDecision(true)">
              <LoaderCircle v-if="phase === 'decide'" class="spin" :size="16" /><Check v-else :size="16" />{{ t('确认执行', 'Confirm and execute') }}
            </button>
          </div>
          <div v-else-if="transferred" class="locked-note"><Headset :size="17" /><span>{{ t('本次咨询已记录转接', 'This conversation has been handed off') }}</span><button @click="startNew">{{ t('新咨询', 'New chat') }}<ArrowRight :size="14" /></button></div>
          <form v-else class="composer" @submit.prevent="send()">
            <textarea ref="composer" v-model="draft" rows="2" :aria-label="t('输入咨询内容', 'Message')" maxlength="8000" :disabled="locked"
              :placeholder="t('输入你的问题，例如「帮我查一下订单进度」', 'Type your question, e.g. “check my order status”')" @keydown="onEnter"></textarea>
            <div class="composer-tools"><span class="key-hint">{{ t('Enter 发送 · Shift + Enter 换行', 'Enter to send · Shift + Enter for a new line') }}</span>
              <button type="submit" class="send-button" :aria-label="t('发送消息', 'Send message')" :disabled="locked || !draft.trim()"><Send :size="15" />{{ t('发送', 'Send') }}</button>
            </div>
          </form>
          <p v-if="home" class="privacy-note"><ShieldCheck :size="14" />{{ t('涉及订单或款项的变更，都会先请你确认。', 'Changes involving orders or payments always require your approval.') }}</p>
        </div>
      </section>

      <aside class="assistant-side" :aria-label="t('订单入口与服务指南', 'Orders and service guide')">
        <section class="surface assistant-links">
          <a href="#orders"><Package :size="19" /><span><strong>{{ t('我的订单', 'My orders') }}</strong><small>{{ t('查看商品、物流和售后', 'Items, delivery, and after-sales') }}</small></span><ArrowUpRight :size="16" /></a>
          <a href="#profile"><UserRound :size="19" /><span><strong>{{ t('客户资料', 'Profile') }}</strong><small>{{ t('查看邮箱、地址和支付方式', 'Email, address, and payment methods') }}</small></span><ArrowUpRight :size="16" /></a>
        </section>
        <section class="surface guide" aria-labelledby="guide-title">
          <div class="panel-title"><BookOpen :size="18" /><h2 id="guide-title">{{ t('服务指南', 'Service guide') }}</h2></div>
          <details><summary>{{ t('怎么查某一笔订单？', 'How do I find an order?') }}<ChevronDown :size="15" /></summary><p>{{ t('在对话里提供订单号，或在「我的订单」中选择「咨询此订单」。', 'Share the order number here, or choose “Ask about this order” in My orders.') }}</p></details>
          <details><summary>{{ t('怎么退回部分商品？', 'How do I return part of an order?') }}<ChevronDown :size="15" /></summary><p>{{ t('在「我的订单」中展开已送达的订单，再选择要退回的商品。', 'Open a delivered order in My orders and select the items to return.') }}</p></details>
          <details><summary>{{ t('变更什么时候生效？', 'When does a change take effect?') }}<ChevronDown :size="15" /></summary><p>{{ t('核对变更前后的信息，点击「确认执行」后才会办理。你可以在咨询记录中查看办理回执。', 'Review the before/after details and choose Confirm and execute. Receipts appear in the conversation.') }}</p></details>
        </section>
      </aside>
    </div>

    <dialog ref="historyDialog" class="modal history-modal" aria-labelledby="history-title" @click="event => { if (event.target === historyDialog) historyDialog?.close() }">
      <div class="modal-inner">
        <div class="modal-heading"><h2 id="history-title">{{ t('咨询记录', 'Conversations') }}</h2>
          <button class="icon-button" :aria-label="t('关闭咨询记录', 'Close conversations')" @click="historyDialog?.close()"><X :size="20" /></button>
        </div>
        <div v-if="!history.length" class="history-empty"><Clock3 :size="28" /><strong>{{ t('还没有咨询记录', 'No conversations yet') }}</strong><p>{{ t('发送第一条消息后，可以在这里继续之前的咨询。', 'Send a message to start one; past conversations will appear here.') }}</p></div>
        <nav v-else class="history-list" :aria-label="t('历史咨询', 'Conversation history')">
          <button v-for="item in history" :key="item.id" :class="{ current: item.id === active?.id }" :aria-current="item.id === active?.id ? 'true' : undefined"
            :disabled="!!phase" @click="pickHistory(item)"><MessageCircle :size="17" /><span>{{ item.title }}</span><Check v-if="item.id === active?.id" :size="16" /><ArrowRight v-else :size="16" /></button>
        </nav>
      </div>
    </dialog>
    <ServiceDialog v-if="chosen" :service="chosen" :orders="orders" @close="chosen = null" @submit="send" @orders="emit('openOrders')" />
  </main>
</template>
