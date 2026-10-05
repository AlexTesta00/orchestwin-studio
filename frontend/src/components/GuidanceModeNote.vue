<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { useGuidanceStore } from "@/stores/guidance";

const guidance = useGuidanceStore();
const { locale } = useI18n({ useScope: "global" });
const copy = computed(() =>
  locale.value === "it"
    ? {
        GUIDED: "Modalità guidata",
        EXPERT: "Modalità esperta",
        hint: "Scelta una volta sola per questo account: non si può cambiare.",
      }
    : {
        GUIDED: "Guided mode",
        EXPERT: "Expert mode",
        hint: "Chosen once for this account: it cannot be changed.",
      },
);
</script>

<template>
  <div data-testid="guidance-mode" :data-mode="guidance.mode">
    <p class="m-0 text-sm font-semibold text-on-night">{{ copy[guidance.mode] }}</p>
    <p class="mt-1 mb-0 text-xs text-on-night-3">{{ copy.hint }}</p>
  </div>
</template>
