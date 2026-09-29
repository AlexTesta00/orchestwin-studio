<script setup lang="ts">
import { computed, ref, useId } from "vue";
import { useI18n } from "vue-i18n";

import { useSurface, type SurfaceContext } from "./UiSurface.vue";

const props = withDefaults(
  defineProps<{
    summary: string;
    rows?: readonly { label: string; value: string }[] | undefined;
    surface?: SurfaceContext | undefined;
  }>(),
  { rows: () => [], surface: undefined },
);

const { t } = useI18n({ useScope: "global" });

const context = useSurface(() => props.surface);
const open = ref(false);
const regionId = useId();

const palettes = {
  light: {
    line: "border-line",
    muted: "text-ink-3",
    toggle: "text-ink-3 hover:text-ink",
    panel: "border-line bg-surface text-ink",
  },
  night: {
    line: "border-night-line",
    muted: "text-on-night-3",
    toggle: "text-on-night-3 hover:text-on-night",
    panel: "border-night-line bg-night-raised text-on-night",
  },
};

const palette = computed(() => palettes[context.value]);
</script>

<template>
  <div
    :class="['mt-10 border-t pt-1', palette.line]"
    data-testid="step-technical-details"
    :data-surface-context="context"
  >
    <button
      type="button"
      :class="[
        'flex min-h-11 flex-wrap items-center gap-x-2 text-left font-mono text-xs transition-colors duration-150',
        palette.toggle,
      ]"
      :aria-expanded="open ? 'true' : 'false'"
      :aria-controls="open ? regionId : undefined"
      data-testid="step-technical-details-toggle"
      @click="open = !open"
    >
      <span>{{ summary }}</span>
      <span aria-hidden="true">·</span>
      <span class="underline underline-offset-[3px]">
        {{ open ? t("ui.technical.hide") : t("ui.technical.show") }}
      </span>
    </button>
    <div
      v-if="open"
      :id="regionId"
      :class="['mt-1 grid gap-3 rounded-field border px-5 py-4 text-[13px]', palette.panel]"
      data-testid="step-technical-details-content"
    >
      <dl
        v-if="rows.length > 0"
        class="grid grid-cols-1 gap-x-5 gap-y-1 sm:grid-cols-[180px_minmax(0,1fr)] sm:gap-y-2"
      >
        <template v-for="(row, index) in rows" :key="index">
          <dt :class="palette.muted">{{ row.label }}</dt>
          <dd class="mb-2 font-mono text-xs leading-[1.6] wrap-anywhere sm:mb-0">
            {{ row.value }}
          </dd>
        </template>
      </dl>
      <slot />
    </div>
  </div>
</template>
