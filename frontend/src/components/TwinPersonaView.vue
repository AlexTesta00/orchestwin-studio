<script setup lang="ts">
import { computed } from "vue";
import UserModelingEpistemicBadge from "./UserModelingEpistemicBadge.vue";
import UserModelingProvenanceInspector from "./UserModelingProvenanceInspector.vue";
import ArtifactWhy from "./ArtifactWhy.vue";
import { twinClaimCode } from "./whyContext";
import { claimText, twinRepresentation } from "./twinRepresentation";
import type { PersonaVersionPayload, UserTwinVersionPayload } from "../types/userModeling";

const props = withDefaults(
  defineProps<{
    twin: UserTwinVersionPayload;
    persona?: PersonaVersionPayload | undefined;
    locale?: "en" | "it";
    showDescription?: boolean;
  }>(),
  { persona: undefined, locale: "en", showDescription: true },
);
const view = computed(() => twinRepresentation(props.twin, props.persona));
const copy = computed(() =>
  props.locale === "it"
    ? {
        PROVISIONAL: "Provvisorio",
        EVIDENCE_BASED: "Fondato su evidenze",
        provenance: "Provenienza",
        represents: "Rappresenta",
        does_not_represent: "Non rappresenta",
        contexts: "Contesti coperti",
        evidence_gaps: "Limiti delle evidenze",
        description: "Descrizione",
        goals: "Obiettivi",
        needs: "Bisogni",
        behaviours: "Comportamenti",
        pain_points: "Difficoltà",
        constraints: "Vincoli",
        persona: "Persona",
        note: "Il brief e le scelte del proprietario non sono evidenze su utenti reali.",
      }
    : {
        PROVISIONAL: "Provisional",
        EVIDENCE_BASED: "Evidence based",
        provenance: "Provenance",
        represents: "Represents",
        does_not_represent: "Does not represent",
        contexts: "Covered contexts",
        evidence_gaps: "Evidence gaps",
        description: "Description",
        goals: "Goals",
        needs: "Needs",
        behaviours: "Behaviours",
        pain_points: "Pain points",
        constraints: "Constraints",
        persona: "Persona",
        note: "The brief and the owner's choices are not evidence about real users.",
      },
);
const representationFields = [
  "represents",
  "does_not_represent",
  "contexts",
  "evidence_gaps",
] as const;
const personaFields = [
  "description",
  "goals",
  "needs",
  "behaviours",
  "pain_points",
  "constraints",
  "contexts",
] as const;
</script>

<template>
  <section
    class="grid gap-3"
    :data-testid="`twin-representation-${twin.twin_id}`"
    :aria-label="twin.profile.name"
  >
    <strong
      class="text-sm"
      :class="view.basis === 'PROVISIONAL' ? 'text-violet-on-night-2' : 'text-petrol-on-night-2'"
      >{{ copy[view.basis] }}</strong
    >
    <p v-if="showDescription" class="m-0 text-[15px] leading-normal">
      {{ claimText(view.persona.description, locale) }}
    </p>
    <p v-if="view.basis === 'PROVISIONAL'" class="m-0 text-xs leading-5 text-on-night-3">
      {{ copy.note }}
    </p>
    <dl class="m-0 grid gap-3 text-sm">
      <div v-for="field in representationFields" :key="field" class="grid gap-1">
        <dt class="font-semibold text-on-night-2">{{ copy[field] }}</dt>
        <dd class="m-0 grid gap-1.5">
          <span>{{ claimText(view[field], locale) }}</span>
          <ArtifactWhy
            :code="twinClaimCode(twin.twin_id, twin.version_number, view[field].observation_key)"
            :title="copy[field]"
            kind="USER_TWIN_CLAIM"
            :artifact-id="twin.twin_id"
            :version-number="twin.version_number"
            :content-hash="twin.content_hash"
            :locale="locale"
            :test-id="`representation-chain-why-${twin.twin_id}-${field}`"
          />
          <UserModelingProvenanceInspector
            :observation="view[field]"
            :locale="locale"
            :summary-label="`${copy.provenance} ${copy[field]}`"
          />
        </dd>
      </div>
    </dl>
    <details
      class="rounded-field border border-night-line bg-night-raised"
      :data-testid="`twin-persona-${twin.twin_id}`"
    >
      <summary class="flex min-h-11 cursor-pointer items-center px-3 text-sm font-semibold">
        {{ copy.persona }}
      </summary>
      <dl class="m-0 grid gap-4 border-t border-night-line p-3">
        <div v-for="field in personaFields" :key="field" class="grid gap-1.5">
          <dt class="text-sm font-semibold">{{ copy[field] }}</dt>
          <dd class="m-0 grid gap-2 text-sm">
            <span>{{ claimText(view.persona[field], locale) }}</span>
            <UserModelingEpistemicBadge
              :status="view.persona[field].display_status"
              :show-details="false"
              :locale="locale"
            />
            <ArtifactWhy
              :code="
                twinClaimCode(
                  twin.twin_id,
                  twin.version_number,
                  `user_twin.${{ description: 'description', goals: 'goals', needs: 'information_needs', behaviours: 'recurring_tasks', pain_points: 'pain_points', constraints: 'operational_constraints', contexts: 'context_of_use' }[field]}`,
                )
              "
              :title="copy[field]"
              kind="USER_TWIN_CLAIM"
              :artifact-id="twin.twin_id"
              :version-number="twin.version_number"
              :content-hash="twin.content_hash"
              :locale="locale"
              :test-id="`persona-chain-why-${twin.twin_id}-${field}`"
            />
            <UserModelingProvenanceInspector
              :observation="view.persona[field]"
              :locale="locale"
              :summary-label="`${copy.provenance} ${copy[field]}`"
              :test-id="`persona-why-${twin.twin_id}-${field}`"
            />
          </dd>
        </div>
      </dl>
    </details>
  </section>
</template>
