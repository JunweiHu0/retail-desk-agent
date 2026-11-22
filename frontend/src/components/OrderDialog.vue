<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ArrowRight, ChevronDown, X } from 'lucide-vue-next'
import { api, authExpired, errorText } from '../api'
import { t } from '../i18n'
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
    else error.value = errorText(reason, t('暂时无法准备变更，请重试。', 'Could not prepare the change. Please try again.'))
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
      <div class="modal-heading"><h2 id="order-detail-title">{{ t('订单', 'Order') }} {{ order.order_id }}</h2>
        <button class="icon-button" type="button" :aria-label="t('关闭订单详情', 'Close order details')" :disabled="busy" @click="dialog?.close()"><X :size="20" /></button>
      </div>
      <p class="order-detail-status"><span :class="['status-tag', order.status.replaceAll(' ', '-')]">{{ statusLabel(order.status) }}</span></p>

      <section class="order-detail-block" :aria-label="t('订单商品', 'Order items')">
        <h3>{{ t('订单商品', 'Order items') }}</h3>
        <div v-for="(item, index) in order.items" :key="index" class="order-item">
          <div><strong>{{ item.name }}</strong><small>{{ Object.values(item.options).join(' / ') }} · {{ t('货号', 'Item') }} {{ item.item_id }}</small></div>
          <b>{{ money(item.price) }}</b>
        </div>
      </section>
      <dl class="order-detail-block order-fields">
        <dt>{{ t('收货地址', 'Shipping address') }}</dt><dd>{{ addressText(order.address) || t('暂无地址', 'No address') }}</dd>
        <dt>{{ t('物流单号', 'Tracking number') }}</dt><dd v-if="!tracking.length">{{ t('暂无物流信息', 'No tracking information') }}</dd>
        <dd v-for="number in tracking" :key="number">{{ number }}</dd>
        <template v-for="record in records" :key="record.label"><dt>{{ record.label }}</dt><dd>{{ record.value }}</dd></template>
      </dl>

      <section v-if="order.status === 'pending' || order.status === 'delivered'" class="order-detail-block manage-order">
        <h3>{{ t('办理售后', 'After-sales actions') }}</h3>
        <p v-if="error" class="notice" role="alert">{{ error }}</p>
        <p v-if="busy" class="action-progress" role="status">{{ t('正在准备变更明细…', 'Preparing the change details…') }}</p>
        <template v-if="order.status === 'pending'">
          <details class="order-action">
            <summary>{{ t('取消订单', 'Cancel order') }}<ChevronDown :size="15" /></summary>
            <form @submit.prevent="stage('cancel_pending_order', { reason })">
              <label class="field">{{ t('取消原因', 'Cancellation reason') }}
                <select v-model="reason" required :disabled="busy">
                  <option disabled value="">{{ t('请选择原因', 'Choose a reason') }}</option><option value="no longer needed">{{ t('不再需要', 'No longer needed') }}</option><option value="ordered by mistake">{{ t('误下单', 'Ordered by mistake') }}</option>
                </select>
              </label>
              <button type="submit" class="button primary" :disabled="busy || assistantBusy">{{ t('预览取消订单', 'Preview cancellation') }}<ArrowRight :size="15" /></button>
            </form>
          </details>
          <details class="order-action">
            <summary>{{ t('修改订单收货地址', 'Change shipping address') }}<ChevronDown :size="15" /></summary>
            <form @submit.prevent="stage('modify_pending_order_address', { ...address })">
              <fieldset :disabled="busy"><AddressFields v-model="address" /></fieldset>
              <button type="submit" class="button primary" :disabled="busy || assistantBusy">{{ t('预览地址变更', 'Preview address change') }}<ArrowRight :size="15" /></button>
            </form>
          </details>
          <details v-if="paymentMethods.length" class="order-action">
            <summary>{{ t('修改支付方式', 'Change payment method') }}<ChevronDown :size="15" /></summary>
            <form @submit.prevent="stage('modify_pending_order_payment', { payment_method_id: selectedPayment })">
              <label class="field">{{ t('新的支付方式', 'New payment method') }}
                <select v-model="selectedPayment" required :disabled="busy">
                  <option disabled value="">{{ t('选择支付方式', 'Choose a payment method') }}</option>
                  <option v-for="id in paymentMethods" :key="id" :value="id">{{ paymentLabel(id, customer) }}</option>
                </select>
              </label>
              <button type="submit" class="button primary" :disabled="busy || assistantBusy">{{ t('预览支付变更', 'Preview payment change') }}<ArrowRight :size="15" /></button>
            </form>
          </details>
        </template>
        <details v-else-if="refundMethods.length" class="order-action">
          <summary>{{ t('申请退货', 'Return items') }}<ChevronDown :size="15" /></summary>
          <form @submit.prevent="previewReturn">
            <fieldset :disabled="busy" class="return-items">
              <legend>{{ t('选择要退回的商品', 'Select the items to return') }}</legend>
              <label v-for="(item, index) in order.items" :key="index">
                <input v-model="selectedItems" type="checkbox" :value="index" />{{ item.name }}
                <small v-if="Object.keys(item.options).length">{{ Object.values(item.options).join(' / ') }}</small>
              </label>
            </fieldset>
            <label class="field">{{ t('退款方式', 'Refund method') }}
              <select v-model="refundPayment" required :disabled="busy">
                <option disabled value="">{{ t('选择退款方式', 'Choose a refund method') }}</option>
                <option v-for="id in refundMethods" :key="id" :value="id">{{ paymentLabel(id, customer) }}</option>
              </select>
            </label>
            <button type="submit" class="button primary" :disabled="busy || assistantBusy || !selectedItems.length || !refundPayment">{{ t('预览退货申请', 'Preview return') }}<ArrowRight :size="15" /></button>
          </form>
        </details>
        <p v-else class="pane-empty">{{ t('请通过客服咨询这笔订单的退款方式。', 'Contact support to discuss the refund method for this order.') }}</p>
      </section>
    </div>
  </dialog>
</template>
