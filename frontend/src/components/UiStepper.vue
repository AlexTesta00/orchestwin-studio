<script setup lang="ts">
import { useI18n } from "vue-i18n";

export type StepStatus = "pending" | "current" | "approved" | "rejected";

export interface StepItem {
  key: string;
  label: string;
  status: StepStatus;
  decision?: number;
  max?: number;
  index?: number;
}

defineProps<{ steps: StepItem[]; active: string }>();

const emit = defineEmits<{ select: [key: string] }>();

const { t } = useI18n({ useScope: "global" });

const dots = {
  pending: "border-line-strong bg-surface text-ink-3",
  current: "border-action bg-action-soft text-action",
  approved: "border-ok bg-ok-bg text-ok",
  rejected: "border-fail bg-fail-bg text-fail",
};

const names = {
  pending: "text-ink-3",
  current: "text-action",
  approved: "text-ink",
  rejected: "text-ink",
};

function sign(step: StepItem): string {
  if (step.status === "approved") {
    return "✓";
  }
  if (step.status === "rejected") {
    return "!";
  }
  return "";
}

function meta(step: StepItem): string {
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
  <nav :aria-label="t('ui.stepper.label')" data-testid="stepper">
    <ol class="flex flex-col gap-1">
      <li v-for="(step, index) in steps" :key="step.key">
        <button
          type="button"
          :class="[
            'grid w-full grid-cols-[21px_1fr] items-center gap-x-3 rounded-control px-2 py-2 text-left transition-colors duration-150',
            step.key === active ? 'bg-surface-3' : 'hover:bg-surface-2',
            step.status === 'pending' ? 'cursor-default' : '',
          ]"
          :disabled="step.status === 'pending'"
          :aria-current="step.status === 'current' ? 'step' : undefined"
          :data-status="step.status"
          :data-stage="step.status === 'pending' ? undefined : (step.index ?? index)"
          @click="emit('select', step.key)"
        >
          <span
            :class="[
              'flex h-[21px] w-[21px] items-center justify-center rounded-full border text-[11px] font-bold',
              dots[step.status],
            ]"
            aria-hidden="true"
          >
            {{ sign(step) || index + 1 }}
          </span>
          <span class="flex min-w-0 flex-col">
            <span :class="['truncate text-[13.5px] font-semibold', names[step.status]]">
              {{ step.label }}
            </span>
            <span class="font-mono text-[11px] text-ink-3">{{ meta(step) }}</span>
          </span>
        </button>
      </li>
    </ol>
  </nav>
</template>
