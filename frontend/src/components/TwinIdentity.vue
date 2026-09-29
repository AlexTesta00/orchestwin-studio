<script setup lang="ts">
import { getActivePinia, piniaSymbol } from "pinia";
import { computed, inject } from "vue";

import { useUserModelingStore } from "@/stores/userModeling";
import { useSurface, type SurfaceContext } from "./UiSurface.vue";
import { rosterAvatar, twinIdentity, type TwinRoster } from "./twinIdentity";

const props = withDefaults(
  defineProps<{
    role?: string | undefined;
    identityKey?: string | undefined;
    name?: string | undefined;
    description?: string | undefined;
    locale?: "it" | "en" | undefined;
    compact?: boolean | undefined;
    peers?: readonly string[] | undefined;
    status?: "hypothesis" | "confirmed" | undefined;
    size?: "md" | "lg" | undefined;
    nameAs?: "span" | "h2" | "h3" | "h4" | undefined;
    surface?: SurfaceContext | undefined;
  }>(),
  {
    role: undefined,
    identityKey: "",
    name: undefined,
    description: undefined,
    locale: "it",
    compact: false,
    peers: undefined,
    status: "hypothesis",
    size: "md",
    nameAs: "span",
    surface: undefined,
  },
);

const context = useSurface(() => props.surface);
const pinia = inject(piniaSymbol, null) ?? getActivePinia() ?? null;
const modeling = pinia === null ? null : useUserModelingStore(pinia);

const roster = computed<TwinRoster>(() => ({
  personaIds: modeling?.currentPersonas.map((persona) => persona.persona_id) ?? [],
  twins:
    modeling?.currentTwins.map((twin) => ({
      twinId: twin.twin_id,
      personaId: twin.profile.persona_reference.persona_id,
    })) ?? [],
}));

const key = computed(() => props.identityKey || props.name || "");

const identity = computed(() => twinIdentity(props.role, key.value, props.locale, props.peers));

const avatar = computed(() =>
  identity.value.isUser && props.peers === undefined
    ? rosterAvatar(key.value, roster.value)
    : identity.value.avatar,
);

const displayName = computed(() => props.name || identity.value.name);

const displayDescription = computed(() => {
  const description = props.description ?? identity.value.description;
  return description.trim().toLocaleLowerCase() === displayName.value.trim().toLocaleLowerCase()
    ? ""
    : description;
});

const palettes = {
  light: {
    name: "text-ink",
    description: "text-ink-2",
    role: "border-line",
    hypothesis: "border-dashed border-hypothesis bg-hypothesis-bg",
    confirmed: "border-solid border-action bg-action-soft",
  },
  night: {
    name: "text-on-night",
    description: "text-on-night-3",
    role: "border-night-line",
    hypothesis: "border-dashed border-violet-on-night bg-violet-on-night/12",
    confirmed: "border-solid border-petrol-on-night bg-petrol-on-night/16",
  },
};

const palette = computed(() => palettes[context.value]);

const frame = computed(() => {
  const size = props.size === "lg" ? "size-[52px]" : "size-10";
  return identity.value.isUser
    ? [size, "rounded-full border-2", palette.value[props.status]]
    : [size, "rounded-panel border", palette.value.role];
});
</script>

<template>
  <span
    class="inline-flex min-w-0 items-center gap-3"
    data-testid="twin-identity"
    :data-avatar="avatar"
    :data-surface-context="context"
  >
    <span
      :class="['inline-flex shrink-0 overflow-hidden bg-night', frame]"
      :data-identity-status="identity.isUser ? status : undefined"
    >
      <img
        :src="avatar"
        alt=""
        :width="size === 'lg' ? 52 : 40"
        :height="size === 'lg' ? 52 : 40"
        decoding="async"
        class="block size-full object-cover"
      />
    </span>
    <span class="min-w-0">
      <component
        :is="nameAs"
        :class="[
          'm-0 block font-semibold break-words',
          size === 'lg' ? 'text-[17px] leading-[1.25]' : 'text-sm leading-5',
          palette.name,
        ]"
        >{{ displayName }}</component
      >
      <span
        v-if="!compact && displayDescription"
        :class="['mt-[3px] block text-xs leading-[1.35]', palette.description]"
        >{{ displayDescription }}</span
      >
    </span>
  </span>
</template>
