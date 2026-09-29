<script setup lang="ts">
import { computed } from "vue";

import { useSurface, type SurfaceContext } from "./UiSurface.vue";

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
    surface?: SurfaceContext | undefined;
  }>(),
  { tone: "default", surface: undefined },
);

const context = useSurface(() => props.surface);

const tones = {
  light: {
    default: "rounded-tile border border-line bg-surface p-6 shadow-card sm:p-7",
    elevated: "rounded-tile border border-line-strong bg-surface p-7 shadow-decision",
    dense: "rounded-panel border border-line bg-surface px-[26px] py-[22px] shadow-card",
    soft: "rounded-panel border border-line-soft bg-surface-2 p-5",
    table: "overflow-hidden rounded-tile border border-line bg-surface shadow-card",
    hypothesis:
      "rounded-tile border-[1.5px] border-dashed border-hypothesis/60 bg-hypothesis-bg p-6 text-hypothesis-text sm:p-7",
    success: "rounded-tile border border-ok-line bg-ok-bg p-6 text-ok-dark",
    failure: "rounded-tile border border-fail-line bg-fail-bg p-6 text-fail-dark",
  },
  night: {
    default: "rounded-tile border border-night-line bg-night-raised p-6 sm:p-7",
    elevated: "rounded-tile border border-night-line-strong bg-night-panel p-7 shadow-bar",
    dense: "rounded-panel border border-night-line bg-night-raised px-[26px] py-[22px]",
    soft: "rounded-panel border border-on-night/8 bg-on-night/3 p-5",
    table: "overflow-hidden rounded-tile border border-night-line bg-night-raised",
    hypothesis:
      "rounded-tile border-[1.5px] border-dashed border-violet-on-night/70 bg-violet-on-night/6 p-6 sm:p-7",
    success: "rounded-tile border border-petrol-on-night/60 bg-petrol-on-night/8 p-6",
    failure:
      "rounded-tile border border-fail-on-night/40 bg-fail-on-night/8 p-6 text-fail-on-night",
  },
};

const classes = computed(() => tones[context.value][props.tone]);
</script>

<template>
  <div :class="classes">
    <slot />
  </div>
</template>
