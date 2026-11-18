<script setup lang="ts">
import { reactive, ref } from 'vue'
import { ArrowRight, LoaderCircle, ShieldCheck, UserRound } from 'lucide-vue-next'
import { api, errorText } from '../api'
import type { Customer } from '../types'

defineProps<{ notice?: string }>()
const emit = defineEmits<{ authenticated: [customer: Customer] }>()
const signup = ref(false)
const busy = ref(false)
const error = ref('')
const form = reactive({ email: '', password: '', first_name: '', last_name: '' })
const demoAccounts = [
  { name: '李明', id: 'li.ming' },
  { name: '王芳', id: 'wang.fang' },
  { name: '张伟', id: 'zhang.wei' },
]
const demoPassword = 'Demo@Retail2026!'

function useDemo(id: string) {
  signup.value = false
  error.value = ''
  form.email = id + '@retail-demo.example.com'
  form.password = demoPassword
}

function toggleSignup() {
  signup.value = !signup.value
  error.value = ''
  form.password = ''
}

async function submit() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    const email = form.email.trim()
    if (signup.value) {
      await api.register({
        email, password: form.password, first_name: form.first_name.trim(), last_name: form.last_name.trim(),
      })
      signup.value = false
    }
    const customer = await api.login(email, form.password)
    form.password = ''
    emit('authenticated', customer)
  } catch (reason) {
    error.value = errorText(reason, '暂时无法连接，请稍后重试。')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main class="frame login-layout">
    <section class="login-hero" aria-label="购物服务中心">
      <h2>一站处理<br />订单与售后</h2>
      <p>查看订单状态、管理账户资料，或向客服咨询。</p>
      <div class="login-privacy"><ShieldCheck :size="17" />订单和资料变更由你确认</div>
    </section>
    <section class="surface login-card" aria-labelledby="login-title">
      <h1 id="login-title">{{ signup ? '创建账户' : '登录账户' }}</h1>
      <p class="login-lead">{{ signup ? '填写邮箱和姓名，创建购物服务账户。' : '登录后查看你的订单和咨询记录。' }}</p>
      <form @submit.prevent="submit">
        <fieldset :disabled="busy">
          <div v-if="signup" class="name-fields">
            <label class="field">姓<input v-model.trim="form.last_name" name="family-name" autocomplete="family-name" maxlength="60" required /></label>
            <label class="field">名<input v-model.trim="form.first_name" name="given-name" autocomplete="given-name" maxlength="60" required /></label>
          </div>
          <label class="field">邮箱
            <input v-model.trim="form.email" name="email" type="email" autocomplete="username" placeholder="name@example.com" maxlength="254" required />
          </label>
          <label class="field">密码
            <input v-model="form.password" name="password" type="password" :autocomplete="signup ? 'new-password' : 'current-password'"
              :minlength="signup ? 10 : 1" maxlength="128" :placeholder="signup ? '至少 10 个字符' : '输入账户密码'" required />
          </label>
          <p v-if="error || notice" class="notice login-error" role="alert">{{ error || notice }}</p>
          <button type="submit" class="button primary login-submit">
            {{ busy ? '正在处理…' : signup ? '注册并登录' : '登录' }}
            <LoaderCircle v-if="busy" class="spin" :size="17" /><ArrowRight v-else :size="17" />
          </button>
        </fieldset>
      </form>
      <p class="signup-link">
        {{ signup ? '已有账户？' : '还没有账户？' }}
        <button class="text-button" :disabled="busy" @click="toggleSignup">{{ signup ? '返回登录' : '注册账户' }}</button>
      </p>
      <section class="demo-accounts" aria-label="体验演示账户">
        <h2>体验演示账户</h2>
        <p>选择一个账户，自动填入邮箱和密码。</p>
        <div class="demo-buttons">
          <button v-for="sample in demoAccounts" :key="sample.id" type="button" :disabled="busy"
            :aria-label="'填入演示账户 ' + sample.name" @click="useDemo(sample.id)">
            <UserRound :size="15" />{{ sample.name }}
          </button>
        </div>
      </section>
    </section>
  </main>
</template>
