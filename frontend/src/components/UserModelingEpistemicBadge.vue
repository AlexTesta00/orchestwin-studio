<script setup lang="ts">
import { computed } from "vue";

import { useSurface, type SurfaceContext } from "./UiSurface.vue";
import type { EpistemicStatus, HumanValidationRequirement } from "../types/userModeling";

type Locale = "en" | "it";

const props = withDefaults(
  defineProps<{
    status: EpistemicStatus;
    confidence: number;
    humanValidation: HumanValidationRequirement;
    locale?: Locale;
    surface?: SurfaceContext | undefined;
  }>(),
  {
    locale: "en",
    surface: undefined,
  },
);

const context = useSurface(() => props.surface);

const statusLabels: Record<Locale, Record<EpistemicStatus, string>> = {
  en: {
    USER_PROVIDED: "User provided",
    EMPIRICALLY_SUPPORTED: "Empirically supported",
    HUMAN_VALIDATED: "Human validated",
    MODEL_INFERRED: "Model inferred",
    UNSUPPORTED_ASSUMPTION: "Unsupported assumption",
  },

  it: {
    USER_PROVIDED: "Fornito dall'utente",
    EMPIRICALLY_SUPPORTED: "Supportato empiricamente",
    HUMAN_VALIDATED: "Validato da una persona",
    MODEL_INFERRED: "Inferito dal modello",
    UNSUPPORTED_ASSUMPTION: "Assunzione non supportata",
  },
};

const statusClasses: Record<"light" | "night", Record<EpistemicStatus, string>> = {
  light: {
    USER_PROVIDED: "border-action-soft-line bg-action-soft text-ink-2",
    EMPIRICALLY_SUPPORTED: "border-ok-line bg-ok-bg text-ok-dark",
    HUMAN_VALIDATED: "border-action bg-action-soft text-action",
    MODEL_INFERRED: "border-dashed border-hypothesis-line bg-hypothesis-bg text-hypothesis",
    UNSUPPORTED_ASSUMPTION: "border-dashed border-line-strong bg-surface-2 text-warn",
  },
  night: {
    USER_PROVIDED: "border-petrol-on-night/60 bg-petrol-on-night/10 text-petrol-on-night-2",
    EMPIRICALLY_SUPPORTED: "border-petrol-on-night bg-petrol-on-night/16 text-petrol-on-night-2",
    HUMAN_VALIDATED: "border-petrol-on-night bg-petrol-on-night/16 text-petrol-on-night-2",
    MODEL_INFERRED:
      "border-dashed border-violet-on-night bg-violet-on-night/10 text-violet-on-night-2",
    UNSUPPORTED_ASSUMPTION:
      "border-dashed border-warn-on-night/70 bg-warn-on-night/10 text-warn-on-night",
  },
};

const palettes = {
  light: {
    text: "text-ink-2",
    track: "bg-surface-3",
    fill: "bg-action",
    required: "bg-warn",
    optional: "bg-ok",
  },
  night: {
    text: "text-on-night-2",
    track: "bg-night-hover",
    fill: "bg-petrol-on-night",
    required: "bg-warn-on-night",
    optional: "bg-petrol-on-night",
  },
};

const palette = computed(() => palettes[context.value]);

const confidenceLabel = computed(() => (props.locale === "it" ? "Confidenza" : "Confidence"));

const validationLabel = computed(() => {
  if (props.humanValidation === "REQUIRED") {
    return props.locale === "it" ? "Validazione umana richiesta" : "Human validation required";
  }

  return props.locale === "it"
    ? "Nessuna validazione aggiuntiva richiesta"
    : "No additional human validation required";
});

const statusLabel = computed(() => statusLabels[props.locale][props.status]);

const confidencePercent = computed(() => {
  const bounded = Math.min(1, Math.max(0, props.confidence));

  return Math.round(bounded * 100);
});
</script>

<template>
  <div class="flex flex-wrap items-center gap-x-3 gap-y-2" :data-surface-context="context">
    <span
      data-testid="epistemic-status"
      class="inline-flex min-h-6 items-center rounded-pill border px-2.5 text-xs font-semibold"
      :class="statusClasses[context][status]"
    >
      {{ statusLabel }}
    </span>

    <span class="inline-flex items-center gap-2 text-xs font-medium" :class="palette.text">
      {{ confidenceLabel }}
      {{ confidencePercent }}%
      <span
        role="progressbar"
        class="relative inline-block h-1.5 w-16 overflow-hidden rounded-pill"
        :class="palette.track"
        :aria-label="`${confidenceLabel}: ${confidencePercent}%`"
        :aria-valuenow="confidencePercent"
        aria-valuemin="0"
        aria-valuemax="100"
      >
        <span
          class="absolute inset-y-0 left-0 rounded-pill"
          :class="palette.fill"
          :style="{ width: `${confidencePercent}%` }"
        />
      </span>
    </span>

    <span
      class="inline-flex items-center gap-1.5 text-xs"
      :class="palette.text"
      data-testid="human-validation"
    >
      <span
        aria-hidden="true"
        class="size-2 rounded-full"
        :class="humanValidation === 'REQUIRED' ? palette.required : palette.optional"
      />

      {{ validationLabel }}
    </span>
  </div>
</template>
