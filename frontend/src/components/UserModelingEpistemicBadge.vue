<script setup lang="ts">
import { computed } from "vue";
import { observationDisplayStatus } from "./twinRepresentation";
import { useSurface, type SurfaceContext } from "./UiSurface.vue";
import type {
  EpistemicStatus,
  HumanValidationRequirement,
  ProfileObservationPayload,
  ReadableClaimStatus,
} from "../types/userModeling";

const props = withDefaults(
  defineProps<{
    status: EpistemicStatus | ReadableClaimStatus;
    confidence?: number;
    humanValidation?: HumanValidationRequirement;
    observation?: ProfileObservationPayload | undefined;
    showDetails?: boolean;
    locale?: "en" | "it";
    surface?: SurfaceContext | undefined;
  }>(),
  {
    confidence: 0,
    humanValidation: "NOT_REQUIRED",
    observation: undefined,
    showDetails: true,
    locale: "en",
    surface: undefined,
  },
);
const context = useSurface(() => props.surface);
const labels = {
  en: {
    EVIDENCED: "Evidenced",
    INFERRED: "Inferred",
    HYPOTHESIZED: "Hypothesized",
    CONTESTED: "Contested",
    UNKNOWN: "Unknown",
  },
  it: {
    EVIDENCED: "Documentato",
    INFERRED: "Dedotto",
    HYPOTHESIZED: "Ipotizzato",
    CONTESTED: "Contestato",
    UNKNOWN: "Sconosciuto",
  },
};
const readable = computed<ReadableClaimStatus>(() => {
  if (props.observation !== undefined) return observationDisplayStatus(props.observation);
  if (props.status in labels.en) return props.status as ReadableClaimStatus;
  return props.status === "MODEL_INFERRED" ? "INFERRED" : "HYPOTHESIZED";
});
const statusClass = computed(() => {
  if (context.value === "night") {
    if (readable.value === "EVIDENCED")
      return "border-petrol-on-night bg-petrol-on-night/16 text-petrol-on-night-2";
    if (readable.value === "CONTESTED")
      return "border-warn-on-night/70 bg-warn-on-night/10 text-warn-on-night";
    if (readable.value === "UNKNOWN") return "border-night-line bg-night-raised text-on-night-3";
    return "border-dashed border-violet-on-night bg-violet-on-night/10 text-violet-on-night-2";
  }
  if (readable.value === "EVIDENCED") return "border-ok-line bg-ok-bg text-ok-dark";
  if (readable.value === "CONTESTED") return "border-hypothesis-line bg-hypothesis-bg text-warn";
  return "border-dashed border-line-strong bg-surface-2 text-ink-2";
});
const confidenceLabel = computed(() => (props.locale === "it" ? "Confidenza" : "Confidence"));
const confidencePercent = computed(() =>
  Math.round(Math.min(1, Math.max(0, props.confidence)) * 100),
);
const validationLabel = computed(() =>
  props.humanValidation === "REQUIRED"
    ? props.locale === "it"
      ? "Validazione umana richiesta"
      : "Human validation required"
    : props.locale === "it"
      ? "Nessuna validazione umana aggiuntiva richiesta"
      : "No additional human validation required",
);
</script>

<template>
  <div class="flex flex-wrap items-center gap-x-3 gap-y-2" :data-surface-context="context">
    <span
      data-testid="epistemic-status"
      class="inline-flex min-h-6 items-center rounded-pill border px-2.5 text-xs font-semibold"
      :class="statusClass"
      >{{ labels[locale][readable] }}</span
    >
    <template v-if="showDetails">
      <span
        class="inline-flex items-center gap-2 text-xs font-medium"
        :class="context === 'night' ? 'text-on-night-2' : 'text-ink-2'"
      >
        {{ confidenceLabel }} {{ confidencePercent }}%
        <span
          role="progressbar"
          class="relative inline-block h-1.5 w-16 overflow-hidden rounded-pill"
          :class="context === 'night' ? 'bg-night-hover' : 'bg-surface-3'"
          :aria-label="`${confidenceLabel}: ${confidencePercent}%`"
          :aria-valuenow="confidencePercent"
          aria-valuemin="0"
          aria-valuemax="100"
        >
          <span
            class="absolute inset-y-0 left-0 rounded-pill"
            :class="context === 'night' ? 'bg-petrol-on-night' : 'bg-action'"
            :style="{ width: `${confidencePercent}%` }"
          />
        </span>
      </span>
      <span
        class="text-xs"
        :class="context === 'night' ? 'text-on-night-2' : 'text-ink-2'"
        data-testid="human-validation"
        >{{ validationLabel }}</span
      >
    </template>
  </div>
</template>
