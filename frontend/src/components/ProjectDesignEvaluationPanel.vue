<script setup lang="ts">
import { computed, onMounted, reactive, ref, useId, watch } from "vue";

import GenerationJobNotice from "./GenerationJobNotice.vue";
import ArtifactWhy from "./ArtifactWhy.vue";
import InsightApplyMenu from "./InsightApplyMenu.vue";
import UiButton from "./UiButton.vue";
import {
  elementNames,
  placeLabel,
  placeScreens,
  withScreenNames,
  type ScreenName,
  type ScreenNaming,
  type WorkflowName,
} from "./screenNames";
import { apiClient } from "@/api/client";
import { designLoopApi, type DesignLoopApi } from "@/api/designLoop";
import { isGenerationInterrupted } from "@/api/generationJobs";
import { useAuthStore } from "@/stores/auth";
import {
  type AuthorizedDesignLoopRequest,
  EVALUATOR_NOT_CONFIGURED,
  findingKey,
  REVIEWER_NOT_CONFIGURED,
  runFindings,
  runMode,
  useDesignLoopStore,
} from "@/stores/designLoop";
import { useGenerationResume } from "@/stores/generationJobs";
import type {
  DesignEvaluationMode,
  DesignEvaluationRunPayload,
  FindingDecision,
  InsightApplicationPayload,
  InsightSource,
  SyntheticFindingPayload,
  SyntheticFindingSeverity,
} from "@/types/designLoop";

type Locale = "en" | "it";

const STATIC_CHECK_NOT_APPLICABLE = "STATIC_CHECK_NOT_APPLICABLE";
const FINDING_NOT_FOUND = "DESIGN_FINDING_NOT_FOUND";
const NOTE_LIMIT = 280;
const NOTICE_CODES = new Set([
  REVIEWER_NOT_CONFIGURED,
  EVALUATOR_NOT_CONFIGURED,
  STATIC_CHECK_NOT_APPLICABLE,
]);

const props = withDefaults(
  defineProps<{
    projectId: string;
    designVersionId: string;
    designContentHash: string;
    twinNames?: Record<string, string>;
    locale?: Locale;
    authorize?: AuthorizedDesignLoopRequest | undefined;
    api?: DesignLoopApi | undefined;
    autoEvaluateVersionId?: string | null;
    staticCheckAvailable?: boolean;
    screens?: readonly ScreenName[];
    elements?: Readonly<Record<string, string>>;
    workflows?: Readonly<Record<string, readonly WorkflowName[]>>;
  }>(),
  {
    twinNames: () => ({}),
    locale: "en",
    authorize: undefined,
    api: undefined,
    autoEvaluateVersionId: null,
    staticCheckAvailable: true,
    screens: () => [],
    elements: () => ({}),
    workflows: () => ({}),
  },
);

const emit = defineEmits<{
  evaluated: [run: DesignEvaluationRunPayload];
  applied: [application: InsightApplicationPayload];
}>();

const messages = {
  en: {
    title: "Synthetic pre-validation",
    intro:
      "Each twin reads the mockup and reports simulated findings: they are design hypotheses to weigh, not evidence from real users. Bring a finding into the brief, the requirements or the design, bring the design up to date and evaluate again.",
    history: "All the reviews ({n})",
    evaluate: "Ask the twins to evaluate the design",
    autoEvaluate: "The review starts on its own when you apply a design.",
    staticCheck: "Static accessibility check",
    staticHelp:
      "The static check looks at the fields and buttons of the mockup without the language model.",
    evaluating: "The twins are evaluating the design…",
    checking: "Checking the fields and buttons of the mockup…",
    empty: "No evaluation yet.",
    reviewerUnavailable:
      "The language model that plays the twins is not connected, so the twin review cannot start. You can still run the static accessibility check.",
    reviewerUnavailableAlone:
      "The language model that plays the twins is not connected, so the twin review cannot start.",
    evaluatorUnavailable:
      "The static accessibility check is not available in this installation of the Studio. The review of the twins is still available.",
    staticNotApplicable:
      "The static check needs at least one screen with both a field and a button. This design has none, so there is nothing to check.",
    run: "Evaluation of {date}",
    kind: {
      TWIN_REVIEW: "Twin review",
      STATIC_CHECK: "Static accessibility check",
    },
    version: "design version {n}, {code}",
    findings: "{n} findings",
    noFindings: "No findings: the twin had nothing to object.",
    summary: "Summary",
    gaps: "Evidence gaps",
    recommended: "Suggested action",
    location: "Where",
    confidence: "confidence {value}",
    comparison: "Compared with the previous evaluation",
    comparisonOf: {
      TWIN_REVIEW: "Compared with the previous twin review",
      STATIC_CHECK: "Compared with the previous static check",
    },
    resolved: "resolved",
    persisting: "still open",
    introduced: "new",
    dismissed: "marked not relevant by you",
    resolvedList: "Findings resolved by the last change",
    decisionGroup: "Your decision on this finding",
    confirm: "I confirm",
    dismiss: "Not relevant",
    noteLabel: "Short note for your decision (optional)",
    notePlaceholder: "Short note (optional)",
    decision: {
      OWNER_CONFIRMED: "Confirmed by you",
      OWNER_DISMISSED: "Marked not relevant",
    },
    dismissedHint:
      "Set aside: it is not brought into the project and does not count in the comparison.",
    yourNote: "Your note: {note}",
    saving: "Saving your decision…",
    decisionError: "Your decision could not be saved. Try again.",
    findingNotFound: "This finding is no longer available. Reload the page.",
    details: "Details",
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
    loadError: "The evaluations could not be loaded.",
  },
  it: {
    title: "Pre-validazione sintetica",
    intro:
      "Ogni twin legge il mockup e riporta osservazioni simulate: sono ipotesi di design da pesare, non evidenze di utenti reali. Porta un'osservazione nel brief, nei requisiti o nel design, aggiorna il design e valuta di nuovo.",
    history: "Tutte le revisioni ({n})",
    evaluate: "Chiedi ai twin di valutare il design",
    autoEvaluate: "La valutazione parte da sola quando applichi un design.",
    staticCheck: "Controllo statico di accessibilità",
    staticHelp:
      "Il controllo statico esamina i campi e i pulsanti del mockup senza usare il modello linguistico.",
    evaluating: "I twin stanno valutando il design…",
    checking: "Controllo dei campi e dei pulsanti del mockup in corso…",
    empty: "Nessuna valutazione ancora.",
    reviewerUnavailable:
      "Il modello linguistico che interpreta i twin non è collegato, quindi la revisione dei twin non può partire. Puoi comunque eseguire il controllo statico di accessibilità.",
    reviewerUnavailableAlone:
      "Il modello linguistico che interpreta i twin non è collegato, quindi la revisione dei twin non può partire.",
    evaluatorUnavailable:
      "Il controllo statico di accessibilità non è disponibile in questa installazione dello Studio. La revisione dei twin resta disponibile.",
    staticNotApplicable:
      "Il controllo statico richiede almeno una schermata con un campo e un pulsante. Questo design non ne ha, quindi non c'è nulla da controllare.",
    run: "Valutazione del {date}",
    kind: {
      TWIN_REVIEW: "Revisione dei twin",
      STATIC_CHECK: "Controllo statico di accessibilità",
    },
    version: "design versione {n}, {code}",
    findings: "{n} osservazioni",
    noFindings: "Nessuna osservazione: il twin non ha nulla da obiettare.",
    summary: "Sintesi",
    gaps: "Evidenze mancanti",
    recommended: "Azione suggerita",
    location: "Dove",
    confidence: "confidenza {value}",
    comparison: "Confronto con la valutazione precedente",
    comparisonOf: {
      TWIN_REVIEW: "Confronto con la revisione dei twin precedente",
      STATIC_CHECK: "Confronto con il controllo statico precedente",
    },
    resolved: "risolte",
    persisting: "ancora aperte",
    introduced: "nuove",
    dismissed: "segnate da te come non pertinenti",
    resolvedList: "Osservazioni risolte dall'ultima modifica",
    decisionGroup: "La tua decisione su questa osservazione",
    confirm: "Confermo",
    dismiss: "Non pertinente",
    noteLabel: "Nota breve per la tua decisione (facoltativa)",
    notePlaceholder: "Nota breve (facoltativa)",
    decision: {
      OWNER_CONFIRMED: "Confermata da te",
      OWNER_DISMISSED: "Segnata come non pertinente",
    },
    dismissedHint: "Messa da parte: non viene portata nel progetto e non conta nel confronto.",
    yourNote: "La tua nota: {note}",
    saving: "Salvo la tua decisione…",
    decisionError: "Non è stato possibile salvare la tua decisione. Riprova.",
    findingNotFound: "Questa osservazione non è più disponibile. Ricarica la pagina.",
    details: "Dettagli",
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
    loadError: "Non è stato possibile caricare le valutazioni.",
  },
} as const;

const auth = useAuthStore();
const store = useDesignLoopStore();
const idPrefix = `finding-note-${useId()}`;
const titleId = `design-evaluation-${useId()}`;
const copy = computed(() => messages[props.locale]);
const api = computed(() => props.api ?? designLoopApi);
const authorize: AuthorizedDesignLoopRequest = (operation) =>
  props.authorize ? props.authorize(operation) : auth.withAccessToken(apiClient, operation);
const active = computed(() => store.projectId === props.projectId);
const runs = computed(() => (active.value ? store.runs : []));
const comparison = computed(() => (active.value ? store.comparison : null));
const evaluating = computed(() => store.busy === "evaluate");
const runningMode = ref<DesignEvaluationMode>("TWIN_REVIEW");
const failure = ref<string | null>(null);
const loadFailure = ref<string | null>(null);
const decisionFailure = ref<{ key: string; code: string } | null>(null);
const notes = reactive<Record<string, string>>({});
const runsLoaded = ref(false);
const autoStarted = new Set<string>();

const {
  job: reviewJob,
  checked: reviewChecked,
  failure: reviewFailure,
  dismiss: dismissReviewFailure,
} = useGenerationResume({
  projectId: () => props.projectId,
  operations: ["DESIGN_EVALUATION"],
  authorize,
  onSettled: load,
});

const reviewShown = computed(() =>
  evaluating.value && runningMode.value === "STATIC_CHECK" ? null : reviewJob.value,
);

watch(reviewJob, (running) => {
  if (running !== null) {
    autoStarted.add(props.designVersionId);
  }
});

const autoReviewDue = computed(
  () =>
    props.autoEvaluateVersionId !== null &&
    props.autoEvaluateVersionId === props.designVersionId &&
    runsLoaded.value &&
    reviewChecked.value &&
    reviewJob.value === null &&
    active.value &&
    !store.isBusy &&
    !runs.value.some(
      (run) =>
        runMode(run) === "TWIN_REVIEW" &&
        run.design_version_id === props.designVersionId &&
        run.design_content_hash === props.designContentHash,
    ),
);

const comparisonTitle = computed(() => {
  const head = runs.value.find((run) => run.id === comparison.value?.head_run_id);
  return head === undefined ? copy.value.comparison : copy.value.comparisonOf[runMode(head)];
});

const runViews = computed(() =>
  runs.value.map((run) => {
    const naming = namingOf(run);
    const named = (text: string) => withScreenNames(text, naming);
    return {
      run,
      mode: runMode(run),
      responses: run.responses.map((response) => ({
        response,
        summary: named(response.summary),
        gaps: response.evidence_gaps.map(named),
        findings: response.findings.map((finding) => {
          const key = findingKey(run.id, finding.twin_id, finding.finding_id);
          const validation = store.validationByKey[key] ?? null;
          return {
            finding,
            key,
            validation,
            dismissed: validation?.decision === "OWNER_DISMISSED",
            source: sourceOf(run, finding, named),
            summary: named(finding.summary),
            location: named(placeLabel(finding.location)),
            rationale: named(finding.rationale),
            action: named(finding.recommended_action),
          };
        }),
      })),
    };
  }),
);

const resolvedViews = computed(() => {
  const value = comparison.value;
  if (value === null) {
    return [];
  }
  const base = runs.value.find((run) => run.id === value.base_run_id);
  const locations = value.resolved.map((finding) => finding.location);
  const naming: ScreenNaming =
    base === undefined
      ? {
          screens: placeScreens(locations),
          elements: elementNames(locations),
          locale: props.locale,
        }
      : namingOf(base);
  return value.resolved.map((finding) => ({
    finding,
    summary: withScreenNames(finding.summary, naming),
  }));
});

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

function frameClass(decision: FindingDecision | null): string {
  if (decision === "OWNER_DISMISSED") {
    return "border border-dashed border-night-line-strong bg-transparent opacity-75";
  }
  if (decision === "OWNER_CONFIRMED") {
    return "border border-petrol-on-night bg-night-raised";
  }
  return "border-[1.5px] border-dashed border-violet-on-night/70 bg-on-night/3";
}

function severityClass(severity: SyntheticFindingSeverity): string {
  if (severity === "critical") {
    return "bg-fail-on-night/12 text-fail-on-night";
  }
  if (severity === "major") {
    return "bg-warn-on-night/12 text-warn-on-night";
  }
  return "bg-on-night/8 text-on-night-2";
}

function kindClass(mode: DesignEvaluationMode): string {
  return mode === "TWIN_REVIEW"
    ? "border-dashed border-violet-on-night text-violet-on-night-2"
    : "border-on-night/40 text-on-night-2";
}

function decisionClass(decision: FindingDecision): string {
  return decision === "OWNER_CONFIRMED"
    ? "border-petrol-on-night/60 bg-petrol-on-night/12 text-petrol-on-night-2"
    : "border-night-line-strong text-on-night-2";
}

function decisionButtonClass(pressed: boolean, decision: FindingDecision): string {
  return pressed
    ? decisionClass(decision)
    : "border-night-line-strong text-on-night hover:bg-night-hover";
}

function namingOf(run: DesignEvaluationRunPayload): ScreenNaming {
  const locations = run.responses.flatMap((response) =>
    response.findings.map((finding) => finding.location),
  );
  const current =
    run.design_version_id === props.designVersionId &&
    run.design_content_hash === props.designContentHash;
  return {
    screens: current ? [...props.screens, ...placeScreens(locations)] : placeScreens(locations),
    elements: current ? { ...props.elements, ...elementNames(locations) } : elementNames(locations),
    workflows: props.workflows[run.alternative_id] ?? [],
    locale: props.locale,
  };
}

function sourceOf(
  run: DesignEvaluationRunPayload,
  finding: SyntheticFindingPayload,
  named: (text: string) => string,
): InsightSource {
  return {
    kind: "SYNTHETIC_FINDING",
    id: `run:${run.id}:${finding.twin_id}:${finding.finding_id}`,
    twinId: finding.twin_id,
    text: named(finding.summary),
    mitigation: named(finding.recommended_action),
  };
}

async function load(): Promise<void> {
  loadFailure.value = null;
  runsLoaded.value = false;
  try {
    await store.load(props.projectId, authorize, api.value);
    runsLoaded.value = true;
  } catch {
    loadFailure.value = store.error ?? "DESIGN_LOOP_REQUEST_FAILED";
  }
}

async function evaluate(mode: DesignEvaluationMode): Promise<void> {
  if (store.isBusy || reviewJob.value !== null) return;
  runningMode.value = mode;
  failure.value = null;
  dismissReviewFailure();
  try {
    const run = await store.evaluate(
      props.projectId,
      props.designVersionId,
      props.designContentHash,
      authorize,
      api.value,
      mode,
      props.locale === "it" ? "it-IT" : "en-US",
    );
    emit("evaluated", run);
  } catch {
    const code = store.error ?? "DESIGN_LOOP_REQUEST_FAILED";
    failure.value = isGenerationInterrupted(code) ? null : code;
  }
}

async function decide(
  run: DesignEvaluationRunPayload,
  finding: SyntheticFindingPayload,
  decision: FindingDecision,
): Promise<void> {
  if (store.validating !== null) return;
  const key = findingKey(run.id, finding.twin_id, finding.finding_id);
  const note = (notes[key] ?? "").trim().replace(/\s+/g, " ");
  decisionFailure.value = null;
  try {
    await store.validate(
      props.projectId,
      run.id,
      {
        twin_id: finding.twin_id,
        finding_id: finding.finding_id,
        decision,
        note: note.length === 0 ? null : note,
      },
      authorize,
      api.value,
    );
    notes[key] = "";
  } catch {
    decisionFailure.value = { key, code: store.validationError ?? "DESIGN_LOOP_REQUEST_FAILED" };
  }
}

async function autoEvaluate(): Promise<void> {
  const versionId = props.designVersionId;
  if (!autoReviewDue.value || autoStarted.has(versionId)) return;
  autoStarted.add(versionId);
  await evaluate("TWIN_REVIEW");
}

onMounted(load);
watch(() => props.projectId, load);
watch(autoReviewDue, (due) => {
  if (due) void autoEvaluate();
});
</script>

<template>
  <section
    class="grid gap-4 text-on-night"
    :aria-labelledby="titleId"
    data-testid="design-evaluation-panel"
  >
    <header class="flex flex-wrap items-center gap-x-4 gap-y-3">
      <div class="grid min-w-[min(100%,16rem)] flex-1 gap-1">
        <h3 :id="titleId" class="m-0 text-base font-semibold">{{ copy.title }}</h3>
        <p class="m-0 text-sm text-on-night-3" data-testid="design-evaluate-auto">
          {{ copy.autoEvaluate }}
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <UiButton
          variant="outline"
          :disabled="store.isBusy || reviewJob !== null"
          data-testid="design-evaluate"
          @click="evaluate('TWIN_REVIEW')"
        >
          {{ copy.evaluate }}
        </UiButton>
        <UiButton
          v-if="staticCheckAvailable"
          variant="quiet"
          :disabled="store.isBusy || reviewJob !== null"
          :title="copy.staticHelp"
          data-testid="design-static-check"
          @click="evaluate('STATIC_CHECK')"
        >
          {{ copy.staticCheck }}
        </UiButton>
      </div>
    </header>
    <GenerationJobNotice
      v-if="reviewShown !== null || reviewFailure !== null"
      :job="reviewShown"
      :failure="reviewFailure"
      :locale="locale"
      @dismiss="dismissReviewFailure"
    />
    <p
      v-else-if="evaluating"
      class="m-0 inline-flex items-center gap-2.5 text-sm text-on-night-2"
      aria-live="polite"
    >
      <span
        class="inline-block h-[15px] w-[15px] shrink-0 animate-spin-arc rounded-full border-2 border-night-line-strong border-t-petrol-on-night"
        aria-hidden="true"
      />
      {{ runningMode === "STATIC_CHECK" ? copy.checking : copy.evaluating }}
    </p>
    <p
      v-if="store.reviewerUnavailable && active"
      class="m-0 rounded-field border border-night-line bg-on-night/3 px-4 py-3 text-sm text-on-night-2"
      role="status"
      data-testid="design-reviewer-unavailable"
    >
      {{ staticCheckAvailable ? copy.reviewerUnavailable : copy.reviewerUnavailableAlone }}
    </p>
    <p
      v-if="store.evaluatorUnavailable && active"
      class="m-0 rounded-field border border-night-line bg-on-night/3 px-4 py-3 text-sm text-on-night-2"
      role="status"
      data-testid="design-evaluator-unavailable"
    >
      {{ copy.evaluatorUnavailable }}
    </p>
    <p
      v-if="failure === STATIC_CHECK_NOT_APPLICABLE"
      class="m-0 rounded-field border border-night-line bg-on-night/3 px-4 py-3 text-sm text-on-night-2"
      role="status"
      data-testid="design-static-not-applicable"
    >
      {{ copy.staticNotApplicable }}
    </p>
    <div
      v-else-if="failure !== null && !NOTICE_CODES.has(failure)"
      class="grid gap-1 rounded-field border border-fail-on-night/40 bg-fail-on-night/10 px-4 py-3 text-sm text-fail-on-night"
      role="alert"
      data-testid="design-evaluation-error"
    >
      <p class="m-0 font-semibold">{{ copy.error }}</p>
      <details class="text-xs">
        <summary class="inline-flex min-h-11 cursor-pointer items-center">
          {{ copy.details }}
        </summary>
        <code class="break-all">{{ failure }}</code>
      </details>
    </div>
    <div
      v-if="loadFailure !== null"
      class="grid gap-1 rounded-field border border-fail-on-night/40 bg-fail-on-night/10 px-4 py-3 text-sm text-fail-on-night"
      role="alert"
    >
      <p class="m-0 font-semibold">{{ copy.loadError }}</p>
      <details class="text-xs">
        <summary class="inline-flex min-h-11 cursor-pointer items-center">
          {{ copy.details }}
        </summary>
        <code class="break-all">{{ loadFailure }}</code>
      </details>
    </div>

    <section
      v-if="comparison"
      class="grid gap-2 rounded-field border border-petrol-on-night/35 bg-petrol-on-night/8 px-4 py-3"
      data-testid="design-evaluation-comparison"
    >
      <h4 class="m-0 text-sm font-semibold text-petrol-on-night-2">{{ comparisonTitle }}</h4>
      <p class="m-0 text-sm text-on-night">
        <strong>{{ comparison.counts.resolved }}</strong> {{ copy.resolved }} ·
        <strong>{{ comparison.counts.persisting }}</strong> {{ copy.persisting }} ·
        <strong>{{ comparison.counts.introduced }}</strong> {{ copy.introduced }}
        <template v-if="comparison.counts.dismissed > 0">
          · <strong>{{ comparison.counts.dismissed }}</strong> {{ copy.dismissed }}
        </template>
      </p>
      <ul v-if="resolvedViews.length > 0" class="m-0 grid list-none gap-1 p-0 text-sm">
        <li class="font-semibold text-on-night-2">{{ copy.resolvedList }}</li>
        <li
          v-for="resolved in resolvedViews"
          :key="resolved.finding.content_hash"
          class="text-on-night-2"
        >
          {{ twinName(resolved.finding.twin_id) }}: {{ resolved.summary }}
        </li>
      </ul>
    </section>

    <p v-if="runs.length === 0 && !evaluating" class="m-0 text-sm text-on-night-3">
      {{ copy.empty }}
    </p>

    <details
      v-if="runViews.length > 0"
      class="group rounded-field border border-night-line"
      data-testid="design-evaluation-history"
    >
      <summary
        class="flex min-h-11 cursor-pointer list-none items-center gap-2.5 px-4 text-sm font-semibold text-on-night-2 [&::-webkit-details-marker]:hidden"
      >
        <span
          aria-hidden="true"
          class="inline-block h-1.5 w-1.5 shrink-0 -rotate-45 border-r-[1.5px] border-b-[1.5px] border-on-night-2 transition-transform duration-150 group-open:rotate-45"
        />
        {{ fill(copy.history, { n: runViews.length }) }}
      </summary>
      <div class="grid gap-3 border-t border-night-line p-3 sm:p-4">
        <p class="m-0 text-[13px] leading-normal text-on-night-3">{{ copy.intro }}</p>
        <article
          v-for="view in runViews"
          :key="view.run.id"
          class="grid gap-4 rounded-field border border-night-line bg-on-night/3 p-4"
          :data-mode="view.mode"
          data-testid="design-evaluation-run"
        >
          <header class="flex flex-wrap items-baseline justify-between gap-2">
            <div class="flex flex-wrap items-center gap-2">
              <h4 class="m-0 text-[15px] font-semibold">
                {{ fill(copy.run, { date: formatDate(view.run.completed_at) }) }}
              </h4>
              <span
                class="inline-flex min-h-6 items-center rounded-pill border px-2.5 text-xs font-semibold"
                :class="kindClass(view.mode)"
                data-testid="design-evaluation-kind"
              >
                {{ copy.kind[view.mode] }}
              </span>
            </div>
            <span class="font-mono text-xs text-on-night-3">
              {{
                fill(copy.version, {
                  n: view.run.design_version_number,
                  code: view.run.alternative_code,
                })
              }}
              · {{ fill(copy.findings, { n: runFindings(view.run).length }) }}
            </span>
          </header>
          <section
            v-for="item in view.responses"
            :key="item.response.twin_id"
            class="grid gap-3"
            data-testid="design-evaluation-twin"
          >
            <p class="m-0 text-sm leading-normal">
              <strong>{{ twinName(item.response.twin_id) }}</strong>
              <span class="text-on-night-2"> · {{ copy.summary }}: {{ item.summary }}</span>
            </p>
            <p v-if="item.gaps.length > 0" class="m-0 text-xs text-on-night-3">
              {{ copy.gaps }}: {{ item.gaps.join("; ") }}
            </p>
            <p v-if="item.findings.length === 0" class="m-0 text-sm text-on-night-3">
              {{ copy.noFindings }}
            </p>
            <ul v-else class="m-0 grid list-none gap-3 p-0">
              <li
                v-for="entry in item.findings"
                :key="entry.finding.content_hash"
                class="grid gap-2 rounded-field p-4"
                :class="frameClass(entry.validation?.decision ?? null)"
                :data-decision="entry.validation?.decision ?? 'NONE'"
                data-testid="design-finding"
              >
                <div class="flex flex-wrap items-center gap-2 text-xs">
                  <span
                    class="inline-flex min-h-6 items-center rounded-pill px-2.5 font-semibold"
                    :class="severityClass(entry.finding.severity)"
                  >
                    {{ copy.severity[entry.finding.severity] }}
                  </span>
                  <span class="text-on-night-3">{{ copy.criterion[entry.finding.criterion] }}</span>
                  <span class="font-mono text-on-night-3">{{ entry.finding.finding_id }}</span>
                  <span class="text-on-night-3">{{
                    fill(copy.confidence, { value: confidence(entry.finding.confidence) })
                  }}</span>
                  <span
                    v-if="entry.validation"
                    class="inline-flex min-h-6 items-center rounded-pill border px-2.5 font-semibold"
                    :class="decisionClass(entry.validation.decision)"
                    data-testid="finding-decision-chip"
                  >
                    {{ copy.decision[entry.validation.decision] }}
                  </span>
                </div>
                <p class="m-0 text-[15px] leading-[1.4] font-semibold">
                  {{ entry.summary }}
                </p>
                <ArtifactWhy
                  :code="entry.finding.finding_id"
                  :title="entry.summary"
                  kind="SYNTHETIC_FINDING"
                  :version-number="entry.finding.artifact_version"
                  :content-hash="entry.finding.content_hash"
                  :contexts="[view.run.id, entry.finding.twin_id]"
                  :locale="locale"
                  test-id="finding-why"
                />
                <p class="m-0 text-[13px] text-on-night-3">
                  {{ copy.location }}: {{ entry.location }}
                </p>
                <p class="m-0 text-sm leading-normal text-on-night-2">
                  {{ entry.rationale }}
                </p>
                <p class="m-0 text-sm leading-normal text-on-night-2">
                  <strong class="font-semibold text-on-night">{{ copy.recommended }}:</strong>
                  {{ entry.action }}
                </p>
                <p
                  v-if="entry.dismissed"
                  class="m-0 text-xs text-on-night-3"
                  data-testid="finding-dismissed-hint"
                >
                  {{ copy.dismissedHint }}
                </p>
                <p v-if="entry.validation?.note" class="m-0 text-xs text-on-night-2">
                  {{ fill(copy.yourNote, { note: entry.validation.note }) }}
                </p>
                <div
                  class="flex flex-wrap items-center gap-2 text-xs"
                  role="group"
                  :aria-label="copy.decisionGroup"
                  data-testid="finding-decision"
                >
                  <label :for="`${idPrefix}-${entry.key}`" class="sr-only">{{
                    copy.noteLabel
                  }}</label>
                  <input
                    :id="`${idPrefix}-${entry.key}`"
                    v-model="notes[entry.key]"
                    type="text"
                    :maxlength="NOTE_LIMIT"
                    :placeholder="copy.notePlaceholder"
                    :disabled="store.validating !== null"
                    class="min-h-11 min-w-0 flex-1 rounded-field border border-night-line-strong bg-night-panel px-3 text-[13px] text-on-night placeholder:text-on-night-3 sm:max-w-xs"
                    data-testid="finding-note"
                  />
                  <button
                    type="button"
                    class="inline-flex min-h-11 items-center rounded-pill border px-3.5 text-[13px] font-semibold transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-60"
                    :class="
                      decisionButtonClass(
                        entry.validation?.decision === 'OWNER_CONFIRMED',
                        'OWNER_CONFIRMED',
                      )
                    "
                    :aria-pressed="entry.validation?.decision === 'OWNER_CONFIRMED'"
                    :disabled="store.validating !== null"
                    data-testid="finding-confirm"
                    @click="decide(view.run, entry.finding, 'OWNER_CONFIRMED')"
                  >
                    {{ copy.confirm }}
                  </button>
                  <button
                    type="button"
                    class="inline-flex min-h-11 items-center rounded-pill border px-3.5 text-[13px] font-semibold transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-60"
                    :class="
                      decisionButtonClass(
                        entry.validation?.decision === 'OWNER_DISMISSED',
                        'OWNER_DISMISSED',
                      )
                    "
                    :aria-pressed="entry.validation?.decision === 'OWNER_DISMISSED'"
                    :disabled="store.validating !== null"
                    data-testid="finding-dismiss"
                    @click="decide(view.run, entry.finding, 'OWNER_DISMISSED')"
                  >
                    {{ copy.dismiss }}
                  </button>
                  <span
                    v-if="store.validating === entry.key"
                    class="text-on-night-3"
                    aria-live="polite"
                  >
                    {{ copy.saving }}
                  </span>
                </div>
                <div
                  v-if="decisionFailure?.key === entry.key"
                  class="grid gap-1 text-xs font-semibold text-fail-on-night"
                  role="alert"
                  data-testid="finding-decision-error"
                >
                  <p class="m-0">
                    {{
                      decisionFailure.code === FINDING_NOT_FOUND
                        ? copy.findingNotFound
                        : copy.decisionError
                    }}
                  </p>
                  <details class="font-normal">
                    <summary class="inline-flex min-h-11 cursor-pointer items-center">
                      {{ copy.details }}
                    </summary>
                    <code class="break-all">{{ decisionFailure.code }}</code>
                  </details>
                </div>
                <InsightApplyMenu
                  v-if="!entry.dismissed"
                  :project-id="projectId"
                  :source="entry.source"
                  :locale="locale"
                  :authorize="authorize"
                  :api="api"
                  @applied="emit('applied', $event)"
                />
              </li>
            </ul>
          </section>
        </article>
      </div>
    </details>
  </section>
</template>
