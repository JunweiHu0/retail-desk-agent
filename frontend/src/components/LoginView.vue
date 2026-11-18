<script setup lang="ts">
import { reactive, ref } from 'vue'
import { ArrowRight, LoaderCircle, ShoppingBag } from 'lucide-vue-next'
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
  <main class="login-screen">
    <div class="login-layout">
      <a class="brand login-brand" href="." aria-label="Retail Desk 购物服务中心">
        <span class="brand-mark"><ShoppingBag :size="23" :stroke-width="2" /></span>
        <span class="wordmark">Retail<span>Desk</span></span>
      </a>
      <section class="login-intro" aria-labelledby="login-intro-title">
        <h2 id="login-intro-title">订单与售后<br class="login-intro-break" />服务中心</h2>
        <p>查订单与物流，管理账户资料，联系在线客服。</p>
      </section>

      <section class="login-card" aria-labelledby="login-title">
        <h1 id="login-title">{{ signup ? '创建账户' : '登录账户' }}</h1>
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
          <button type="button" class="text-button" :disabled="busy" @click="toggleSignup">{{ signup ? '返回登录' : '注册账户' }}</button>
        </p>
        <section class="demo-accounts" aria-label="体验演示账户">
          <div class="demo-heading">
            <h2>演示账户</h2><p>点选后自动填入邮箱和密码</p>
          </div>
          <div class="demo-buttons">
            <button v-for="sample in demoAccounts" :key="sample.id" type="button" :disabled="busy"
              :aria-label="'填入演示账户 ' + sample.name" @click="useDemo(sample.id)">{{ sample.name }}</button>
          </div>
        </section>
      </section>
    </div>
  </main>
</template>
