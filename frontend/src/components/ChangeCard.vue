<script setup lang="ts">
import { computed } from 'vue'
import { ChevronDown, CircleCheck, ClipboardCheck } from 'lucide-vue-next'
import { actionLabel, changeRows, fullName } from '../retail'
import type { Pending } from '../types'

const props = defineProps<{ change: Pending; receiptTime?: string; stale?: boolean }>()
const rows = computed(() => changeRows(props.change))
const target = computed(() => props.change.before.order?.order_id || fullName(props.change.before.user))
const time = computed(() => props.receiptTime && new Date(props.receiptTime).toLocaleString('zh-CN', {
  month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
}))
</script>

<template>
  <article :class="['change-card', { receipt: receiptTime }]" :data-testid="receiptTime ? 'receipt-card' : 'approval-card'">
    <header class="change-heading">
      <span class="change-symbol"><CircleCheck v-if="receiptTime" :size="21" /><ClipboardCheck v-else :size="21" /></span>
      <div><span class="change-caption">{{ receiptTime ? '办理回执' : '请核对变更' }}</span><h3>{{ actionLabel(change.tool) }}</h3></div>
      <span class="state-chip">{{ receiptTime ? '已办理' : stale ? '需重新申请' : '待你确认' }}</span>
    </header>
    <div class="change-target"><strong>{{ target }}</strong>
      <time v-if="receiptTime" :datetime="receiptTime">{{ time }}</time>
      <span v-else-if="change.before.order">{{ change.before.order.items.length }} 件商品</span>
    </div>
    <component :is="receiptTime ? 'details' : 'div'" class="change-details">
      <summary v-if="receiptTime">查看办理明细<ChevronDown :size="15" /></summary>
      <table v-if="rows.length" class="diff-table">
        <thead><tr><th scope="col">项目</th><th scope="col">变更前</th><th scope="col">变更后</th></tr></thead>
        <tbody><tr v-for="(row, index) in rows" :key="index">
          <th scope="row">{{ row.label }}</th><td>{{ row.before }}</td><td>{{ row.after }}</td>
        </tr></tbody>
      </table>
      <p v-else class="change-note">核对后，前后信息一致。</p>
    </component>
    <p v-if="!receiptTime" class="change-note">{{ stale ? '订单或账户信息已更新，请撤回本次申请后重新办理。' : '确认后生效。涉及款项的变更仅作模拟记录。' }}</p>
  </article>
</template>
