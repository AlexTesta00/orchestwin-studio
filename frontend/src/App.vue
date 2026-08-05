<script setup lang="ts">
const bootstrapStatus = "Frontend workspace operational";
</script>

<template>
  <main class="app-shell" aria-labelledby="app-title">
    <section class="status-panel">
      <p class="eyebrow">Human-governed Agentic UCD</p>

      <h1 id="app-title">OrchesTwin Studio</h1>

      <p class="status-copy">
        {{ bootstrapStatus }}
      </p>
    </section>
  </main>
</template>