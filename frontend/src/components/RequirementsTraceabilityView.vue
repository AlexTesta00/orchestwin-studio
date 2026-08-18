<script setup lang="ts">
import { computed } from "vue";

import type {
  RequirementsCoveragePayload,
  RequirementsTraceabilityPayload,
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
    nodes: "Artifacts",
    links: "Traceability links",
    source: "Source",
    relation: "Relation",
    target: "Target",
    coverage: "Coverage",
    full: "All requirements and user stories have acceptance criteria.",
    incomplete: "The specification contains uncovered artifacts.",
    requirementsWithoutStories: "Requirements without user stories",
    requirementsWithoutCriteria: "Requirements without acceptance criteria",
    storiesWithoutCriteria: "User stories without acceptance criteria",
    criteriaWithoutScenarios: "Acceptance criteria without scenarios",
    none: "None",
  },
  it: {
    title: "Tracciabilità e copertura",
    nodes: "Artefatti",
    links: "Collegamenti di tracciabilità",
    source: "Origine",
    relation: "Relazione",
    target: "Destinazione",
    coverage: "Copertura",
    full: "Tutti i requisiti e le user story hanno criteri di accettazione.",
    incomplete: "La specifica contiene artefatti non coperti.",
    requirementsWithoutStories: "Requisiti senza user story",
    requirementsWithoutCriteria: "Requisiti senza criteri di accettazione",
    storiesWithoutCriteria: "User story senza criteri di accettazione",
    criteriaWithoutScenarios: "Criteri di accettazione senza scenari",
    none: "Nessuno",
  },
} as const;

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
  <section
    class="grid gap-5 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
    aria-labelledby="requirements-traceability-title"
  >
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h3 id="requirements-traceability-title" class="text-xl font-black text-slate-950">
          {{ copy.title }}
        </h3>
        <p class="m-0 text-sm text-slate-600">
          {{ traceability.nodes.length }} {{ copy.nodes.toLowerCase() }} ·
          {{ traceability.links.length }} {{ copy.links.toLowerCase() }}
        </p>
      </div>
      <code class="max-w-full rounded bg-slate-100 px-2 py-1 text-xs break-all text-slate-500">
        {{ traceability.content_hash }}
      </code>
    </div>

    <div class="overflow-x-auto">
      <table class="w-full border-collapse text-left text-sm" data-testid="traceability-links">
        <thead>
          <tr class="border-b border-slate-200 text-xs tracking-wide text-slate-500 uppercase">
            <th class="px-2 py-2">{{ copy.source }}</th>
            <th class="px-2 py-2">{{ copy.relation }}</th>
            <th class="px-2 py-2">{{ copy.target }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="link in traceability.links"
            :key="`${referenceKey(link.source)}:${link.kind}:${referenceKey(link.target)}`"
            class="border-b border-slate-100"
          >
            <td class="px-2 py-2 font-bold text-slate-900">
              {{ displayCode(link.source) }}
            </td>
            <td class="px-2 py-2 text-slate-600">{{ link.kind }}</td>
            <td class="px-2 py-2 font-bold text-slate-900">
              {{ displayCode(link.target) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <section class="grid gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4">
      <h4 class="font-black text-slate-950">{{ copy.coverage }}</h4>
      <p
        class="m-0 text-sm font-bold"
        :class="coverage.has_full_acceptance_coverage ? 'text-emerald-700' : 'text-amber-800'"
        data-testid="coverage-status"
      >
        {{ coverage.has_full_acceptance_coverage ? copy.full : copy.incomplete }}
      </p>
      <dl class="grid gap-2 text-sm text-slate-700">
        <div>
          <dt class="font-bold">{{ copy.requirementsWithoutStories }}</dt>
          <dd class="m-0 break-all">
            {{ displayIds(coverage.requirement_ids_without_user_stories) }}
          </dd>
        </div>
        <div>
          <dt class="font-bold">{{ copy.requirementsWithoutCriteria }}</dt>
          <dd class="m-0 break-all">
            {{ displayIds(coverage.requirement_ids_without_acceptance_criteria) }}
          </dd>
        </div>
        <div>
          <dt class="font-bold">{{ copy.storiesWithoutCriteria }}</dt>
          <dd class="m-0 break-all">
            {{ displayIds(coverage.user_story_ids_without_acceptance_criteria) }}
          </dd>
        </div>
        <div>
          <dt class="font-bold">{{ copy.criteriaWithoutScenarios }}</dt>
          <dd class="m-0 break-all">
            {{ displayIds(coverage.acceptance_criterion_ids_without_scenarios) }}
          </dd>
        </div>
      </dl>
    </section>
  </section>
</template>
