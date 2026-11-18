<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ArrowRight, ChevronDown, X } from 'lucide-vue-next'
import { api, authExpired, errorText } from '../api'
import { addressText, money, paymentAndServiceFields, paymentLabel, statusLabel } from '../retail'
import type { ChatTarget, Customer, Order } from '../types'
import AddressFields from './AddressFields.vue'

const props = defineProps<{ order: Order; customer: Customer; assistantBusy: boolean }>()
const emit = defineEmits<{ close: []; openChat: [target: ChatTarget]; authExpired: []; busy: [value: boolean] }>()
const dialog = ref<HTMLDialogElement | null>(null)
const busy = ref(false)
const error = ref('')
const address = ref({ ...props.order.address })
const reason = ref('')
const originalPayment = props.order.payment_history.find(transaction => transaction.transaction_type === 'payment')?.payment_method_id
const selectedPayment = ref('')
const refundPayment = ref(originalPayment || '')
const selectedItems = ref<number[]>([])
const paymentMethods = computed(() => Object.keys(props.customer.payment_methods).filter(id => id !== originalPayment))
const refundMethods = computed(() => Object.keys(props.customer.payment_methods)
  .filter(id => id === originalPayment || props.customer.payment_methods[id].source === 'gift_card'))
const tracking = computed(() => [...new Set(props.order.fulfillments.flatMap(value => value.tracking_id))])
const records = computed(() => paymentAndServiceFields(props.order, props.customer))

let mounted = true
onMounted(() => dialog.value?.showModal())
onUnmounted(() => { mounted = false; emit('busy', false) })

async function stage(tool: string, args: Record<string, unknown>) {
  if (busy.value || props.assistantBusy) return
  busy.value = true
  emit('busy', true)
  error.value = ''
  try {
    const state = await api.stageOrder(props.order.order_id, tool, args)
    if (mounted) {
      dialog.value?.close()
      emit('openChat', { id: state.id })
    }
  } catch (reason) {
    if (!mounted) return
    if (authExpired(reason)) emit('authExpired')
    else error.value = errorText(reason, '暂时无法准备变更，请重试。')
  } finally {
    busy.value = false
    if (mounted) emit('busy', false)
  }
}

function previewReturn() {
  if (!selectedItems.value.length || !refundMethods.value.includes(refundPayment.value)) return
  void stage('return_delivered_order_items', {
    item_ids: selectedItems.value.map(index => props.order.items[index].item_id),
    payment_method_id: refundPayment.value,
  })
}
</script>

<template>
  <dialog ref="dialog" class="modal order-detail-modal" aria-labelledby="order-detail-title"
    @close="emit('close')" @cancel="event => { if (busy) event.preventDefault() }"
    @click="event => { if (event.target === dialog && !busy) dialog?.close() }">
    <div class="modal-inner">
      <div class="modal-heading"><h2 id="order-detail-title">订单 {{ order.order_id }}</h2>
        <button class="icon-button" type="button" aria-label="关闭订单详情" :disabled="busy" @click="dialog?.close()"><X :size="20" /></button>
      </div>
      <p class="order-detail-status"><span :class="['status-tag', order.status.replaceAll(' ', '-')]">{{ statusLabel(order.status) }}</span></p>

      <section class="order-detail-block" aria-label="订单商品">
        <h3>订单商品</h3>
        <div v-for="(item, index) in order.items" :key="index" class="order-item">
          <div><strong>{{ item.name }}</strong><small>{{ Object.values(item.options).join(' / ') }} · 货号 {{ item.item_id }}</small></div>
          <b>{{ money(item.price) }}</b>
        </div>
      </section>
      <dl class="order-detail-block order-fields">
        <dt>收货地址</dt><dd>{{ addressText(order.address) || '暂无地址' }}</dd>
        <dt>物流单号</dt><dd v-if="!tracking.length">暂无物流信息</dd>
        <dd v-for="number in tracking" :key="number">{{ number }}</dd>
        <template v-for="record in records" :key="record.label"><dt>{{ record.label }}</dt><dd>{{ record.value }}</dd></template>
      </dl>

      <section v-if="order.status === 'pending' || order.status === 'delivered'" class="order-detail-block manage-order">
        <h3>办理售后</h3>
        <p v-if="error" class="notice" role="alert">{{ error }}</p>
        <p v-if="busy" class="action-progress" role="status">正在准备变更明细…</p>
        <template v-if="order.status === 'pending'">
          <details class="order-action">
            <summary>取消订单<ChevronDown :size="15" /></summary>
            <form @submit.prevent="stage('cancel_pending_order', { reason })">
              <label class="field">取消原因
                <select v-model="reason" required :disabled="busy">
                  <option disabled value="">请选择原因</option><option value="no longer needed">不再需要</option><option value="ordered by mistake">误下单</option>
                </select>
              </label>
              <button type="submit" class="button primary" :disabled="busy || assistantBusy">预览取消订单<ArrowRight :size="15" /></button>
            </form>
          </details>
          <details class="order-action">
            <summary>修改订单收货地址<ChevronDown :size="15" /></summary>
            <form @submit.prevent="stage('modify_pending_order_address', { ...address })">
              <fieldset :disabled="busy"><AddressFields v-model="address" /></fieldset>
              <button type="submit" class="button primary" :disabled="busy || assistantBusy">预览地址变更<ArrowRight :size="15" /></button>
            </form>
          </details>
          <details v-if="paymentMethods.length" class="order-action">
            <summary>修改支付方式<ChevronDown :size="15" /></summary>
            <form @submit.prevent="stage('modify_pending_order_payment', { payment_method_id: selectedPayment })">
              <label class="field">新的支付方式
                <select v-model="selectedPayment" required :disabled="busy">
                  <option disabled value="">选择支付方式</option>
                  <option v-for="id in paymentMethods" :key="id" :value="id">{{ paymentLabel(id, customer) }}</option>
                </select>
              </label>
              <button type="submit" class="button primary" :disabled="busy || assistantBusy">预览支付变更<ArrowRight :size="15" /></button>
            </form>
          </details>
        </template>
        <details v-else-if="refundMethods.length" class="order-action">
          <summary>申请退货<ChevronDown :size="15" /></summary>
          <form @submit.prevent="previewReturn">
            <fieldset :disabled="busy" class="return-items">
              <legend>选择要退回的商品</legend>
              <label v-for="(item, index) in order.items" :key="index">
                <input v-model="selectedItems" type="checkbox" :value="index" />{{ item.name }}
                <small v-if="Object.keys(item.options).length">{{ Object.values(item.options).join(' / ') }}</small>
              </label>
            </fieldset>
            <label class="field">退款方式
              <select v-model="refundPayment" required :disabled="busy">
                <option disabled value="">选择退款方式</option>
                <option v-for="id in refundMethods" :key="id" :value="id">{{ paymentLabel(id, customer) }}</option>
              </select>
            </label>
            <button type="submit" class="button primary" :disabled="busy || assistantBusy || !selectedItems.length || !refundPayment">预览退货申请<ArrowRight :size="15" /></button>
          </form>
        </details>
        <p v-else class="pane-empty">请通过客服咨询这笔订单的退款方式。</p>
      </section>
    </div>
  </dialog>
</template>
