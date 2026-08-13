<script setup lang="ts">
import { computed } from "vue";

import type { EpistemicStatus, HumanValidationRequirement } from "../types/userModeling";

type Locale = "en" | "it";

const props = withDefaults(
  defineProps<{
    status: EpistemicStatus;
    confidence: number;
    humanValidation: HumanValidationRequirement;
    locale?: Locale;
  }>(),
  {
    locale: "en",
  },
);

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

const statusClassByStatus: Record<EpistemicStatus, string> = {
  USER_PROVIDED: "border-blue-300 bg-blue-50 text-blue-800",

  EMPIRICALLY_SUPPORTED: "border-emerald-300 bg-emerald-50 text-emerald-800",

  HUMAN_VALIDATED: "border-teal-300 bg-teal-50 text-teal-800",

  MODEL_INFERRED: "border-violet-300 bg-violet-50 text-violet-800",

  UNSUPPORTED_ASSUMPTION: "border-amber-300 bg-amber-50 text-amber-900",
};

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

const statusClasses = computed(() => statusClassByStatus[props.status]);
</script>

<template>
  <div class="flex flex-wrap items-center gap-2">
    <span
      data-testid="epistemic-status"
      class="inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold"
      :class="statusClasses"
    >
      {{ statusLabel }}
    </span>

    <span class="text-xs font-medium text-slate-600">
      {{ confidenceLabel }}
      {{ confidencePercent }}%
    </span>

    <progress
      class="h-2 w-20 overflow-hidden rounded-full"
      :value="confidencePercent"
      max="100"
      :aria-label="`${confidenceLabel}: ${confidencePercent}%`"
    />

    <span
      class="inline-flex items-center gap-1 text-xs text-slate-600"
      data-testid="human-validation"
    >
      <span
        aria-hidden="true"
        class="h-2 w-2 rounded-full"
        :class="humanValidation === 'REQUIRED' ? 'bg-amber-500' : 'bg-emerald-500'"
      />

      {{ validationLabel }}
    </span>
  </div>
</template>
