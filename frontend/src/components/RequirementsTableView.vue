<script setup lang="ts">
import { computed } from "vue";

import ArtifactTable, { type ArtifactTableColumn } from "./ArtifactTable.vue";
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
      title: "Usage scenarios",
      description:
        "Each row follows a real situation step by step, from what starts it to the result the person expects.",
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
    code: "Code",
    title: "Title",
    type: "Type",
    priority: "Priority",
    requirement: "Requirement",
    for: "For",
    storiesColumn: "Stories",
    criteriaColumn: "Criteria",
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
      FUNCTIONAL: "Functional",
      NON_FUNCTIONAL: "Non functional",
      CONSTRAINT: "Constraint",
    },
    priorities: {
      MUST: "Must",
      SHOULD: "Should",
      COULD: "Could",
      WONT_FOR_NOW: "Not for now",
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
    requirements: {
      title: "Requisiti",
      description:
        "Ogni riga è una cosa che l'app deve fare o rispettare, per chi serve e come verrà controllata.",
    },
    stories: {
      title: "Storie degli utenti",
      description: "Ogni riga racconta cosa vuole fare una persona con l'app e perché le serve.",
    },
    criteria: {
      title: "Criteri di accettazione",
      description:
        "Ogni riga è una verifica concreta che dice se un requisito è soddisfatto, e come si fa la verifica.",
    },
    scenarios: {
      title: "Scenari d'uso",
      description:
        "Ogni riga segue passo per passo una situazione reale, da cosa la avvia al risultato che la persona si aspetta.",
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
    code: "Codice",
    title: "Titolo",
    type: "Tipo",
    priority: "Priorità",
    requirement: "Requisito",
    for: "Per chi",
    storiesColumn: "Storie",
    criteriaColumn: "Criteri",
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
      FUNCTIONAL: "Funzionale",
      NON_FUNCTIONAL: "Non funzionale",
      CONSTRAINT: "Vincolo",
    },
    priorities: {
      MUST: "Indispensabile",
      SHOULD: "Importante",
      COULD: "Utile",
      WONT_FOR_NOW: "Non ora",
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

  return [
    {
      key: "requirements",
      ...text.requirements,
      columns: [
        { key: "code", label: text.code, sortable: true },
        { key: "title", label: text.title, sortable: true },
        { key: "kind", label: text.type, sortable: true },
        { key: "priority", label: text.priority, sortable: true, sortKey: "priorityOrder" },
        { key: "statement", label: text.requirement },
        { key: "twins", label: text.for },
        { key: "stories", label: text.storiesColumn },
        { key: "criteria", label: text.criteriaColumn },
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
      ],
      rows: specification.user_stories.map((story) => ({
        code: story.code,
        who: story.user_twin_reference.name,
        goal: story.goal,
        benefit: story.benefit,
        requirements: referenceCodes(story.requirement_ids, requirementCodes.value),
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
        { key: "who", label: text.who },
        { key: "trigger", label: text.startsWhen },
        { key: "steps", label: text.steps },
        { key: "outcome", label: text.expected },
        { key: "requirements", label: text.requirementsColumn },
        { key: "criteria", label: text.criteriaColumn },
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
  ];
});

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
  <div class="grid gap-8" data-testid="requirements-table-view">
    <section
      v-for="section in sections"
      :key="section.key"
      class="grid gap-3"
      :data-testid="`requirements-section-${section.key}`"
    >
      <div class="grid gap-1">
        <h4 class="m-0 text-base font-semibold tracking-block text-ink">{{ section.title }}</h4>
        <p class="m-0 text-sm leading-6 text-ink-2">{{ section.description }}</p>
      </div>
      <ArtifactTable
        :caption="section.title"
        :columns="section.columns"
        :rows="section.rows"
        row-key="code"
        :locale="locale"
      />
    </section>
  </div>
</template>
