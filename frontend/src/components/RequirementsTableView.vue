<script setup lang="ts">
import { computed } from "vue";

import ArtifactTable, { type ArtifactTableColumn } from "./ArtifactTable.vue";
import { useSurface } from "./UiSurface.vue";
import type {
  DefinitionOfDoneItemPayload,
  RequirementPriority,
  RequirementsSpecificationPayload,
  UserTwinVersionReferencePayload,
} from "../types/requirements";

type Locale = "en" | "it";

interface TableSection {
  key: string;
  title: string;
  description: string;
  columns: ArtifactTableColumn[];
  rows: Record<string, string>[];
}

interface CodedItem {
  id: string;
  code: string;
}

interface RequirementLinkedItem {
  code: string;
  requirement_ids: readonly string[];
}

const EM_DASH = "—";

const PRIORITY_ORDER: Record<RequirementPriority, number> = {
  MUST: 1,
  SHOULD: 2,
  COULD: 3,
  WONT_FOR_NOW: 4,
};

const props = withDefaults(
  defineProps<{
    specification: RequirementsSpecificationPayload;
    locale?: Locale;
  }>(),
  { locale: "en" },
);

const messages = {
  en: {
    needs: { title: "Needs", description: "Needs linked to their scenarios and sources." },
    journeys: {
      title: "Journey",
      description: "Ordered phases linked to a scenario and its needs.",
    },
    phase: "Phase",
    action: "Action",
    touchpoint: "Touchpoint",
    noNeeds: "Needs were not recorded in this definition.",
    context: "Context",
    criticalities: "Potential difficulties",
    sources: "Sources",
    actor: "Actor",
    needsColumn: "Needs",
    scenariosColumn: "Scenarios",
    requirements: {
      title: "Requirements",
      description:
        "Each row is one thing the app must do or respect, who it is for and how it will be checked.",
    },
    stories: {
      title: "User stories",
      description:
        "Each row tells what a person wants to do with the app and why it matters to them.",
    },
    criteria: {
      title: "Acceptance criteria",
      description:
        "Each row is a concrete check that tells whether a requirement is met, and how the check is done.",
    },
    scenarios: {
      title: "Scenarios",
      description:
        "Each row follows a possible situation step by step, from what starts it to the result the person expects.",
    },
    risks: {
      title: "Risks",
      description:
        "Each row is something that could go wrong: how likely it is, how much it would hurt and how to prevent it.",
    },
    done: {
      title: "When the work is done",
      description: "Each row is a check the work must pass before it can be called finished.",
    },
    otherTables: "Other tables",
    oneRow: "1 row",
    manyRows: "{count} rows",
    code: "Code",
    title: "Title",
    type: "Type",
    priority: "Priority",
    requirement: "Requirement",
    for: "For",
    storiesColumn: "Stories",
    criteriaColumn: "Criteria",
    verification: "Verification",
    missing: "Missing",
    who: "Who",
    goal: "Goal",
    benefit: "Benefit",
    requirementsColumn: "Requirements",
    criterion: "Criterion",
    method: "How it is checked",
    startsWhen: "Starts when",
    steps: "Steps",
    expected: "Expected result",
    risk: "Risk",
    likelihood: "Likelihood",
    impact: "Impact",
    mitigation: "Mitigation",
    status: "Status",
    check: "Check",
    applies: "Applies",
    always: "Always",
    onlyIf: "Only if {condition}",
    someCases: "Only in some cases",
    kinds: {
      FUNCTIONAL: "Feature",
      NON_FUNCTIONAL: "Quality",
      CONSTRAINT: "Constraint",
    },
    priorities: {
      MUST: "Essential",
      SHOULD: "Important",
      COULD: "Optional",
      WONT_FOR_NOW: "For later",
    },
    methods: {
      AUTOMATED_TEST: "Automated test",
      MANUAL_REVIEW: "Manual review",
      INSPECTION: "Inspection",
      DEMONSTRATION: "Demonstration",
      ANALYSIS: "Analysis",
    },
    likelihoods: {
      RARE: "Rare",
      UNLIKELY: "Unlikely",
      POSSIBLE: "Possible",
      LIKELY: "Likely",
      ALMOST_CERTAIN: "Almost certain",
    },
    impacts: {
      LOW: "Low",
      MEDIUM: "Medium",
      HIGH: "High",
      CRITICAL: "Critical",
    },
    statuses: {
      PROPOSED: "Proposed",
      OWNER_ACKNOWLEDGED: "Confirmed by you",
      OWNER_REJECTED: "Rejected by you",
    },
  },
  it: {
    needs: { title: "Bisogni", description: "Bisogni collegati ai loro scenari e alle fonti." },
    journeys: {
      title: "Journey",
      description: "Fasi ordinate collegate a uno scenario e ai suoi bisogni.",
    },
    phase: "Fase",
    action: "Azione",
    touchpoint: "Punto di contatto",
    noNeeds: "I bisogni non erano registrati in questa definizione.",
    context: "Contesto",
    criticalities: "Criticità",
    sources: "Fonti",
    actor: "Attore",
    needsColumn: "Bisogni",
    scenariosColumn: "Scenari",
    requirements: {
      title: "Requisiti",
      description:
        "Ogni riga è una cosa che l'app deve fare o rispettare, per chi serve e come verrà controllata.",
    },
    stories: {
      title: "Storie",
      description: "Ogni riga racconta cosa vuole fare una persona con l'app e perché le serve.",
    },
    criteria: {
      title: "Criteri di accettazione",
      description:
        "Ogni riga è una verifica concreta che dice se un requisito è soddisfatto, e come si fa la verifica.",
    },
    scenarios: {
      title: "Scenari",
      description:
        "Ogni riga segue passo per passo una situazione ipotizzata, da cosa la avvia al risultato che la persona si aspetta.",
    },
    risks: {
      title: "Rischi",
      description:
        "Ogni riga è qualcosa che potrebbe andare storto: quanto è probabile, quanto peserebbe e come prevenirlo.",
    },
    done: {
      title: "Quando il lavoro è finito",
      description:
        "Ogni riga è un controllo che il lavoro deve superare prima di poterlo considerare concluso.",
    },
    otherTables: "Altre tabelle",
    oneRow: "1 riga",
    manyRows: "{count} righe",
    code: "Codice",
    title: "Titolo",
    type: "Tipo",
    priority: "Priorità",
    requirement: "Requisito",
    for: "Per chi",
    storiesColumn: "Storie",
    criteriaColumn: "Criteri",
    verification: "Verifica",
    missing: "Mancante",
    who: "Chi",
    goal: "Obiettivo",
    benefit: "Beneficio",
    requirementsColumn: "Requisiti",
    criterion: "Criterio",
    method: "Come si verifica",
    startsWhen: "Inizia quando",
    steps: "Passi",
    expected: "Risultato atteso",
    risk: "Rischio",
    likelihood: "Probabilità",
    impact: "Impatto",
    mitigation: "Mitigazione",
    status: "Stato",
    check: "Controllo",
    applies: "Quando vale",
    always: "Sempre",
    onlyIf: "Solo se {condition}",
    someCases: "Solo in alcuni casi",
    kinds: {
      FUNCTIONAL: "Funzionalità",
      NON_FUNCTIONAL: "Qualità",
      CONSTRAINT: "Vincolo",
    },
    priorities: {
      MUST: "Essenziale",
      SHOULD: "Importante",
      COULD: "Facoltativo",
      WONT_FOR_NOW: "Per il futuro",
    },
    methods: {
      AUTOMATED_TEST: "Test automatico",
      MANUAL_REVIEW: "Revisione manuale",
      INSPECTION: "Ispezione",
      DEMONSTRATION: "Dimostrazione",
      ANALYSIS: "Analisi",
    },
    likelihoods: {
      RARE: "Raro",
      UNLIKELY: "Improbabile",
      POSSIBLE: "Possibile",
      LIKELY: "Probabile",
      ALMOST_CERTAIN: "Quasi certo",
    },
    impacts: {
      LOW: "Basso",
      MEDIUM: "Medio",
      HIGH: "Alto",
      CRITICAL: "Critico",
    },
    statuses: {
      PROPOSED: "Proposto",
      OWNER_ACKNOWLEDGED: "Confermato da te",
      OWNER_REJECTED: "Respinto da te",
    },
  },
} as const;

const copy = computed(() => messages[props.locale]);
const requirementCodes = computed(() => codeLookup(props.specification.requirements));
const storyCodes = computed(() => codeLookup(props.specification.user_stories));
const criterionCodes = computed(() => codeLookup(props.specification.acceptance_criteria));

const sections = computed<TableSection[]>(() => {
  const text = copy.value;
  const specification = props.specification;
  const chain = specification.schema_version === 2;
  const needTitles = new Map((specification.needs ?? []).map((item) => [item.id, item.title]));
  const scenarioTitles = new Map(specification.scenarios.map((item) => [item.id, item.title]));

  return [
    ...((specification.journeys ?? []).length > 0
      ? [
          {
            key: "journeys",
            ...text.journeys,
            columns: [
              { key: "code", label: text.code },
              { key: "title", label: text.title },
              { key: "scenario", label: text.scenariosColumn },
              { key: "phase", label: text.phase },
              { key: "action", label: text.action },
              { key: "touchpoint", label: text.touchpoint },
              { key: "needs", label: text.needsColumn },
              { key: "criticalities", label: text.criticalities },
              { key: "sources", label: text.sources },
            ],
            rows: (specification.journeys ?? []).flatMap((journey) =>
              journey.phases.map((phase, index) => ({
                code: journey.code,
                title: journey.title,
                scenario: scenarioTitles.get(journey.scenario_id) ?? journey.scenario_id,
                phase: `${index + 1}. ${phase.title}`,
                action: phase.action,
                touchpoint: phase.touchpoint ?? "",
                needs: referenceCodes(phase.need_ids, needTitles),
                criticalities: phase.criticalities.join("\n"),
                sources: journey.sources
                  .map((source) =>
                    Object.values(source)
                      .filter((value) => value !== null)
                      .join(" · "),
                  )
                  .join("\n"),
              })),
            ),
          },
        ]
      : []),
    {
      key: "requirements",
      ...text.requirements,
      columns: [
        { key: "code", label: text.code, sortable: true },
        { key: "title", label: text.title, sortable: true, strong: true },
        { key: "kind", label: text.type, sortable: true },
        { key: "priority", label: text.priority, sortable: true, sortKey: "priorityOrder" },
        { key: "statement", label: text.requirement },
        { key: "criteria", label: text.verification, missing: text.missing },
        { key: "twins", label: text.for, nowrap: true },
        { key: "stories", label: text.storiesColumn, nowrap: true },
        ...(chain ? [{ key: "needs", label: text.needsColumn }] : []),
      ],
      rows: specification.requirements.map((requirement) => ({
        code: requirement.code,
        title: requirement.title,
        kind: text.kinds[requirement.kind],
        priority: text.priorities[requirement.priority],
        priorityOrder: String(PRIORITY_ORDER[requirement.priority]),
        statement: requirement.statement,
        twins: twinNames(requirement.user_twin_references),
        stories: linkedCodes(specification.user_stories, requirement.id),
        criteria: linkedCodes(specification.acceptance_criteria, requirement.id),
        ...(chain ? { needs: referenceCodes(requirement.need_ids ?? [], needTitles) } : {}),
      })),
    },
    {
      key: "stories",
      ...text.stories,
      columns: [
        { key: "code", label: text.code },
        { key: "who", label: text.who },
        { key: "goal", label: text.goal },
        { key: "benefit", label: text.benefit },
        { key: "requirements", label: text.requirementsColumn },
        ...(chain ? [{ key: "needs", label: text.needsColumn }] : []),
      ],
      rows: specification.user_stories.map((story) => ({
        code: story.code,
        who: story.user_twin_reference.name,
        goal: story.goal,
        benefit: story.benefit,
        requirements: referenceCodes(story.requirement_ids, requirementCodes.value),
        ...(chain ? { needs: referenceCodes(story.need_ids ?? [], needTitles) } : {}),
      })),
    },
    {
      key: "criteria",
      ...text.criteria,
      columns: [
        { key: "code", label: text.code },
        { key: "statement", label: text.criterion },
        { key: "method", label: text.method },
        { key: "requirements", label: text.requirementsColumn },
        { key: "stories", label: text.storiesColumn },
      ],
      rows: specification.acceptance_criteria.map((criterion) => ({
        code: criterion.code,
        statement: criterion.statement,
        method: text.methods[criterion.verification_method],
        requirements: referenceCodes(criterion.requirement_ids, requirementCodes.value),
        stories: referenceCodes(criterion.user_story_ids, storyCodes.value),
      })),
    },
    {
      key: "scenarios",
      ...text.scenarios,
      columns: [
        { key: "code", label: text.code },
        { key: "title", label: text.title },
        { key: "who", label: text.actor },
        { key: "trigger", label: text.startsWhen },
        { key: "steps", label: text.steps },
        { key: "outcome", label: text.expected },
        { key: "requirements", label: text.requirementsColumn },
        { key: "criteria", label: text.criteriaColumn },
        ...(chain
          ? [
              { key: "context", label: text.context },
              { key: "goal", label: text.goal },
              { key: "criticalities", label: text.criticalities },
              { key: "sources", label: text.sources },
            ]
          : []),
      ],
      rows: specification.scenarios.map((scenario) => ({
        code: scenario.code,
        title: scenario.title,
        who: scenario.actor.name,
        trigger: scenario.trigger,
        steps: scenario.steps.map((step, index) => `${index + 1}. ${step}`).join("\n"),
        outcome: scenario.expected_outcome,
        requirements: referenceCodes(scenario.requirement_ids, requirementCodes.value),
        criteria: referenceCodes(scenario.acceptance_criterion_ids, criterionCodes.value),
        ...(chain
          ? {
              context: scenario.context ?? "",
              goal: scenario.goal ?? "",
              criticalities: scenario.criticalities?.join("\n") ?? "",
              sources:
                scenario.sources?.map((source) => source.locator ?? source.source_id).join("\n") ??
                "",
            }
          : {}),
      })),
    },
    {
      key: "needs",
      ...text.needs,
      description: (specification.needs ?? []).length > 0 ? text.needs.description : text.noNeeds,
      columns: [
        { key: "code", label: text.code },
        { key: "title", label: text.title },
        { key: "statement", label: text.needsColumn },
        { key: "scenarios", label: text.scenariosColumn },
        { key: "sources", label: text.sources },
      ],
      rows: (specification.needs ?? []).map((need) => ({
        code: need.code,
        title: need.title,
        statement: need.statement,
        scenarios: referenceCodes(need.scenario_ids, scenarioTitles),
        sources: need.sources.map((source) => source.locator ?? source.source_id).join("\n"),
      })),
    },
    {
      key: "risks",
      ...text.risks,
      columns: [
        { key: "code", label: text.code },
        { key: "summary", label: text.risk },
        { key: "likelihood", label: text.likelihood },
        { key: "impact", label: text.impact },
        { key: "mitigation", label: text.mitigation },
        { key: "status", label: text.status },
        { key: "requirements", label: text.requirementsColumn },
      ],
      rows: specification.risks.map((risk) => ({
        code: risk.code,
        summary: risk.summary,
        likelihood: text.likelihoods[risk.likelihood],
        impact: text.impacts[risk.impact],
        mitigation: risk.mitigation,
        status: text.statuses[risk.review_status],
        requirements: referenceCodes(risk.requirement_ids, requirementCodes.value),
      })),
    },
    {
      key: "done",
      ...text.done,
      columns: [
        { key: "code", label: text.code },
        { key: "statement", label: text.check },
        { key: "method", label: text.method },
        { key: "applies", label: text.applies },
        { key: "requirements", label: text.requirementsColumn },
      ],
      rows: specification.definition_of_done.map((item) => ({
        code: item.code,
        statement: item.statement,
        method: text.methods[item.verification_method],
        applies: applicability(item),
        requirements: referenceCodes(item.requirement_ids, requirementCodes.value),
      })),
    },
  ].sort(
    (left, right) =>
      [
        "scenarios",
        "needs",
        "journeys",
        "stories",
        "requirements",
        "criteria",
        "risks",
        "done",
      ].indexOf(left.key) -
      [
        "scenarios",
        "needs",
        "journeys",
        "stories",
        "requirements",
        "criteria",
        "risks",
        "done",
      ].indexOf(right.key),
  );
});

const palettes = {
  light: {
    description: "text-ink-2",
    kicker: "text-ink-3",
    panel: "border-line bg-surface",
    line: "border-line",
    title: "text-ink",
    count: "text-ink-3",
    chevron: "text-ink-3",
  },
  night: {
    description: "text-on-night-3",
    kicker: "text-on-night-3",
    panel: "border-night-line bg-night-raised",
    line: "border-night-line",
    title: "text-on-night",
    count: "text-on-night-3",
    chevron: "text-on-night-3",
  },
};

const surface = useSurface(() => undefined);
const palette = computed(() => palettes[surface.value]);
const primary = computed(() => sections.value[0]);
const others = computed(() => sections.value.slice(1));

function rowCount(section: TableSection): string {
  return section.rows.length === 1
    ? copy.value.oneRow
    : copy.value.manyRows.replace("{count}", String(section.rows.length));
}

function codeLookup(items: readonly CodedItem[]): Map<string, string> {
  return new Map(items.map((item) => [item.id, item.code]));
}

function compareCodes(left: string, right: string): number {
  return left.localeCompare(right, props.locale, { numeric: true, sensitivity: "base" });
}

function joinCodes(codes: readonly string[]): string {
  return [...new Set(codes)].sort(compareCodes).join("\n");
}

function referenceCodes(ids: readonly string[], lookup: ReadonlyMap<string, string>): string {
  const known = ids.flatMap((id) => {
    const code = lookup.get(id);

    return code === undefined ? [] : [code];
  });
  const text = joinCodes(known);

  if (known.length === ids.length) {
    return text;
  }

  return text.length === 0 ? EM_DASH : `${text}\n${EM_DASH}`;
}

function linkedCodes(items: readonly RequirementLinkedItem[], requirementId: string): string {
  return joinCodes(
    items.filter((item) => item.requirement_ids.includes(requirementId)).map((item) => item.code),
  );
}

function twinNames(references: readonly UserTwinVersionReferencePayload[]): string {
  return [...new Set(references.map((reference) => reference.name))].join("\n");
}

function applicability(item: DefinitionOfDoneItemPayload): string {
  if (item.applicability === "REQUIRED") {
    return copy.value.always;
  }

  const condition = item.condition?.trim() ?? "";

  return condition.length === 0
    ? copy.value.someCases
    : copy.value.onlyIf.replace("{condition}", () => condition);
}
</script>

<template>
  <div class="grid gap-6" data-testid="requirements-table-view">
    <section v-if="primary" class="grid gap-2" :data-testid="`requirements-section-${primary.key}`">
      <h2 class="sr-only">{{ primary.title }}</h2>
      <p :class="['m-0 text-[13px] leading-normal', palette.description]">
        {{ primary.description }}
      </p>
      <ArtifactTable
        :caption="primary.title"
        :columns="primary.columns"
        :rows="primary.rows"
        row-key="code"
        :locale="locale"
      />
    </section>

    <div class="grid gap-2">
      <p :class="['m-0 font-mono text-[11px] tracking-[0.06em] uppercase', palette.kicker]">
        {{ copy.otherTables }}
      </p>
      <details
        v-for="section in others"
        :key="section.key"
        :class="['group rounded-tile border', palette.panel]"
        :data-testid="`requirements-section-${section.key}`"
      >
        <summary
          class="flex min-h-12 cursor-pointer list-none flex-wrap items-center gap-x-3 gap-y-0.5 px-5 py-3 [&::-webkit-details-marker]:hidden"
        >
          <span
            :class="['inline-block text-xs group-open:rotate-90', palette.chevron]"
            aria-hidden="true"
            >▸</span
          >
          <h2 :class="['m-0 text-[15px] font-semibold', palette.title]">{{ section.title }}</h2>
          <span :class="['ml-auto text-[13px] whitespace-nowrap', palette.count]">
            {{ rowCount(section) }}
          </span>
        </summary>
        <div :class="['grid gap-3 border-t px-5 py-4', palette.line]">
          <p :class="['m-0 text-[13px] leading-normal', palette.description]">
            {{ section.description }}
          </p>
          <ArtifactTable
            :caption="section.title"
            :columns="section.columns"
            :rows="section.rows"
            row-key="code"
            :locale="locale"
          />
        </div>
      </details>
    </div>
  </div>
</template>
