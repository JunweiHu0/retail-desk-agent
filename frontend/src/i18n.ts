import { computed, ref } from 'vue'

export type Locale = 'zh' | 'en'

function initialLocale(): Locale {
  try {
    return localStorage.getItem('retail-locale') === 'en' ? 'en' : 'zh'
  } catch {
    return 'zh'
  }
}

export const locale = ref<Locale>(initialLocale())

export function setLocale(next: Locale) {
  locale.value = next
  try {
    localStorage.setItem('retail-locale', next)
  } catch {
    // Storage can be unavailable in private windows; the toggle still works.
  }
  document.documentElement.lang = next === 'en' ? 'en' : 'zh-CN'
}

export function t(zh: string, en: string): string {
  return locale.value === 'en' ? en : zh
}

export function useI18n() {
  return {
    locale: computed(() => locale.value),
    t,
    setLocale,
  }
}
