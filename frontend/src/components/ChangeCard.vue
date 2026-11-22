<script setup lang="ts">
import { computed } from 'vue'
import { ChevronDown, CircleCheck, ClipboardCheck } from 'lucide-vue-next'
import { locale, t } from '../i18n'
import { actionLabel, changeRows, fullName } from '../retail'
import type { Pending } from '../types'

const props = defineProps<{ change: Pending; receiptTime?: string; stale?: boolean }>()
const rows = computed(() => changeRows(props.change))
const target = computed(() => props.change.before.order?.order_id || fullName(props.change.before.user))
const time = computed(() => props.receiptTime && new Date(props.receiptTime).toLocaleString(locale.value === 'en' ? 'en-US' : 'zh-CN', {
  month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
}))
</script>

<template>
  <article :class="['change-card', { receipt: receiptTime }]" :data-testid="receiptTime ? 'receipt-card' : 'approval-card'">
    <header class="change-heading">
      <span class="change-symbol"><CircleCheck v-if="receiptTime" :size="21" /><ClipboardCheck v-else :size="21" /></span>
      <div><span class="change-caption">{{ receiptTime ? t('办理回执', 'Receipt') : t('请核对变更', 'Review this change') }}</span><h3>{{ actionLabel(change.tool) }}</h3></div>
      <span class="state-chip">{{ receiptTime ? t('已办理', 'Completed') : stale ? t('需重新申请', 'Resubmit') : t('待你确认', 'Awaiting approval') }}</span>
    </header>
    <div class="change-target"><strong>{{ target }}</strong>
      <time v-if="receiptTime" :datetime="receiptTime">{{ time }}</time>
      <span v-else-if="change.before.order">{{ change.before.order.items.length }} {{ t('件商品', 'items') }}</span>
    </div>
    <component :is="receiptTime ? 'details' : 'div'" class="change-details">
      <summary v-if="receiptTime">{{ t('查看办理明细', 'View receipt details') }}<ChevronDown :size="15" /></summary>
      <table v-if="rows.length" class="diff-table">
        <thead><tr><th scope="col">{{ t('项目', 'Field') }}</th><th scope="col">{{ t('变更前', 'Before') }}</th><th scope="col">{{ t('变更后', 'After') }}</th></tr></thead>
        <tbody><tr v-for="(row, index) in rows" :key="index">
          <th scope="row">{{ row.label }}</th><td>{{ row.before }}</td><td>{{ row.after }}</td>
        </tr></tbody>
      </table>
      <p v-else class="change-note">{{ t('核对后，前后信息一致。', 'The before and after values are identical.') }}</p>
    </component>
    <p v-if="!receiptTime" class="change-note">{{ stale ? t('订单或账户信息已更新，请撤回本次申请后重新办理。', 'The order or account changed. Withdraw this request and try again.') : t('确认后生效。涉及款项的变更仅作模拟记录。', 'Takes effect after approval. Payment changes are simulated records.') }}</p>
  </article>
</template>
