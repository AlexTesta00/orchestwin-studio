<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

const props = withDefaults(
  defineProps<{
    kind: "empty" | "loading" | "error" | "success";
    title?: string | undefined;
    text?: string | undefined;
  }>(),
  { title: "", text: "" },
);

const { t } = useI18n({ useScope: "global" });

const tones = {
  empty: "border-line bg-surface-2 text-ink-2",
  loading: "border-line bg-surface-2 text-ink-2",
  error: "border-fail-line bg-fail-bg text-fail-dark",
  success: "border-ok-line bg-ok-bg text-ok-dark",
};

const classes = computed(() => tones[props.kind]);
const heading = computed(
  () => props.title || (props.kind === "loading" ? t("ui.state.loading") : ""),
);
</script>

<template>
  <div
    :class="['rounded-panel border px-5 py-4', classes]"
    :role="kind === 'error' ? 'alert' : kind === 'loading' ? 'status' : undefined"
    :aria-live="kind === 'loading' ? 'polite' : undefined"
    :data-state="kind"
  >
    <div class="flex items-center gap-3">
      <span
        v-if="kind === 'loading'"
        class="inline-block h-[15px] w-[15px] animate-spin-arc rounded-full border-2 border-line-strong border-t-action"
        aria-hidden="true"
      />
      <p v-if="heading" class="text-[15px] font-semibold">{{ heading }}</p>
    </div>
    <p v-if="text" class="mt-1 text-[15px]">{{ text }}</p>
    <div v-if="$slots.default" class="mt-3">
      <slot />
    </div>
  </div>
</template>
