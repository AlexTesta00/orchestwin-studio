<script setup lang="ts">
import { computed } from "vue";

import type { VisualLanguagePayload } from "../types/design";
import {
  archetypeLabel,
  dimensionLabel,
  tokenStyle,
  valueLabel,
  type VisualLocale,
} from "./visualLanguage";

const props = withDefaults(
  defineProps<{ visual: VisualLanguagePayload; locale?: VisualLocale; compact?: boolean }>(),
  { locale: "en", compact: false },
);

const messages = {
  en: {
    title: "Visual language",
    sample: "The quick brown fox jumps over the lazy dog.",
    palette: "Palette",
  },
  it: {
    title: "Linguaggio visivo",
    sample: "Il rapido volpino salta sopra il cane pigro.",
    palette: "Palette",
  },
} as const;

const copy = computed(() => messages[props.locale]);
const style = computed(() => tokenStyle(props.visual));
const swatches = computed(() =>
  (["background", "surface", "primary", "accent", "text", "success", "danger"] as const).map(
    (role) => ({ role, value: props.visual.palette[role] ?? "#000000" }),
  ),
);
const chips = computed(() =>
  (["color_mode", "tone", "density", "corners", "navigation"] as const).map((dimension) => ({
    dimension,
    label: dimensionLabel(props.locale, dimension),
    value: valueLabel(props.visual.choices[dimension]),
  })),
);
</script>

<template>
  <div
    class="grid gap-3 rounded-panel border p-3"
    :style="{
      ...style,
      background: 'var(--vl-color-surface)',
      color: 'var(--vl-color-text)',
      borderColor: 'var(--vl-color-border)',
      fontFamily: 'var(--vl-font-body)',
    }"
    data-testid="design-style-tile"
  >
    <div class="flex flex-wrap items-baseline justify-between gap-2">
      <p
        class="m-0 text-lg leading-tight"
        :style="{
          fontFamily: 'var(--vl-font-heading)',
          fontWeight: 'var(--vl-heading-weight)',
          textTransform: 'var(--vl-heading-transform)',
          fontVariant: 'var(--vl-heading-variant)',
          letterSpacing: 'var(--vl-heading-tracking)',
        }"
        data-testid="style-product-name"
      >
        {{ visual.product_name }}
      </p>
      <span
        class="rounded-pill px-2.5 py-1 text-xs font-semibold"
        :style="{ background: 'var(--vl-color-primary)', color: 'var(--vl-color-on-primary)' }"
        data-testid="style-archetype"
      >
        {{ archetypeLabel(locale, visual.choices.archetype) }}
      </span>
    </div>
    <ul class="m-0 flex list-none gap-1 p-0" :aria-label="copy.palette">
      <li
        v-for="swatch in swatches"
        :key="swatch.role"
        class="h-6 flex-1 rounded-control border"
        :style="{ background: swatch.value, borderColor: 'var(--vl-color-border)' }"
        :title="`${swatch.role}: ${swatch.value}`"
        :data-role="swatch.role"
      />
    </ul>
    <p
      v-if="!compact"
      class="m-0 text-sm"
      :style="{ color: 'var(--vl-color-text-muted)', fontFamily: 'var(--vl-font-body)' }"
    >
      {{ copy.sample }}
    </p>
    <ul class="m-0 flex list-none flex-wrap gap-1.5 p-0 text-xs">
      <li
        v-for="chip in chips"
        :key="chip.dimension"
        class="rounded-pill px-2 py-0.5"
        :style="{ background: 'var(--vl-color-surface-alt)', color: 'var(--vl-color-text-muted)' }"
      >
        <span class="sr-only">{{ chip.label }}: </span>{{ chip.value }}
      </li>
    </ul>
    <p
      v-if="!compact"
      class="m-0 text-xs leading-5"
      :style="{ color: 'var(--vl-color-text-muted)' }"
    >
      {{ visual.rationale }}
    </p>
    <ul
      v-if="!compact && visual.twin_fit.length > 0"
      class="m-0 grid list-none gap-1 p-0 text-xs leading-5"
      :style="{ color: 'var(--vl-color-text-muted)' }"
      data-testid="style-twin-fit"
    >
      <li v-for="fit in visual.twin_fit" :key="fit.twin_id">
        <strong :style="{ color: 'var(--vl-color-text)' }">{{ fit.name }}</strong>
        {{ fit.statement }}
      </li>
    </ul>
  </div>
</template>
