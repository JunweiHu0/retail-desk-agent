<script setup lang="ts">
import { BookOpen, ChevronDown, Package, PackageSearch, ShieldCheck, ShoppingBag } from 'lucide-vue-next'
import { addressText, fullName, money, orderTotal, paymentAndServiceFields, paymentLabel, statusLabel } from '../retail'
import type { Customer, Order } from '../types'

defineProps<{ customer?: Customer | null; orders: Order[]; demo: boolean }>()
</script>

<template>
  <aside class="order-column" aria-label="订单与服务指南">
    <section id="my-orders" class="surface orders-surface" tabindex="-1" aria-labelledby="orders-title">
      <div class="panel-title"><Package :size="19" /><h2 id="orders-title">我的订单</h2><span v-if="customer" class="order-count">{{ orders.length }}</span></div>
      <div v-if="!customer" class="order-placeholder">
        <span class="empty-icon"><PackageSearch :size="26" :stroke-width="1.6" /></span>
        <strong>尚未关联订单</strong>
        <p>在咨询中核验下单邮箱后，即可在这里查看订单与物流。</p>
      </div>
      <template v-else>
        <details class="account">
          <summary><span class="initials">{{ customer.name.first_name[0] }}{{ customer.name.last_name[0] }}</span>
            <span class="account-name"><strong>{{ fullName(customer) }}</strong><small><ShieldCheck :size="12" />账户已核验</small></span><ChevronDown :size="15" />
          </summary>
          <dl class="account-fields"><dt>下单邮箱</dt><dd>{{ customer.email }}</dd><dt>默认地址</dt><dd>{{ addressText(customer.address) }}</dd>
            <dt v-if="Object.keys(customer.payment_methods).length">支付方式</dt>
            <dd v-for="(method, id) in customer.payment_methods" :key="id">{{ paymentLabel(id, customer) }}<span v-if="method.balance != null"> · 余额 {{ money(method.balance) }}</span></dd>
          </dl>
        </details>
        <p v-if="!orders.length" class="panel-empty">这个账户暂时没有订单。</p>
        <div v-else class="order-list">
          <details v-for="order in orders" :key="order.order_id" class="order-card" :open="orders.length === 1">
            <summary><span><strong>{{ order.order_id }}</strong><small>{{ order.items.length }} 件商品 · {{ money(orderTotal(order)) }}</small></span>
              <span :class="['status-tag', order.status.replaceAll(' ', '-')]">{{ statusLabel(order.status) }}</span><ChevronDown :size="14" />
            </summary>
            <div class="order-body">
              <div v-for="(item, index) in order.items" :key="index" class="order-item"><ShoppingBag :size="16" />
                <div><strong>{{ item.name }}</strong><small>{{ Object.values(item.options).join(' / ') }}</small><small>货号 {{ item.item_id }}</small></div><b>{{ money(item.price) }}</b>
              </div>
              <dl class="order-fields"><dt>收货地址</dt><dd>{{ addressText(order.address) }}</dd>
                <template v-if="order.fulfillments.some(shipment => shipment.tracking_id.length)"><dt>物流单号</dt>
                  <dd v-for="id in order.fulfillments.flatMap(shipment => shipment.tracking_id)" :key="id">{{ id }}</dd>
                </template>
              </dl>
              <details class="order-finance"><summary>支付与售后<ChevronDown :size="14" /></summary>
                <dl class="order-fields"><template v-for="field in paymentAndServiceFields(order, customer)" :key="field.label">
                  <dt>{{ field.label }}</dt><dd>{{ field.value }}</dd>
                </template></dl>
              </details>
            </div>
          </details>
        </div>
      </template>
    </section>
    <section class="surface guide" aria-labelledby="guide-title">
      <div class="panel-title"><BookOpen :size="18" /><h2 id="guide-title">服务指南</h2></div>
      <details><summary>查订单需要准备什么？<ChevronDown :size="15" /></summary><p>请准备下单时使用的邮箱。提供订单号可以更快找到对应的商品和物流信息。</p></details>
      <details><summary>哪些订单可以退货？<ChevronDown :size="15" /></summary><p>{{ demo ? '已送达订单可申请整单退货，退回原支付方式。提交前可核对商品和退款信息。' : '已送达订单可申请退货。在对话中说明商品和退款方式，即可核对可办理的明细。' }}</p></details>
      <details><summary>申请提交后会立即生效吗？<ChevronDown :size="15" /></summary><p>助手会先列出变更前后的信息。点击「确认执行」后才会办理，完成后可在咨询记录中查看回执。</p></details>
    </section>
  </aside>
</template>
