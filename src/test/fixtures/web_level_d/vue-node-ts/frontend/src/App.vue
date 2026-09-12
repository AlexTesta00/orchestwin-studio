<script setup lang="ts">
import { ref } from 'vue';
import { countFromPayload } from './counter';
const count = ref(0);
const error = ref('');
const pending = ref(false);
async function incrementCounter() {
  pending.value = true;
  try {
    const response = await fetch('/api/next?value=' + count.value);
    if (!response.ok) throw new Error('Counter service returned ' + response.status);
    count.value = countFromPayload(await response.json());
  } catch (failure) {
    error.value = failure instanceof Error ? failure.message : 'Counter request failed';
    throw failure;
  } finally {
    pending.value = false;
  }
}
</script>

<template>
  <main>
    <h1>Vue and Express counter</h1>
    <button id="increment" type="button" :disabled="pending" @click="incrementCounter">Increment counter</button>
    <p>Count: <output id="count" aria-live="polite">{{ count }}</output></p>
    <p v-if="error" role="alert">{{ error }}</p>
  </main>
</template>
