<script setup lang="ts">
import { nextTick, ref, useId, watch } from "vue";
import { useI18n } from "vue-i18n";

const props = defineProps<{ open: boolean; title: string }>();

const emit = defineEmits<{ close: [] }>();

const { t } = useI18n({ useScope: "global" });

const panel = ref<HTMLElement | null>(null);
const titleId = useId();

watch(
  () => props.open,
  async (open) => {
    if (open) {
      await nextTick();
      panel.value?.focus();
    }
  },
);
</script>

<template>
  <div v-if="open" class="fixed inset-0 z-50 flex justify-end" data-testid="side-panel">
    <button
      type="button"
      class="absolute inset-0 bg-ink/42"
      :aria-label="t('ui.panel.close')"
      data-testid="side-panel-veil"
      @click="emit('close')"
    />
    <aside
      ref="panel"
      class="relative flex h-full w-full max-w-[560px] flex-col overflow-y-auto bg-surface shadow-decision outline-none"
      role="dialog"
      aria-modal="true"
      :aria-labelledby="titleId"
      tabindex="-1"
      @keydown.esc="emit('close')"
    >
      <div
        class="sticky top-0 flex items-center justify-between gap-4 border-b border-line bg-surface px-6 py-4"
      >
        <h2 :id="titleId" class="m-0 text-2xl font-semibold tracking-card">{{ title }}</h2>
        <button
          type="button"
          class="inline-flex min-h-9 items-center justify-center rounded-control border border-button-line bg-surface px-3 text-sm font-semibold text-ink hover:bg-surface-3"
          data-testid="side-panel-close"
          @click="emit('close')"
        >
          {{ t("ui.panel.close") }}
        </button>
      </div>
      <div class="grid gap-5 px-6 py-5">
        <slot />
      </div>
    </aside>
  </div>
</template>
