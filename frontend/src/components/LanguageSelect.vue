<script setup lang="ts">
import { locale, setLocale } from '../i18n'

function onchange(event: Event) {
  setLocale((event.target as HTMLSelectElement).value as 'zh' | 'en')
}
</script>

<template>
  <label class="language-select">
    <span class="sr-only">{{ locale === 'en' ? 'Language' : '语言' }}</span>
    <select :value="locale" aria-label="Language" @change="onchange">
      <option value="zh">中文</option>
      <option value="en">English</option>
    </select>
  </label>
</template>
