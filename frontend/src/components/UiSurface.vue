<script lang="ts">
import { computed, inject, type ComputedRef, type InjectionKey, type Ref } from "vue";

export type SurfaceTone = "night" | "panel" | "light";
export type SurfaceContext = "night" | "light";
export type SurfaceRadius = "field" | "tile" | "sheet" | "stage";

export const surfaceKey: InjectionKey<Readonly<Ref<SurfaceContext>>> = Symbol("surface");

export function useSurface(
  override: () => SurfaceContext | undefined,
): ComputedRef<SurfaceContext> {
  const surrounding = inject(surfaceKey, null);
  return computed(() => override() ?? surrounding?.value ?? "light");
}
</script>

<script setup lang="ts">
import { provide } from "vue";

const props = withDefaults(
  defineProps<{
    tone?: SurfaceTone | undefined;
    radius?: SurfaceRadius | undefined;
    padded?: boolean | undefined;
    as?: "div" | "section" | "article" | "aside" | "header" | "footer" | undefined;
  }>(),
  { tone: "night", radius: "stage", padded: true, as: "div" },
);

const context = computed<SurfaceContext>(() => (props.tone === "light" ? "light" : "night"));

provide(surfaceKey, context);

const tones = {
  night: "bg-night text-on-night",
  panel: "bg-night-panel text-on-night",
  light: "border border-line bg-surface text-ink",
};

const radii = {
  field: "rounded-field",
  tile: "rounded-tile",
  sheet: "rounded-sheet",
  stage: "rounded-stage",
};

const paddings = {
  field: "px-3.5 py-3",
  tile: "p-5 sm:p-6",
  sheet: "p-6 sm:p-8",
  stage: "px-6 py-10 sm:px-10 sm:py-12 lg:px-14",
};

const classes = computed(() => [
  "relative isolate",
  tones[props.tone],
  radii[props.radius],
  props.padded ? paddings[props.radius] : "",
]);
</script>

<template>
  <component :is="as" :class="classes" :data-surface="tone">
    <slot />
  </component>
</template>
