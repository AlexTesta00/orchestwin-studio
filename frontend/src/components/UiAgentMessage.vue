<script setup lang="ts">
import { computed } from "vue";

import { useSurface, type SurfaceContext } from "./UiSurface.vue";

const props = withDefaults(
  defineProps<{
    roleLabel: string;
    avatar: string;
    avatarAlt?: string | undefined;
    surface?: SurfaceContext | undefined;
  }>(),
  { avatarAlt: "", surface: undefined },
);

const context = useSurface(() => props.surface);

const palettes = {
  light: {
    box: "border-line bg-surface",
    role: "text-action",
    message: "text-ink-2",
  },
  night: {
    box: "border-night-line bg-night-raised",
    role: "text-petrol-on-night-2",
    message: "text-on-night-2",
  },
};

const palette = computed(() => palettes[context.value]);
</script>

<template>
  <div
    :class="['flex items-center gap-3.5 rounded-tile border py-3 pr-4 pl-3', palette.box]"
    data-testid="agent-message"
    :data-surface-context="context"
  >
    <img
      :src="avatar"
      :alt="avatarAlt"
      width="52"
      height="52"
      decoding="async"
      class="h-[52px] w-[52px] shrink-0 rounded-panel bg-night object-cover"
    />
    <div class="min-w-0">
      <p :class="['font-mono text-[11px] tracking-label uppercase', palette.role]">
        {{ roleLabel }}
      </p>
      <div :class="['mt-[3px] text-[15px] leading-[1.45]', palette.message]">
        <slot />
      </div>
    </div>
  </div>
</template>
