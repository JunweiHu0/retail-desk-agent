<script setup lang="ts">
import { onUnmounted, ref } from 'vue'
import { ArrowRight, CreditCard, Mail, MapPin, Pencil, UserRound, Wallet } from 'lucide-vue-next'
import { api, authExpired, errorText } from '../api'
import { addressText, fullName, money, paymentLabel } from '../retail'
import type { ChatTarget, Customer } from '../types'
import AddressFields from './AddressFields.vue'

const props = defineProps<{ customer: Customer; assistantBusy: boolean }>()
const emit = defineEmits<{ openChat: [target: ChatTarget]; authExpired: []; busy: [value: boolean] }>()
const editing = ref(false)
const busy = ref(false)
const error = ref('')
const draft = ref({ ...props.customer.address })
let mounted = true
onUnmounted(() => { mounted = false; emit('busy', false) })

function edit() {
  draft.value = { ...props.customer.address }
  error.value = ''
  editing.value = true
}

async function reviewAddress() {
  if (busy.value || props.assistantBusy) return
  busy.value = true
  emit('busy', true)
  error.value = ''
  try {
    const preview = await api.stageAddress(draft.value)
    if (mounted) emit('openChat', { id: preview.id })
  } catch (reason) {
    if (!mounted) return
    if (authExpired(reason)) emit('authExpired')
    else error.value = errorText(reason, '暂时无法准备变更，请重试。')
  } finally {
    busy.value = false
    if (mounted) emit('busy', false)
  }
}
</script>

<template>
  <main class="frame portal-page">
    <header class="page-intro">
      <div><h1>客户资料</h1><p>查看你的邮箱、默认收货地址和支付方式。</p></div>
    </header>
    <div class="profile-layout">
      <section class="surface profile-card profile-identity" aria-labelledby="identity-title">
        <div class="panel-title"><UserRound :size="19" /><h2 id="identity-title">账户信息</h2></div>
        <div class="profile-person">
          <span class="profile-initial">{{ customer.name.first_name.slice(0, 1) }}{{ customer.name.last_name.slice(0, 1) }}</span>
          <div><strong>{{ fullName(customer) }}</strong><small><Mail :size="13" />{{ customer.email }}</small></div>
        </div>
      </section>

      <section class="surface profile-card profile-address" aria-labelledby="address-title">
        <div class="panel-title"><MapPin :size="19" /><h2 id="address-title">默认收货地址</h2>
          <button v-if="!editing" class="text-button profile-edit" @click="edit"><Pencil :size="15" />编辑地址</button>
        </div>
        <div v-if="!editing" class="address-summary">
          <strong>{{ fullName(customer) }}</strong>
          <p>{{ addressText(customer.address) || '暂未设置默认收货地址。' }}</p>
        </div>
        <form v-else @submit.prevent="reviewAddress">
          <fieldset :disabled="busy"><AddressFields v-model="draft" /></fieldset>
          <p v-if="error" class="notice" role="alert">{{ error }}</p>
          <div class="form-actions">
            <button type="button" class="button secondary" :disabled="busy" @click="editing = false">取消编辑</button>
            <button type="submit" class="button primary" :disabled="busy || assistantBusy">
              {{ busy ? '正在准备…' : '预览地址变更' }}<ArrowRight :size="16" />
            </button>
          </div>
        </form>
      </section>

      <section class="surface profile-card profile-payments" aria-labelledby="payment-title">
        <div class="panel-title"><Wallet :size="19" /><h2 id="payment-title">支付方式</h2></div>
        <p v-if="!Object.keys(customer.payment_methods).length" class="pane-empty">暂无支付方式。</p>
        <div v-for="(method, id) in customer.payment_methods" :key="id" class="payment-row">
          <span class="payment-icon"><CreditCard :size="18" /></span>
          <strong>{{ paymentLabel(id, customer) }}</strong>
          <small v-if="method.balance != null">余额 {{ money(method.balance) }}</small>
        </div>
      </section>
    </div>
  </main>
</template>
