<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { useSurface, type SurfaceContext } from "./UiSurface.vue";

const props = withDefaults(
  defineProps<{
    current: number;
    total: number;
    reached?: number | undefined;
    surface?: SurfaceContext | undefined;
  }>(),
  { reached: undefined, surface: undefined },
);

const { t } = useI18n({ useScope: "global" });

const context = useSurface(() => props.surface);

const palettes = {
  light: { label: "text-ink-3", done: "bg-action", current: "bg-ink", pending: "bg-line" },
  night: {
    label: "text-on-night-3",
    done: "bg-petrol-on-night",
    current: "bg-on-night",
    pending: "bg-on-night/14",
  },
};

const palette = computed(() => palettes[context.value]);
const reachedStep = computed(() => Math.max(props.reached ?? props.current, props.current));
const steps = computed(() => Array.from({ length: props.total }, (_, index) => index + 1));
const text = computed(() => t("ui.progress.step", { n: props.current, total: props.total }));

function stateOf(step: number): "done" | "current" | "pending" {
  if (step === props.current) {
    return "current";
  }
  return step < reachedStep.value ? "done" : "pending";
}
</script>

<template>
  <div class="grid gap-2" data-testid="progress-bar">
    <span :class="['font-mono text-xs tracking-[0.08em] uppercase', palette.label]">
      {{ text }}
    </span>
    <div
      class="flex gap-1"
      role="progressbar"
      :aria-label="text"
      :aria-valuenow="current"
      aria-valuemin="1"
      :aria-valuemax="total"
      :aria-valuetext="text"
    >
      <span
        v-for="step in steps"
        :key="step"
        :class="['h-1 flex-1 rounded-[2px]', palette[stateOf(step)]]"
        :data-step-state="stateOf(step)"
      />
    </div>
  </div>
</template>
