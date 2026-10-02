<script setup lang="ts">
import { computed, nextTick, provide, ref, watch } from "vue";

import UiButton from "./UiButton.vue";
import { surfaceKey, type SurfaceContext } from "./UiSurface.vue";

import { PROJECT_STAGES, type ProjectStage } from "@/api/contracts";
import type { ProjectSectionsPayload, SectionsAlignmentPayload } from "@/types/sections";

type Locale = "en" | "it";
type ReasonKey =
  "requirementMissing" | "twins" | "revision" | "upstream" | "prepare" | "prepareTwins" | "unknown";
type LineKind =
  | "done"
  | "nothing"
  | "blocked"
  | "failed"
  | "behind"
  | "uncovered"
  | "learned"
  | "covered"
  | "evaluation"
  | "affected";

interface LinePart {
  text: string;
  command: boolean;
}

interface NoticeLine {
  key: string;
  kind: LineKind;
  parts: LinePart[];
  link: ProjectStage | null;
  summary?: string;
}

const LEARN_COMMAND = "ut twins update";

const REASONS: ReadonlyMap<string, ReasonKey> = new Map<string, ReasonKey>([
  ["REQUIREMENT_NO_LONGER_AVAILABLE", "requirementMissing"],
  ["TWIN_SET_CHANGED", "twins"],
  ["TWIN_NO_LONGER_AVAILABLE", "twins"],
  ["REVISION_PENDING", "revision"],
  ["USER_TWIN_REVISION_PENDING", "revision"],
  ["REQUIREMENTS_REVISION_PENDING", "revision"],
  ["DESIGN_REVISION_PENDING", "revision"],
  ["UPSTREAM_NOT_READY", "upstream"],
  ["BRIEF_APPROVAL_REQUIRED", "upstream"],
  ["TEAM_APPROVAL_REQUIRED", "upstream"],
  ["USER_TWINS_APPROVAL_REQUIRED", "upstream"],
  ["REQUIREMENTS_APPROVAL_REQUIRED", "upstream"],
  ["PREPARE_AGAIN", "prepare"],
  ["PREPARE_TWINS", "prepareTwins"],
]);

const props = withDefaults(
  defineProps<{
    sections: ProjectSectionsPayload;
    labels: readonly string[];
    openKey: ProjectStage;
    locale?: Locale;
    busy?: boolean;
    result?: SectionsAlignmentPayload | null;
    failed?: boolean;
  }>(),
  {
    locale: "en",
    busy: false,
    result: null,
    failed: false,
  },
);

const emit = defineEmits<{ align: []; open: [stage: ProjectStage] }>();

provide(
  surfaceKey,
  computed<SurfaceContext>(() => "night"),
);

const messages = {
  en: {
    archetypesBehind:
      "{sections} to update: the archetypes changed. Prepare and approve the updated twins, then update the dependent sections. Earlier versions remain in the history.",
    behind:
      "{sections} to update: something upstream changed. The content you approved stays the same, it is only re-anchored to the new versions.",
    uncovered:
      "New requirements that the design does not cover yet: {codes}. After the update you can ask for a change to the design.",
    covered:
      "New requirements that the design does not cover yet: {codes}. Ask for a change to the design to cover them.",
    gesture: "Update and confirm",
    running: "Updating the sections…",
    done: "Sections updated: {sections}.",
    nothing: "There was nothing to update: the sections were already up to date.",
    blocked: "{section} cannot be updated by itself: {reason}.",
    reasons: {
      requirementMissing:
        "the design cites {codes}, which the Definition no longer contains: regenerate the alternatives in the Design & Evaluation step",
      twins: "the twins are no longer the same",
      revision: "a proposed change is waiting for your decision",
      upstream: "the section upstream has to be settled first",
      prepare: "the brief changed: prepare the perspectives again",
      prepareTwins:
        "the archetypes changed: prepare and approve the updated twins in the User Twin step",
      unknown: "it could not be done right now, try again in a moment",
    },
    evaluation:
      "The design was re-anchored to the new Definition: you can ask the twins for a new evaluation.",
    learned: "The twins learned something during development: see the proposal with {command}.",
    failed: "The sections could not be updated: try again.",
    open: "Open {section}",
    affected:
      "Review {section} after the twin changed: {items}. Re-anchoring preserves identities; review what these items say.",
    affectedSummary: "References to review for {section} ({count})",
    affectedScenarios: "scenarios {codes}",
    affectedNeeds: "needs {codes}",
    affectedRequirements: "requirements {codes}",
  },
  it: {
    archetypesBehind:
      "{sections} da aggiornare: gli archetipi sono cambiati. Prepara e approva i twin aggiornati, poi aggiorna le sezioni dipendenti. Le versioni precedenti restano nello storico.",
    behind:
      "{sections} da aggiornare: a monte qualcosa è cambiato. I contenuti che hai approvato restano gli stessi, vengono solo riagganciati alle versioni nuove.",
    uncovered:
      "Requisiti nuovi che il design non copre ancora: {codes}. Dopo l'aggiornamento puoi chiedere una modifica al design.",
    covered:
      "Requisiti nuovi che il design non copre ancora: {codes}. Chiedi una modifica al design per coprirli.",
    gesture: "Aggiorna e conferma",
    running: "Aggiorno le sezioni…",
    done: "Sezioni aggiornate: {sections}.",
    nothing: "Non c'era niente da aggiornare: le sezioni erano già a posto.",
    blocked: "{section} non si aggiorna da sola: {reason}.",
    reasons: {
      requirementMissing:
        "il design cita {codes}, che la Definizione non contiene più: rigenera le alternative nel passo Design e valutazione",
      twins: "i twin non sono più gli stessi",
      revision: "c'è una modifica proposta da decidere",
      upstream: "prima va sistemata la sezione a monte",
      prepare: "il brief è cambiato: prepara di nuovo le prospettive",
      prepareTwins:
        "gli archetipi sono cambiati: prepara e approva i twin aggiornati nel passo User Twin",
      unknown: "non è stato possibile farlo adesso, riprova tra poco",
    },
    evaluation:
      "Il design è stato riagganciato alla Definizione nuova: puoi chiedere ai twin una nuova valutazione.",
    learned:
      "I twin hanno imparato qualcosa durante lo sviluppo: guarda la proposta con {command}.",
    failed: "Non è stato possibile aggiornare le sezioni: riprova.",
    open: "Apri {section}",
    affected:
      "Rivedi {section} dopo il cambiamento del twin: {items}. Il riaggancio conserva le identità; controlla ciò che dicono questi elementi.",
    affectedSummary: "Riferimenti da rivedere per {section} ({count})",
    affectedScenarios: "scenari {codes}",
    affectedNeeds: "bisogni {codes}",
    affectedRequirements: "requisiti {codes}",
  },
} as const;

const root = ref<HTMLElement | null>(null);
const copy = computed(() => messages[props.locale]);
let regainFocus = false;

function fill(template: string, values: Record<string, string>): string {
  return template.replace(/\{(\w+)\}/g, (match, key: string) => values[key] ?? match);
}

function listOf(items: readonly string[]): string {
  return new Intl.ListFormat(props.locale === "it" ? "it-IT" : "en-GB", {
    style: "long",
    type: "conjunction",
  }).format(items);
}

function label(key: ProjectStage): string {
  return props.labels[PROJECT_STAGES.indexOf(key)] ?? key;
}

function partsOf(template: string, values: Record<string, string> = {}): LinePart[] {
  const [before, after] = template.split("{command}");
  if (after === undefined) {
    return [{ text: fill(template, values), command: false }];
  }
  return [
    { text: fill(before ?? "", values), command: false },
    { text: LEARN_COMMAND, command: true },
    { text: fill(after, values), command: false },
  ];
}

function blockedLine(
  key: ProjectStage,
  issue: string | null,
  codes: readonly string[],
): NoticeLine {
  const reason = (issue === null ? undefined : REASONS.get(issue)) ?? "unknown";
  return {
    key: `blocked-${key}`,
    kind: "blocked",
    parts: partsOf(copy.value.blocked, {
      section: label(key),
      reason: fill(copy.value.reasons[reason], { codes: listOf(codes) }),
    }),
    link: reason === "prepare" ? "TEAM" : reason === "prepareTwins" ? "USER_TWINS" : null,
  };
}

function resultLines(result: SectionsAlignmentPayload): NoticeLine[] {
  const aligned = result.results.filter((item) => item.outcome === "ALIGNED");
  const blocked = result.results.filter((item) => item.outcome === "BLOCKED");
  const lines = blocked.map((item) => blockedLine(item.key, item.issue, item.codes));
  if (aligned.length > 0) {
    lines.unshift({
      key: "done",
      kind: "done",
      parts: partsOf(copy.value.done, { sections: listOf(aligned.map((item) => label(item.key))) }),
      link: null,
    });
  }
  if (aligned.length === 0 && blocked.length === 0) {
    lines.push({ key: "nothing", kind: "nothing", parts: partsOf(copy.value.nothing), link: null });
  }
  return lines;
}

function availableLines(sections: ProjectSectionsPayload): NoticeLine[] {
  const lines: NoticeLine[] = [];
  for (const section of sections.sections) {
    if (section.state !== "UPDATE_AVAILABLE") continue;
    for (const reason of section.reasons) {
      if (reason === "TWINS_LEARNED") {
        lines.push({
          key: `learned-${section.key}`,
          kind: "learned",
          parts: partsOf(copy.value.learned),
          link: null,
        });
      } else if (reason === "REQUIREMENTS_NOT_COVERED") {
        lines.push({
          key: `covered-${section.key}`,
          kind: "covered",
          parts: partsOf(copy.value.covered, { codes: listOf(section.codes) }),
          link: "DESIGN",
        });
      } else if (reason === "EVALUATION_MISSING") {
        lines.push({
          key: `evaluation-${section.key}`,
          kind: "evaluation",
          parts: partsOf(copy.value.evaluation),
          link: null,
        });
      }
    }
  }
  return lines;
}

function affectedLines(sections: ProjectSectionsPayload): NoticeLine[] {
  return sections.sections.flatMap((section) => {
    const codes = section.affected_codes;
    if (codes === undefined) return [];
    const items = [
      codes.scenarios.length > 0
        ? fill(copy.value.affectedScenarios, { codes: listOf(codes.scenarios) })
        : null,
      codes.needs.length > 0
        ? fill(copy.value.affectedNeeds, { codes: listOf(codes.needs) })
        : null,
      codes.requirements.length > 0
        ? fill(copy.value.affectedRequirements, { codes: listOf(codes.requirements) })
        : null,
    ].filter((item): item is string => item !== null);
    if (items.length === 0) return [];
    return [
      {
        key: `affected-${section.key}`,
        kind: "affected" as const,
        parts: partsOf(copy.value.affected, { section: label(section.key), items: listOf(items) }),
        link: section.key,
        summary: fill(copy.value.affectedSummary, {
          section: label(section.key),
          count: String(new Set([...codes.scenarios, ...codes.needs, ...codes.requirements]).size),
        }),
      },
    ];
  });
}

const lines = computed<NoticeLine[]>(() => {
  const result = props.result;
  const collected = result === null ? [] : resultLines(result);
  const reported = new Set<string>(
    (result?.results ?? []).filter((item) => item.outcome === "BLOCKED").map((item) => item.key),
  );
  if (props.failed) {
    collected.push({
      key: "failed",
      kind: "failed",
      parts: partsOf(copy.value.failed),
      link: null,
    });
  }
  const summary = props.sections.alignment;
  if (summary.available) {
    collected.push({
      key: "behind",
      kind: "behind",
      parts: partsOf(
        props.sections.sections.some((section) => section.reasons.includes("ARCHETYPES_CHANGED"))
          ? copy.value.archetypesBehind
          : copy.value.behind,
        { sections: listOf(summary.sections.map(label)) },
      ),
      link: null,
    });
    if (summary.uncovered_codes.length > 0) {
      collected.push({
        key: "uncovered",
        kind: "uncovered",
        parts: partsOf(copy.value.uncovered, { codes: listOf(summary.uncovered_codes) }),
        link: null,
      });
    }
  }
  const stuck = props.sections.sections.find(
    (section) => section.state === "TO_UPDATE" && section.blocked !== null,
  );
  if (stuck !== undefined && !reported.has(stuck.key)) {
    collected.push(blockedLine(stuck.key, stuck.blocked, stuck.codes));
  }
  return [...collected, ...affectedLines(props.sections), ...availableLines(props.sections)];
});

const alignable = computed(() => props.sections.alignment.available);
const visible = computed(() => lines.value.length > 0 || props.busy);

function lineClass(kind: LineKind): string {
  if (kind === "done") return "font-semibold text-petrol-on-night-2";
  if (kind === "failed") return "text-fail-on-night";
  return kind === "behind" ? "text-on-night" : "text-on-night-2";
}

function keepFocus(): void {
  const active = document.activeElement;
  if (active !== null && active !== document.body && active.isConnected) return;
  const button = root.value?.querySelector<HTMLElement>('[data-testid="sections-align"]');
  (button ?? root.value)?.focus();
}

function align(): void {
  if (props.busy) return;
  regainFocus = true;
  emit("align");
}

async function openSection(stage: ProjectStage): Promise<void> {
  emit("open", stage);
  await nextTick();
  keepFocus();
}

watch(
  () => props.busy,
  async (busy, wasBusy) => {
    if (busy || !wasBusy || !regainFocus) return;
    regainFocus = false;
    await nextTick();
    keepFocus();
  },
);
</script>

<template>
  <div
    v-if="visible"
    ref="root"
    role="status"
    tabindex="-1"
    :aria-busy="busy ? 'true' : undefined"
    class="mt-7 flex flex-wrap items-center gap-x-4 gap-y-3 rounded-panel border border-night-line bg-night-raised py-3 pr-3 pl-5 text-on-night outline-none"
    data-surface="night"
    data-testid="sections-notice"
  >
    <div class="grid min-w-[min(100%,16rem)] flex-1 gap-1.5">
      <div
        v-for="line in lines"
        :key="line.key"
        class="flex flex-wrap items-center gap-x-4 gap-y-1"
      >
        <details
          v-if="line.kind === 'affected'"
          class="w-full min-w-0 flex-none sm:w-auto sm:flex-1"
          data-testid="sections-affected-details"
        >
          <summary class="min-h-11 cursor-pointer py-3 text-sm font-semibold text-on-night-2">
            {{ line.summary }}
          </summary>
          <p
            class="m-0 pb-3 text-[15px] leading-normal text-on-night-2"
            :data-kind="line.kind"
            data-testid="sections-notice-line"
          >
            <template v-for="(part, index) in line.parts" :key="index">{{ part.text }}</template>
          </p>
        </details>
        <p
          v-else
          :class="['m-0 text-[15px] leading-normal', lineClass(line.kind)]"
          :data-kind="line.kind"
          data-testid="sections-notice-line"
        >
          <span v-if="line.kind === 'done'" aria-hidden="true">✓ </span>
          <template v-for="(part, index) in line.parts" :key="index">
            <code v-if="part.command" class="font-mono text-[13px] text-on-night">{{
              part.text
            }}</code>
            <template v-else>{{ part.text }}</template>
          </template>
        </p>
        <button
          v-if="line.link !== null && line.link !== openKey"
          type="button"
          class="inline-flex min-h-11 items-center text-sm font-semibold text-petrol-on-night-2 underline-offset-4 hover:underline"
          :data-target="line.link"
          data-testid="sections-notice-open"
          @click="openSection(line.link)"
        >
          {{ fill(copy.open, { section: label(line.link) }) }}
        </button>
      </div>
      <p v-if="busy" class="m-0 text-sm text-on-night-3" data-testid="sections-notice-running">
        {{ copy.running }}
      </p>
    </div>
    <UiButton
      v-if="alignable"
      variant="outline"
      :disabled="busy"
      data-testid="sections-align"
      @click="align"
    >
      {{ copy.gesture }}
    </UiButton>
  </div>
</template>
