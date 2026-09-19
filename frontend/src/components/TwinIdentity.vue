<script setup lang="ts">
import { computed } from "vue";
import { identityInitials, twinIdentity } from "./twinIdentity";

const props = withDefaults(
  defineProps<{
    role?: string;
    identityKey?: string;
    name?: string;
    description?: string | undefined;
    locale?: "it" | "en";
    compact?: boolean;
  }>(),
  { locale: "it", identityKey: "", compact: false },
);

const identity = computed(() =>
  twinIdentity(props.role, props.identityKey || props.name || "", props.locale),
);
const displayName = computed(() => props.name || identity.value.name);
const displayDescription = computed(() => {
  const description = props.description ?? identity.value.description;
  return description.trim().toLocaleLowerCase() === displayName.value.trim().toLocaleLowerCase()
    ? ""
    : description;
});
</script>

<template>
  <span class="inline-flex min-w-0 items-start gap-3" data-testid="twin-identity">
    <span
      class="relative inline-flex size-10 shrink-0 items-center justify-center rounded-xl ring-1 ring-inset"
      :class="identity.accent"
      aria-hidden="true"
    >
      <svg
        v-if="!identity.isUser"
        class="size-6"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="1.6"
        stroke-linecap="round"
        stroke-linejoin="round"
        focusable="false"
      >
        <path :d="identity.path" />
      </svg>
      <span v-else class="text-sm font-bold">{{ identityInitials(displayName) || "UT" }}</span>
    </span>
    <span class="min-w-0">
      <span class="block text-sm font-semibold break-words text-slate-950">{{ displayName }}</span>
      <span
        v-if="!compact && displayDescription"
        class="mt-0.5 block text-xs leading-5 text-slate-600"
        >{{ displayDescription }}</span
      >
    </span>
  </span>
</template>
