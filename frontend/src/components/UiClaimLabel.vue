<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

const props = defineProps<{ kind: "hypothesis" | "proof" }>();

const { t } = useI18n({ useScope: "global" });

const classes = computed(() =>
  props.kind === "hypothesis"
    ? {
        chip: "border-hypothesis-line bg-hypothesis-bg text-hypothesis",
        dot: "border-2 border-hypothesis bg-transparent",
      }
    : {
        chip: "border-proof-line bg-proof-bg text-proof",
        dot: "border-2 border-proof bg-proof",
      },
);
</script>

<template>
  <span
    :class="[
      'inline-flex items-center gap-2 rounded-pill border px-2.5 py-1 text-xs font-semibold',
      classes.chip,
    ]"
    :data-claim="kind"
  >
    <span :class="['inline-block h-2.5 w-2.5 rounded-full', classes.dot]" aria-hidden="true" />
    <span>{{ t(`ui.claim.${kind}`) }}</span>
  </span>
</template>
