<script lang="ts">
export type ObservationSeverity = "critical" | "major" | "moderate" | "minor" | "observation";

export type ObservationCriterion =
  | "usefulness"
  | "comprehensibility"
  | "actionability"
  | "cognitive_load"
  | "trust"
  | "accessibility"
  | "task_alignment";

export type ObservationDecision = "OWNER_CONFIRMED" | "OWNER_DISMISSED";

export type ObservationTarget = "BRIEF" | "REQUIREMENTS" | "DESIGN";

export interface ObservationFinding {
  finding_id: string;
  twin_id: string;
  summary: string;
  location: string;
  criterion: ObservationCriterion;
  severity: ObservationSeverity;
  recommended_action: string;
  number?: number | null | undefined;
}

export interface ObservationCritique {
  code: string;
  user_twin_reference: { twin_id: string; name: string };
  strengths: readonly string[];
  concerns: readonly string[];
  unmet_needs: readonly string[];
  accessibility_observations: readonly string[];
  trust_concerns: readonly string[];
  questions: readonly string[];
  suggested_changes: readonly string[];
}

export interface ObservationInsightSource {
  kind: "SYNTHETIC_FINDING" | "DESIGN_CRITIQUE";
  id: string;
  twinId: string | null;
  text: string;
  mitigation: string | null;
}

export interface ObservationInsightRequest {
  target: ObservationTarget;
  source: ObservationInsightSource;
}
</script>

<script setup lang="ts">
import { computed, provide, useId } from "vue";
import { useI18n } from "vue-i18n";

import UiClaimFrame from "./UiClaimFrame.vue";
import { surfaceKey, type SurfaceContext } from "./UiSurface.vue";
import {
  elementNames,
  placeLabel,
  placeScreens,
  withScreenNames,
  type ScreenName,
  type ScreenNaming,
  type WorkflowName,
} from "./screenNames";

type Locale = "en" | "it";

type CritiqueList =
  | "strengths"
  | "concerns"
  | "unmet_needs"
  | "accessibility_observations"
  | "trust_concerns"
  | "questions"
  | "suggested_changes";

const CRITIQUE_LISTS: readonly CritiqueList[] = [
  "strengths",
  "concerns",
  "unmet_needs",
  "accessibility_observations",
  "trust_concerns",
  "questions",
  "suggested_changes",
];

const TARGETS: readonly ObservationTarget[] = ["BRIEF", "REQUIREMENTS", "DESIGN"];

const FINDING_NOT_FOUND = "DESIGN_FINDING_NOT_FOUND";

const props = withDefaults(
  defineProps<{
    twin?: { id: string; name: string; avatar?: string | null | undefined } | null | undefined;
    alternative?: { id: string; code: string; title: string } | null | undefined;
    runId?: string | null | undefined;
    findings?: readonly ObservationFinding[] | null | undefined;
    critique?: ObservationCritique | null | undefined;
    validations?: Readonly<Record<string, { decision: ObservationDecision }>> | undefined;
    validating?: string | null | undefined;
    failure?: { key: string; code: string } | null | undefined;
    applied?: Readonly<Record<string, ObservationTarget>> | undefined;
    applying?: string | null | undefined;
    applyFailure?: { id: string; code: string } | null | undefined;
    screens?: readonly ScreenName[] | undefined;
    elements?: Readonly<Record<string, string>> | undefined;
    workflows?: readonly WorkflowName[] | undefined;
    locale?: Locale | undefined;
  }>(),
  {
    twin: null,
    alternative: null,
    runId: null,
    findings: null,
    critique: null,
    validations: () => ({}),
    validating: null,
    failure: null,
    applied: () => ({}),
    applying: null,
    applyFailure: null,
    screens: () => [],
    elements: () => ({}),
    workflows: () => [],
    locale: undefined,
  },
);

const emit = defineEmits<{
  confirm: [finding: ObservationFinding];
  dismiss: [finding: ObservationFinding];
  "apply-insight": [request: ObservationInsightRequest];
}>();

const messages = {
  it: {
    heading: "{twin} su {code} · {title}",
    fallbackHeading: "Osservazioni dei twin",
    noFindings: "Nessuna osservazione: il twin non ha nulla da obiettare su questa alternativa.",
    nothing: "Questo twin non ha ancora espresso un parere su questa alternativa.",
    where: "Dove",
    action: "Azione suggerita",
    decisionGroup: "La tua decisione su questa osservazione",
    confirm: "Confermo",
    dismiss: "Non pertinente",
    confirmed: "Confermata · portala nel progetto:",
    dismissed: "Non pertinente: resta fuori dal progetto.",
    reconsider: "Confermala",
    saving: "Salvo la tua decisione…",
    decisionError: "Non è stato possibile salvare la tua decisione. Riprova.",
    findingNotFound: "Questa osservazione non è più disponibile. Ricarica la pagina.",
    bring: "Porta nel progetto",
    bringGroup: "Portala nel progetto",
    targets: { BRIEF: "Brief", REQUIREMENTS: "Requisiti", DESIGN: "Design" },
    applied: {
      BRIEF: "Messa da parte per il brief",
      REQUIREMENTS: "Aggiunta ai requisiti come proposta",
      DESIGN: "Aggiunta al design come proposta",
    },
    applying: "La porto nel progetto…",
    applyErrors: {
      INSIGHT_ALREADY_APPLIED: "Questo spunto è già nel progetto.",
      INSIGHT_SOURCE_DISMISSED:
        "Hai segnato questa osservazione come non pertinente, quindi resta fuori dal progetto.",
      default: "Non è stato possibile portare lo spunto nel progetto. Riprova.",
    },
    lists: {
      strengths: "Punti di forza",
      concerns: "Criticità",
      unmet_needs: "Bisogni non coperti",
      accessibility_observations: "Accessibilità",
      trust_concerns: "Fiducia",
      questions: "Domande aperte",
      suggested_changes: "Modifiche suggerite",
    },
    severity: {
      critical: "Critica",
      major: "Importante",
      moderate: "Moderata",
      minor: "Minore",
      observation: "Nota",
    },
    criterion: {
      usefulness: "Utilità",
      comprehensibility: "Comprensibilità",
      actionability: "Azionabilità",
      cognitive_load: "Carico cognitivo",
      trust: "Fiducia",
      accessibility: "Accessibilità",
      task_alignment: "Aderenza al compito",
    },
  },
  en: {
    heading: "{twin} on {code} · {title}",
    fallbackHeading: "What the twins noticed",
    noFindings: "No observations: the twin has nothing to object to in this alternative.",
    nothing: "This twin has not given an opinion on this alternative yet.",
    where: "Where",
    action: "Suggested action",
    decisionGroup: "Your decision on this observation",
    confirm: "I confirm",
    dismiss: "Not relevant",
    confirmed: "Confirmed · bring it into the project:",
    dismissed: "Not relevant: it stays out of the project.",
    reconsider: "Confirm it",
    saving: "Saving your decision…",
    decisionError: "Your decision could not be saved. Try again.",
    findingNotFound: "This observation is no longer available. Reload the page.",
    bring: "Bring into the project",
    bringGroup: "Bring it into the project",
    targets: { BRIEF: "Brief", REQUIREMENTS: "Requirements", DESIGN: "Design" },
    applied: {
      BRIEF: "Set aside for the brief",
      REQUIREMENTS: "Added to the requirements as a proposal",
      DESIGN: "Added to the design as a proposal",
    },
    applying: "Bringing it into the project…",
    applyErrors: {
      INSIGHT_ALREADY_APPLIED: "This insight is already in the project.",
      INSIGHT_SOURCE_DISMISSED:
        "You marked this observation as not relevant, so it stays out of the project.",
      default: "The insight could not be brought into the project. Try again.",
    },
    lists: {
      strengths: "Strengths",
      concerns: "Concerns",
      unmet_needs: "Unmet needs",
      accessibility_observations: "Accessibility",
      trust_concerns: "Trust",
      questions: "Open questions",
      suggested_changes: "Suggested changes",
    },
    severity: {
      critical: "Critical",
      major: "Major",
      moderate: "Moderate",
      minor: "Minor",
      observation: "Note",
    },
    criterion: {
      usefulness: "Usefulness",
      comprehensibility: "Comprehensibility",
      actionability: "Actionability",
      cognitive_load: "Cognitive load",
      trust: "Trust",
      accessibility: "Accessibility",
      task_alignment: "Task alignment",
    },
  },
} as const;

const SEVERITY_STYLES: Record<ObservationSeverity, string> = {
  critical: "bg-fail-on-night/12 text-fail-on-night",
  major: "bg-warn-on-night/12 text-warn-on-night",
  moderate: "bg-on-night/8 text-on-night-2",
  minor: "bg-on-night/8 text-on-night-2",
  observation: "bg-on-night/8 text-on-night-2",
};

provide(
  surfaceKey,
  computed<SurfaceContext>(() => "night"),
);

const { locale: appLocale } = useI18n({ useScope: "global" });

const lang = computed<Locale>(() => props.locale ?? (appLocale.value === "it" ? "it" : "en"));
const copy = computed(() => messages[lang.value]);
const headingId = useId();

const heading = computed(() =>
  props.twin !== null && props.alternative !== null
    ? fill(copy.value.heading, {
        twin: props.twin.name,
        code: props.alternative.code,
        title: props.alternative.title,
      })
    : copy.value.fallbackHeading,
);

const naming = computed<ScreenNaming>(() => {
  const locations = (props.findings ?? []).map((finding) => finding.location);
  return {
    screens: [...props.screens, ...placeScreens(locations)],
    elements: { ...props.elements, ...elementNames(locations) },
    workflows: props.workflows,
    locale: lang.value,
  };
});

const entries = computed(() =>
  (props.findings ?? []).map((finding) => {
    const key = `${props.runId ?? ""}:${finding.twin_id}:${finding.finding_id}`;
    const summary = named(finding.summary);
    const action = named(finding.recommended_action);
    const source: ObservationInsightSource = {
      kind: "SYNTHETIC_FINDING",
      id: `run:${props.runId ?? ""}:${finding.twin_id}:${finding.finding_id}`,
      twinId: finding.twin_id,
      text: summary,
      mitigation: action || null,
    };
    const decision = props.validations[key]?.decision ?? null;
    return {
      finding,
      key,
      summary,
      action,
      place: finding.location ? named(placeLabel(finding.location)) : "",
      source,
      decision,
      appliedTarget: props.applied[source.id] ?? null,
    };
  }),
);

const critiqueLists = computed(() => {
  const critique = props.critique;
  if (critique === null) {
    return [];
  }
  const mitigation = critique.suggested_changes[0];
  return CRITIQUE_LISTS.map((key) => ({
    key,
    items: critique[key]
      .map((text, index) => ({ text: named(text.trim()), index }))
      .filter((item) => item.text.length > 0)
      .map((item) => {
        const source: ObservationInsightSource = {
          kind: "DESIGN_CRITIQUE",
          id: `${critique.code}:${item.index}`,
          twinId: critique.user_twin_reference.twin_id,
          text: item.text,
          mitigation: mitigation === undefined ? null : named(mitigation),
        };
        return { ...item, source, appliedTarget: props.applied[source.id] ?? null };
      }),
  })).filter((list) => list.items.length > 0);
});

const deciding = computed(() => props.validating !== null);

function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_match, key: string) => String(values[key] ?? ""));
}

function named(text: string): string {
  return withScreenNames(text, naming.value);
}

function decisionError(code: string): string {
  return code === FINDING_NOT_FOUND ? copy.value.findingNotFound : copy.value.decisionError;
}

function applyError(code: string): string {
  const errors = copy.value.applyErrors;
  return code === "INSIGHT_ALREADY_APPLIED" || code === "INSIGHT_SOURCE_DISMISSED"
    ? errors[code]
    : errors.default;
}

function bring(target: ObservationTarget, source: ObservationInsightSource): void {
  if (props.applying === null) {
    emit("apply-insight", { target, source });
  }
}

function confirm(finding: ObservationFinding): void {
  if (!deciding.value) {
    emit("confirm", finding);
  }
}

function dismiss(finding: ObservationFinding): void {
  if (!deciding.value) {
    emit("dismiss", finding);
  }
}
</script>

<template>
  <section
    class="grid gap-3 text-on-night"
    data-surface="night"
    :aria-labelledby="headingId"
    data-testid="design-observation-list"
  >
    <div class="flex items-center gap-2.5">
      <span
        v-if="twin?.avatar"
        class="inline-flex h-9 w-9 shrink-0 overflow-hidden rounded-full border-2 border-dashed border-violet-on-night"
        aria-hidden="true"
        data-testid="design-observation-avatar"
      >
        <img
          :src="twin.avatar"
          alt=""
          width="36"
          height="36"
          decoding="async"
          class="h-full w-full object-cover"
        />
      </span>
      <h3 :id="headingId" class="min-w-0 text-base font-semibold">{{ heading }}</h3>
    </div>
    <template v-if="findings !== null">
      <p
        v-if="entries.length === 0"
        class="text-sm text-on-night-3"
        data-testid="design-observation-empty"
      >
        {{ copy.noFindings }}
      </p>
      <ul v-else class="grid list-none grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-2.5">
        <li v-for="entry in entries" :key="entry.key">
          <UiClaimFrame
            as="article"
            :status="entry.decision === 'OWNER_CONFIRMED' ? 'confirmed' : 'hypothesis'"
            radius="tile"
            :padded="false"
            :class="[
              'flex h-full flex-col gap-[7px] p-4',
              entry.decision === 'OWNER_DISMISSED' ? 'opacity-60' : '',
            ]"
            :data-decision="entry.decision ?? 'NONE'"
            :data-finding="entry.finding.finding_id"
            data-testid="design-observation"
          >
            <div class="flex flex-wrap items-center gap-2">
              <span
                v-if="entry.finding.number"
                class="inline-flex h-6 min-w-6 items-center justify-center rounded-xl bg-violet-on-night px-1.5 text-xs font-bold text-night"
                data-testid="design-observation-number"
              >
                {{ entry.finding.number }}
              </span>
              <span
                :class="[
                  'inline-flex min-h-6 items-center rounded-pill px-[9px] text-xs font-semibold',
                  SEVERITY_STYLES[entry.finding.severity],
                ]"
              >
                {{ copy.severity[entry.finding.severity] }}
              </span>
              <span class="text-xs text-on-night-3">
                {{ copy.criterion[entry.finding.criterion] }}
              </span>
              <span
                v-if="twin !== null && twin.id === entry.finding.twin_id"
                class="ml-auto text-xs text-on-night-3"
                >{{ twin.name }}</span
              >
            </div>
            <p class="text-[15px] leading-[1.4] font-semibold">{{ entry.summary }}</p>
            <p v-if="entry.place" class="text-[13px] text-on-night-3">
              {{ copy.where }}: {{ entry.place }}
            </p>
            <p v-if="entry.action" class="text-sm leading-normal text-on-night-2">
              <strong class="font-semibold text-on-night">{{ copy.action }}:</strong>
              {{ entry.action }}
            </p>
            <div
              v-if="entry.decision === null"
              class="mt-1 flex flex-wrap gap-1.5"
              role="group"
              :aria-label="copy.decisionGroup"
              data-testid="design-observation-decision"
            >
              <button
                type="button"
                class="inline-flex min-h-11 items-center rounded-pill border border-petrol-on-night px-3.5 text-[13px] font-semibold text-petrol-on-night-2 transition-colors duration-150 hover:bg-petrol-on-night/12 disabled:cursor-not-allowed disabled:opacity-60"
                :disabled="deciding"
                data-testid="design-observation-confirm"
                @click="confirm(entry.finding)"
              >
                {{ copy.confirm }}
              </button>
              <button
                type="button"
                class="inline-flex min-h-11 items-center rounded-pill border border-night-line-strong px-3.5 text-[13px] text-on-night transition-colors duration-150 hover:bg-night-hover disabled:cursor-not-allowed disabled:opacity-60"
                :disabled="deciding"
                data-testid="design-observation-dismiss"
                @click="dismiss(entry.finding)"
              >
                {{ copy.dismiss }}
              </button>
            </div>
            <template v-else-if="entry.decision === 'OWNER_CONFIRMED'">
              <p
                v-if="entry.appliedTarget !== null"
                class="mt-1 text-[13px] font-semibold text-petrol-on-night-2"
                data-testid="design-observation-applied"
              >
                {{ copy.applied[entry.appliedTarget] }}
              </p>
              <div v-else class="mt-1 flex flex-wrap items-center gap-1.5">
                <span class="w-full text-xs font-semibold text-petrol-on-night-2">
                  {{ copy.confirmed }}
                </span>
                <div
                  class="flex flex-wrap gap-1.5"
                  role="group"
                  :aria-label="copy.bringGroup"
                  data-testid="design-observation-bring"
                >
                  <button
                    v-for="target in TARGETS"
                    :key="target"
                    type="button"
                    class="inline-flex min-h-11 items-center rounded-pill border border-night-line-strong px-3 text-xs text-on-night transition-colors duration-150 hover:bg-night-hover disabled:cursor-not-allowed disabled:opacity-60"
                    :disabled="applying !== null"
                    :data-target="target"
                    data-testid="design-observation-target"
                    @click="bring(target, entry.source)"
                  >
                    {{ copy.targets[target] }}
                  </button>
                </div>
              </div>
            </template>
            <div
              v-else
              class="mt-1 flex flex-wrap items-center gap-x-2 text-[13px] text-on-night-3"
              data-testid="design-observation-dismissed"
            >
              <span>{{ copy.dismissed }}</span>
              <button
                type="button"
                class="inline-flex min-h-11 items-center text-[13px] text-on-night-3 underline underline-offset-4 transition-colors duration-150 hover:text-on-night disabled:cursor-not-allowed"
                :disabled="deciding"
                data-testid="design-observation-reconsider"
                @click="confirm(entry.finding)"
              >
                {{ copy.reconsider }}
              </button>
            </div>
            <p
              v-if="validating === entry.key"
              class="text-xs text-on-night-3"
              role="status"
              data-testid="design-observation-saving"
            >
              {{ copy.saving }}
            </p>
            <p
              v-if="applying === entry.source.id"
              class="text-xs text-on-night-3"
              role="status"
              data-testid="design-observation-applying"
            >
              {{ copy.applying }}
            </p>
            <p
              v-if="failure !== null && failure.key === entry.key"
              class="text-xs font-semibold text-fail-on-night"
              role="alert"
              data-testid="design-observation-error"
            >
              {{ decisionError(failure.code) }}
            </p>
            <p
              v-if="applyFailure !== null && applyFailure.id === entry.source.id"
              class="text-xs font-semibold text-fail-on-night"
              role="alert"
              data-testid="design-observation-apply-error"
            >
              {{ applyError(applyFailure.code) }}
            </p>
          </UiClaimFrame>
        </li>
      </ul>
    </template>
    <ul
      v-else-if="critiqueLists.length > 0"
      class="grid list-none grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-2.5"
    >
      <li v-for="list in critiqueLists" :key="list.key">
        <UiClaimFrame
          as="section"
          status="hypothesis"
          radius="tile"
          :padded="false"
          class="h-full p-4"
          :data-list="list.key"
          data-testid="design-critique-list"
        >
          <h4 class="text-sm font-semibold">{{ copy.lists[list.key] }}</h4>
          <ul class="mt-2 grid list-none gap-2.5 text-sm leading-normal text-on-night-2">
            <li
              v-for="item in list.items"
              :key="item.index"
              class="grid gap-1"
              data-testid="design-critique-item"
            >
              <span>{{ item.text }}</span>
              <template v-if="list.key === 'concerns'">
                <p
                  v-if="item.appliedTarget !== null"
                  class="text-[13px] font-semibold text-petrol-on-night-2"
                  data-testid="design-observation-applied"
                >
                  {{ copy.applied[item.appliedTarget] }}
                </p>
                <details v-else class="group" data-testid="design-critique-bring">
                  <summary
                    class="inline-flex min-h-11 cursor-pointer items-center text-[13px] font-semibold text-petrol-on-night-2 underline-offset-4 hover:underline"
                  >
                    {{ copy.bring }}
                  </summary>
                  <div
                    class="flex flex-wrap gap-1.5 pb-1"
                    role="group"
                    :aria-label="copy.bringGroup"
                  >
                    <button
                      v-for="target in TARGETS"
                      :key="target"
                      type="button"
                      class="inline-flex min-h-11 items-center rounded-pill border border-night-line-strong px-3 text-xs text-on-night transition-colors duration-150 hover:bg-night-hover disabled:cursor-not-allowed disabled:opacity-60"
                      :disabled="applying !== null"
                      :data-target="target"
                      data-testid="design-observation-target"
                      @click="bring(target, item.source)"
                    >
                      {{ copy.targets[target] }}
                    </button>
                  </div>
                </details>
                <p v-if="applying === item.source.id" class="text-xs text-on-night-3" role="status">
                  {{ copy.applying }}
                </p>
                <p
                  v-if="applyFailure !== null && applyFailure.id === item.source.id"
                  class="text-xs font-semibold text-fail-on-night"
                  role="alert"
                >
                  {{ applyError(applyFailure.code) }}
                </p>
              </template>
            </li>
          </ul>
        </UiClaimFrame>
      </li>
    </ul>
    <p v-else class="text-sm text-on-night-3" data-testid="design-observation-empty">
      {{ copy.nothing }}
    </p>
  </section>
</template>
