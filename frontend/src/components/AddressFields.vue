<script setup lang="ts">
import { addressFields } from '../retail'
import type { Address } from '../types'

const address = defineModel<Address>({ required: true })
</script>

<template>
  <div class="address-fields">
    <label v-for="(label, key) in addressFields" :key="key" class="field" :class="{ 'address-wide': key === 'address1' || key === 'address2' }">
      <span>{{ label }} <small v-if="key === 'address2'">选填</small></span>
      <input v-model.trim="address[key]" :name="key" :required="key !== 'address2'" maxlength="200" />
    </label>
  </div>
</template>
