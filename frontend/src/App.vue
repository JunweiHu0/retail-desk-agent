<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { Headset, LoaderCircle, LogOut, Package, ShoppingBag, UserRound } from 'lucide-vue-next'
import { api, authExpired, errorText } from './api'
import AgentDesk from './AgentDesk.vue'
import LoginView from './components/LoginView.vue'
import OrdersView from './components/OrdersView.vue'
import ProfileView from './components/ProfileView.vue'
import { fullName } from './retail'
import type { ChatTarget, Customer, Order, PortalPage } from './types'

const pages = [
  { id: 'assistant', label: '客服助手', icon: Headset },
  { id: 'orders', label: '我的订单', icon: Package },
  { id: 'profile', label: '客户资料', icon: UserRound },
] as const

function pageFromUrl(): PortalPage {
  const hash = window.location.hash.slice(1)
  return pages.find(page => page.id === hash)?.id || 'assistant'
}

const page = ref<PortalPage>(pageFromUrl())
const account = ref<Customer | null>(null)
const accountId = computed(() => account.value?.user_id)
const loadingAccount = ref(true)
const signingOut = ref(false)
const sessionNote = ref('')
const portalError = ref('')
const orders = ref<Order[]>([])
const ordersLoading = ref(false)
const ordersError = ref('')
const assistantBusy = ref(false)
const orderActionBusy = ref(false)
const profileActionBusy = ref(false)
const chatKey = ref(0)
const chatTarget = ref<ChatTarget>()
let accountGeneration = 0

function onHashChange() {
  const next = pageFromUrl()
  if (page.value === next) return
  document.querySelectorAll<HTMLDialogElement>('dialog[open]').forEach(dialog => dialog.close())
  page.value = next
  portalError.value = ''
  window.scrollTo({ top: 0 })
}

function navigate(next: PortalPage) {
  if (page.value === next) return
  window.location.hash = next
  onHashChange()
}

function authenticated(customer: Customer) {
  accountGeneration += 1
  account.value = customer
  sessionNote.value = ''
}
function clearAccount() {
  accountGeneration += 1
  account.value = null
  orders.value = []
  ordersLoading.value = false
  ordersError.value = ''
  assistantBusy.value = false
  orderActionBusy.value = false
  profileActionBusy.value = false
  portalError.value = ''
  chatTarget.value = undefined
}
function expired() {
  if (!account.value) return
  clearAccount()
  sessionNote.value = '登录已过期，请重新登录。'
}

async function refreshOrders() {
  if (!account.value || ordersLoading.value) return
  const generation = accountGeneration
  ordersLoading.value = true
  ordersError.value = ''
  try {
    const { orders: latest } = await api.orders()
    if (generation === accountGeneration) orders.value = latest
  } catch (reason) {
    if (generation === accountGeneration) {
      if (authExpired(reason)) expired()
      else ordersError.value = errorText(reason, '暂时无法载入订单，请重试。')
    }
  } finally {
    if (generation === accountGeneration) ordersLoading.value = false
  }
}
async function refreshProfile() {
  const generation = accountGeneration
  try {
    const latest = await api.me()
    if (generation === accountGeneration) account.value = latest
  } catch (reason) {
    if (generation === accountGeneration) {
      if (authExpired(reason)) expired()
      else portalError.value = errorText(reason, '暂时无法更新账户资料，请刷新重试。')
    }
  }
}

watch([accountId, page], ([id, next], [previousId]) => {
  if (!id) return
  if (id !== previousId || next === 'orders') void refreshOrders()
  if (next === 'profile' && id === previousId) void refreshProfile()
})

onMounted(async () => {
  window.addEventListener('hashchange', onHashChange)
  try {
    authenticated(await api.me())
  } catch (reason) {
    if (!authExpired(reason)) sessionNote.value = errorText(reason, '暂时无法连接服务，请稍后重试。')
  } finally {
    loadingAccount.value = false
  }
})
onUnmounted(() => window.removeEventListener('hashchange', onHashChange))

async function signOut() {
  if (signingOut.value || assistantBusy.value || orderActionBusy.value || profileActionBusy.value) return
  signingOut.value = true
  portalError.value = ''
  try {
    await api.logout()
    clearAccount()
    sessionNote.value = ''
    navigate('assistant')
  } catch (reason) {
    portalError.value = errorText(reason, '暂时无法退出登录，请重试。')
  } finally {
    signingOut.value = false
  }
}

function openChat(target: ChatTarget) {
  chatTarget.value = target
  chatKey.value += 1
  navigate('assistant')
}
</script>

<template>
  <header class="masthead">
    <div :class="['frame masthead-inner portal-header', { signed: account }]">
      <a class="brand" :href="account ? '#assistant' : '.'" aria-label="Retail Desk 购物服务中心">
        <span class="brand-mark"><ShoppingBag :size="23" :stroke-width="2" /></span>
        <span class="wordmark">Retail<span>Desk</span></span>
      </a>
      <span v-if="!account" class="brand-section">服务中心</span>
      <template v-else>
        <nav class="portal-nav" aria-label="账户导航">
          <a v-for="tab in pages" :key="tab.id" :href="'#' + tab.id" :aria-current="page === tab.id ? 'page' : undefined">
            <component :is="tab.icon" :size="17" />{{ tab.label }}
          </a>
        </nav>
        <div class="portal-account">
          <span>{{ fullName(account) }}</span>
          <button class="button secondary" aria-label="退出登录" title="退出登录"
            :disabled="signingOut || assistantBusy || orderActionBusy || profileActionBusy" @click="signOut">
            <LoaderCircle v-if="signingOut" :size="16" class="spin" /><LogOut v-else :size="16" />退出登录
          </button>
        </div>
      </template>
    </div>
  </header>

  <main v-if="loadingAccount" class="frame loading-account" role="status"><LoaderCircle :size="18" class="spin" />正在查看登录状态</main>
  <LoginView v-else-if="!account" :notice="sessionNote" @authenticated="authenticated" />

  <template v-else>
    <p v-if="portalError" class="frame notice portal-notice" role="alert">{{ portalError }}</p>
    <AgentDesk v-show="page === 'assistant'" :key="account.user_id + ':' + chatKey" :user-id="account.user_id"
      :target="chatTarget" :orders="orders" :orders-loading="ordersLoading"
      @open-orders="navigate('orders')" @auth-expired="expired" @busy="assistantBusy = $event" @orders-changed="refreshOrders" />
    <OrdersView v-if="page === 'orders'" :orders="orders" :customer="account" :loading="ordersLoading" :error="ordersError"
      :assistant-busy="assistantBusy" @refresh="refreshOrders" @open-chat="openChat" @auth-expired="expired" @busy="orderActionBusy = $event" />
    <ProfileView v-if="page === 'profile'" :customer="account" :assistant-busy="assistantBusy"
      @open-chat="openChat" @auth-expired="expired" @busy="profileActionBusy = $event" />
  </template>
</template>
