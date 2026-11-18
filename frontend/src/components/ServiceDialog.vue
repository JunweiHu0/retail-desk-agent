<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ArrowRight, PackageOpen, X } from 'lucide-vue-next'
import { api } from '../api'
import { services } from '../retail'
import type { Customer, Sample, Service } from '../types'

const props = defineProps<{ service: Service; demo: boolean; customer?: Customer | null }>()
const emit = defineEmits<{ close: []; submit: [message: string] }>()
const dialog = ref<HTMLDialogElement | null>(null)
const email = ref(props.customer?.email || '')
const order = ref('')
const reason = ref('')
const sample = ref<Sample>()
const lead: Record<Service, string> = {
  query: '使用下单邮箱查找订单。填写订单号可直接查询某一笔订单。',
  return: '此处办理整单退货，退款退回原支付方式。提交后可先核对商品明细。',
  cancel: '仅待处理订单可申请取消。提交后，请核对取消原因和退款信息。',
}

onMounted(async () => {
  dialog.value?.showModal()
  if (!props.demo || props.customer) return
  try {
    const { samples } = await api.samples()
    const status = { query: 'processed', cancel: 'pending', return: 'delivered' }[props.service]
    sample.value = samples.find(item => item.status === status) || (props.service === 'query' ? samples[0] : undefined)
  } catch { /* Manual entry remains available if sample orders cannot be loaded. */ }
})

function fillSample() {
  if (!sample.value) return
  email.value = sample.value.email
  order.value = sample.value.order_id
  if (props.service === 'cancel') reason.value = '不再需要'
}
function submit() {
  const id = order.value.trim().replace(/^#?w/i, '#W')
  const target = id ? '订单 ' + id : '我的订单'
  const request = {
    query: '请查询' + target + '的状态和商品明细。',
    cancel: '请取消' + target + '，原因是' + reason.value + '。',
    return: '请将' + target + '的全部商品退货，退回原支付方式。',
  }[props.service]
  dialog.value?.close()
  emit('submit', request + '我的邮箱是 ' + email.value.trim() + '。')
}
</script>

<template>
  <dialog ref="dialog" class="modal service-modal" aria-labelledby="service-title" @close="emit('close')" @click="event => { if (event.target === dialog) dialog?.close() }">
    <div class="modal-inner">
      <div class="modal-heading">
        <h2 id="service-title">{{ services[service].title }}</h2>
        <button type="button" class="icon-button" aria-label="关闭服务窗口" @click="dialog?.close()"><X :size="20" /></button>
      </div>
      <p class="modal-intro">{{ lead[service] }}</p>
      <form @submit.prevent="submit">
        <label class="field">下单邮箱<input v-model.trim="email" type="email" name="email" autocomplete="email" maxlength="254" placeholder="name@example.com" :readonly="!!customer" required autofocus /></label>
        <label class="field"><span>订单号 <small v-if="service === 'query'">选填</small></span>
          <input v-model.trim="order" type="text" name="order" placeholder="#W1234567" pattern="#?[Ww][0-9]+" title="订单号由 W 和数字组成，例如 #W1234567" maxlength="32" :required="service !== 'query'" />
        </label>
        <label v-if="service === 'cancel'" class="field">取消原因
          <select v-model="reason" required><option disabled value="">请选择原因</option><option>不再需要</option><option>误下单</option></select>
        </label>
        <div class="modal-actions">
          <button v-if="sample" type="button" class="text-button" @click="fillSample"><PackageOpen :size="16" />填入示例订单</button>
          <button type="submit" class="button primary">{{ service === 'query' ? '查询订单' : '查看变更预览' }}<ArrowRight :size="16" /></button>
        </div>
      </form>
    </div>
  </dialog>
</template>
