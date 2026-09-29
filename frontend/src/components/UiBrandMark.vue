<script setup lang="ts">
import { computed } from "vue";

import { useSurface, type SurfaceContext } from "./UiSurface.vue";

const props = withDefaults(
  defineProps<{
    size?: number | undefined;
    title?: string;
    wordmark?: boolean | undefined;
    surface?: SurfaceContext | undefined;
  }>(),
  { size: 36, title: "OrchesTwin", wordmark: false, surface: undefined },
);

const context = useSurface(() => props.surface);
const night = computed(() => context.value === "night");
const height = computed(() => Math.round(((props.size * 30) / 36) * 100) / 100);
</script>

<template>
  <span class="inline-flex items-center gap-2.5" :data-surface-context="context">
    <svg
      :width="size"
      :height="height"
      viewBox="0 0 36 30"
      :role="wordmark ? undefined : 'img'"
      :aria-label="wordmark ? undefined : title"
      :aria-hidden="wordmark ? 'true' : undefined"
      focusable="false"
      data-testid="brand-mark"
    >
      <rect width="36" height="30" rx="11" :class="night ? 'fill-on-night' : 'fill-ink'" />
      <rect
        x="4.5"
        y="5"
        width="27"
        height="20"
        rx="7.5"
        class="fill-night"
        :class="night ? 'stroke-night' : 'stroke-on-night/14'"
        stroke-width="1"
      />
      <rect x="11" y="10.5" width="4" height="9" rx="2" class="fill-petrol-on-night" />
      <rect x="21" y="10.5" width="4" height="9" rx="2" class="fill-petrol-on-night" />
    </svg>
    <span
      v-if="wordmark"
      class="flex flex-col items-start gap-[3px] leading-none"
      data-testid="brand-wordmark"
    >
      <span
        class="font-display text-sm leading-none font-light tracking-wordmark uppercase"
        :class="night ? 'text-on-night' : 'text-ink'"
      >
        OrchesTwin
      </span>
      <span
        class="font-mono text-[9px] leading-none tracking-[0.32em] uppercase"
        :class="night ? 'text-on-night-3' : 'text-ink-3'"
      >
        Studio
      </span>
    </span>
  </span>
</template>
