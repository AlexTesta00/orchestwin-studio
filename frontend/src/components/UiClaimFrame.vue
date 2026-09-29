<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { useSurface, type SurfaceContext } from "./UiSurface.vue";

type ClaimStatus = "hypothesis" | "confirmed" | "evidence";

const props = withDefaults(
  defineProps<{
    status: ClaimStatus;
    as?: "div" | "article" | "section" | "li" | undefined;
    radius?: "field" | "tile" | "sheet" | undefined;
    padded?: boolean | undefined;
    surface?: SurfaceContext | undefined;
  }>(),
  { as: "div", radius: "field", padded: true, surface: undefined },
);

const { t } = useI18n({ useScope: "global" });

const context = useSurface(() => props.surface);

const frames = {
  light: {
    hypothesis: "border-[1.5px] border-dashed border-hypothesis/70 bg-surface",
    confirmed: "border border-action bg-action-soft/50",
    evidence: "border border-ink bg-surface",
  },
  night: {
    hypothesis: "border-[1.5px] border-dashed border-violet-on-night/70 bg-violet-on-night/6",
    confirmed: "border border-petrol-on-night bg-night-raised",
    evidence: "border border-on-night/40 bg-on-night/6",
  },
};

const radii = {
  field: "rounded-field",
  tile: "rounded-tile",
  sheet: "rounded-sheet",
};

const paddings = {
  field: "px-3.5 py-3",
  tile: "p-5",
  sheet: "p-6",
};

const labels = {
  hypothesis: "ui.claim.hypothesis",
  confirmed: "ui.claim.confirmed",
  evidence: "ui.claim.proof",
};

const classes = computed(() => [
  frames[context.value][props.status],
  radii[props.radius],
  props.padded ? paddings[props.radius] : "",
]);
</script>

<template>
  <component :is="as" :class="classes" :data-claim-status="status">
    <span class="sr-only" data-claim-text>{{ t(labels[status]) }}</span>
    <slot />
  </component>
</template>
