<script lang="ts">
import type { SectionState } from "@/types/sections";

export type StepStatus = "pending" | "current" | "approved" | "rejected";

export interface StepSection {
  state: SectionState;
  version: number | null;
}

export interface StepItem {
  key: string;
  label: string;
  status: StepStatus;
  decision?: number;
  max?: number;
  index?: number;
  note?: string;
  open?: boolean;
  section?: StepSection;
}

export const SECTION_MARKS: Readonly<Record<SectionState, string>> = {
  NOT_STARTED: "○",
  IN_PROGRESS: "●",
  FINE: "✓",
  UPDATE_AVAILABLE: "+",
  TO_UPDATE: "↻",
};
</script>

<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { useSurface, type SurfaceContext } from "./UiSurface.vue";

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
      behind: "text-warn-on-night",
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
    section: {
      NOT_STARTED: "text-on-night-3",
      IN_PROGRESS: "text-on-night",
      FINE: "text-petrol-on-night-2",
      UPDATE_AVAILABLE: "text-petrol-on-night-2",
      TO_UPDATE: "text-warn-on-night",
    },
  },
  light: {
    line: "border-line",
    number: {
      active: "text-ink",
      approved: "text-action",
      rejected: "text-fail",
      behind: "text-warn",
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
    section: {
      NOT_STARTED: "text-ink-3",
      IN_PROGRESS: "text-ink",
      FINE: "text-action",
      UPDATE_AVAILABLE: "text-action",
      TO_UPDATE: "text-warn",
    },
  },
};

const palette = computed(() => palettes[context.value]);
const sectionsShown = computed(() => props.steps.some((step) => step.section !== undefined));

function numberClass(step: StepItem): string {
  if (step.key === props.active) {
    return palette.value.number.active;
  }
  if (step.section !== undefined) {
    if (step.section.state === "TO_UPDATE") {
      return palette.value.number.behind;
    }
    return step.section.state === "FINE" || step.section.state === "UPDATE_AVAILABLE"
      ? palette.value.number.approved
      : palette.value.number.idle;
  }
  if (step.status === "approved" || step.status === "rejected") {
    return palette.value.number[step.status];
  }
  return palette.value.number.idle;
}

function locked(step: StepItem): boolean {
  return step.section === undefined && step.status === "pending" && step.open !== true;
}

function titleClass(step: StepItem): string {
  if (step.key === props.active) {
    return palette.value.title.active;
  }
  return locked(step) ? palette.value.title.locked : palette.value.title.available;
}

function metaClass(step: StepItem): string {
  return step.section === undefined
    ? palette.value.status[step.status]
    : palette.value.section[step.section.state];
}

function current(step: StepItem): "step" | "true" | undefined {
  if (step.section !== undefined) {
    return step.key === props.active ? "true" : undefined;
  }
  return step.status === "current" ? "step" : undefined;
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
  <nav
    :aria-label="sectionsShown ? t('ui.stepper.sectionsLabel') : t('ui.stepper.label')"
    data-testid="stepper"
    :data-surface-context="context"
  >
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
          :aria-current="current(step)"
          :data-status="step.status"
          :data-state="step.section?.state"
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
                'font-mono text-[11px] font-semibold tracking-label break-words uppercase transition-colors duration-150',
                titleClass(step),
              ]"
              data-testid="stepper-label"
            >
              {{ step.label }}
            </span>
            <span
              v-if="step.section !== undefined"
              :class="['text-xs leading-snug', metaClass(step)]"
              data-testid="stepper-section"
            >
              <span aria-hidden="true">{{ SECTION_MARKS[step.section.state] }} </span>
              {{ t(`ui.sections.states.${step.section.state}`) }}
              <template v-if="step.section.version !== null">
                <span aria-hidden="true"> · </span>
                <span data-testid="stepper-version">
                  {{ t("ui.sections.version", { n: step.section.version }) }}
                </span>
              </template>
            </span>
            <span v-else :class="['text-xs leading-snug', metaClass(step)]">
              <span v-if="step.status === 'approved' && !step.note" aria-hidden="true">✓ </span>
              {{ meta(step) }}
            </span>
          </span>
        </button>
      </li>
    </ol>
  </nav>
</template>
