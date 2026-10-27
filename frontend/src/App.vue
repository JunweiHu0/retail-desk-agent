<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import AgentDesk from "./AgentDesk.vue";
import { api } from "./api";
import type { Customer, Order, Session } from "./types";
const account = ref<Customer | null>(null),
  loading = ref(true),
  busy = ref(false),
  error = ref(""),
  page = ref("chat"),
  initialId = ref(""),
  chatKey = ref(0),
  signup = ref(false);
const form = reactive({
    email: "",
    password: "",
    first_name: "",
    last_name: "",
  }),
  orders = ref<Order[]>([]),
  search = ref(""),
  filter = ref(""),
  selected = ref<Order | null>(null),
  proposal = ref<Session | null>(null);
const address = reactive<Record<string, string>>({
    address1: "",
    address2: "",
    city: "",
    state: "",
    country: "",
    zip: "",
  }),
  reason = ref("no longer needed"),
  payment = ref(""),
  chosen = ref<number[]>([]);
const labels: Record<string, string> = {
  pending: "待处理",
  processed: "处理中",
  delivered: "已送达",
  cancelled: "已取消",
  "return requested": "退货已申请",
  "exchange requested": "换货已申请",
  "pending (item modified)": "商品已修改",
};
const fields: Record<string, string> = {
  address1: "街道地址",
  address2: "详细地址（可选）",
  city: "城市",
  state: "州 / 省",
  country: "国家",
  zip: "邮编",
};
const money = (n: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(
    n,
  );
const visible = computed(() =>
  orders.value.filter(
    (o) =>
      (!filter.value || o.status === filter.value) &&
      `${o.order_id} ${o.items.map((i) => i.name).join(" ")}`
        .toLowerCase()
        .includes(search.value.toLowerCase()),
  ),
);
async function run(fn: () => Promise<void>) {
  busy.value = true;
  error.value = "";
  try {
    await fn();
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    busy.value = false;
  }
}
async function refresh() {
  account.value = await api.me();
  orders.value = (await api.orders()).orders;
}
async function login() {
  await run(async () => {
    if (signup.value) {
      await api.register({ ...form });
      signup.value = false;
    }
    account.value = await api.login(form.email, form.password);
    form.password = "";
    await refresh();
  });
}
async function logout() {
  await run(async () => {
    await api.logout();
    account.value = null;
    orders.value = [];
    selected.value = null;
    proposal.value = null;
    initialId.value = "";
    page.value = "chat";
    chatKey.value++;
  });
}
async function navigate(next: string) {
  await run(async () => {
    await refresh();
    page.value = next;
    selected.value = null;
    if (next === "profile") Object.assign(address, account.value!.address);
    if (next === "chat") chatKey.value++;
  });
}
function openOrder(o: Order) {
  selected.value = o;
  chosen.value = [];
  payment.value =
    o.payment_history.find((p) => p.transaction_type === "payment")
      ?.payment_method_id || "";
  Object.assign(address, o.address);
}
async function stage(tool: string, args: Record<string, unknown>) {
  await run(async () => {
    proposal.value = await api.action(selected.value!.order_id, tool, args);
  });
}
async function consult(o?: Order) {
  await run(async () => {
    const s = await api.create();
    initialId.value = s.id;
    page.value = "chat";
    chatKey.value++;
    if (o)
      sessionStorage.setItem(
        "retail.order.intent",
        `请查询订单 ${o.order_id} 的状态和商品明细。`,
      );
    selected.value = null;
  });
}
function review() {
  initialId.value = proposal.value!.id;
  proposal.value = null;
  selected.value = null;
  page.value = "chat";
  chatKey.value++;
}
onMounted(async () => {
  try {
    await refresh();
  } catch {
    account.value = null;
  } finally {
    loading.value = false;
  }
});
</script>
<template>
  <div v-if="loading" class="login-screen">正在连接 Retail Desk…</div>
  <main v-else-if="!account" class="login-screen">
    <section class="login-story">
      <div class="portal-logo">◈ retaildesk</div>
      <small>YOUR RETAIL COMPANION</small>
      <h1>每一笔订单，<br />都有更好的服务。</h1>
      <p>查询订单、管理资料，与能够处理实际业务的智能客服对话。</p>
      <p class="login-points">
        01　专属账户空间<br />02　订单与客服实时联动<br />03　每次变更由你确认
      </p>
      <small>τ²-bench Retail · 本地零售沙盒</small>
    </section>
    <section class="login-card">
      <small>WELCOME TO RETAIL DESK</small>
      <h2>{{ signup ? "创建账户" : "欢迎回来" }}</h2>
      <p>登录后查看订单，继续与客服对话。</p>
      <form @submit.prevent="login">
        <template v-if="signup"
          ><label
            >名<input
              v-model="form.first_name"
              required
              maxlength="60"
              autocomplete="given-name" /></label
          ><label
            >姓<input
              v-model="form.last_name"
              required
              maxlength="60"
              autocomplete="family-name" /></label></template
        ><label
          >邮箱<input
            v-model="form.email"
            type="email"
            required
            autocomplete="username"
            placeholder="your@email.com" /></label
        ><label
          >密码<input
            v-model="form.password"
            type="password"
            :minlength="signup ? 10 : 1"
            maxlength="128"
            required
            :autocomplete="signup ? 'new-password' : 'current-password'"
        /></label>
        <p v-if="error" role="alert" class="portal-error">{{ error }}</p>
        <button class="portal-primary" :disabled="busy">
          {{ busy ? "请稍候…" : signup ? "注册并登录" : "登录工作台 →" }}
        </button>
      </form>
      <button
        class="text-button"
        @click="
          signup = !signup;
          error = '';
        "
      >
        {{ signup ? "已有账户？返回登录" : "没有账户？注册" }}
      </button>
      <div class="demo-login">
        <strong>体验演示账户</strong>
        <p>内置模拟客户与订单，新注册账号暂无订单。</p>
        <button
          v-for="email in ['li.ming', 'wang.fang', 'zhang.wei']"
          :key="email"
          @click="
            form.email = email + '@retail-demo.example.com';
            form.password = 'Demo@Retail2026!';
            signup = false;
          "
        >
          {{ email }} ↗</button
        ><small>演示密码：Demo@Retail2026!</small>
      </div>
    </section>
  </main>
  <div v-else class="portal-shell">
    <nav class="account-nav" aria-label="账户导航">
      <strong>◈ Retail Desk</strong>
      <div>
        <button
          v-for="(name, key) in {
            chat: '客服助手',
            orders: '订单管理',
            profile: '个人信息',
          }"
          :key="key"
          :class="{ active: page === key }"
          @click="navigate(key)"
          :disabled="busy"
        >
          {{ name }}
        </button>
      </div>
      <span>{{ account.name.first_name }} {{ account.name.last_name }}</span
      ><button @click="logout" :disabled="busy">退出登录</button>
    </nav>
    <p v-if="error" role="alert" class="portal-error global-error">
      {{ error }}
    </p>
    <AgentDesk
      v-if="page === 'chat'"
      :key="chatKey"
      :initial-id="initialId"
      @busy="busy = $event"
    />
    <main v-else class="portal-main">
      <header class="portal-heading">
        <div>
          <small>MY RETAIL SPACE</small>
          <h1>{{ page === "orders" ? "我的订单" : "个人信息" }}</h1>
          <p>与你的智能客服共享同一份资料与订单，每次操作都有记录。</p>
        </div>
        <button @click="consult()" :disabled="busy">联系智能客服 ↗</button>
      </header>
      <div v-if="page === 'profile'" class="profile-grid">
        <section class="portal-card">
          <h2>账户信息</h2>
          <div class="account-avatar">
            {{ account.name.first_name.slice(0, 1) }}
          </div>
          <h3>{{ account.name.first_name }} {{ account.name.last_name }}</h3>
          <p>{{ account.email }}</p>
          <small>客户编号 {{ account.user_id }}</small>
          <hr />
          <h3>支付方式</h3>
          <p v-if="!Object.keys(account.payment_methods).length">
            暂无支付方式
          </p>
          <p v-for="(p, id) in account.payment_methods" :key="id">
            {{ p.source }} · {{ p.last_four || String(id).slice(-4) }}
            <b v-if="p.balance !== undefined">{{ money(p.balance) }}</b>
          </p>
        </section>
        <section class="portal-card">
          <h2>默认收货地址</h2>
          <p>更新默认地址不会改变已有订单的收货地址。</p>
          <form
            class="address-form"
            @submit.prevent="
              run(async () => {
                proposal = await api.address({ ...address });
              })
            "
          >
            <label v-for="(label, key) in fields" :key="key"
              >{{ label
              }}<input
                v-model="address[key]"
                :required="key !== 'address2'"
                maxlength="200" /></label
            ><button class="portal-primary" :disabled="busy">
              预览地址变更
            </button>
          </form>
        </section>
      </div>
      <template v-else
        ><div class="order-toolbar">
          <input
            v-model="search"
            placeholder="搜索订单号或商品名称"
            aria-label="搜索订单"
          /><select v-model="filter" aria-label="筛选订单状态">
            <option value="">全部状态</option>
            <option v-for="(label, key) in labels" :key="key" :value="key">
              {{ label }}
            </option></select
          ><span>{{ visible.length }} 笔订单</span
          ><button @click="navigate('orders')" :disabled="busy">刷新</button>
        </div>
        <div v-if="!visible.length" class="portal-card empty-orders">
          暂无符合条件的订单。
        </div>
        <div class="order-grid">
          <article
            v-for="order in visible"
            :key="order.order_id"
            class="portal-card order-tile"
          >
            <header>
              <strong>{{ order.order_id }}</strong
              ><span class="order-badge">{{
                labels[order.status] || order.status
              }}</span>
            </header>
            <div
              v-for="(item, i) in order.items"
              :key="i"
              class="order-product"
            >
              <span class="product-symbol">▧</span>
              <div>
                <strong>{{ item.name }}</strong
                ><small>{{ Object.values(item.options).join(" / ") }}</small>
              </div>
              <b>{{ money(item.price) }}</b>
            </div>
            <footer>
              <span
                >{{ order.items.length }} 件 ·
                <b>{{
                  money(order.items.reduce((s, i) => s + i.price, 0))
                }}</b></span
              ><button @click="openOrder(order)">管理订单 →</button
              ><button @click="consult(order)" :disabled="busy">
                咨询此订单
              </button>
            </footer>
          </article>
        </div></template
      >
    </main>
    <div v-if="selected" class="modal-backdrop" @click.self="selected = null">
      <section class="order-modal">
        <header>
          <h2>{{ selected.order_id }}</h2>
          <button @click="selected = null" aria-label="关闭订单">✕</button>
        </header>
        <span class="order-badge">{{
          labels[selected.status] || selected.status
        }}</span>
        <div v-for="(item, i) in selected.items" :key="i" class="order-product">
          <input
            v-if="selected.status === 'delivered'"
            v-model="chosen"
            type="checkbox"
            :value="i"
            :aria-label="'选择 ' + item.name"
          />
          <div>
            <strong>{{ item.name }}</strong
            ><small
              >{{ Object.values(item.options).join(" / ") }} ·
              {{ item.item_id }}</small
            >
          </div>
          <b>{{ money(item.price) }}</b>
        </div>
        <h3>收货地址</h3>
        <p>{{ Object.values(selected.address).filter(Boolean).join(", ") }}</p>
        <h3>支付记录</h3>
        <p v-for="(p, i) in selected.payment_history" :key="i">
          {{ p.transaction_type === "refund" ? "退款" : "付款" }}
          {{ money(p.amount) }} · {{ p.payment_method_id }}
        </p>
        <template v-if="selected.fulfillments?.length"
          ><h3>物流信息</h3>
          <p v-for="(f, i) in selected.fulfillments" :key="i">
            {{ f.tracking_id.join(" / ") }}
          </p></template
        >
        <div v-if="selected.status === 'pending'" class="order-actions">
          <h3>取消订单</h3>
          <select v-model="reason">
            <option value="no longer needed">不再需要</option>
            <option value="ordered by mistake">误下单</option></select
          ><button
            @click="stage('cancel_pending_order', { reason })"
            :disabled="busy"
          >
            预览取消订单
          </button>
          <details>
            <summary>修改订单收货地址</summary>
            <form
              class="address-form"
              @submit.prevent="
                stage('modify_pending_order_address', { ...address })
              "
            >
              <label v-for="(label, key) in fields" :key="key"
                >{{ label
                }}<input
                  v-model="address[key]"
                  :required="key !== 'address2'"
                  maxlength="200" /></label
              ><button :disabled="busy">预览地址变更</button>
            </form>
          </details>
          <h3>修改支付方式</h3>
          <select v-model="payment">
            <option value="" disabled>选择支付方式</option>
            <option
              v-for="(p, id) in account.payment_methods"
              :key="id"
              :value="id"
            >
              {{ p.source }} · {{ p.last_four || String(id).slice(-4) }}
            </option></select
          ><button
            @click="
              stage('modify_pending_order_payment', {
                payment_method_id: payment,
              })
            "
            :disabled="busy || !payment"
          >
            预览支付变更
          </button>
        </div>
        <div v-if="selected.status === 'delivered'" class="order-actions">
          <h3>申请退货</h3>
          <p>勾选要退回的商品，选择退款方式。</p>
          <select v-model="payment">
            <option
              v-for="(p, id) in account.payment_methods"
              :key="id"
              :value="id"
            >
              {{ p.source }} · {{ p.last_four || String(id).slice(-4) }}
            </option></select
          ><button
            :disabled="busy || !chosen.length || !payment"
            @click="
              stage('return_delivered_order_items', {
                item_ids: chosen.map((i) => selected!.items[i]!.item_id),
                payment_method_id: payment,
              })
            "
          >
            预览退货申请
          </button>
        </div>
        <p>修改商品或换货，可让智能客服根据规格与库存协助办理。</p>
        <button
          class="portal-primary"
          @click="consult(selected!)"
          :disabled="busy"
        >
          让智能客服协助处理 →
        </button>
        <p v-if="error" role="alert" class="portal-error">{{ error }}</p>
      </section>
    </div>
    <div v-if="proposal" class="modal-backdrop">
      <section class="order-modal">
        <small>REVIEW BEFORE CONFIRMING</small>
        <h2>操作预览已生成</h2>
        <p>
          本次操作尚未执行。进入客服确认卡片，查看变更前后的具体内容，再选择确认或取消。记录会保存在你的历史咨询中。
        </p>
        <button class="portal-primary" @click="review">
          查看变更明细并处理 →
        </button>
      </section>
    </div>
  </div>
</template>
<style>
.login-screen {
  min-height: 100vh;
  background: #f5f6f2;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 100px;
  padding: 55px;
  color: #243d34;
}
.login-story {
  max-width: 440px;
}
.portal-logo {
  font-size: 30px;
  font-weight: 750;
  margin-bottom: 80px;
}
.login-story h1 {
  font-size: 45px;
  line-height: 1.5;
  margin: 20px 0;
}
.login-story p {
  color: #748078;
  line-height: 1.9;
}
.login-points {
  line-height: 3 !important;
  margin: 30px 0 60px;
}
.login-card {
  background: white;
  padding: 40px;
  width: 420px;
  border: 1px solid #e1e8df;
  border-radius: 16px;
  box-shadow: 0 20px 60px #294e3410;
}
.login-card h2 {
  font-size: 27px;
  margin: 16px 0;
}
.login-card p,
.portal-card p {
  font-size: 13px;
  line-height: 1.8;
  color: #7b847d;
}
.login-card form {
  display: grid;
  gap: 18px;
  margin-top: 28px;
}
.login-card label,
.address-form label {
  display: grid;
  gap: 9px;
  font-size: 12px;
  color: #66776b;
}
.login-card input,
.address-form input,
.order-toolbar input,
.portal-shell select {
  border: 1px solid #dce4dc;
  border-radius: 7px;
  padding: 12px;
  background: #fff;
  color: #243d34;
  outline-color: #4c8263;
  min-width: 0;
}
.portal-primary {
  background: #275c43 !important;
  color: white !important;
  border-color: #275c43 !important;
}
.login-card button,
.portal-main button,
.order-modal button {
  padding: 11px 18px;
  border: 1px solid #dce5dd;
  background: white;
  border-radius: 7px;
  cursor: pointer;
  color: #2c5a41;
}
.login-card button:disabled,
.portal-shell button:disabled {
  opacity: 0.45;
  cursor: wait;
}
.text-button {
  border: 0 !important;
  width: 100%;
  margin-top: 16px;
}
.demo-login {
  border-top: 1px solid #e8ede7;
  margin-top: 24px;
  padding-top: 23px;
  font-size: 12px;
}
.demo-login button {
  margin: 0 5px 10px 0;
  padding: 7px 12px;
}
.demo-login small {
  display: block;
  color: #78847b;
}
.portal-error {
  color: #a84439 !important;
  background: #fff1ec;
  padding: 12px;
  border-radius: 6px;
  font-size: 13px;
}
.account-nav {
  height: 58px;
  background: #fff;
  border-bottom: 1px solid #dce5dd;
  display: flex;
  align-items: center;
  padding: 0 25px;
  gap: 24px;
  position: relative;
  z-index: 20;
  color: #31533e;
  font-size: 12px;
}
.account-nav > div {
  display: flex;
  gap: 8px;
  flex: 1;
}
.account-nav button {
  border: 0;
  background: transparent;
  padding: 11px 17px;
  cursor: pointer;
  color: #627468;
  border-radius: 6px;
}
.account-nav button.active {
  background: #eaf0e9;
  color: #275c43;
  font-weight: 700;
}
.portal-shell .main {
  height: calc(100dvh - 58px);
}
.portal-main {
  max-width: 1370px;
  margin: auto;
  padding: 40px 55px;
  color: #2e4737;
}
.portal-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 30px;
}
.portal-heading h1 {
  font-size: 30px;
  margin: 12px 0;
}
.portal-heading p {
  font-size: 13px;
  color: #7b887e;
}
.portal-heading button {
  height: 42px;
}
.portal-card {
  background: white;
  border: 1px solid #e0e7de;
  border-radius: 12px;
  padding: 25px;
}
.portal-card h2 {
  font-size: 18px;
  margin: 0 0 23px;
}
.profile-grid {
  display: grid;
  grid-template-columns: 1fr 1.5fr;
  gap: 25px;
}
.account-avatar {
  width: 65px;
  height: 65px;
  border-radius: 18px;
  background: #e8efe5;
  color: #326045;
  display: grid;
  place-items: center;
  font-size: 26px;
}
.portal-shell small,
.login-screen small {
  color: #8c978d;
  font-size: 10px;
  letter-spacing: 1px;
}
.portal-card hr {
  border: 0;
  border-top: 1px solid #edf0eb;
  margin: 25px 0;
}
.address-form {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
  margin: 22px 0;
}
.address-form button {
  grid-column: 1/-1;
}
.order-toolbar {
  display: flex;
  gap: 15px;
  align-items: center;
  margin: 25px 0;
  font-size: 12px;
}
.order-toolbar input {
  flex: 1;
}
.order-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 22px;
}
.order-tile header,
.order-tile footer,
.order-modal > header {
  display: flex;
  align-items: center;
  gap: 12px;
  justify-content: space-between;
}
.order-tile header {
  margin-bottom: 20px;
  font-size: 13px;
}
.order-badge {
  font-size: 11px;
  padding: 6px 10px;
  border-radius: 5px;
  background: #eff3e9;
  color: #5c754c;
}
.order-product {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 17px 0;
  border-bottom: 1px solid #edf0e9;
  font-size: 12px;
}
.order-product div {
  flex: 1;
}
.order-product small {
  display: block;
  color: #929c93;
  font-size: 11px;
  margin-top: 8px;
  letter-spacing: 0;
}
.product-symbol {
  width: 40px;
  height: 45px;
  display: grid;
  place-items: center;
  font-size: 25px;
  background: #f2f4ed;
  border-radius: 7px;
  color: #78936e;
}
.order-tile footer {
  margin-top: 20px;
  font-size: 11px;
  flex-wrap: wrap;
}
.order-tile footer button {
  padding: 8px 10px;
}
.empty-orders {
  text-align: center;
  padding: 60px;
}
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: #18352660;
  backdrop-filter: blur(3px);
  z-index: 50;
  display: grid;
  place-items: center;
  padding: 30px;
}
.order-modal {
  width: min(800px, 90vw);
  max-height: 88vh;
  overflow: auto;
  background: white;
  border-radius: 14px;
  padding: 30px;
  color: #304b3a;
  box-shadow: 0 20px 70px #16331a30;
}
.order-modal h3 {
  font-size: 14px;
  margin: 22px 0 10px;
}
.order-modal p {
  font-size: 12px;
  line-height: 1.8;
  color: #7b887b;
}
.order-actions {
  padding: 5px 0 20px;
  border-bottom: 1px solid #e5eae2;
}
.order-actions button {
  margin: 10px;
}
.order-actions details {
  margin: 15px 0;
}
.global-error {
  position: fixed;
  top: 58px;
  right: 25px;
  z-index: 70;
  max-width: 450px;
}
</style>
