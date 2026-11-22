<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ArrowRight, X } from 'lucide-vue-next'
import { serviceTitle, statusLabel } from '../retail'
import { t } from '../i18n'
import type { Order, Service } from '../types'

const props = defineProps<{ service: Service; orders: Order[] }>()
const emit = defineEmits<{ close: []; submit: [message: string]; orders: [] }>()
const dialog = ref<HTMLDialogElement | null>(null)
const order = ref('')
const reason = ref('')
const eligible = computed(() => props.orders.filter(item => props.service === 'query' ||
  item.status === (props.service === 'cancel' ? 'pending' : 'delivered')))
const descriptions = computed<Record<Service, string>>(() => ({
  query: t('选择一笔订单，或询问当前账户的订单进度。', 'Choose an order, or ask about the orders on this account.'),
  return: t('此处可申请整单退货，退回原支付方式。部分退货可在「我的订单」中办理。', 'Return a whole order to the original payment method here. Partial returns are available in My orders.'),
  cancel: t('待处理的订单可申请取消。提交后由你核对退款信息。', 'Pending orders can be cancelled. Review the refund details before confirming.'),
}))

onMounted(() => dialog.value?.showModal())

function submit() {
  if (order.value && !eligible.value.some(item => item.order_id === order.value)) return
  const target = order.value
    ? t('订单 ', 'order ') + order.value
    : t('我的订单', 'my orders')
  const reasonText = reason.value === 'no longer needed'
    ? t('不再需要', 'no longer needed')
    : t('误下单', 'ordered by mistake')
  const request = {
    query: t('请查询' + target + '的状态和商品明细。', 'Please check the status and items for ' + target + '.'),
    cancel: t('请取消' + target + '，原因是' + reasonText + '。', 'Please cancel ' + target + ' because it is ' + reasonText + '.'),
    return: t('请将' + target + '的全部商品退货，退回原支付方式。', 'Please return every item in ' + target + ' to the original payment method.'),
  }[props.service]
  dialog.value?.close()
  emit('submit', request)
}
</script>

<template>
  <dialog ref="dialog" class="modal service-modal" aria-labelledby="service-title" @close="emit('close')" @click="event => { if (event.target === dialog) dialog?.close() }">
    <div class="modal-inner">
      <div class="modal-heading">
        <h2 id="service-title">{{ serviceTitle(service) }}</h2>
        <button type="button" class="icon-button" :aria-label="t('关闭服务窗口', 'Close service dialog')" @click="dialog?.close()"><X :size="20" /></button>
      </div>
      <p class="modal-intro">{{ descriptions[service] }}</p>
      <div v-if="!eligible.length" class="no-eligible">
        <p>{{ t('当前没有可办理的订单。', 'No eligible orders right now.') }}</p>
        <button type="button" class="text-button" @click="dialog?.close(); emit('orders')">{{ t('查看我的订单', 'View my orders') }}<ArrowRight :size="15" /></button>
      </div>
      <form v-else @submit.prevent="submit">
        <label class="field">{{ t('订单', 'Order') }}
          <select v-model="order" :required="service !== 'query'">
            <option :disabled="service !== 'query'" value="">{{ service === 'query' ? t('查询我的订单', 'All my orders') : t('选择一笔订单', 'Choose an order') }}</option>
            <option v-for="item in eligible" :key="item.order_id" :value="item.order_id">{{ item.order_id }} · {{ statusLabel(item.status) }}</option>
          </select>
        </label>
        <label v-if="service === 'cancel'" class="field">{{ t('取消原因', 'Cancellation reason') }}
          <select v-model="reason" required><option disabled value="">{{ t('请选择原因', 'Choose a reason') }}</option><option value="no longer needed">{{ t('不再需要', 'No longer needed') }}</option><option value="ordered by mistake">{{ t('误下单', 'Ordered by mistake') }}</option></select>
        </label>
        <div class="modal-actions">
          <button type="submit" class="button primary">{{ service === 'query' ? t('查询订单', 'Check order') : t('查看变更预览', 'Review change') }}<ArrowRight :size="16" /></button>
        </div>
      </form>
    </div>
  </dialog>
</template>
