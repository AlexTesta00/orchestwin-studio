<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import type { StepStatus } from "./UiStepper.vue";
import { useSurface, type SurfaceContext } from "./UiSurface.vue";

const props = withDefaults(
  defineProps<{
    step: number;
    total: number;
    title: string;
    description?: string | undefined;
    status?: StepStatus | undefined;
    as?: "h1" | "h2" | undefined;
    surface?: SurfaceContext | undefined;
  }>(),
  { description: "", status: undefined, as: "h1", surface: undefined },
);

const { t } = useI18n({ useScope: "global" });

const context = useSurface(() => props.surface);

const palettes = {
  light: {
    muted: "text-ink-3",
    chips: {
      current: { chip: "border-ink bg-ink text-white", dot: "" },
      approved: { chip: "border-action bg-action-soft text-action", dot: "bg-action" },
      pending: {
        chip: "border-line-strong bg-surface text-ink-3",
        dot: "border-[1.5px] border-ink-3",
      },
      rejected: { chip: "border-fail-line bg-fail-bg text-fail-dark", dot: "bg-fail" },
    },
  },
  night: {
    muted: "text-on-night-3",
    chips: {
      current: { chip: "border-on-night bg-on-night text-ink", dot: "" },
      approved: {
        chip: "border-petrol-on-night bg-petrol-on-night/16 text-petrol-on-night-2",
        dot: "bg-petrol-on-night",
      },
      pending: {
        chip: "border-night-line-strong bg-night-raised text-on-night-3",
        dot: "border-[1.5px] border-on-night-3",
      },
      rejected: {
        chip: "border-fail-on-night/60 bg-fail-on-night/10 text-fail-on-night",
        dot: "bg-fail-on-night",
      },
    },
  },
};

const palette = computed(() => palettes[context.value]);
const chip = computed(() => (props.status ? palette.value.chips[props.status] : null));
</script>

<template>
  <div class="grid" data-testid="step-header" :data-surface-context="context">
    <div class="flex flex-wrap items-center gap-3">
      <span :class="['font-mono text-xs tracking-[0.08em] uppercase', palette.muted]">
        {{ t("ui.progress.step", { n: step, total }) }}
      </span>
      <span
        v-if="status && chip"
        :class="[
          'inline-flex min-h-[26px] items-center gap-1.5 rounded-pill border px-2.5 text-xs font-medium whitespace-nowrap',
          chip.chip,
        ]"
        :data-status="status"
        data-testid="step-status"
      >
        <span
          v-if="chip.dot"
          :class="['inline-block h-2 w-2 shrink-0 rounded-full', chip.dot]"
          aria-hidden="true"
        />
        {{ t(`ui.stepHeader.${status}`) }}
      </span>
    </div>
    <component
      :is="as"
      class="mt-3.5 mb-2.5 font-display text-[clamp(28px,3.2vw,44px)] leading-[1.08] font-extralight tracking-display text-balance uppercase"
    >
      {{ title }}
    </component>
    <p
      v-if="description"
      :class="['max-w-[720px] text-base leading-normal sm:text-lg', palette.muted]"
    >
      {{ description }}
    </p>
    <slot />
  </div>
</template>
