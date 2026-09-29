<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { useSurface, type SurfaceContext } from "./UiSurface.vue";

const props = withDefaults(
  defineProps<{
    kind: "empty" | "loading" | "error" | "success";
    title?: string | undefined;
    text?: string | undefined;
    surface?: SurfaceContext | undefined;
  }>(),
  { title: "", text: "", surface: undefined },
);

const { t } = useI18n({ useScope: "global" });

const context = useSurface(() => props.surface);

const tones = {
  light: {
    empty: "border-line bg-surface-2 text-ink-2",
    loading: "border-line bg-surface-2 text-ink-2",
    error: "border-fail-line bg-fail-bg text-fail-dark",
    success: "border-ok-line bg-ok-bg text-ok-dark",
  },
  night: {
    empty: "border-night-line bg-night-raised text-on-night-2",
    loading: "border-night-line bg-night-raised text-on-night-2",
    error: "border-fail-on-night/40 bg-fail-on-night/10 text-fail-on-night",
    success: "border-petrol-on-night/50 bg-petrol-on-night/10 text-petrol-on-night-2",
  },
};

const spinners = {
  light: "border-line-strong border-t-action",
  night: "border-night-line-strong border-t-petrol-on-night",
};

const classes = computed(() => tones[context.value][props.kind]);
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
        :class="[
          'inline-block h-[15px] w-[15px] shrink-0 animate-spin-arc rounded-full border-2',
          spinners[context],
        ]"
        aria-hidden="true"
      />
      <p v-if="heading" class="text-[15px] font-semibold">{{ heading }}</p>
    </div>
    <p v-if="text" class="mt-1 text-[15px] leading-normal">{{ text }}</p>
    <div v-if="$slots.default" class="mt-3">
      <slot />
    </div>
  </div>
</template>
