<script setup lang="ts">
import { computed, ref } from 'vue'
import { ArrowRight, ChevronDown, Package, PackageSearch, RefreshCw, Search, ShoppingBag } from 'lucide-vue-next'
import { money, orderTotal, statusLabel, statusValues } from '../retail'
import { t } from '../i18n'
import type { ChatTarget, Customer, Order } from '../types'
import OrderDialog from './OrderDialog.vue'

const props = defineProps<{ customer: Customer; orders: Order[]; loading: boolean; error: string; assistantBusy: boolean }>()
const emit = defineEmits<{ refresh: []; openChat: [target: ChatTarget]; authExpired: []; busy: [value: boolean] }>()
const search = ref('')
const status = ref('')
const selected = ref<Order>()
const visibleOrders = computed(() => {
  const term = search.value.trim().toLowerCase()
  return props.orders.filter(order => (!status.value || order.status === status.value) &&
    (!term || [order.order_id, ...order.items.map(item => item.name)].some(value => value.toLowerCase().includes(term))))
})

function consult(order: Order) {
  emit('openChat', { draft: t('请查询订单 ' + order.order_id + ' 的状态和商品明细。', 'Please check the status and items for order ' + order.order_id + '.') })
}
</script>

<template>
  <main class="frame portal-page">
    <header class="page-intro">
      <div><h1>{{ t('我的订单', 'My orders') }}</h1><p>{{ t('查看当前账户的所有订单、物流及售后信息。', 'View every order, delivery, and after-sales record for this account.') }}</p></div>
      <button class="button secondary" :disabled="loading" @click="emit('refresh')">
        <RefreshCw :size="16" :class="{ spin: loading }" />{{ t('刷新订单', 'Refresh orders') }}
      </button>
    </header>

    <section class="surface orders-toolbar" :aria-label="t('筛选订单', 'Filter orders')">
      <label class="orders-search">
        <Search :size="18" /><input v-model="search" type="search" :aria-label="t('搜索订单', 'Search orders')" :placeholder="t('搜索订单号或商品名称', 'Search by order number or item')" />
      </label>
      <label class="orders-filter">
        <select v-model="status" :aria-label="t('筛选订单状态', 'Filter order status')">
          <option value="">{{ t('全部状态', 'All statuses') }}</option>
          <option v-for="value in statusValues" :key="value" :value="value">{{ statusLabel(value) }}</option>
        </select><ChevronDown :size="15" />
      </label>
      <p v-if="!loading" class="orders-count">{{ search.trim() || status ? t('找到 ', 'Found ') : t('共 ', 'Total ') }}{{ visibleOrders.length }}{{ t(' 笔订单', ' orders') }}</p>
    </section>
    <p v-if="error" class="notice list-notice" role="alert">{{ error }}</p>
    <p v-if="loading && !orders.length" class="loading-list" role="status">{{ t('正在载入订单…', 'Loading orders…') }}</p>
    <section v-else-if="!visibleOrders.length && !error" class="surface orders-empty-card">
      <PackageSearch :size="28" />
      <h2>{{ search.trim() || status ? t('没有匹配的订单', 'No matching orders') : t('当前账户暂无订单', 'No orders on this account') }}</h2>
      <button v-if="search.trim() || status" class="text-button" @click="search = ''; status = ''">{{ t('清除筛选', 'Clear filters') }}</button>
    </section>
    <div v-else class="order-cards">
      <article v-for="order in visibleOrders" :key="order.order_id" class="surface listed-order">
        <header><Package :size="18" /><strong>{{ order.order_id }}</strong>
          <span :class="['status-tag', order.status.replaceAll(' ', '-')]">{{ statusLabel(order.status) }}</span></header>
        <div v-for="(item, index) in order.items" :key="index" class="order-item listed-item">
          <span class="product-icon"><ShoppingBag :size="17" /></span>
          <div><strong>{{ item.name }}</strong><small>{{ Object.values(item.options).join(' / ') }}</small></div>
          <b>{{ money(item.price) }}</b>
        </div>
        <footer>
          <div><span>{{ order.items.length }} {{ t('件商品', 'items') }}</span><b>{{ money(orderTotal(order)) }}</b></div>
          <button class="text-button" :disabled="assistantBusy" @click="consult(order)">{{ t('咨询此订单', 'Ask about this order') }}</button>
          <button class="button secondary" @click="selected = order">{{ t('订单详情', 'Order details') }}<ArrowRight :size="15" /></button>
        </footer>
      </article>
    </div>
    <OrderDialog v-if="selected" :key="selected.order_id" :order="selected" :customer="customer" :assistant-busy="assistantBusy"
      @close="selected = undefined" @open-chat="emit('openChat', $event)" @auth-expired="emit('authExpired')" @busy="emit('busy', $event)" />
  </main>
</template>
