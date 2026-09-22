<script setup lang="ts">
import { useI18n } from "vue-i18n";

import UiCard from "./UiCard.vue";

defineProps<{ rule: string; title: string; what: string; where: string; change: string }>();

const { t } = useI18n({ useScope: "global" });
</script>

<template>
  <UiCard tone="failure">
    <div class="flex flex-wrap items-center gap-3">
      <span
        class="inline-flex items-center gap-1.5 rounded-pill border border-fail-line bg-surface px-2.5 py-1 text-xs font-semibold text-fail-dark"
      >
        <span aria-hidden="true">!</span>
        {{ t("ui.findings.chip") }}
      </span>
      <code class="font-mono text-xs text-fail-dark" data-testid="finding-rule">{{ rule }}</code>
    </div>
    <h3 class="mt-3 text-lg font-semibold tracking-block">{{ title }}</h3>
    <dl
      class="mt-3 grid grid-cols-[minmax(0,1fr)] gap-y-2 text-[15px] sm:grid-cols-[180px_minmax(0,1fr)]"
    >
      <dt class="font-semibold">{{ t("ui.findings.what") }}</dt>
      <dd>{{ what }}</dd>
      <dt class="font-semibold">{{ t("ui.findings.where") }}</dt>
      <dd>{{ where }}</dd>
      <dt class="font-semibold">{{ t("ui.findings.change") }}</dt>
      <dd>{{ change }}</dd>
    </dl>
    <div v-if="$slots.action" class="mt-5">
      <slot name="action" />
    </div>
  </UiCard>
</template>
