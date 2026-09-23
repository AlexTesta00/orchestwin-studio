<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

const props = withDefaults(
  defineProps<{ current: number; total: number; reached?: number | undefined }>(),
  { reached: undefined },
);

const { t } = useI18n({ useScope: "global" });

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
    <span class="font-mono text-xs tracking-wide text-ink-3 uppercase">{{ text }}</span>
    <div
      class="grid gap-1"
      :style="{ gridTemplateColumns: `repeat(${total}, minmax(0, 1fr))` }"
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
        :class="[
          'h-1.5 rounded-pill',
          stateOf(step) === 'done'
            ? 'bg-action'
            : stateOf(step) === 'current'
              ? 'bg-action-soft-line'
              : 'bg-bar-track-end',
        ]"
        :data-step-state="stateOf(step)"
      />
    </div>
  </div>
</template>
