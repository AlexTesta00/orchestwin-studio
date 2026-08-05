<script setup lang="ts">
import { useI18n } from "vue-i18n";

const { t } = useI18n({
  useScope: "global",
});
</script>

<template>
  <section class="page" aria-labelledby="projects-title">
    <header class="page__header">
      <p class="page__eyebrow">
        {{ t("projects.eyebrow") }}
      </p>

      <h1 id="projects-title">
        {{ t("projects.title") }}
      </h1>

      <p class="page__lead">
        {{ t("projects.description") }}
      </p>
    </header>

    <section class="empty-state" aria-labelledby="projects-empty-title">
      <h2 id="projects-empty-title">
        {{ t("projects.emptyTitle") }}
      </h2>

      <p>
        {{ t("projects.emptyDescription") }}
      </p>
    </section>
  </section>
</template>
