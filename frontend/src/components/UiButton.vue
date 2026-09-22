<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(
  defineProps<{
    variant?: "primary" | "secondary" | "danger" | undefined;
    type?: "button" | "submit" | undefined;
    disabled?: boolean | undefined;
    full?: boolean | undefined;
  }>(),
  { variant: "primary", type: "button", disabled: false, full: false },
);

const variants = {
  primary: "bg-action text-white hover:bg-action-hover",
  secondary: "border border-button-line bg-surface text-ink hover:bg-surface-3",
  danger: "bg-fail-strong text-white hover:bg-fail-dark",
};

const classes = computed(() => [
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-control px-[18px] py-2.5 text-sm font-semibold transition-colors duration-150",
  "disabled:cursor-not-allowed disabled:border disabled:border-line disabled:bg-surface-3 disabled:text-ink-3",
  props.full ? "w-full" : "",
  variants[props.variant],
]);
</script>

<template>
  <button :class="classes" :type="type" :disabled="disabled">
    <slot />
  </button>
</template>
