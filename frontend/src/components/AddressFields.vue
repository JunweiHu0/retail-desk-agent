<script setup lang="ts">
import { addressFieldKeys, addressFieldLabel } from '../retail'
import { t } from '../i18n'
import type { Address } from '../types'

const address = defineModel<Address>({ required: true })
</script>

<template>
  <div class="address-fields">
    <label v-for="key in addressFieldKeys" :key="key" class="field" :class="{ 'address-wide': key === 'address1' || key === 'address2' }">
      <span>{{ addressFieldLabel(key) }} <small v-if="key === 'address2'">{{ t('选填', 'optional') }}</small></span>
      <input v-model.trim="address[key]" :name="key" :required="key !== 'address2'" maxlength="200" />
    </label>
  </div>
</template>
