<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import {
  ArrowDown,
  ArrowRight,
  ArrowUp,
  Check,
  CheckCheck,
  ChevronDown,
  CircleHelp,
  Database,
  ExternalLink,
  Headphones,
  History,
  LoaderCircle,
  MessageSquare,
  Package,
  Plus,
  RefreshCw,
  ShieldCheck,
  ShoppingBag,
  Sparkles,
  Terminal,
  UserRound,
  X,
  Zap,
} from "lucide-vue-next";
import { api } from "./api";
import type {
  Health,
  Order,
  Pending,
  Sample,
  Session,
  SessionRef,
  ToolEvent,
} from "./types";

const props = defineProps<{ initialId?: string }>();
const emit = defineEmits<{ busy: [value: boolean] }>();
const health = ref<Health | null>(null),
  samples = ref<Sample[]>([]);
const refs = ref<SessionRef[]>([]),
  active = ref<SessionRef | null>(null),
  session = ref<Session | null>(null);
const input = ref(""),
  busy = ref(false),
  error = ref(""),
  tab = ref<"customer" | "tools">("customer");
const liveTools = ref<ToolEvent[]>([]),
  running = ref(""),
  chatArea = ref<HTMLElement | null>(null);
const connected = ref(false);
watch(busy, (value) => emit("busy", value));
const customer = computed(() => session.value?.context.user);
const pending = computed(() => session.value?.context.pending);
const orders = computed(() => session.value?.context.orders || []);
const events = computed(() => session.value?.events || []);
const toolCount = computed(
  () => events.value.filter((e) => e.kind === "tool").length,
);
const writes = computed(
  () =>
    events.value.filter((e) => e.kind === "decision" && e.data.approved).length,
);
const hasMessages = computed(() => !!session.value?.messages.length);
const labels: Record<string, string> = {
  pending: "待处理",
  processed: "处理中",
  delivered: "已送达",
  cancelled: "已取消",
  "return requested": "退货已申请",
  "exchange requested": "换货已申请",
  "pending (item modified)": "商品已修改",
};
const toolNames: Record<string, string> = {
  find_user_id_by_email: "核验账户邮箱",
  find_user_id_by_name_zip: "核验姓名与邮编",
  get_user_details: "获取客户资料",
  get_order_details: "查询订单明细",
  get_product_details: "查询商品信息",
  get_item_details: "查询商品规格",
  list_all_product_types: "查询商品目录",
  calculate: "计算金额",
  cancel_pending_order: "取消订单",
  modify_pending_order_address: "修改收货地址",
  modify_pending_order_items: "修改订单商品",
  modify_pending_order_payment: "修改支付方式",
  modify_user_address: "修改默认地址",
  return_delivered_order_items: "申请退货",
  exchange_delivered_order_items: "申请换货",
  transfer_to_human_agents: "转接人工客服",
};
const money = (n: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(
    n,
  );
const total = (o: Order) => o.items.reduce((sum, i) => sum + i.price, 0);
const json = (v: unknown) => JSON.stringify(v, null, 2);
const resultStatus = (v: unknown) => (v as { status?: string } | null)?.status;
const save = () => {};
const scroll = async () => {
  await nextTick();
  chatArea.value?.scrollTo({
    top: chatArea.value.scrollHeight,
    behavior: "smooth",
  });
};

function changes(action: Pending) {
  const fieldNames: Record<string, string> = {
    status: "订单状态",
    cancel_reason: "取消原因",
    payment_history: "付款与退款记录",
    items: "订单商品",
    return_items: "退货商品",
    return_payment_method_id: "退款方式",
    exchange_items: "待换出商品",
    exchange_new_items: "待换入商品",
    exchange_payment_method_id: "差价支付 / 退款方式",
    exchange_price_difference: "换货差价",
    address1: "街道地址",
    address2: "详细地址",
    city: "城市",
    state: "州 / 省",
    country: "国家",
    zip: "邮编",
  };
  const payment = (id: string) => {
    const value = action.after.user.payment_methods[id];
    const names: Record<string, string> = {
      gift_card: "礼品卡",
      credit_card: "信用卡",
      paypal: "PayPal",
    };
    return value
      ? `${names[value.source] || value.source} · ${value.last_four || id.slice(-4)}`
      : id;
  };
  const item = (id: string) => {
    const value =
      action.item_details?.[id] ||
      action.before.order?.items.find((i) => i.item_id === id);
    return value
      ? `${value.name} · ${Object.values(value.options).join(" / ")} (${id})`
      : id;
  };
  const describe = (value: unknown, path: string) => {
    if (value === null || value === undefined) return "—";
    if (path.endsWith(".status")) return labels[String(value)] || String(value);
    if (path.endsWith(".cancel_reason"))
      return (
        (
          {
            "no longer needed": "不再需要",
            "ordered by mistake": "误下单",
          } as Record<string, string>
        )[String(value)] || String(value)
      );
    if (
      path.endsWith(".balance") ||
      path.endsWith(".exchange_price_difference")
    )
      return money(Number(value));
    if (path.endsWith("_payment_method_id")) return payment(String(value));
    if (Array.isArray(value)) {
      if (path.endsWith(".payment_history"))
        return value
          .map(
            (p) =>
              `${p.transaction_type === "refund" ? "退款" : "付款"} ${money(p.amount)} → ${payment(p.payment_method_id)}`,
          )
          .join("\n");
      if (path.endsWith(".items"))
        return value
          .map(
            (i) =>
              `${i.name} · ${Object.values(i.options).join(" / ")} · ${money(i.price)}`,
          )
          .join("\n");
      if (path.endsWith("_items") || path.endsWith("_new_items"))
        return value.map(item).join("\n");
    }
    return typeof value === "string" ? value : json(value);
  };
  const label = (path: string) => {
    const parts = path.split("."),
      key = parts.at(-1) || path;
    if (key === "balance") return `${payment(parts.at(-2) || "")}余额`;
    const prefix = path.includes(".address.")
      ? path.startsWith("user.")
        ? "默认地址 · "
        : "收货地址 · "
      : "";
    return prefix + (fieldNames[key] || key);
  };
  const result: { key: string; before: string; after: string }[] = [];
  const walk = (a: unknown, b: unknown, path: string) => {
    if (JSON.stringify(a) === JSON.stringify(b)) return;
    if (
      a &&
      b &&
      typeof a === "object" &&
      typeof b === "object" &&
      !Array.isArray(a) &&
      !Array.isArray(b)
    ) {
      for (const key of new Set([...Object.keys(a), ...Object.keys(b)]))
        walk(
          (a as Record<string, unknown>)[key],
          (b as Record<string, unknown>)[key],
          path ? `${path}.${key}` : key,
        );
    } else
      result.push({
        key: label(path),
        before: describe(a, path),
        after: describe(b, path),
      });
  };
  walk(action.before, action.after, "");
  return result;
}

async function createSession() {
  if (busy.value) return;
  error.value = "";
  try {
    const item = await api.create();
    refs.value.unshift(item);
    save();
    await openSession(item);
  } catch (e) {
    error.value = (e as Error).message;
  }
}
async function openSession(item: SessionRef) {
  if (busy.value) return;
  error.value = "";
  liveTools.value = [];
  try {
    const state = await api.session(item);
    active.value = item;
    session.value = state;
    localStorage.setItem("retail.active.v1", item.id);
    await scroll();
  } catch (e) {
    error.value = (e as Error).message;
  }
}
async function refresh() {
  if (active.value && !busy.value) await openSession(active.value);
}
async function send(text = input.value) {
  if (!text.trim() || busy.value || pending.value || session.value?.transferred)
    return;
  if (!active.value) await createSession();
  if (!active.value || !session.value) return;
  busy.value = true;
  input.value = "";
  error.value = "";
  liveTools.value = [];
  running.value = "正在理解你的需求";
  session.value.messages.push({
    id: `temp-${Date.now()}`,
    role: "user",
    content: text,
  });
  await scroll();
  try {
    await api.chat(active.value, text, (event) => {
      if (event.type === "tool_start") {
        running.value = toolNames[String(event.name)] || String(event.name);
        liveTools.value.push(event as unknown as ToolEvent);
      }
      if (event.type === "tool_end") {
        const index = liveTools.value.findLastIndex(
          (t) => t.name === event.name && t.type === "tool_start",
        );
        if (index >= 0) liveTools.value[index] = event as unknown as ToolEvent;
      }
      if (event.type === "done" || event.type === "error") {
        session.value = event.session as Session;
        if (active.value) {
          active.value.title = session.value.title;
          save();
        }
        if (event.type === "error") error.value = String(event.message);
        liveTools.value = [];
        void scroll();
      }
    });
  } catch (e) {
    error.value = (e as Error).message;
    try {
      session.value = await api.session(active.value);
    } catch {
      /* leave the readable local transcript */
    }
  } finally {
    busy.value = false;
    running.value = "";
    await scroll();
  }
}
async function decide(approve: boolean) {
  if (!active.value || !pending.value || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    const result = await api.decide(active.value, pending.value.id, approve);
    session.value = result.session;
    samples.value = (await api.samples()).samples;
    await scroll();
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    busy.value = false;
  }
}
function scenario(sample: Sample, kind: string) {
  const base = `我的邮箱是 ${sample.email}，`;
  const query =
    kind === "cancel"
      ? `请取消订单 ${sample.order_id}，原因是不再需要。`
      : kind === "return"
        ? `请将订单 ${sample.order_id} 的全部商品退货，退回原支付方式。`
        : `请查询订单 ${sample.order_id} 的状态和商品明细。`;
  void send(base + query);
}

onMounted(async () => {
  try {
    health.value = await api.health();
    connected.value = true;
    samples.value = (await api.samples()).samples;
    refs.value = (await api.sessions()).sessions;
    const current =
      refs.value.find((r) => r.id === props.initialId) || refs.value[0];
    if (current) await openSession(current);
    else await createSession();
    const intent = sessionStorage.getItem("retail.order.intent");
    sessionStorage.removeItem("retail.order.intent");
    if (intent && props.initialId) await send(intent);
  } catch (e) {
    error.value = `无法连接服务：${(e as Error).message}`;
  }
});
</script>

<template>
  <div class="workspace">
    <aside class="sidebar">
      <a class="brand" href="/" aria-label="Retail Desk 首页"
        ><span class="brand-icon"><ShoppingBag :size="23" /></span
        ><span
          >retail<span class="brand-light">desk</span
          ><small>智能零售服务工作台</small></span
        ></a
      >
      <button class="new-chat" @click="createSession" :disabled="busy">
        <Plus :size="17" /> 发起新咨询 <span>NEW</span>
      </button>
      <div class="nav-label">工作空间</div>
      <div class="nav-item selected">
        <MessageSquare :size="17" /> 客服助手 <span class="nav-dot"></span>
      </div>
      <div class="sidebar-section">
        <span>最近的咨询</span><History :size="14" />
      </div>
      <nav class="session-list" aria-label="历史会话">
        <button
          v-for="item in refs"
          :key="item.id"
          :class="['session-link', { active: item.id === active?.id }]"
          @click="openSession(item)"
          :disabled="busy"
        >
          <MessageSquare :size="14" /><span>{{ item.title }}</span>
        </button>
      </nav>
      <div class="sidebar-bottom">
        <div class="sandbox-note">
          <ShieldCheck :size="18" />
          <div>独立零售沙盒<small>基于 τ²-bench Retail 数据</small></div>
        </div>
        <a
          href="https://github.com/sierra-research/tau2-bench"
          target="_blank"
          rel="noreferrer"
          class="source-link"
          >查看 benchmark <ExternalLink :size="13"
        /></a>
        <div class="sidebar-profile">
          <div class="profile-avatar">R</div>
          <div>Retail Workspace<small>本地开发环境</small></div>
          <span class="online-dot"></span>
        </div>
      </div>
    </aside>

    <main class="main">
      <header class="topbar">
        <div class="breadcrumb">
          工作空间 <span>/</span> <strong>客服助手</strong>
        </div>
        <div class="topbar-right">
          <span :class="['connection', { offline: !connected }]"
            ><i></i>{{ connected ? "服务已连接" : "连接中" }}</span
          ><span class="mode-tag">{{
            health?.mode === "live" ? "真实模型" : "演示模式"
          }}</span
          ><button
            class="mobile-new icon-button"
            aria-label="发起新咨询"
            title="发起新咨询"
            @click="createSession"
            :disabled="busy"
          >
            <Plus :size="16" />
          </button>
        </div>
      </header>
      <div class="workspace-heading">
        <div>
          <div class="eyebrow"><span></span> RETAIL CUSTOMER SERVICE</div>
          <h1>客服助手 <span>Retail</span></h1>
          <p>理解需求，调用工具，让服务真正发生。</p>
        </div>
        <button
          class="icon-button"
          aria-label="刷新会话"
          title="刷新会话"
          @click="refresh"
          :disabled="busy"
        >
          <RefreshCw :size="18" />
        </button>
      </div>
      <div class="desk">
        <section class="conversation">
          <div class="conversation-header">
            <div>
              <span class="agent-avatar small"><Sparkles :size="16" /></span
              ><strong>Retail 智能助手</strong
              ><span class="available">在线</span>
            </div>
            <span class="powered">Powered by Deep Agents</span>
          </div>
          <div class="chat-scroll" ref="chatArea" aria-live="polite">
            <div v-if="!hasMessages" class="welcome">
              <div class="welcome-symbol">
                <ShoppingBag :size="30" /><span><Sparkles :size="14" /></span>
              </div>
              <div class="welcome-kicker">你的零售服务，向前一步</div>
              <h2>不止回答，也能帮你处理。</h2>
              <p>
                从了解订单到完成售后，我会获取所需信息，<br
                  class="desktop-break"
                />并在你确认后，安全地执行每一步操作。
              </p>
              <div class="capabilities">
                <span><Package :size="14" /> 订单查询</span
                ><span><RefreshCw :size="14" /> 退换与修改</span
                ><span><ShieldCheck :size="14" /> 确认后执行</span>
              </div>
              <div class="scenario-heading">
                <span>从一个场景开始</span
                ><small>使用 benchmark 中的虚拟客户</small>
              </div>
              <div class="scenario-grid">
                <button
                  v-for="(sample, i) in samples"
                  :key="sample.order_id"
                  @click="
                    scenario(
                      sample,
                      i === 0 ? 'cancel' : i === 1 ? 'return' : 'query',
                    )
                  "
                  :disabled="busy"
                >
                  <span :class="['scenario-icon', `variant-${i}`]"
                    ><component
                      :is="
                        i === 0 ? Package : i === 1 ? RefreshCw : ShoppingBag
                      "
                      :size="19" /></span
                  ><strong>{{
                    i === 0
                      ? "帮我取消订单"
                      : i === 1
                        ? "申请商品退货"
                        : "我的订单到哪了"
                  }}</strong>
                  <p>
                    {{
                      i === 0
                        ? "查看待处理订单，确认后取消"
                        : i === 1
                          ? "核对已送达商品，发起退货"
                          : "获取订单状态与商品明细"
                    }}
                  </p>
                  <span class="scenario-bottom"
                    >{{ sample.order_id }} <ArrowRight :size="15"
                  /></span>
                </button>
              </div>
              <div class="welcome-tip">
                <CircleHelp :size="14" />
                也可以直接输入需求。开始前，助手会先核验你的账户。
              </div>
            </div>
            <div v-else class="messages">
              <div class="date-divider"><span>本次咨询</span></div>
              <article
                v-for="message in session?.messages"
                :key="message.id"
                :class="['message', message.role]"
              >
                <span v-if="message.role === 'assistant'" class="agent-avatar"
                  ><Sparkles :size="18"
                /></span>
                <div class="message-main">
                  <div class="message-label">
                    {{ message.role === "assistant" ? "Retail 智能助手" : "你"
                    }}<span v-if="message.role === 'assistant'">客服</span>
                  </div>
                  <div class="bubble">{{ message.content }}</div>
                </div>
                <span v-if="message.role === 'user'" class="user-avatar"
                  ><UserRound :size="17"
                /></span>
              </article>
              <div v-if="busy && running" class="working">
                <LoaderCircle :size="15" class="spin" /><span>{{
                  running
                }}</span
                ><span class="working-dots">•••</span>
              </div>
              <article
                v-if="pending"
                class="approval-card"
                data-testid="approval-card"
              >
                <div class="approval-heading">
                  <span><ShieldCheck :size="21" /></span>
                  <div>
                    <small>需要你的确认</small>
                    <h3>{{ toolNames[pending.tool] || pending.tool }}</h3>
                  </div>
                  <span class="pending-label">尚未执行</span>
                </div>
                <p>请核对本次操作。确认后，以下变更将保存到零售沙盒。</p>
                <div class="approval-target">
                  <Package :size="16" /><strong>{{
                    pending.args.order_id || pending.args.user_id
                  }}</strong
                  ><span>{{
                    pending.before.order
                      ? `${pending.before.order.items.length} 件商品`
                      : "客户资料"
                  }}</span>
                </div>
                <div class="diff-list">
                  <div
                    v-for="change in changes(pending)"
                    :key="change.key"
                    class="diff-row"
                  >
                    <span>{{ change.key }}</span>
                    <div>
                      <pre>{{ change.before }}</pre>
                      <ArrowRight :size="14" />
                      <pre class="diff-after">{{ change.after }}</pre>
                    </div>
                  </div>
                </div>
                <details class="technical">
                  <summary>操作与参数明细 <ChevronDown :size="13" /></summary>
                  <pre
                    >{{ pending.tool }}
{{ json(pending.args) }}</pre
                  >
                </details>
                <p class="approval-note">
                  退款与邮件为 benchmark 模拟记录，不会连接真实支付或发送邮件。
                </p>
                <div class="approval-actions">
                  <button @click="decide(false)" :disabled="busy">
                    <X :size="15" />取消操作</button
                  ><button
                    class="primary"
                    @click="decide(true)"
                    :disabled="busy"
                  >
                    <Check :size="16" />确认执行
                  </button>
                </div>
              </article>
              <div v-if="session?.transferred" class="transfer-note">
                <Headphones
                  :size="17"
                />已记录人工转接，请新建会话继续使用助手。
              </div>
            </div>
          </div>
          <div class="composer-area">
            <div v-if="error" role="alert" class="error-banner">
              <span>{{ error }}</span
              ><button aria-label="关闭错误提示" @click="error = ''">
                <X :size="15" />
              </button>
            </div>
            <div v-if="pending" class="composer-hint">
              <ShieldCheck :size="14" /> 请先确认或取消上方操作，再继续咨询。
            </div>
            <form class="composer" @submit.prevent="send()">
              <textarea
                v-model="input"
                aria-label="输入咨询内容"
                :disabled="busy || !!pending || !!session?.transferred"
                placeholder="描述你的需求，例如：帮我查询订单状态…"
                rows="2"
                @keydown.enter.exact.prevent="send()"
              ></textarea>
              <div class="composer-footer">
                <span
                  ><ShieldCheck :size="13" /> 你的每一次变更，都由你确认</span
                ><button
                  type="submit"
                  aria-label="发送消息"
                  :disabled="
                    busy || !input.trim() || !!pending || !!session?.transferred
                  "
                >
                  <LoaderCircle v-if="busy" :size="18" class="spin" /><ArrowUp
                    v-else
                    :size="18"
                  />
                </button>
              </div>
            </form>
            <div class="composer-caption">
              <span>{{
                health?.mode === "demo"
                  ? "离线演示 · 支持查询、取消与整单退货；完整操作请启用真实模型"
                  : "AI 可能出错，请核对重要信息与操作明细"
              }}</span
              ><span>Enter 发送 · Shift + Enter 换行</span>
            </div>
          </div>
        </section>

        <aside class="context-panel">
          <div class="context-tabs">
            <button
              :class="{ active: tab === 'customer' }"
              @click="tab = 'customer'"
            >
              <UserRound :size="15" />客户与订单</button
            ><button
              :class="{ active: tab === 'tools' }"
              @click="tab = 'tools'"
            >
              <Terminal :size="15" />工具轨迹<span v-if="toolCount">{{
                toolCount
              }}</span>
            </button>
          </div>
          <div v-if="tab === 'customer'" class="context-content">
            <div class="section-heading">
              <span>客户档案</span
              ><span v-if="customer" class="verified"
                ><ShieldCheck :size="12" />已核验</span
              ><span v-else class="muted-label">待核验</span>
            </div>
            <div v-if="!customer" class="identity-empty">
              <div><UserRound :size="25" /></div>
              <strong>从认识客户开始</strong>
              <p>核验账户后，客户资料与相关订单<br />会自动出现在这里。</p>
              <span><ShieldCheck :size="12" />仅可查看当前客户的数据</span>
            </div>
            <div v-else class="customer-card">
              <div class="customer-top">
                <span class="customer-avatar"
                  >{{ customer.name.first_name[0]
                  }}{{ customer.name.last_name[0] }}</span
                >
                <div>
                  <h3>
                    {{ customer.name.first_name }} {{ customer.name.last_name }}
                  </h3>
                  <p>{{ customer.user_id }}</p>
                </div>
              </div>
              <div class="customer-field">
                <span>账户邮箱</span><strong>{{ customer.email }}</strong>
              </div>
              <div class="customer-field">
                <span>默认地址</span
                ><strong
                  >{{ customer.address.address1 }} {{ customer.address.address2
                  }}<br />{{ customer.address.city }},
                  {{ customer.address.state }}
                  {{ customer.address.zip }}</strong
                >
              </div>
              <details class="payment-details">
                <summary>
                  支付方式
                  <span
                    >{{ Object.keys(customer.payment_methods).length }} 种
                    <ChevronDown :size="12"
                  /></span>
                </summary>
                <div
                  v-for="(payment, id) in customer.payment_methods"
                  :key="id"
                >
                  <strong
                    >{{ payment.source }}
                    {{
                      payment.last_four ? `•••• ${payment.last_four}` : ""
                    }}</strong
                  ><small
                    >{{ id }}
                    {{
                      payment.balance !== undefined
                        ? money(payment.balance)
                        : ""
                    }}</small
                  >
                </div>
              </details>
            </div>
            <div class="section-heading order-section">
              <span>关联订单</span
              ><span class="count-pill">{{ orders.length }}</span>
            </div>
            <div v-if="!orders.length" class="orders-empty">
              <Package :size="28" /><span>等待获取订单</span>
              <p>查询与变更将同步到这里</p>
            </div>
            <details
              v-for="order in orders"
              :key="order.order_id"
              class="order-card"
              :open="orders.length === 1"
            >
              <summary>
                <span class="order-icon"><Package :size="16" /></span
                ><span
                  ><strong>{{ order.order_id }}</strong
                  ><small
                    >{{ order.items.length }} 件商品 ·
                    {{ money(total(order)) }}</small
                  ></span
                ><span
                  :class="['status-tag', order.status.replaceAll(' ', '-')]"
                  >{{ labels[order.status] || order.status }}</span
                ><ChevronDown :size="14" />
              </summary>
              <div class="order-body">
                <div
                  v-for="(item, index) in order.items"
                  :key="`${item.item_id}-${index}`"
                  class="order-item"
                >
                  <ShoppingBag :size="16" />
                  <div>
                    <strong>{{ item.name }}</strong>
                    <p>{{ Object.values(item.options).join(" · ") }}</p>
                    <small>{{ item.item_id }}</small>
                  </div>
                  <span>{{ money(item.price) }}</span>
                </div>
                <div class="order-address">
                  <span>配送至</span>
                  <p>
                    {{ order.address.address1 }}, {{ order.address.city }},
                    {{ order.address.state }} {{ order.address.zip }}
                  </p>
                </div>
                <div v-if="order.fulfillments.length" class="order-address">
                  <span>物流单号</span>
                  <p v-for="(f, i) in order.fulfillments" :key="i">
                    {{ f.tracking_id.join(", ") }}
                  </p>
                </div>
                <details class="technical">
                  <summary>完整订单记录</summary>
                  <pre>{{ json(order) }}</pre>
                </details>
              </div>
            </details>
            <div class="trust-card">
              <span><Zap :size="17" /></span>
              <div>
                <strong>工具驱动的真实操作</strong>
                <p>
                  查询补充上下文，确认后更新数据。<br />每次操作都留有可追溯记录。
                </p>
              </div>
            </div>
          </div>
          <div v-else class="context-content tools-content">
            <div class="section-heading">
              <span>执行记录</span><span class="muted-label">实时更新</span>
            </div>
            <div
              v-if="!events.length && !liveTools.length"
              class="orders-empty"
            >
              <Terminal :size="28" /><span>每一步，都清晰可见</span>
              <p>身份核验、订单查询与变更<br />会按执行顺序记录在这里</p>
            </div>
            <div class="timeline">
              <article
                v-for="event in events"
                :key="event.id"
                :class="['trace', event.kind]"
              >
                <span class="trace-dot"
                  ><Check
                    v-if="event.kind === 'decision' && event.data.approved"
                    :size="11" /><Database v-else :size="11"
                /></span>
                <div class="trace-heading">
                  <strong>{{
                    event.kind === "tool"
                      ? toolNames[event.data.name] || event.data.name
                      : event.kind === "decision"
                        ? event.data.approved
                          ? "已确认并提交"
                          : "已取消操作"
                        : "请求未完成"
                  }}</strong
                  ><span v-if="event.data.duration_ms !== undefined"
                    >{{ event.data.duration_ms }} ms</span
                  >
                </div>
                <p>
                  {{
                    event.kind === "tool"
                      ? event.data.name
                      : new Date(event.created_at).toLocaleTimeString()
                  }}
                </p>
                <span
                  v-if="event.kind === 'tool'"
                  :class="['trace-status', { failed: event.data.ok === false }]"
                  >{{
                    event.data.ok === false
                      ? "执行受阻"
                      : resultStatus(event.data.result) ===
                          "awaiting_confirmation"
                        ? "待用户确认"
                        : "调用成功"
                  }}</span
                >
                <details>
                  <summary>查看详情 <ChevronDown :size="11" /></summary>
                  <pre>{{ json(event.data) }}</pre>
                </details>
              </article>
              <article
                v-for="(event, i) in liveTools"
                :key="`live-${i}`"
                class="trace"
              >
                <span class="trace-dot"
                  ><LoaderCircle
                    v-if="event.type === 'tool_start'"
                    class="spin"
                    :size="11" /><Check v-else :size="11" /></span
                ><strong>{{ toolNames[event.name] || event.name }}</strong>
                <p>
                  {{
                    event.type === "tool_start"
                      ? "正在调用…"
                      : event.ok
                        ? "调用完成"
                        : "执行受阻"
                  }}
                </p>
              </article>
            </div>
          </div>
          <div class="context-footer">
            <span><CheckCheck :size="14" />{{ toolCount }} 次工具调用</span
            ><span><ArrowDown :size="13" />{{ writes }} 次变更</span>
          </div>
        </aside>
      </div>
      <footer class="workspace-footer">
        <span
          ><span class="tiny-dot"></span> RETAIL DESK
          <i> / </i> 工具连接服务，行动带来价值。</span
        ><span>Vue 3 <i>·</i> FastAPI <i>·</i> Deep Agents</span>
      </footer>
    </main>
  </div>
</template>
