<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import {
  ArrowDownRight, ArrowRight, ArrowUpRight, BookOpen, Check, ChevronDown, Clock3, Headset, History, LoaderCircle,
  MessageCircle, Package, PackageCheck, Plus, RefreshCw, RotateCcw, Send, ShieldCheck, SquareX, UserRound, X,
} from 'lucide-vue-next'
import ChangeCard from './components/ChangeCard.vue'
import ServiceDialog from './components/ServiceDialog.vue'
import { messageText, receiptsByMessage, services } from './retail'
import { useDesk } from './useDesk'
import type { ChatTarget, Order, Service, SessionRef } from './types'

const props = defineProps<{ userId: string; target?: ChatTarget; orders: Order[]; ordersLoading: boolean }>()
const emit = defineEmits<{ authExpired: []; busy: [busy: boolean]; openOrders: []; ordersChanged: [] }>()
const {
  history, active, session, draft, phase, error, pending, transferred, locked, availability,
  messages, progress, waitingForReply, mustRefresh, staleAction, newChat, open, refresh, send, decide,
} = useDesk(props.userId, props.target, () => emit('authExpired'))

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
  if (mustRefresh.value) return '待同步'
  if (pending.value) return staleAction.value === pending.value.id ? '需重新申请' : '待你确认'
  if (transferred.value) return '已记录转接'
  if (availability.value === 'unavailable') return '暂时离线'
  if (availability.value === 'checking' || phase.value === 'load') return '连接中'
  if (phase.value || waitingForReply.value) return '处理中'
  return '在线'
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
        <h1 id="welcome-title">你好，<span>需要什么帮助？</span></h1>
        <p>查询订单进度，或告诉客服你想办理的售后。</p>
        <button class="hero-link" :disabled="locked" @click="composer?.focus()">开始咨询<ArrowDownRight :size="16" /></button>
      </div>
    </section>
    <div class="desk">
      <section class="surface conversation" aria-labelledby="chat-title">
        <header class="chat-heading">
          <span class="assistant-mark"><Headset :size="22" /></span>
          <component :is="home ? 'h2' : 'h1'" id="chat-title">在线客服</component>
          <span :class="['availability', { idle: status !== '在线' }]"><i></i>{{ status }}</span>
          <div class="chat-actions">
            <button class="button history-button chat-history" aria-label="咨询记录" title="咨询记录" @click="historyDialog?.showModal()">
              <History :size="17" /><span>咨询记录</span>
            </button>
            <button class="button new-button chat-new" aria-label="新咨询" title="新咨询" :disabled="!!phase" @click="startNew"><Plus :size="17" /><span>新咨询</span></button>
            <button v-if="!home" class="icon-button" aria-label="刷新咨询" title="刷新咨询" :disabled="!!phase" @click="refresh"><RefreshCw :size="16" /></button>
          </div>
        </header>

        <div v-if="home" class="start-area">
          <h3>快捷服务</h3>
          <div class="service-grid">
            <button v-for="key in serviceKeys" :key="key" :class="['service-tile', 'tile-' + key]"
              :disabled="locked || ordersLoading" @click="chosen = key">
              <span class="tile-top"><component :is="serviceIcons[key]" :size="26" :stroke-width="1.7" /><ArrowUpRight class="tile-arrow" :size="16" /></span>
              <strong>{{ services[key].title }}</strong><small>{{ services[key].detail }}</small>
            </button>
          </div>
        </div>
        <div v-else ref="transcript" class="transcript" role="log" aria-label="咨询对话" aria-live="polite">
          <template v-for="message in messages" :key="message.id">
            <div v-if="receipts.has(message.id)" class="receipt-wrap">
              <ChangeCard :change="receipts.get(message.id)!.change" :receipt-time="receipts.get(message.id)!.time" />
            </div>
            <article v-else :class="['message', message.role]" :aria-label="message.role === 'user' ? '你' : '客服助手'">
              <span v-if="message.role === 'assistant'" class="message-avatar"><Headset :size="16" /></span>
              <p class="bubble">{{ messageText(message) }}</p>
            </article>
          </template>
          <div v-if="progress || waitingForReply" class="working" role="status"><LoaderCircle class="spin" :size="16" />{{ progress || '正在准备回复' }}</div>
          <div v-if="pending" ref="approval" class="approval-wrap"><ChangeCard :change="pending" :stale="staleAction === pending.id" /></div>
        </div>

        <div class="composer-area">
          <div v-if="error || (availability === 'unavailable' && !pending)" class="notice" role="alert">
            <span>{{ error || '客服暂时无法连接，请稍后重试。' }}</span>
            <button v-if="mustRefresh || availability === 'unavailable'" type="button" :disabled="!!phase" @click="refresh">{{ mustRefresh ? '同步咨询' : '重新连接' }}</button>
            <button v-else type="button" aria-label="关闭提示" @click="error = ''"><X :size="16" /></button>
          </div>
          <div v-if="pending" class="review-controls" role="group" aria-label="确认本次变更">
            <button class="text-button" @click="scrollChat"><ShieldCheck :size="16" />核对明细</button>
            <button class="button secondary" :disabled="!!phase || mustRefresh" @click="onDecision(false)">取消操作</button>
            <button class="button primary" :disabled="!!phase || mustRefresh || staleAction === pending.id" @click="onDecision(true)">
              <LoaderCircle v-if="phase === 'decide'" class="spin" :size="16" /><Check v-else :size="16" />确认执行
            </button>
          </div>
          <div v-else-if="transferred" class="locked-note"><Headset :size="17" /><span>本次咨询已记录转接</span><button @click="startNew">新咨询<ArrowRight :size="14" /></button></div>
          <form v-else class="composer" @submit.prevent="send()">
            <textarea ref="composer" v-model="draft" rows="2" aria-label="输入咨询内容" maxlength="8000" :disabled="locked"
              placeholder="输入你的问题，例如「帮我查一下订单进度」" @keydown="onEnter"></textarea>
            <div class="composer-tools"><span class="key-hint">Enter 发送 · Shift + Enter 换行</span>
              <button type="submit" class="send-button" aria-label="发送消息" :disabled="locked || !draft.trim()"><Send :size="15" />发送</button>
            </div>
          </form>
          <p v-if="home" class="privacy-note"><ShieldCheck :size="14" />涉及订单或款项的变更，都会先请你确认。</p>
        </div>
      </section>

      <aside class="assistant-side" aria-label="订单入口与服务指南">
        <section class="surface assistant-links">
          <a href="#orders"><Package :size="19" /><span><strong>我的订单</strong><small>查看商品、物流和售后</small></span><ArrowUpRight :size="16" /></a>
          <a href="#profile"><UserRound :size="19" /><span><strong>客户资料</strong><small>查看邮箱、地址和支付方式</small></span><ArrowUpRight :size="16" /></a>
        </section>
        <section class="surface guide" aria-labelledby="guide-title">
          <div class="panel-title"><BookOpen :size="18" /><h2 id="guide-title">服务指南</h2></div>
          <details><summary>怎么查某一笔订单？<ChevronDown :size="15" /></summary><p>在对话里提供订单号，或在「我的订单」中选择「咨询此订单」。</p></details>
          <details><summary>怎么退回部分商品？<ChevronDown :size="15" /></summary><p>在「我的订单」中展开已送达的订单，再选择要退回的商品。</p></details>
          <details><summary>变更什么时候生效？<ChevronDown :size="15" /></summary><p>核对变更前后的信息，点击「确认执行」后才会办理。你可以在咨询记录中查看办理回执。</p></details>
        </section>
      </aside>
    </div>

    <dialog ref="historyDialog" class="modal history-modal" aria-labelledby="history-title" @click="event => { if (event.target === historyDialog) historyDialog?.close() }">
      <div class="modal-inner">
        <div class="modal-heading"><h2 id="history-title">咨询记录</h2>
          <button class="icon-button" aria-label="关闭咨询记录" @click="historyDialog?.close()"><X :size="20" /></button>
        </div>
        <div v-if="!history.length" class="history-empty"><Clock3 :size="28" /><strong>还没有咨询记录</strong><p>发送第一条消息后，可以在这里继续之前的咨询。</p></div>
        <nav v-else class="history-list" aria-label="历史咨询">
          <button v-for="item in history" :key="item.id" :class="{ current: item.id === active?.id }" :aria-current="item.id === active?.id ? 'true' : undefined"
            :disabled="!!phase" @click="pickHistory(item)"><MessageCircle :size="17" /><span>{{ item.title }}</span><Check v-if="item.id === active?.id" :size="16" /><ArrowRight v-else :size="16" /></button>
        </nav>
      </div>
    </dialog>
    <ServiceDialog v-if="chosen" :service="chosen" :orders="orders" @close="chosen = null" @submit="send" @orders="emit('openOrders')" />
  </main>
</template>
