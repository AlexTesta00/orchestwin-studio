<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { useGuidanceStore, type GuidanceMode } from "@/stores/guidance";

const guidance = useGuidanceStore();
const { locale } = useI18n({ useScope: "global" });
const copy = computed(() =>
  locale.value === "it"
    ? {
        label: "Guida personale",
        GUIDED: "Guidata",
        EXPERT: "Esperta",
        hint: "Preferenza di questo browser per il tuo account.",
      }
    : {
        label: "Personal guidance",
        GUIDED: "Guided",
        EXPERT: "Expert",
        hint: "This browser's preference for your account.",
      },
);
const modes: GuidanceMode[] = ["GUIDED", "EXPERT"];
</script>

<template>
  <fieldset class="m-0 min-w-0 border-0 p-0" data-testid="guidance-selector">
    <legend class="mb-2 text-sm text-on-night-2">{{ copy.label }}</legend>
    <div class="flex flex-wrap gap-2">
      <button
        v-for="mode in modes"
        :key="mode"
        type="button"
        :aria-pressed="guidance.mode === mode"
        :disabled="!guidance.accountId"
        :data-testid="`guidance-${mode.toLowerCase()}`"
        :class="[
          'min-h-11 rounded-field border px-4 text-sm font-semibold disabled:opacity-50',
          guidance.mode === mode
            ? 'border-petrol-on-night bg-petrol-on-night/15 text-petrol-on-night-2'
            : 'border-night-line text-on-night-2',
        ]"
        @click="guidance.select(mode)"
      >
        {{ copy[mode] }}
      </button>
    </div>
    <p class="mt-2 text-xs text-on-night-3">{{ copy.hint }}</p>
  </fieldset>
</template>
