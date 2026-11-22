<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { ArrowRight, LoaderCircle, ShoppingBag } from 'lucide-vue-next'
import LanguageSelect from './LanguageSelect.vue'
import { t } from '../i18n'
import { api, errorText } from '../api'
import type { Customer } from '../types'

defineProps<{ notice?: string }>()
const emit = defineEmits<{ authenticated: [customer: Customer] }>()
const signup = ref(false)
const busy = ref(false)
const error = ref('')
const form = reactive({ email: '', password: '', first_name: '', last_name: '' })
const demoAccounts = computed(() => [
  { name: t('李明', 'Ming Li'), id: 'li.ming' },
  { name: t('王芳', 'Fang Wang'), id: 'wang.fang' },
  { name: t('张伟', 'Wei Zhang'), id: 'zhang.wei' },
  { name: t('回放', 'Replay'), id: 'replay', password: 'Replay@2026!' },
])
const demoPassword = 'Demo@Retail2026!'

function useDemo(sample: { id: string; password?: string }) {
  signup.value = false
  error.value = ''
  form.email = sample.id + '@retail-demo.example.com'
  form.password = sample.password ?? demoPassword
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
    error.value = errorText(reason, t('暂时无法连接，请稍后重试。', 'Could not connect. Please try again later.'))
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main class="login-screen">
    <div class="login-layout">
      <a class="brand login-brand" href="." :aria-label="t('Retail Desk 购物服务中心', 'Retail Desk customer service')">
        <span class="brand-mark"><ShoppingBag :size="23" :stroke-width="2" /></span>
        <span class="wordmark">Retail<span>Desk</span></span>
      </a>
      <LanguageSelect />
      <section class="login-intro" aria-labelledby="login-intro-title">
        <h2 id="login-intro-title">{{ t('订单与售后', 'Orders and after-sales') }}<br class="login-intro-break" />{{ t('服务中心', 'service center') }}</h2>
        <p>{{ t('查订单与物流，管理账户资料，联系在线客服。', 'Track orders and deliveries, manage your profile, and talk to support.') }}</p>
      </section>

      <section class="login-card" aria-labelledby="login-title">
        <h1 id="login-title">{{ signup ? t('创建账户', 'Create an account') : t('登录账户', 'Sign in') }}</h1>
        <form @submit.prevent="submit">
          <fieldset :disabled="busy">
            <div v-if="signup" class="name-fields">
              <label class="field">{{ t('姓', 'Last name') }}<input v-model.trim="form.last_name" name="family-name" autocomplete="family-name" maxlength="60" required /></label>
              <label class="field">{{ t('名', 'First name') }}<input v-model.trim="form.first_name" name="given-name" autocomplete="given-name" maxlength="60" required /></label>
            </div>
            <label class="field">{{ t('邮箱', 'Email') }}
              <input v-model.trim="form.email" name="email" type="email" autocomplete="username" placeholder="name@example.com" maxlength="254" required />
            </label>
            <label class="field">{{ t('密码', 'Password') }}
              <input v-model="form.password" name="password" type="password" :autocomplete="signup ? 'new-password' : 'current-password'"
                :minlength="signup ? 10 : 1" maxlength="128" :placeholder="signup ? t('至少 10 个字符', 'At least 10 characters') : t('输入账户密码', 'Enter your password')" required />
            </label>
            <p v-if="error || notice" class="notice login-error" role="alert">{{ error || notice }}</p>
            <button type="submit" class="button primary login-submit">
              {{ busy ? t('正在处理…', 'Working…') : signup ? t('注册并登录', 'Create account and sign in') : t('登录', 'Sign in') }}
              <LoaderCircle v-if="busy" class="spin" :size="17" /><ArrowRight v-else :size="17" />
            </button>
          </fieldset>
        </form>
        <p class="signup-link">
          {{ signup ? t('已有账户？', 'Already have an account?') : t('还没有账户？', 'New here?') }}
          <button type="button" class="text-button" :disabled="busy" @click="toggleSignup">{{ signup ? t('返回登录', 'Back to sign in') : t('注册账户', 'Create an account') }}</button>
        </p>
        <section class="demo-accounts" :aria-label="t('体验演示账户', 'Demo accounts')">
          <div class="demo-heading">
            <h2>{{ t('演示账户', 'Demo accounts') }}</h2><p>{{ t('点选后自动填入邮箱和密码', 'Select one to fill the email and password') }}</p>
          </div>
          <div class="demo-buttons">
            <button v-for="sample in demoAccounts" :key="sample.id" type="button" :disabled="busy"
              :aria-label="t('填入演示账户 ', 'Fill demo account ') + sample.name" @click="useDemo(sample)">{{ sample.name }}</button>
          </div>
        </section>
      </section>
    </div>
  </main>
</template>
