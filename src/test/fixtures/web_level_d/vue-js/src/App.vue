<script setup>
import { ref } from 'vue';
import { increment } from './counter';
const count = ref(0);
function incrementCounter() { count.value = increment(count.value); }
</script>

<template>
  <main>
    <h1>Vue counter</h1>
    <button id="increment" type="button" @click="incrementCounter">Increment counter</button>
    <p>Count: <output id="count" aria-live="polite">{{ count }}</output></p>
  </main>
</template>
