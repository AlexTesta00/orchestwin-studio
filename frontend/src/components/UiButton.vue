<script setup lang="ts">
import { computed } from "vue";
import { RouterLink, type RouteLocationRaw } from "vue-router";

import { useSurface, type SurfaceContext } from "./UiSurface.vue";

type Variant = "primary" | "secondary" | "danger" | "pill" | "outline" | "quiet";

const props = withDefaults(
  defineProps<{
    variant?: Variant | undefined;
    type?: "button" | "submit" | undefined;
    disabled?: boolean | undefined;
    full?: boolean | undefined;
    size?: "md" | "lg" | undefined;
    to?: RouteLocationRaw | undefined;
    href?: string | undefined;
    surface?: SurfaceContext | undefined;
  }>(),
  {
    variant: "primary",
    type: "button",
    disabled: false,
    full: false,
    size: "md",
    to: undefined,
    href: undefined,
    surface: undefined,
  },
);

const context = useSurface(() => props.surface);

const lightPill =
  "rounded-pill bg-on-night text-ink hover:bg-petrol-on-night-2 disabled:bg-night-hover disabled:text-on-night-3";
const lightOutline =
  "rounded-pill border border-on-night/32 bg-on-night/5 text-on-night hover:bg-on-night hover:text-ink disabled:border-night-line disabled:bg-transparent disabled:text-on-night-3";

const shapes = {
  light: {
    primary:
      "rounded-control bg-action text-white hover:bg-action-hover disabled:border disabled:border-line disabled:bg-surface-3 disabled:text-ink-3",
    secondary:
      "rounded-control border border-button-line bg-surface text-ink hover:bg-surface-3 disabled:border-line disabled:bg-surface-3 disabled:text-ink-3",
    danger:
      "rounded-control bg-fail-strong text-white hover:bg-fail-dark disabled:border disabled:border-line disabled:bg-surface-3 disabled:text-ink-3",
    pill: "rounded-pill bg-ink text-white hover:bg-ink-2 disabled:bg-surface-3 disabled:text-ink-3",
    outline:
      "rounded-pill border border-ink/25 text-ink hover:bg-ink hover:text-white disabled:border-line disabled:bg-transparent disabled:text-ink-3",
    quiet:
      "rounded-pill text-ink-3 hover:bg-surface-3 hover:text-ink disabled:text-ink-3 disabled:hover:bg-transparent",
  },
  night: {
    primary: lightPill,
    secondary: lightOutline,
    danger:
      "rounded-pill border border-fail-on-night/60 text-fail-on-night hover:bg-fail-on-night hover:text-ink disabled:border-night-line disabled:text-on-night-3 disabled:hover:bg-transparent",
    pill: lightPill,
    outline: lightOutline,
    quiet:
      "rounded-pill text-on-night-3 hover:bg-night-hover hover:text-on-night disabled:text-on-night-3 disabled:hover:bg-transparent",
  },
};

const sizes = {
  md: "min-h-11 px-5 py-2.5 text-sm",
  lg: "min-h-[50px] px-[26px] py-3 text-[15px]",
};

const classes = computed(() => [
  "inline-flex items-center justify-center gap-2 text-center font-semibold transition-colors duration-150 disabled:cursor-not-allowed",
  sizes[props.size],
  props.full ? "w-full" : "",
  shapes[context.value][props.variant],
]);
</script>

<template>
  <RouterLink v-if="to !== undefined" :to="to" :class="classes" :data-variant="variant">
    <slot />
  </RouterLink>
  <a v-else-if="href !== undefined" :href="href" :class="classes" :data-variant="variant">
    <slot />
  </a>
  <button v-else :class="classes" :type="type" :disabled="disabled" :data-variant="variant">
    <slot />
  </button>
</template>
