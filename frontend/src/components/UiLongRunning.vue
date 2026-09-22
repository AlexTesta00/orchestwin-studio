<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import UiButton from "./UiButton.vue";
import UiCard from "./UiCard.vue";

const props = withDefaults(
  defineProps<{
    title: string;
    expected?: string | undefined;
    elapsed?: number | undefined;
    progress?: number | undefined;
    cancellable?: boolean | undefined;
  }>(),
  { expected: "", elapsed: 0, progress: 0, cancellable: false },
);

const emit = defineEmits<{ cancel: [] }>();

const { t } = useI18n({ useScope: "global" });

const width = computed(() => `${Math.min(100, Math.max(0, props.progress))}%`);
</script>

<template>
  <UiCard>
    <div aria-live="polite" data-testid="long-running">
      <div class="flex flex-wrap items-center gap-3">
        <span
          class="inline-block h-[15px] w-[15px] animate-spin-arc rounded-full border-2 border-line-strong border-t-action"
          aria-hidden="true"
        />
        <span class="flex-1 text-[15px] font-semibold">{{ title }}</span>
        <span v-if="expected" class="font-mono text-xs text-ink-3">{{ expected }}</span>
      </div>
      <div
        class="mt-4 h-1.5 overflow-hidden rounded-pill bg-bar-track-end"
        role="progressbar"
        :aria-valuenow="Math.round(progress)"
        aria-valuemin="0"
        aria-valuemax="100"
      >
        <div class="h-full rounded-pill bg-action transition-[width]" :style="{ width }" />
      </div>
      <div class="mt-3 flex flex-wrap items-center justify-between gap-3">
        <span class="font-mono text-xs text-ink-3">
          {{ t("ui.running.elapsed", { seconds: Math.round(elapsed) }) }}
        </span>
        <UiButton
          v-if="cancellable"
          variant="secondary"
          data-testid="cancel"
          @click="emit('cancel')"
        >
          {{ t("ui.running.cancel") }}
        </UiButton>
      </div>
    </div>
  </UiCard>
</template>
