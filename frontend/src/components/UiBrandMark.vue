<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(defineProps<{ size?: number | undefined; title?: string }>(), {
  size: 26,
  title: "OrchesTwin",
});

const radius = computed(() => (props.size <= 26 ? 4.4 : 3.4));

const points = Array.from({ length: 8 }, (_, index) => {
  const angle = (Math.PI * 2 * index) / 8 - Math.PI / 2;
  return {
    x: (27 + 19 * Math.cos(angle)).toFixed(2),
    y: (27 + 19 * Math.sin(angle)).toFixed(2),
  };
});

const fills = [
  "#0a5fba",
  "#1c1c1e",
  "#c9c9d1",
  "#c9c9d1",
  "#1c1c1e",
  "#c9c9d1",
  "#c9c9d1",
  "#c9c9d1",
];
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 54 54"
    role="img"
    :aria-label="title"
    focusable="false"
    data-testid="brand-mark"
  >
    <circle
      v-for="(point, index) in points"
      :key="index"
      :cx="point.x"
      :cy="point.y"
      :r="radius"
      :fill="fills[index]"
    />
  </svg>
</template>
