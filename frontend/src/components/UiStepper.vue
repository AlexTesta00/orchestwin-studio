<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { useSurface, type SurfaceContext } from "./UiSurface.vue";

export type StepStatus = "pending" | "current" | "approved" | "rejected";

export interface StepItem {
  key: string;
  label: string;
  status: StepStatus;
  decision?: number;
  max?: number;
  index?: number;
  note?: string;
  open?: boolean;
}

const props = withDefaults(
  defineProps<{ steps: StepItem[]; active: string; surface?: SurfaceContext | undefined }>(),
  { surface: undefined },
);

const emit = defineEmits<{ select: [key: string] }>();

const { t } = useI18n({ useScope: "global" });

const context = useSurface(() => props.surface);

const palettes = {
  night: {
    line: "border-on-night/14",
    number: {
      active: "text-on-night",
      approved: "text-petrol-on-night",
      rejected: "text-fail-on-night",
      idle: "text-on-night/32",
    },
    title: {
      active: "text-on-night",
      available: "text-on-night-2 group-hover:text-on-night",
      locked: "text-on-night-3",
    },
    status: {
      pending: "text-on-night-3",
      current: "text-on-night",
      approved: "text-petrol-on-night-2",
      rejected: "text-fail-on-night",
    },
  },
  light: {
    line: "border-line",
    number: {
      active: "text-ink",
      approved: "text-action",
      rejected: "text-fail",
      idle: "text-ink/25",
    },
    title: {
      active: "text-ink",
      available: "text-ink-2 group-hover:text-ink",
      locked: "text-ink-3",
    },
    status: {
      pending: "text-ink-3",
      current: "text-ink",
      approved: "text-action",
      rejected: "text-fail-dark",
    },
  },
};

const palette = computed(() => palettes[context.value]);

function numberClass(step: StepItem): string {
  if (step.key === props.active) {
    return palette.value.number.active;
  }
  if (step.status === "approved" || step.status === "rejected") {
    return palette.value.number[step.status];
  }
  return palette.value.number.idle;
}

function locked(step: StepItem): boolean {
  return step.status === "pending" && step.open !== true;
}

function titleClass(step: StepItem): string {
  if (step.key === props.active) {
    return palette.value.title.active;
  }
  return locked(step) ? palette.value.title.locked : palette.value.title.available;
}

function meta(step: StepItem): string {
  if (step.note) {
    return step.note;
  }
  if (step.status === "pending") {
    return t("ui.stepper.pending");
  }
  if (step.status === "approved") {
    return t("ui.stepper.approved");
  }
  if (step.decision === undefined || step.max === undefined) {
    return t("ui.stepper.current");
  }
  return t("ui.stepper.decision", { n: step.decision, max: step.max });
}
</script>

<template>
  <nav :aria-label="t('ui.stepper.label')" data-testid="stepper" :data-surface-context="context">
    <ol :class="['m-0 flex list-none flex-col border-t p-0', palette.line]">
      <li v-for="(step, index) in steps" :key="step.key">
        <button
          type="button"
          :class="[
            'group grid min-h-[66px] w-full grid-cols-[104px_minmax(0,1fr)] items-end gap-x-2.5 border-b text-left',
            palette.line,
            locked(step) ? 'cursor-not-allowed' : 'cursor-pointer',
          ]"
          :disabled="locked(step)"
          :aria-current="step.status === 'current' ? 'step' : undefined"
          :data-status="step.status"
          :data-active="step.key === active ? 'true' : undefined"
          :data-stage="locked(step) ? undefined : (step.index ?? index)"
          @click="emit('select', step.key)"
        >
          <span class="block h-[46px] overflow-hidden" aria-hidden="true">
            <span
              :class="[
                'block font-display text-[60px] leading-[0.84] font-extralight tracking-[-0.05em] transition-colors duration-150',
                numberClass(step),
              ]"
              data-step-number
            >
              {{ String(index + 1).padStart(2, "0") }}
            </span>
          </span>
          <span class="flex min-w-0 flex-col gap-1 py-3">
            <span
              :class="[
                'truncate font-mono text-[11px] font-semibold tracking-label uppercase transition-colors duration-150',
                titleClass(step),
              ]"
            >
              {{ step.label }}
            </span>
            <span :class="['text-xs leading-snug', palette.status[step.status]]">
              <span v-if="step.status === 'approved' && !step.note" aria-hidden="true">✓ </span>
              {{ meta(step) }}
            </span>
          </span>
        </button>
      </li>
    </ol>
  </nav>
</template>
