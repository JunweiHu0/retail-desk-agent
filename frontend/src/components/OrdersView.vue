<script setup lang="ts">
import { computed, ref } from 'vue'
import { ArrowRight, ChevronDown, Package, PackageSearch, RefreshCw, Search, ShoppingBag } from 'lucide-vue-next'
import { money, orderTotal, statuses, statusLabel } from '../retail'
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
  emit('openChat', { draft: '请查询订单 ' + order.order_id + ' 的状态和商品明细。' })
}
</script>

<template>
  <main class="frame portal-page">
    <header class="page-intro">
      <div><h1>我的订单</h1><p>查看当前账户的所有订单、物流及售后信息。</p></div>
      <button class="button secondary" :disabled="loading" @click="emit('refresh')">
        <RefreshCw :size="16" :class="{ spin: loading }" />刷新订单
      </button>
    </header>

    <section class="surface orders-toolbar" aria-label="筛选订单">
      <label class="orders-search">
        <Search :size="18" /><input v-model="search" type="search" aria-label="搜索订单" placeholder="搜索订单号或商品名称" />
      </label>
      <label class="orders-filter">
        <select v-model="status" aria-label="筛选订单状态">
          <option value="">全部状态</option>
          <option v-for="(label, value) in statuses" :key="value" :value="value">{{ label }}</option>
        </select><ChevronDown :size="15" />
      </label>
      <p v-if="!loading" class="orders-count">{{ search.trim() || status ? '找到 ' : '共 ' }}{{ visibleOrders.length }} 笔订单</p>
    </section>
    <p v-if="error" class="notice list-notice" role="alert">{{ error }}</p>
    <p v-if="loading && !orders.length" class="loading-list" role="status">正在载入订单…</p>
    <section v-else-if="!visibleOrders.length && !error" class="surface orders-empty-card">
      <PackageSearch :size="28" />
      <h2>{{ search.trim() || status ? '没有匹配的订单' : '当前账户暂无订单' }}</h2>
      <button v-if="search.trim() || status" class="text-button" @click="search = ''; status = ''">清除筛选</button>
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
          <div><span>{{ order.items.length }} 件商品</span><b>{{ money(orderTotal(order)) }}</b></div>
          <button class="text-button" :disabled="assistantBusy" @click="consult(order)">咨询此订单</button>
          <button class="button secondary" @click="selected = order">订单详情<ArrowRight :size="15" /></button>
        </footer>
      </article>
    </div>
    <OrderDialog v-if="selected" :key="selected.order_id" :order="selected" :customer="customer" :assistant-busy="assistantBusy"
      @close="selected = undefined" @open-chat="emit('openChat', $event)" @auth-expired="emit('authExpired')" @busy="emit('busy', $event)" />
  </main>
</template>
