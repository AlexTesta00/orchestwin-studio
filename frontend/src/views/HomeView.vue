<script setup lang="ts">
import { useI18n } from "vue-i18n";

const capabilityKeys = ["backend", "api", "frontend"] as const;

const { t } = useI18n({
  useScope: "global",
});
</script>

<template>
  <section class="page" aria-labelledby="overview-title">
    <header class="page__header">
      <p class="page__eyebrow">
        {{ t("overview.eyebrow") }}
      </p>

      <h1 id="overview-title">
        {{ t("overview.title") }}
      </h1>

      <p class="page__lead">
        {{ t("overview.status") }}
      </p>

      <p>
        {{ t("overview.description") }}
      </p>
    </header>

    <section aria-labelledby="foundation-capabilities-title">
      <h2 id="foundation-capabilities-title">
        {{ t("overview.capabilitiesTitle") }}
      </h2>

      <ul class="capability-grid">
        <li v-for="capabilityKey in capabilityKeys" :key="capabilityKey" class="capability-card">
          {{ t(`overview.capabilities.${capabilityKey}`) }}
        </li>
      </ul>
    </section>
  </section>
</template>
