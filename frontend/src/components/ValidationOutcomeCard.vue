<script setup lang="ts">
import { computed } from "vue";
import ArtifactWhy from "./ArtifactWhy.vue";
import { humanValidationCopy } from "./humanValidationCopy";
import type { EvidenceFocus, HumanValidationOutcome } from "../types/humanValidation";
import type { ResearchEvidencePayload } from "../types/researchEvidence";

const props = withDefaults(
  defineProps<{
    outcome: HumanValidationOutcome;
    source?: ResearchEvidencePayload | undefined;
    locale?: "it" | "en";
  }>(),
  { locale: "en", source: undefined },
);
const emit = defineEmits<{ "open-evidence": [source: EvidenceFocus] }>();
const copy = computed(() => humanValidationCopy[props.locale]);
</script>

<template>
  <article
    class="grid min-w-0 gap-2 rounded-field border border-night-line p-4 text-sm [overflow-wrap:anywhere]"
    data-testid="validation-outcome"
    :data-session-kind="outcome.session_kind"
    :data-effective-status="outcome.effective_status"
  >
    <div class="flex flex-wrap items-center gap-2">
      <strong>{{ copy.states[outcome.outcome] }}</strong>
      <span class="rounded-pill border border-night-line-strong px-2 py-1 text-xs">{{
        outcome.session_kind === "HUMAN_SESSION" ? copy.human : copy.synthetic
      }}</span>
      <strong
        v-if="outcome.effective_status === 'RETIRED'"
        class="text-warn-on-night"
        data-testid="validation-retired-outcome"
        >{{ copy.retired }}</strong
      >
      <span
        v-if="outcome.coverage === 'PARTIAL'"
        class="text-warn-on-night"
        data-testid="validation-partial"
        >{{ copy.partial }}</span
      >
    </div>
    <p class="m-0 text-xs text-on-night-2">
      {{ outcome.session_ref }} · {{ copy.version }} {{ outcome.hypothesis_version_number }}
    </p>
    <blockquote
      class="m-0 border-l-2 border-petrol-on-night/60 pl-3 whitespace-pre-wrap"
      data-testid="validation-quote"
    >
      {{ outcome.citation.quote }}
    </blockquote>
    <p class="m-0 whitespace-pre-wrap text-on-night-2">{{ outcome.limitations }}</p>
    <p v-if="outcome.effective_status === 'RETIRED'" class="m-0 text-xs text-on-night-2">
      {{ copy.retiredHelp }}
    </p>
    <p
      v-if="outcome.effective_status === 'SOURCE_UNAVAILABLE'"
      class="m-0 text-xs text-warn-on-night"
    >
      {{ copy.missingSource }}
    </p>
    <p v-if="outcome.source_text_available === false" class="m-0 text-xs text-on-night-2">
      {{ copy.sourceUnavailable }}
    </p>
    <details class="text-xs">
      <summary tabindex="0" class="flex min-h-11 cursor-pointer items-center font-semibold">
        {{ copy.source }} · {{ source?.title ?? source?.code ?? outcome.code }}
      </summary>
      <dl class="m-0 grid gap-2 pb-2">
        <div>
          <dt class="font-semibold">{{ copy.version }}</dt>
          <dd class="m-0">{{ outcome.evidence_version }}</dd>
        </div>
        <div v-if="source">
          <dt class="font-semibold">{{ copy.sourceContext }}</dt>
          <dd class="m-0 whitespace-pre-wrap">{{ source.context }}</dd>
        </div>
        <div v-if="source">
          <dt class="font-semibold">{{ copy.sourceMethod }}</dt>
          <dd class="m-0 whitespace-pre-wrap">{{ source.method }}</dd>
        </div>
        <div v-if="source?.collected_at">
          <dt class="font-semibold">{{ copy.sourceDate }}</dt>
          <dd class="m-0">{{ source.collected_at }}</dd>
        </div>
        <div v-if="source">
          <dt class="font-semibold">{{ copy.limitations }}</dt>
          <dd class="m-0 whitespace-pre-wrap">{{ source.limitations }}</dd>
        </div>
      </dl>
      <p class="m-0 font-mono break-all">{{ outcome.evidence_content_hash }}</p>
      <p class="m-0 font-mono break-all">{{ outcome.hypothesis_content_hash }}</p>
    </details>
    <button
      type="button"
      class="min-h-11 justify-self-start text-left font-semibold text-petrol-on-night-2 underline underline-offset-4"
      data-testid="validation-return-evidence"
      @click="emit('open-evidence', { id: outcome.evidence_id, version: outcome.evidence_version })"
    >
      {{ copy.returnEvidence }}
    </button>
    <ArtifactWhy
      :code="outcome.code"
      kind="VALIDATION_OUTCOME"
      :artifact-id="outcome.id"
      :content-hash="outcome.content_hash"
      :version-number="1"
      :locale="locale"
      test-id="validation-outcome-why"
    />
  </article>
</template>
