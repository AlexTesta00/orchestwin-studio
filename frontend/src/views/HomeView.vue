<script setup lang="ts">
const foundationCapabilities = [
  "Typed FastAPI backend",
  "Versioned health API",
  "Verified Vue frontend workspace",
] as const;
</script>

<template>
  <section class="page" aria-labelledby="overview-title">
    <header class="page__header">
      <p class="page__eyebrow">Human-governed Agentic UCD</p>

      <h1 id="overview-title">OrchesTwin Studio</h1>

      <p class="page__lead">Frontend workspace operational</p>

      <p>
        The current foundation provides independently verifiable backend and frontend workspaces.
        Project workflows will be introduced in later sprints.
      </p>
    </header>

    <section aria-labelledby="foundation-capabilities-title">
      <h2 id="foundation-capabilities-title">Foundation capabilities</h2>

      <ul class="capability-grid">
        <li v-for="capability in foundationCapabilities" :key="capability" class="capability-card">
          {{ capability }}
        </li>
      </ul>
    </section>
  </section>
</template>
