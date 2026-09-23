<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

const props = defineProps<{
  status: "approved" | "rejected" | "pending" | "blocked" | "observed" | "failed" | "passed";
  label?: string | undefined;
}>();

const { t } = useI18n({ useScope: "global" });

const styles = {
  approved: { chip: "border-ok-line bg-ok-bg text-ok-text", sign: "✓" },
  passed: { chip: "border-ok-line bg-ok-bg text-ok-text", sign: "✓" },
  rejected: { chip: "border-fail-line bg-fail-bg text-fail-dark", sign: "!" },
  failed: { chip: "border-fail-line bg-fail-bg text-fail-dark", sign: "!" },
  pending: { chip: "border-line-strong bg-surface text-ink-3", sign: "•" },
  blocked: { chip: "border-line-strong bg-surface text-warn", sign: "!" },
  observed: { chip: "border-proof-line bg-proof-bg text-proof", sign: "●" },
};

const style = computed(() => styles[props.status]);
const text = computed(() => props.label ?? t(`ui.status.${props.status}`));
</script>

<template>
  <span
    :class="[
      'inline-flex items-center gap-1.5 rounded-pill border px-2.5 py-1 text-xs font-semibold whitespace-nowrap',
      style.chip,
    ]"
    :data-status="status"
  >
    <span aria-hidden="true">{{ style.sign }}</span>
    <span>{{ text }}</span>
  </span>
</template>
