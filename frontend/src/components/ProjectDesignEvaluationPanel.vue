<script setup lang="ts">
import { computed, onMounted, watch } from "vue";

import InsightApplyMenu from "./InsightApplyMenu.vue";
import { apiClient } from "@/api/client";
import { designLoopApi, type DesignLoopApi } from "@/api/designLoop";
import { useAuthStore } from "@/stores/auth";
import {
  type AuthorizedDesignLoopRequest,
  runFindings,
  useDesignLoopStore,
} from "@/stores/designLoop";
import type {
  DesignEvaluationRunPayload,
  SyntheticFindingPayload,
  SyntheticFindingSeverity,
} from "@/types/designLoop";

type Locale = "en" | "it";

const props = withDefaults(
  defineProps<{
    projectId: string;
    designVersionId: string;
    designContentHash: string;
    twinNames?: Record<string, string>;
    locale?: Locale;
    authorize?: AuthorizedDesignLoopRequest | undefined;
    api?: DesignLoopApi | undefined;
  }>(),
  { twinNames: () => ({}), locale: "en", authorize: undefined, api: undefined },
);

const emit = defineEmits<{ evaluated: [run: DesignEvaluationRunPayload] }>();

const messages = {
  en: {
    eyebrow: "Twin feedback loop",
    title: "What the user twins think of the chosen design",
    intro:
      "Each twin reads the mockup and reports simulated findings: they are design hypotheses to weigh, not evidence from real users. Bring a finding into the brief, the requirements or the design, regenerate the design and evaluate again.",
    evaluate: "Ask the twins to evaluate the design",
    evaluating: "The twins are evaluating the design…",
    empty: "No evaluation yet.",
    unavailable:
      "The local evaluator is not configured: start the Studio with the evaluator to run the twins.",
    run: "Evaluation of {date}",
    version: "design version {n}, {code}",
    findings: "{n} findings",
    noFindings: "No findings: the twin had nothing to object.",
    summary: "Summary",
    gaps: "Evidence gaps",
    recommended: "Suggested action",
    location: "Where",
    confidence: "confidence {value}",
    comparison: "Compared with the previous evaluation",
    resolved: "resolved",
    persisting: "still open",
    introduced: "new",
    resolvedList: "Findings resolved by the last change",
    severity: {
      critical: "Critical",
      major: "Major",
      moderate: "Moderate",
      minor: "Minor",
      observation: "Observation",
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
    error: "The evaluation could not be completed.",
  },
  it: {
    eyebrow: "Ciclo di feedback dei twin",
    title: "Cosa pensano gli user twin del design scelto",
    intro:
      "Ogni twin legge il mockup e riporta osservazioni simulate: sono ipotesi di design da pesare, non evidenze di utenti reali. Porta un'osservazione nel brief, nei requisiti o nel design, rigenera il design e valuta di nuovo.",
    evaluate: "Chiedi ai twin di valutare il design",
    evaluating: "I twin stanno valutando il design…",
    empty: "Nessuna valutazione ancora.",
    unavailable:
      "L'evaluator locale non è configurato: avvia lo Studio con l'evaluator per far lavorare i twin.",
    run: "Valutazione del {date}",
    version: "design versione {n}, {code}",
    findings: "{n} osservazioni",
    noFindings: "Nessuna osservazione: il twin non ha nulla da obiettare.",
    summary: "Sintesi",
    gaps: "Evidenze mancanti",
    recommended: "Azione suggerita",
    location: "Dove",
    confidence: "confidenza {value}",
    comparison: "Confronto con la valutazione precedente",
    resolved: "risolte",
    persisting: "ancora aperte",
    introduced: "nuove",
    resolvedList: "Osservazioni risolte dall'ultima modifica",
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
    error: "La valutazione non è stata completata.",
  },
} as const;

const auth = useAuthStore();
const store = useDesignLoopStore();
const copy = computed(() => messages[props.locale]);
const api = computed(() => props.api ?? designLoopApi);
const authorize: AuthorizedDesignLoopRequest = (operation) =>
  props.authorize ? props.authorize(operation) : auth.withAccessToken(apiClient, operation);
const runs = computed(() => (store.projectId === props.projectId ? store.runs : []));
const comparison = computed(() => (store.projectId === props.projectId ? store.comparison : null));
const evaluating = computed(() => store.busy === "evaluate");

function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_match, key: string) => String(values[key] ?? ""));
}

function twinName(id: string): string {
  return props.twinNames[id] ?? id.slice(0, 8);
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(props.locale, { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(value),
  );
}

function confidence(value: number): string {
  return new Intl.NumberFormat(props.locale, { style: "percent", maximumFractionDigits: 0 }).format(
    value,
  );
}

function severityClass(severity: SyntheticFindingSeverity): string {
  if (severity === "critical" || severity === "major") {
    return "border-fail-line bg-fail-bg text-fail-dark";
  }
  if (severity === "moderate") {
    return "border-hypothesis-line bg-hypothesis-bg text-hypothesis-text";
  }
  return "border-line bg-surface-3 text-ink-2";
}

function sourceOf(run: DesignEvaluationRunPayload, finding: SyntheticFindingPayload) {
  return {
    kind: "SYNTHETIC_FINDING" as const,
    id: `run:${run.id}:${finding.twin_id}:${finding.finding_id}`,
    twinId: finding.twin_id,
    text: finding.summary,
    mitigation: finding.recommended_action,
  };
}

async function load(): Promise<void> {
  try {
    await store.load(props.projectId, authorize, api.value);
  } catch {
    return;
  }
}

async function evaluate(): Promise<void> {
  if (store.isBusy) return;
  try {
    const run = await store.evaluate(
      props.projectId,
      props.designVersionId,
      props.designContentHash,
      authorize,
      api.value,
    );
    emit("evaluated", run);
  } catch {
    return;
  }
}

onMounted(load);
watch(() => props.projectId, load);
</script>

<template>
  <section
    class="grid gap-4 rounded-card border border-line bg-white p-4 shadow-sm sm:p-5"
    data-testid="design-evaluation-panel"
  >
    <header class="grid gap-2">
      <p class="m-0 text-xs font-semibold tracking-widest text-action uppercase">
        {{ copy.eyebrow }}
      </p>
      <h3 class="m-0 text-lg font-bold text-ink">{{ copy.title }}</h3>
      <p class="m-0 max-w-3xl text-sm leading-6 text-ink-2">{{ copy.intro }}</p>
    </header>
    <div class="flex flex-wrap items-center gap-3">
      <button
        type="button"
        class="rounded-panel bg-action px-5 py-3 font-semibold text-white hover:bg-action-hover disabled:cursor-not-allowed disabled:bg-surface-3"
        :disabled="store.isBusy"
        data-testid="design-evaluate"
        @click="evaluate"
      >
        {{ copy.evaluate }}
      </button>
      <p v-if="evaluating" class="m-0 text-sm text-ink-2" aria-live="polite">
        {{ copy.evaluating }}
      </p>
    </div>
    <p
      v-if="store.evaluatorUnavailable"
      class="m-0 rounded-panel border border-line bg-surface-3 p-3 text-sm text-ink-2"
      role="status"
    >
      {{ copy.unavailable }}
    </p>
    <p
      v-else-if="store.error && store.projectId === projectId"
      class="m-0 rounded-panel border border-fail-line bg-fail-bg p-3 text-sm font-semibold text-fail-dark"
      role="alert"
    >
      {{ copy.error }} ({{ store.error }})
    </p>

    <section
      v-if="comparison"
      class="grid gap-2 rounded-panel border border-action-soft-line bg-action-soft p-4"
      data-testid="design-evaluation-comparison"
    >
      <h4 class="m-0 text-sm font-semibold text-action">{{ copy.comparison }}</h4>
      <p class="m-0 text-sm text-ink">
        <strong>{{ comparison.counts.resolved }}</strong> {{ copy.resolved }} ·
        <strong>{{ comparison.counts.persisting }}</strong> {{ copy.persisting }} ·
        <strong>{{ comparison.counts.introduced }}</strong> {{ copy.introduced }}
      </p>
      <ul v-if="comparison.resolved.length > 0" class="m-0 grid list-none gap-1 p-0 text-sm">
        <li class="font-semibold text-ink-2">{{ copy.resolvedList }}</li>
        <li v-for="finding in comparison.resolved" :key="finding.content_hash" class="text-ink-2">
          {{ twinName(finding.twin_id) }}: {{ finding.summary }}
        </li>
      </ul>
    </section>

    <p v-if="runs.length === 0 && !evaluating" class="m-0 text-sm text-ink-3">{{ copy.empty }}</p>

    <article
      v-for="run in runs"
      :key="run.id"
      class="grid gap-4 rounded-panel border border-line p-4"
      data-testid="design-evaluation-run"
    >
      <header class="flex flex-wrap items-baseline justify-between gap-2">
        <h4 class="m-0 text-base font-semibold text-ink">
          {{ fill(copy.run, { date: formatDate(run.completed_at) }) }}
        </h4>
        <span class="font-mono text-xs text-ink-3">
          {{ fill(copy.version, { n: run.design_version_number, code: run.alternative_code }) }} ·
          {{ fill(copy.findings, { n: runFindings(run).length }) }}
        </span>
      </header>
      <section
        v-for="response in run.responses"
        :key="response.twin_id"
        class="grid gap-3"
        data-testid="design-evaluation-twin"
      >
        <p class="m-0 text-sm leading-6 text-ink">
          <strong>{{ twinName(response.twin_id) }}</strong>
          <span class="text-ink-2"> · {{ copy.summary }}: {{ response.summary }}</span>
        </p>
        <p v-if="response.evidence_gaps.length > 0" class="m-0 text-xs text-ink-3">
          {{ copy.gaps }}: {{ response.evidence_gaps.join("; ") }}
        </p>
        <p v-if="response.findings.length === 0" class="m-0 text-sm text-ink-3">
          {{ copy.noFindings }}
        </p>
        <ul v-else class="m-0 grid list-none gap-3 p-0">
          <li
            v-for="finding in response.findings"
            :key="finding.content_hash"
            class="grid gap-2 rounded-panel border p-3"
            :class="severityClass(finding.severity)"
            data-testid="design-finding"
          >
            <div class="flex flex-wrap items-center gap-2 text-xs font-semibold">
              <span class="rounded-pill border border-current px-2 py-0.5 uppercase">
                {{ copy.severity[finding.severity] }}
              </span>
              <span>{{ copy.criterion[finding.criterion] }}</span>
              <span class="font-mono font-normal">{{ finding.finding_id }}</span>
              <span class="font-normal">{{
                fill(copy.confidence, { value: confidence(finding.confidence) })
              }}</span>
            </div>
            <p class="m-0 text-sm font-semibold">{{ finding.summary }}</p>
            <p class="m-0 text-xs">
              <strong>{{ copy.location }}:</strong> {{ finding.location }}
            </p>
            <p class="m-0 text-sm">{{ finding.rationale }}</p>
            <p class="m-0 text-sm">
              <strong>{{ copy.recommended }}:</strong> {{ finding.recommended_action }}
            </p>
            <InsightApplyMenu
              :project-id="projectId"
              :source="sourceOf(run, finding)"
              :locale="locale"
              :authorize="authorize"
              :api="api"
            />
          </li>
        </ul>
      </section>
    </article>
  </section>
</template>
