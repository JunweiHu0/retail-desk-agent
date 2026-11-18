<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ArrowRight, X } from 'lucide-vue-next'
import { services, statusLabel } from '../retail'
import type { Order, Service } from '../types'

const props = defineProps<{ service: Service; orders: Order[] }>()
const emit = defineEmits<{ close: []; submit: [message: string]; orders: [] }>()
const dialog = ref<HTMLDialogElement | null>(null)
const order = ref('')
const reason = ref('')
const eligible = computed(() => props.orders.filter(item => props.service === 'query' ||
  item.status === (props.service === 'cancel' ? 'pending' : 'delivered')))
const descriptions: Record<Service, string> = {
  query: '选择一笔订单，或询问当前账户的订单进度。',
  return: '此处可申请整单退货，退回原支付方式。部分退货可在「我的订单」中办理。',
  cancel: '待处理的订单可申请取消。提交后由你核对退款信息。',
}

onMounted(() => dialog.value?.showModal())

function submit() {
  if (order.value && !eligible.value.some(item => item.order_id === order.value)) return
  const target = order.value ? '订单 ' + order.value : '我的订单'
  const request = {
    query: '请查询' + target + '的状态和商品明细。',
    cancel: '请取消' + target + '，原因是' + reason.value + '。',
    return: '请将' + target + '的全部商品退货，退回原支付方式。',
  }[props.service]
  dialog.value?.close()
  emit('submit', request)
}
</script>

<template>
  <dialog ref="dialog" class="modal service-modal" aria-labelledby="service-title" @close="emit('close')" @click="event => { if (event.target === dialog) dialog?.close() }">
    <div class="modal-inner">
      <div class="modal-heading">
        <h2 id="service-title">{{ services[service].title }}</h2>
        <button type="button" class="icon-button" aria-label="关闭服务窗口" @click="dialog?.close()"><X :size="20" /></button>
      </div>
      <p class="modal-intro">{{ descriptions[service] }}</p>
      <div v-if="!eligible.length" class="no-eligible">
        <p>当前没有可办理的订单。</p>
        <button type="button" class="text-button" @click="dialog?.close(); emit('orders')">查看我的订单<ArrowRight :size="15" /></button>
      </div>
      <form v-else @submit.prevent="submit">
        <label class="field">订单
          <select v-model="order" :required="service !== 'query'">
            <option :disabled="service !== 'query'" value="">{{ service === 'query' ? '查询我的订单' : '选择一笔订单' }}</option>
            <option v-for="item in eligible" :key="item.order_id" :value="item.order_id">{{ item.order_id }} · {{ statusLabel(item.status) }}</option>
          </select>
        </label>
        <label v-if="service === 'cancel'" class="field">取消原因
          <select v-model="reason" required><option disabled value="">请选择原因</option><option>不再需要</option><option>误下单</option></select>
        </label>
        <div class="modal-actions">
          <button type="submit" class="button primary">{{ service === 'query' ? '查询订单' : '查看变更预览' }}<ArrowRight :size="16" /></button>
        </div>
      </form>
    </div>
  </dialog>
</template>
