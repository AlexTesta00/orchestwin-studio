<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(
  defineProps<{
    tone?:
      | "default"
      | "elevated"
      | "dense"
      | "soft"
      | "table"
      | "hypothesis"
      | "success"
      | "failure"
      | undefined;
  }>(),
  { tone: "default" },
);

const tones = {
  default: "rounded-card border border-line bg-surface p-6 shadow-card sm:p-7",
  elevated: "rounded-card border border-line-strong bg-surface p-7 shadow-decision",
  dense: "rounded-panel border border-line bg-surface px-[26px] py-[22px] shadow-card",
  soft: "rounded-panel border border-line-soft bg-surface-2 p-5",
  table: "overflow-hidden rounded-card border border-line bg-surface shadow-card",
  hypothesis:
    "rounded-card border border-hypothesis-line bg-hypothesis-bg p-6 text-hypothesis-text sm:p-7",
  success: "rounded-card border border-ok-line bg-ok-bg p-6 text-ok-dark",
  failure: "rounded-card border border-fail-line bg-fail-bg p-6 text-fail-dark",
};

const classes = computed(() => tones[props.tone]);
</script>

<template>
  <div :class="classes">
    <slot />
  </div>
</template>
