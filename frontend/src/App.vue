<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { Headset, LoaderCircle, LogOut, Package, ShoppingBag, UserRound } from 'lucide-vue-next'
import { api, authExpired, errorText } from './api'
import AgentDesk from './AgentDesk.vue'
import LanguageSelect from './components/LanguageSelect.vue'
import LoginView from './components/LoginView.vue'
import OrdersView from './components/OrdersView.vue'
import ProfileView from './components/ProfileView.vue'
import { t } from './i18n'
import { fullName } from './retail'
import type { ChatTarget, Customer, Order, PortalPage } from './types'

const pageDefs = [
  { id: 'assistant', zh: '客服助手', en: 'Assistant', icon: Headset },
  { id: 'orders', zh: '我的订单', en: 'Orders', icon: Package },
  { id: 'profile', zh: '客户资料', en: 'Profile', icon: UserRound },
] as const
const pages = computed(() => pageDefs.map(page => ({ ...page, label: t(page.zh, page.en) })))

function pageFromUrl(): PortalPage {
  const hash = window.location.hash.slice(1)
  return pageDefs.find(page => page.id === hash)?.id || 'assistant'
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
  sessionNote.value = t('登录已过期，请重新登录。', 'Your session expired. Please sign in again.')
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
      else ordersError.value = errorText(reason, t('暂时无法载入订单，请重试。', 'Could not load orders. Please try again.'))
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
      else portalError.value = errorText(reason, t('暂时无法更新账户资料，请刷新重试。', 'Could not refresh your profile. Please try again.'))
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
    if (!authExpired(reason)) sessionNote.value = errorText(reason, t('暂时无法连接服务，请稍后重试。', 'Could not reach the service. Please try again later.'))
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
    portalError.value = errorText(reason, t('暂时无法退出登录，请重试。', 'Could not sign out. Please try again.'))
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
  <header v-if="account" class="masthead">
    <div class="frame masthead-inner portal-header signed">
      <a class="brand" href="#assistant" :aria-label="t('Retail Desk 购物服务中心', 'Retail Desk customer service')">
        <span class="brand-mark"><ShoppingBag :size="23" :stroke-width="2" /></span>
        <span class="wordmark">Retail<span>Desk</span></span>
      </a>
      <nav class="portal-nav" :aria-label="t('账户导航', 'Account navigation')">
        <a v-for="tab in pages" :key="tab.id" :href="'#' + tab.id" :aria-current="page === tab.id ? 'page' : undefined">
          <component :is="tab.icon" :size="17" />{{ tab.label }}
        </a>
      </nav>
      <div class="portal-account">
        <LanguageSelect />
        <span>{{ fullName(account) }}</span>
        <button class="button secondary" :aria-label="t('退出登录', 'Sign out')" :title="t('退出登录', 'Sign out')"
          :disabled="signingOut || assistantBusy || orderActionBusy || profileActionBusy" @click="signOut">
          <LoaderCircle v-if="signingOut" :size="16" class="spin" /><LogOut v-else :size="16" />{{ t('退出登录', 'Sign out') }}
        </button>
      </div>
    </div>
  </header>

  <main v-if="loadingAccount" class="loading-account" role="status"><LoaderCircle :size="18" class="spin" />{{ t('正在查看登录状态', 'Checking your session') }}</main>
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
