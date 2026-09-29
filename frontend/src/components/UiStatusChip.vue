<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { useSurface, type SurfaceContext } from "./UiSurface.vue";

type Status = "approved" | "rejected" | "pending" | "blocked" | "observed" | "failed" | "passed";

const props = defineProps<{
  status: Status;
  label?: string | undefined;
  surface?: SurfaceContext | undefined;
}>();

const { t } = useI18n({ useScope: "global" });

const context = useSurface(() => props.surface);

const styles = {
  light: {
    approved: { chip: "border-action bg-action-soft text-action", dot: "bg-action" },
    passed: { chip: "border-action bg-action-soft text-action", dot: "bg-action" },
    rejected: { chip: "border-fail-line bg-fail-bg text-fail-dark", dot: "bg-fail" },
    failed: { chip: "border-fail-line bg-fail-bg text-fail-dark", dot: "bg-fail" },
    pending: {
      chip: "border-line-strong bg-surface text-ink-3",
      dot: "border-[1.5px] border-ink-3",
    },
    blocked: { chip: "border-line-strong bg-surface text-warn", dot: "bg-warn" },
    observed: { chip: "border-ink bg-ink text-white", dot: "bg-petrol-on-night-2" },
  },
  night: {
    approved: {
      chip: "border-petrol-on-night bg-petrol-on-night/16 text-petrol-on-night-2",
      dot: "bg-petrol-on-night",
    },
    passed: {
      chip: "border-petrol-on-night bg-petrol-on-night/16 text-petrol-on-night-2",
      dot: "bg-petrol-on-night",
    },
    rejected: {
      chip: "border-fail-on-night/60 bg-fail-on-night/10 text-fail-on-night",
      dot: "bg-fail-on-night",
    },
    failed: {
      chip: "border-fail-on-night/60 bg-fail-on-night/10 text-fail-on-night",
      dot: "bg-fail-on-night",
    },
    pending: {
      chip: "border-night-line-strong bg-night-raised text-on-night-3",
      dot: "border-[1.5px] border-on-night-3",
    },
    blocked: {
      chip: "border-warn-on-night/60 bg-warn-on-night/10 text-warn-on-night",
      dot: "bg-warn-on-night",
    },
    observed: { chip: "border-on-night bg-on-night text-ink", dot: "bg-action" },
  },
};

const style = computed(() => styles[context.value][props.status]);
const text = computed(() => props.label ?? t(`ui.status.${props.status}`));
</script>

<template>
  <span
    :class="[
      'inline-flex min-h-[26px] items-center gap-1.5 rounded-pill border px-2.5 text-xs font-medium whitespace-nowrap',
      style.chip,
    ]"
    :data-status="status"
  >
    <span
      :class="['inline-block h-2 w-2 shrink-0 rounded-full', style.dot]"
      aria-hidden="true"
      data-status-dot
    />
    <span>{{ text }}</span>
  </span>
</template>
