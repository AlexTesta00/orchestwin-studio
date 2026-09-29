<script setup lang="ts">
import { computed, useId } from "vue";

import { useSurface } from "./UiSurface.vue";
import type {
  RequirementsCoveragePayload,
  RequirementsTraceabilityPayload,
  TraceabilityLinkKind,
  TraceabilityNodeReferencePayload,
} from "../types/requirements";

type Locale = "en" | "it";

const props = withDefaults(
  defineProps<{
    traceability: RequirementsTraceabilityPayload;
    coverage: RequirementsCoveragePayload;
    locale?: Locale;
  }>(),
  {
    locale: "en",
  },
);

const messages = {
  en: {
    title: "Traceability and coverage",
    nodes: "items",
    links: "links",
    source: "From",
    relation: "Relation",
    target: "To",
    coverage: "Coverage",
    full: "Every requirement and user story has an acceptance criterion.",
    incomplete: "Some items are not covered yet.",
    requirementsWithoutStories: "Requirements without user stories",
    requirementsWithoutCriteria: "Requirements without acceptance criteria",
    storiesWithoutCriteria: "User stories without acceptance criteria",
    criteriaWithoutScenarios: "Acceptance criteria without scenarios",
    none: "None",
    kinds: {
      ACTS_AS: "acts as",
      MOTIVATES: "motivates",
      VERIFIED_BY: "is verified by",
      EXERCISES: "exercises",
      AFFECTS: "affects",
      GOVERNS: "governs",
    },
  },
  it: {
    title: "Tracciabilità e copertura",
    nodes: "elementi",
    links: "collegamenti",
    source: "Da",
    relation: "Relazione",
    target: "A",
    coverage: "Copertura",
    full: "Ogni requisito e ogni storia dell'utente hanno un criterio di accettazione.",
    incomplete: "Alcuni elementi non sono ancora coperti.",
    requirementsWithoutStories: "Requisiti senza storie dell'utente",
    requirementsWithoutCriteria: "Requisiti senza criteri di accettazione",
    storiesWithoutCriteria: "Storie dell'utente senza criteri di accettazione",
    criteriaWithoutScenarios: "Criteri di accettazione senza scenari",
    none: "Nessuno",
    kinds: {
      ACTS_AS: "interpreta",
      MOTIVATES: "motiva",
      VERIFIED_BY: "è verificato da",
      EXERCISES: "mette alla prova",
      AFFECTS: "riguarda",
      GOVERNS: "regola",
    },
  },
} as const;

const palettes = {
  light: {
    title: "text-ink",
    muted: "text-ink-3",
    line: "border-line",
    code: "text-ink",
    cell: "text-ink-2",
    full: "text-ok-dark",
    incomplete: "text-warn",
  },
  night: {
    title: "text-on-night",
    muted: "text-on-night-3",
    line: "border-night-line",
    code: "text-on-night",
    cell: "text-on-night-2",
    full: "text-petrol-on-night-2",
    incomplete: "text-warn-on-night",
  },
};

const titleId = `requirements-traceability-${useId()}`;
const surface = useSurface(() => undefined);
const palette = computed(() => palettes[surface.value]);
const copy = computed(() => messages[props.locale]);
const codeByReference = computed(() => {
  const values = new Map<string, string>();

  for (const node of props.traceability.nodes) {
    values.set(referenceKey(node.reference), node.display_code);
  }

  return values;
});

function referenceKey(reference: TraceabilityNodeReferencePayload): string {
  return `${reference.kind}:${reference.artifact_id}`;
}

function displayCode(reference: TraceabilityNodeReferencePayload): string {
  return codeByReference.value.get(referenceKey(reference)) ?? reference.artifact_id;
}

function relation(kind: TraceabilityLinkKind): string {
  return copy.value.kinds[kind];
}

function displayIds(values: string[]): string {
  if (values.length === 0) {
    return copy.value.none;
  }

  const codes = values.map((artifactId) => {
    const node = props.traceability.nodes.find(
      (candidate) => candidate.reference.artifact_id === artifactId,
    );

    return node?.display_code ?? artifactId;
  });

  return codes.join(", ");
}
</script>

<template>
  <section class="grid gap-4">
    <div class="grid gap-1">
      <h2 :id="titleId" :class="['m-0 text-sm font-semibold', palette.title]">
        {{ copy.title }}
      </h2>
      <p :class="['m-0 text-[13px]', palette.muted]">
        {{ traceability.nodes.length }} {{ copy.nodes }} · {{ traceability.links.length }}
        {{ copy.links }}
      </p>
      <code :class="['font-mono text-xs break-all', palette.muted]">
        {{ traceability.content_hash }}
      </code>
    </div>

    <div class="overflow-x-auto" role="region" tabindex="0" :aria-labelledby="titleId">
      <table class="w-full border-collapse text-left text-[13px]" data-testid="traceability-links">
        <thead>
          <tr :class="['border-b', palette.line, palette.muted]">
            <th scope="col" class="px-2 py-2 font-medium">{{ copy.source }}</th>
            <th scope="col" class="px-2 py-2 font-medium">{{ copy.relation }}</th>
            <th scope="col" class="px-2 py-2 font-medium">{{ copy.target }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="link in traceability.links"
            :key="`${referenceKey(link.source)}:${link.kind}:${referenceKey(link.target)}`"
            :class="['border-b', palette.line]"
          >
            <td :class="['px-2 py-2 font-mono text-xs', palette.code]">
              {{ displayCode(link.source) }}
            </td>
            <td :class="['px-2 py-2', palette.cell]">{{ relation(link.kind) }}</td>
            <td :class="['px-2 py-2 font-mono text-xs', palette.code]">
              {{ displayCode(link.target) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="grid gap-2">
      <h3 :class="['m-0 text-[13px] font-semibold', palette.title]">{{ copy.coverage }}</h3>
      <p
        :class="[
          'm-0 text-[13px] font-semibold',
          coverage.has_full_acceptance_coverage ? palette.full : palette.incomplete,
        ]"
        data-testid="coverage-status"
      >
        {{ coverage.has_full_acceptance_coverage ? copy.full : copy.incomplete }}
      </p>
      <dl :class="['m-0 grid gap-2 text-[13px]', palette.cell]">
        <div>
          <dt class="font-medium">{{ copy.requirementsWithoutStories }}</dt>
          <dd class="m-0 font-mono text-xs break-all">
            {{ displayIds(coverage.requirement_ids_without_user_stories) }}
          </dd>
        </div>
        <div>
          <dt class="font-medium">{{ copy.requirementsWithoutCriteria }}</dt>
          <dd class="m-0 font-mono text-xs break-all">
            {{ displayIds(coverage.requirement_ids_without_acceptance_criteria) }}
          </dd>
        </div>
        <div>
          <dt class="font-medium">{{ copy.storiesWithoutCriteria }}</dt>
          <dd class="m-0 font-mono text-xs break-all">
            {{ displayIds(coverage.user_story_ids_without_acceptance_criteria) }}
          </dd>
        </div>
        <div>
          <dt class="font-medium">{{ copy.criteriaWithoutScenarios }}</dt>
          <dd class="m-0 font-mono text-xs break-all">
            {{ displayIds(coverage.acceptance_criterion_ids_without_scenarios) }}
          </dd>
        </div>
      </dl>
    </div>
  </section>
</template>
