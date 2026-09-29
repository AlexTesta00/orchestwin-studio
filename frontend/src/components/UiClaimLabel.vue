<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { useSurface, type SurfaceContext } from "./UiSurface.vue";

const props = defineProps<{
  kind: "hypothesis" | "confirmed" | "proof";
  surface?: SurfaceContext | undefined;
}>();

const { t } = useI18n({ useScope: "global" });

const context = useSurface(() => props.surface);

const styles = {
  light: {
    hypothesis: {
      chip: "border-dashed border-hypothesis bg-white/85 text-hypothesis",
      dot: "border-[1.5px] border-hypothesis bg-transparent",
    },
    confirmed: {
      chip: "border-action bg-action-soft text-action",
      dot: "bg-action",
    },
    proof: {
      chip: "border-ink bg-ink text-white",
      dot: "bg-petrol-on-night-2",
    },
  },
  night: {
    hypothesis: {
      chip: "border-dashed border-violet-on-night bg-night-raised text-violet-on-night-2",
      dot: "border-[1.5px] border-violet-on-night bg-transparent",
    },
    confirmed: {
      chip: "border-petrol-on-night bg-petrol-on-night/16 text-petrol-on-night-2",
      dot: "bg-petrol-on-night",
    },
    proof: {
      chip: "border-on-night bg-on-night text-ink",
      dot: "bg-action",
    },
  },
};

const classes = computed(() => styles[context.value][props.kind]);
</script>

<template>
  <span
    :class="[
      'inline-flex min-h-8 items-center gap-2 rounded-pill border px-3.5 text-[13px] font-medium whitespace-nowrap',
      classes.chip,
    ]"
    :data-claim="kind"
  >
    <span
      :class="['inline-block h-[9px] w-[9px] shrink-0 rounded-full', classes.dot]"
      aria-hidden="true"
    />
    <span>{{ t(`ui.claim.${kind}`) }}</span>
  </span>
</template>
