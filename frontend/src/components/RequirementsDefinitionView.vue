<script setup lang="ts">
import { computed, ref } from "vue";

import type {
  RequirementSourcePayload,
  RequirementsSpecificationPayload,
} from "../types/requirements";
import { useSurface } from "./UiSurface.vue";

const props = withDefaults(
  defineProps<{
    specification: RequirementsSpecificationPayload;
    locale?: "en" | "it";
    highlighted?: string | null;
  }>(),
  { locale: "en" },
);
const emit = defineEmits<{ "select-item": [code: string] }>();
const opened = ref(new Set<string>());
const surface = useSurface(() => undefined);
const messages = {
  en: {
    scenarios: "Scenarios",
    needs: "Needs",
    stories: "User stories",
    actor: "Actor",
    context: "Context",
    goal: "Goal",
    trigger: "Trigger",
    steps: "Steps",
    criticalities: "Potential difficulties",
    sources: "Sources",
    preconditions: "Preconditions",
    outcome: "Expected outcome",
    benefit: "Benefit",
    requirements: "Requirements",
    code: "Code",
    version: "Version",
    warning:
      "This definition comes from the brief and the twins: it still needs to be checked with real users.",
    legacy: "Needs were not recorded in this definition. Ask for a new definition to add them.",
    sourceKinds: {
      PROJECT_BRIEF: "Project brief",
      USER_TWIN: "User twin",
      OWNER_INPUT: "Owner input",
      MODEL_PROPOSAL: "Model proposal",
      SYSTEM_ARTIFACT: "System artifact",
    },
  },
  it: {
    scenarios: "Scenari",
    needs: "Bisogni",
    stories: "Storie",
    actor: "Attore",
    context: "Contesto",
    goal: "Obiettivo",
    trigger: "Evento iniziale",
    steps: "Passi",
    criticalities: "Criticità",
    sources: "Fonti",
    preconditions: "Precondizioni",
    outcome: "Risultato atteso",
    benefit: "Beneficio",
    requirements: "Requisiti",
    code: "Codice",
    version: "Versione",
    warning:
      "Questa definizione deriva dal brief e dai twin: resta da verificare con utenti reali.",
    legacy:
      "I bisogni non erano registrati in questa definizione. Chiedi una nuova definizione per aggiungerli.",
    sourceKinds: {
      PROJECT_BRIEF: "Brief di progetto",
      USER_TWIN: "Twin utente",
      OWNER_INPUT: "Indicazione del committente",
      MODEL_PROPOSAL: "Proposta del modello",
      SYSTEM_ARTIFACT: "Artefatto di sistema",
    },
  },
} as const;
const copy = computed(() => messages[props.locale]);
const needs = computed(() => props.specification.needs ?? []);
const itemById = computed(
  () =>
    new Map([
      ...props.specification.scenarios.map(
        (item) => [item.id, { code: item.code, title: item.title }] as const,
      ),
      ...needs.value.map((item) => [item.id, { code: item.code, title: item.title }] as const),
      ...props.specification.user_stories.map(
        (item) => [item.id, { code: item.code, title: item.goal }] as const,
      ),
      ...props.specification.requirements.map(
        (item) => [item.id, { code: item.code, title: item.title }] as const,
      ),
    ]),
);
const sections = computed(() => {
  const text = copy.value;
  return [
    {
      key: "scenarios",
      title: text.scenarios,
      items: props.specification.scenarios.map((item) => ({
        id: item.id,
        code: item.code,
        title: item.title,
        fields: [
          [text.actor, item.actor.name],
          [text.context, item.context],
          [text.goal, item.goal],
          [text.trigger, item.trigger],
          [text.preconditions, item.preconditions.join("\n")],
          [text.steps, item.steps.map((step, index) => `${index + 1}. ${step}`).join("\n")],
          [text.criticalities, item.criticalities?.join("\n")],
          [text.outcome, item.expected_outcome],
        ],
        links: [
          [
            text.needs,
            needs.value
              .filter((need) => need.scenario_ids.includes(item.id))
              .map((need) => need.id),
          ],
          [text.requirements, item.requirement_ids],
        ] as const,
        sources: item.sources ?? [],
      })),
    },
    {
      key: "needs",
      title: text.needs,
      items: needs.value.map((item) => ({
        id: item.id,
        code: item.code,
        title: item.title,
        fields: [[text.needs, item.statement]],
        links: [
          [text.scenarios, item.scenario_ids],
          [
            text.stories,
            props.specification.user_stories
              .filter((story) => story.need_ids?.includes(item.id))
              .map((story) => story.id),
          ],
          [
            text.requirements,
            props.specification.requirements
              .filter((requirement) => requirement.need_ids?.includes(item.id))
              .map((requirement) => requirement.id),
          ],
        ] as const,
        sources: item.sources,
      })),
    },
    {
      key: "stories",
      title: text.stories,
      items: props.specification.user_stories.map((item) => ({
        id: item.id,
        code: item.code,
        title: item.goal,
        fields: [
          [text.actor, item.user_twin_reference.name],
          [text.benefit, item.benefit],
        ],
        links: [
          [text.needs, item.need_ids ?? []],
          [text.requirements, item.requirement_ids],
        ] as const,
        sources: [] as RequirementSourcePayload[],
      })),
    },
  ];
});

function links(ids: readonly string[]) {
  return ids.flatMap((id) => {
    const item = itemById.value.get(id);
    return item ? [item] : [];
  });
}
function sourceDetails(source: RequirementSourcePayload): string {
  return [
    source.locator,
    source.source_id,
    source.source_version === null ? null : `${copy.value.version} ${source.source_version}`,
    source.content_hash,
  ]
    .filter(Boolean)
    .join(" · ");
}
function toggle(code: string, event: Event): void {
  if (!(event.target instanceof HTMLDetailsElement)) return;
  if (event.target.open) opened.value.add(code);
  else opened.value.delete(code);
}
function openItem(code: string): void {
  opened.value.add(code);
}
defineExpose({ openItem });
</script>

<template>
  <div
    class="grid max-w-full min-w-0 gap-4 [overflow-wrap:anywhere]"
    data-testid="requirements-definition-chain"
  >
    <p class="m-0 text-sm leading-normal" data-testid="definition-validation-warning">
      {{ copy.warning }}
    </p>
    <section
      v-for="section in sections"
      :key="section.key"
      class="grid max-w-full min-w-0 gap-2"
      :data-testid="`definition-section-${section.key}`"
    >
      <h2 class="m-0 text-lg font-semibold">
        {{ section.title }} <span class="text-sm font-normal">· {{ section.items.length }}</span>
      </h2>
      <p
        v-if="section.key === 'needs' && needs.length === 0"
        class="m-0 text-sm leading-normal"
        data-testid="definition-legacy-needs"
      >
        {{ copy.legacy }}
      </p>
      <details
        v-for="item in section.items"
        :key="item.id"
        :open="opened.has(item.code)"
        :data-requirements-item="item.code"
        :data-testid="`definition-${section.key}-item`"
        tabindex="-1"
        :class="[
          'group max-w-full min-w-0 rounded-tile border p-4',
          surface === 'night' ? 'border-night-line bg-night-raised' : 'border-line bg-surface',
          highlighted === item.code ? 'bg-petrol-on-night/12 ring-1 ring-petrol-on-night/60' : '',
        ]"
        @toggle="toggle(item.code, $event)"
      >
        <summary class="cursor-pointer text-base font-semibold">{{ item.title }}</summary>
        <div class="mt-3 grid max-w-full min-w-0 gap-3 text-sm leading-normal">
          <template v-for="([label, value], index) in item.fields" :key="index">
            <p v-if="value" class="m-0 whitespace-pre-line">
              <strong>{{ label }}:</strong> {{ value }}
            </p>
          </template>
          <p
            v-for="([label, ids], index) in item.links.filter(([, ids]) => ids.length > 0)"
            :key="index"
            class="m-0"
          >
            <strong>{{ label }}:</strong>{{ " " }}
            <template v-for="(linked, linkIndex) in links(ids)" :key="linked.code">
              <span v-if="linkIndex > 0"> · </span>
              <button
                type="button"
                class="max-w-full cursor-pointer text-left underline"
                @click="emit('select-item', linked.code)"
              >
                {{ linked.title }}
              </button>
            </template>
          </p>
          <div
            v-if="item.sources.length > 0"
            class="max-w-full min-w-0"
            data-testid="definition-sources"
          >
            <strong>{{ copy.sources }}:</strong>
            <ul class="m-0 grid max-w-full min-w-0 gap-1 pl-5">
              <li v-for="(source, index) in item.sources" :key="index" class="min-w-0">
                <span>{{ copy.sourceKinds[source.kind] }}</span
                ><span class="block text-xs">{{ sourceDetails(source) }}</span>
              </li>
            </ul>
          </div>
          <p class="m-0 font-mono text-xs">{{ copy.code }}: {{ item.code }}</p>
        </div>
      </details>
    </section>
  </div>
</template>
