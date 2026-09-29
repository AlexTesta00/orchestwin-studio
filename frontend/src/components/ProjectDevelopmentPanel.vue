<script setup lang="ts">
import { computed, provide, ref, watch } from "vue";

import { placeLabel } from "./screenNames";
import UiButton from "./UiButton.vue";
import UiClaimFrame from "./UiClaimFrame.vue";
import UiStatusChip from "./UiStatusChip.vue";
import { surfaceKey, type SurfaceContext } from "./UiSurface.vue";
import UiTechnicalDetails from "./UiTechnicalDetails.vue";

import { apiClient } from "../api/client";
import type { CodeChangesApi } from "../api/codeChanges";
import { useAuthStore } from "../stores/auth";
import { useCodeChangesStore, type AuthorizedRequest } from "../stores/codeChanges";
import { useDesignStore } from "../stores/design";
import { useRequirementsStore } from "../stores/requirements";
import type {
  AlignmentStatus,
  ChangeDecisionKind,
  CodeChangePayload,
  CodeSubjectsPayload,
  CritiqueFindingPayload,
  CritiqueVerdict,
  FindingSeverity,
} from "../types/codeChanges";

type Locale = "en" | "it";
type ChipStatus = "approved" | "pending" | "blocked" | "failed";

interface Subject {
  key: string;
  code: string | null;
  title: string | null;
}

interface Badge {
  status: ChipStatus;
  label: string;
}

const props = withDefaults(
  defineProps<{
    projectId: string;
    locale?: Locale;
    authorize?: AuthorizedRequest;
    api?: CodeChangesApi;
  }>(),
  {
    locale: "en",
  },
);

provide(
  surfaceKey,
  computed<SurfaceContext>(() => "night"),
);

const messages = {
  en: {
    eyebrow: "After the design",
    title: "Development outside the Studio",
    intro:
      "The code is written with your own tools. Here you read how the commits stand against the approved requirements and design.",
    terminal:
      "Reviews and decisions are made from the terminal with `ut align`: this page only shows their result.",
    refresh: "Refresh",
    refreshLabel: "Refresh the development state",
    loading: "Loading the development state…",
    loadFailed: "The development state could not be loaded.",
    details: "Details",
    noModel: "On this Studio the twins cannot review the code: connect a model.",
    empty: "No commit recorded yet. Record the first one with `ut align` or `ut watch`.",
    reference: "The approved reference",
    requirements: "Requirements",
    design: "Design",
    aligned: "Aligned point",
    versionValue: "version {number}",
    requirementsMissing: "not approved yet",
    designMissing: "not approved yet",
    alignedValue: "commit {commit} · {date}",
    noAligned: "No commit aligned yet",
    pendingTitle: "Pending commits ({count})",
    pendingIntro: "The commits recorded after the aligned point.",
    noPending: "No commit after the aligned point.",
    files: ["{count} file", "{count} files"],
    verdictBadge: {
      NONE: "Not reviewed yet",
      ALIGNED: "Review: aligned",
      CODE_DRIFT: "Review: the code should change",
      DESIGN_OUTDATED: "Review: the design should change",
      REQUIREMENTS_OUTDATED: "Review: the requirements should change",
    },
    decisionBadge: {
      NONE: "No decision yet",
      ALIGNED: "Decision: aligned point",
      DESIGN_CHANGE: "Decision: new design requested",
      REQUIREMENTS_CHANGE: "Decision: requirements change requested",
      CODE_TASKS: "Decision: tasks for the code",
      DISMISSED: "Decision: nothing to do",
    },
    tasksTitle: "Open tasks for the code ({count})",
    tasksIntro: "They close when a later commit is marked as aligned.",
    noTasks: "No open task.",
    latestReview: "Latest review",
    runTitle: "Latest review, commit {commit}",
    runMeta:
      "{date} · checked against requirements version {requirements} and design version {design}{alternative}",
    noRun: "No commit has been reviewed yet.",
    runLoading: "Loading the latest review…",
    runFailed: "The latest review could not be loaded.",
    runMissing: "The latest review is not available.",
    critique: {
      FINE: "No concerns",
      CONCERN: "Some concerns",
      DRIFT: "Off course",
    },
    severity: {
      LOW: "Minor",
      MEDIUM: "Moderate",
      HIGH: "Major",
    },
    about: "About",
    action: "Suggested action",
    noFindings: "No remarks.",
    verdictTitle: "The model's verdict",
    verdict: {
      ALIGNED: "The code follows the approved requirements and design.",
      CODE_DRIFT:
        "The code moves away from the approved requirements or design: the code should change.",
      DESIGN_OUTDATED: "The change is a sound evolution: the design should get a new version.",
      REQUIREMENTS_OUTDATED:
        "The change is a sound evolution: the requirements should get a new version.",
    },
    designRequest: "Design change to request",
    requirementsRequest: "Requirements change to request",
    codeTasks: "Tasks proposed for the code",
    codeTasksNote: "They become open tasks only when you decide so with `ut align`.",
    technical: "Development state",
    technicalChanges: "Recorded commits",
    technicalPending: "Pending commits",
    technicalTasks: "Open tasks",
    technicalRun: "Latest review",
  },
  it: {
    eyebrow: "Dopo il design",
    title: "Sviluppo fuori dallo Studio",
    intro:
      "Il codice si scrive con i tuoi strumenti. Qui leggi come stanno i commit rispetto ai requisiti e al design approvati.",
    terminal:
      "Revisioni e decisioni si fanno dal terminale con `ut align`: questa pagina ne mostra solo il risultato.",
    refresh: "Aggiorna",
    refreshLabel: "Aggiorna lo stato dello sviluppo",
    loading: "Carico lo stato dello sviluppo…",
    loadFailed: "Non è stato possibile caricare lo stato dello sviluppo.",
    details: "Dettagli",
    noModel: "In questo Studio i twin non possono rivedere il codice: collega un modello.",
    empty: "Nessun commit registrato. Registra il primo con `ut align` o `ut watch`.",
    reference: "Il riferimento approvato",
    requirements: "Requisiti",
    design: "Design",
    aligned: "Punto allineato",
    versionValue: "versione {number}",
    requirementsMissing: "non ancora approvati",
    designMissing: "non ancora approvato",
    alignedValue: "commit {commit} · {date}",
    noAligned: "Nessun commit ancora allineato",
    pendingTitle: "Commit in attesa ({count})",
    pendingIntro: "I commit registrati dopo il punto allineato.",
    noPending: "Nessun commit dopo il punto allineato.",
    files: ["{count} file", "{count} file"],
    verdictBadge: {
      NONE: "Non ancora rivisto",
      ALIGNED: "Revisione: allineato",
      CODE_DRIFT: "Revisione: va cambiato il codice",
      DESIGN_OUTDATED: "Revisione: va aggiornato il design",
      REQUIREMENTS_OUTDATED: "Revisione: vanno aggiornati i requisiti",
    },
    decisionBadge: {
      NONE: "Nessuna decisione",
      ALIGNED: "Decisione: punto allineato",
      DESIGN_CHANGE: "Decisione: chiesto un nuovo design",
      REQUIREMENTS_CHANGE: "Decisione: chiesta una modifica dei requisiti",
      CODE_TASKS: "Decisione: compiti per il codice",
      DISMISSED: "Decisione: niente da fare",
    },
    tasksTitle: "Compiti aperti per il codice ({count})",
    tasksIntro: "Si chiudono quando un commit successivo viene segnato come allineato.",
    noTasks: "Nessun compito aperto.",
    latestReview: "Ultima revisione",
    runTitle: "Ultima revisione, commit {commit}",
    runMeta:
      "{date} · confrontata con i requisiti versione {requirements} e il design versione {design}{alternative}",
    noRun: "Nessun commit è ancora stato rivisto.",
    runLoading: "Carico l'ultima revisione…",
    runFailed: "Non è stato possibile caricare l'ultima revisione.",
    runMissing: "L'ultima revisione non è disponibile.",
    critique: {
      FINE: "Nessun dubbio",
      CONCERN: "Qualche dubbio",
      DRIFT: "Fuori strada",
    },
    severity: {
      LOW: "Minore",
      MEDIUM: "Moderata",
      HIGH: "Importante",
    },
    about: "Riguarda",
    action: "Azione suggerita",
    noFindings: "Nessuna osservazione.",
    verdictTitle: "Il verdetto del modello",
    verdict: {
      ALIGNED: "Il codice segue i requisiti e il design approvati.",
      CODE_DRIFT:
        "Il codice si allontana dai requisiti o dal design approvati: va cambiato il codice.",
      DESIGN_OUTDATED: "La modifica è un'evoluzione sensata: il design merita una nuova versione.",
      REQUIREMENTS_OUTDATED:
        "La modifica è un'evoluzione sensata: i requisiti meritano una nuova versione.",
    },
    designRequest: "Modifica del design da chiedere",
    requirementsRequest: "Modifica dei requisiti da chiedere",
    codeTasks: "Compiti proposti per il codice",
    codeTasksNote: "Diventano compiti aperti solo quando lo decidi con `ut align`.",
    technical: "Stato dello sviluppo",
    technicalChanges: "Commit registrati",
    technicalPending: "Commit in attesa",
    technicalTasks: "Compiti aperti",
    technicalRun: "Ultima revisione",
  },
} as const;

const VERDICT_STATUS: Readonly<Record<AlignmentStatus, ChipStatus>> = {
  ALIGNED: "approved",
  CODE_DRIFT: "failed",
  DESIGN_OUTDATED: "blocked",
  REQUIREMENTS_OUTDATED: "blocked",
};

const DECISION_STATUS: Readonly<Record<ChangeDecisionKind, ChipStatus>> = {
  ALIGNED: "approved",
  DESIGN_CHANGE: "blocked",
  REQUIREMENTS_CHANGE: "blocked",
  CODE_TASKS: "blocked",
  DISMISSED: "pending",
};

const CRITIQUE_STATUS: Readonly<Record<CritiqueVerdict, ChipStatus>> = {
  FINE: "approved",
  CONCERN: "blocked",
  DRIFT: "failed",
};

const SEVERITY_STYLES: Readonly<Record<FindingSeverity, string>> = {
  HIGH: "bg-warn-on-night/12 text-warn-on-night",
  MEDIUM: "bg-on-night/8 text-on-night-2",
  LOW: "bg-on-night/8 text-on-night-2",
};

const SHORT_COMMIT = 7;

const auth = useAuthStore();
const design = useDesignStore();
const requirements = useRequirementsStore();
const store = useCodeChangesStore();

const copy = computed(() => messages[props.locale]);
const failure = ref<{ operation: "load" | "run"; code: string | null } | null>(null);
let refreshes = 0;

const current = computed(() => store.projectId === props.projectId);
const alignment = computed(() => (current.value ? store.alignment : null));
const changes = computed<CodeChangePayload[]>(() => (current.value ? store.changes : []));
const pendingChanges = computed<CodeChangePayload[]>(() =>
  current.value ? store.pendingChanges : [],
);
const tasks = computed(() => (current.value ? store.openTasks : []));
const reviewed = computed(() => (current.value ? store.latestReviewed : null));
const run = computed(() => (current.value ? store.latestRun : null));
const runFetched = computed(() => {
  const change = reviewed.value;
  return change !== null && change.commit in store.runs;
});
const loading = computed(() => current.value && store.pending.load);
const loaded = computed(() => alignment.value !== null);

const dateFormat = computed(
  () =>
    new Intl.DateTimeFormat(props.locale === "it" ? "it-IT" : "en-GB", {
      dateStyle: "medium",
      timeStyle: "short",
    }),
);

const requirementTitles = computed<Readonly<Record<string, string>>>(() => {
  if (requirements.projectId !== props.projectId) {
    return {};
  }
  const items = requirements.current?.specification.requirements ?? [];
  return Object.fromEntries(items.map((item) => [item.code, item.title]));
});

const designPackage = computed(() =>
  design.projectId === props.projectId ? (design.current?.package ?? null) : null,
);

const screenTitles = computed<Readonly<Record<string, string>>>(() => {
  const value = designPackage.value;
  if (value === null) {
    return {};
  }
  const chosen = value.owner_selected_alternative_id;
  const generated = value.generated_mockup?.mockup ?? null;
  const screens: readonly { code: string; title: string }[] =
    generated !== null && generated.design_alternative_id === chosen && generated.screens.length > 0
      ? generated.screens
      : value.prototype !== null && value.prototype.design_alternative_id === chosen
        ? value.prototype.screens
        : [];
  return Object.fromEntries(screens.map((screen) => [screen.code, placeLabel(screen.title)]));
});

const reference = computed(() => {
  const value = alignment.value?.reference ?? null;
  const requirementsVersion = value?.requirements ?? null;
  const designVersion = value?.design ?? null;
  const code = designVersion?.alternative_code ?? null;
  return {
    requirements:
      requirementsVersion === null
        ? copy.value.requirementsMissing
        : fill(copy.value.versionValue, { number: requirementsVersion.version_number }),
    design:
      designVersion === null
        ? copy.value.designMissing
        : fill(copy.value.versionValue, { number: designVersion.version_number }),
    alternative:
      code === null
        ? null
        : {
            code,
            title: designPackage.value?.alternatives.find((item) => item.code === code)?.title,
          },
  };
});

const alignedText = computed(() => {
  const value = alignment.value?.aligned ?? null;
  return value === null
    ? copy.value.noAligned
    : fill(copy.value.alignedValue, {
        commit: shortCommit(value.commit),
        date: formatDate(value.decided_at),
      });
});

const pendingRows = computed(() =>
  pendingChanges.value.map((change) => ({
    commit: change.commit,
    short: shortCommit(change.commit),
    date: formatDate(change.committed_at),
    title: firstLine(change.message),
    files: plural(change.files.length, copy.value.files),
    verdict: verdictBadge(change),
    decision: decisionBadge(change),
  })),
);

const taskRows = computed(() =>
  tasks.value.map((task) => ({
    code: task.code,
    text: task.text,
    subjects: codeSubjects(task.about),
  })),
);

const runHeading = computed(() => {
  const change = reviewed.value;
  return change === null
    ? copy.value.latestReview
    : fill(copy.value.runTitle, { commit: shortCommit(change.commit) });
});

const runView = computed(() => {
  const value = run.value;
  if (value === null) {
    return null;
  }
  const code = value.reference.alternative_code;
  const verdict = value.alignment;
  return {
    id: value.id,
    meta: fill(copy.value.runMeta, {
      date: formatDate(value.reviewed_at),
      requirements: value.reference.requirements_version_number,
      design: value.reference.design_version_number,
      alternative: code === null ? "" : ` (${code})`,
    }),
    critiques: value.critiques.map((critique, index) => ({
      key: `${critique.twin_id}:${index}`,
      name: critique.twin_name,
      badge: {
        status: CRITIQUE_STATUS[critique.verdict],
        label: copy.value.critique[critique.verdict],
      },
      summary: critique.summary,
      findings: critique.findings.map((finding, position) => ({
        key: `${critique.twin_id}:${index}:${position}`,
        severity: copy.value.severity[finding.severity],
        style: SEVERITY_STYLES[finding.severity],
        text: finding.text,
        action: finding.action,
        subjects: findingSubjects(finding),
      })),
    })),
    verdict: {
      badge: {
        status: VERDICT_STATUS[verdict.status],
        label: copy.value.verdictBadge[verdict.status],
      },
      sentence: copy.value.verdict[verdict.status],
      summary: verdict.summary,
      subjects: codeSubjects(verdict.affected),
      designRequest: verdict.design_request,
      requirementsRequest: verdict.requirements_request,
      codeTasks: verdict.code_tasks,
    },
  };
});

const technicalRows = computed(() => {
  const rows: { label: string; value: string }[] = [
    { label: copy.value.technicalChanges, value: String(changes.value.length) },
    {
      label: copy.value.technicalPending,
      value: String(alignment.value?.pending_changes ?? 0),
    },
    { label: copy.value.technicalTasks, value: String(tasks.value.length) },
  ];
  if (run.value !== null) {
    rows.push({ label: copy.value.technicalRun, value: run.value.id });
  }
  return rows;
});

function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_match, key: string) => String(values[key] ?? ""));
}

function plural(count: number, forms: readonly [string, string]): string {
  return fill(count === 1 ? forms[0] : forms[1], { count });
}

function commandParts(text: string): { key: number; text: string; command: boolean }[] {
  return text
    .split("`")
    .map((part, index) => ({ key: index, text: part, command: index % 2 === 1 }))
    .filter((part) => part.text.length > 0);
}

function shortCommit(commit: string): string {
  return commit.slice(0, SHORT_COMMIT);
}

function firstLine(message: string): string {
  return (message.split("\n")[0] ?? "").trim();
}

function formatDate(value: string): string {
  const time = Date.parse(value);
  return Number.isNaN(time) ? value : dateFormat.value.format(time);
}

function verdictBadge(change: CodeChangePayload): Badge {
  const review = change.review;
  return review === null
    ? { status: "pending", label: copy.value.verdictBadge.NONE }
    : { status: VERDICT_STATUS[review.verdict], label: copy.value.verdictBadge[review.verdict] };
}

function decisionBadge(change: CodeChangePayload): Badge {
  const decision = change.decision;
  return decision === null
    ? { status: "pending", label: copy.value.decisionBadge.NONE }
    : { status: DECISION_STATUS[decision.kind], label: copy.value.decisionBadge[decision.kind] };
}

function requirementSubject(code: string): Subject {
  return { key: code, code, title: requirementTitles.value[code] ?? null };
}

function screenSubject(code: string): Subject {
  return { key: code, code, title: screenTitles.value[code] ?? null };
}

function codeSubjects(about: CodeSubjectsPayload): Subject[] {
  return [...about.requirements.map(requirementSubject), ...about.screens.map(screenSubject)];
}

function findingSubjects(finding: CritiqueFindingPayload): Subject[] {
  const subjects: Subject[] = [];
  if (finding.about.requirement !== null) {
    subjects.push(requirementSubject(finding.about.requirement));
  }
  if (finding.about.screen !== null) {
    subjects.push(screenSubject(finding.about.screen));
  }
  if (finding.about.file !== null) {
    subjects.push({ key: `file:${finding.about.file}`, code: null, title: finding.about.file });
  }
  return subjects;
}

function authorizedRequest<T>(operation: (accessToken: string) => Promise<T>): Promise<T> {
  return props.authorize ? props.authorize(operation) : auth.withAccessToken(apiClient, operation);
}

async function refresh(): Promise<void> {
  const projectId = props.projectId;
  const attempt = ++refreshes;
  failure.value = null;

  let latest: CodeChangePayload | undefined;
  try {
    const snapshot = await store.load(projectId, authorizedRequest, props.api);
    latest = snapshot.changes.find((change) => change.review !== null);
  } catch {
    if (attempt === refreshes) {
      failure.value = { operation: "load", code: store.error?.code ?? null };
    }
    return;
  }

  if (attempt !== refreshes || latest === undefined) {
    return;
  }

  try {
    await store.loadRun(projectId, latest.commit, authorizedRequest, props.api);
  } catch {
    if (attempt === refreshes) {
      failure.value = { operation: "run", code: store.error?.code ?? null };
    }
  }
}

watch(() => props.projectId, refresh, { immediate: true });
</script>

<template>
  <section
    class="rounded-tile border border-night-line bg-night-raised p-6 text-on-night"
    aria-labelledby="development-title"
    data-surface="night"
    data-testid="development-panel"
  >
    <div class="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
      <div class="min-w-[min(100%,18rem)] flex-1">
        <p class="m-0 font-mono text-[11px] tracking-label text-petrol-on-night-2 uppercase">
          {{ copy.eyebrow }}
        </p>
        <h2 id="development-title" class="m-0 mt-2 text-lg leading-tight font-semibold">
          {{ copy.title }}
        </h2>
        <p class="m-0 mt-1.5 text-sm leading-normal text-on-night-2">{{ copy.intro }}</p>
        <p
          class="m-0 mt-1.5 text-sm leading-normal text-on-night-2"
          data-testid="development-terminal"
        >
          <template v-for="part in commandParts(copy.terminal)" :key="part.key">
            <code
              v-if="part.command"
              class="rounded-[4px] bg-on-night/8 px-1 font-mono text-[13px] text-on-night"
              >{{ part.text }}</code
            >
            <template v-else>{{ part.text }}</template>
          </template>
        </p>
      </div>
      <UiButton
        variant="outline"
        :disabled="loading"
        :aria-label="copy.refreshLabel"
        data-testid="development-refresh"
        @click="refresh"
      >
        {{ copy.refresh }}
      </UiButton>
    </div>

    <div
      class="mt-5 grid gap-5"
      aria-live="polite"
      :aria-busy="loading ? 'true' : undefined"
      data-testid="development-state"
    >
      <div
        v-if="failure !== null && failure.operation === 'load'"
        class="grid gap-1 rounded-field border border-fail-on-night/40 bg-fail-on-night/10 px-4 py-3 text-sm text-fail-on-night"
        role="alert"
        data-testid="development-error"
      >
        <p class="m-0 font-semibold">{{ copy.loadFailed }}</p>
        <details v-if="failure.code !== null" class="text-xs">
          <summary class="inline-flex min-h-11 cursor-pointer items-center">
            {{ copy.details }}
          </summary>
          <code class="break-all">{{ failure.code }}</code>
        </details>
      </div>

      <p
        v-if="!loaded && failure === null"
        class="m-0 text-sm text-on-night-3"
        data-testid="development-loading"
      >
        {{ copy.loading }}
      </p>

      <template v-if="alignment !== null">
        <p
          v-if="!alignment.review_available"
          class="m-0 rounded-field border border-warn-on-night/40 bg-warn-on-night/8 px-4 py-3 text-sm leading-normal text-warn-on-night"
          data-testid="development-no-model"
        >
          {{ copy.noModel }}
        </p>

        <div class="border-t border-on-night/10 pt-4">
          <h3 class="m-0 text-base leading-tight font-semibold">{{ copy.reference }}</h3>
          <dl
            class="m-0 mt-3 grid grid-cols-1 gap-x-5 gap-y-1 text-sm sm:grid-cols-[180px_minmax(0,1fr)] sm:gap-y-2"
            data-testid="development-reference"
          >
            <dt class="text-on-night-3">{{ copy.requirements }}</dt>
            <dd class="m-0 mb-2 sm:mb-0" data-testid="development-reference-requirements">
              {{ reference.requirements }}
            </dd>
            <dt class="text-on-night-3">{{ copy.design }}</dt>
            <dd class="m-0 mb-2 wrap-anywhere sm:mb-0" data-testid="development-reference-design">
              {{ reference.design }}
              <template v-if="reference.alternative">
                ·
                <span class="font-mono text-xs text-on-night-2">{{
                  reference.alternative.code
                }}</span>
                <template v-if="reference.alternative.title">
                  · {{ reference.alternative.title }}
                </template>
              </template>
            </dd>
            <dt class="text-on-night-3">{{ copy.aligned }}</dt>
            <dd class="m-0" data-testid="development-aligned">{{ alignedText }}</dd>
          </dl>
        </div>

        <p
          v-if="changes.length === 0"
          class="m-0 rounded-field border border-night-line px-4 py-3 text-sm leading-normal text-on-night-2"
          data-testid="development-empty"
        >
          <template v-for="part in commandParts(copy.empty)" :key="part.key">
            <code
              v-if="part.command"
              class="rounded-[4px] bg-on-night/8 px-1 font-mono text-[13px] text-on-night"
              >{{ part.text }}</code
            >
            <template v-else>{{ part.text }}</template>
          </template>
        </p>

        <template v-else>
          <div class="border-t border-on-night/10 pt-4" data-testid="development-pending">
            <h3 class="m-0 text-base leading-tight font-semibold">
              {{ fill(copy.pendingTitle, { count: pendingRows.length }) }}
            </h3>
            <p class="m-0 mt-1 text-sm leading-normal text-on-night-3">{{ copy.pendingIntro }}</p>
            <ul v-if="pendingRows.length > 0" class="m-0 mt-2 list-none p-0">
              <li
                v-for="row in pendingRows"
                :key="row.commit"
                class="grid gap-1.5 border-t border-on-night/10 py-3"
                data-testid="development-change"
              >
                <p class="m-0 text-xs text-on-night-3">
                  <span class="font-mono text-on-night-2" data-testid="development-change-commit">
                    {{ row.short }}
                  </span>
                  · {{ row.date }} · {{ row.files }}
                </p>
                <p
                  class="m-0 text-[15px] leading-snug font-semibold wrap-anywhere"
                  data-testid="development-change-title"
                >
                  {{ row.title }}
                </p>
                <div class="flex flex-wrap gap-1.5">
                  <UiStatusChip
                    :status="row.verdict.status"
                    :label="row.verdict.label"
                    class="whitespace-normal!"
                    data-testid="development-change-verdict"
                  />
                  {{ " " }}
                  <UiStatusChip
                    :status="row.decision.status"
                    :label="row.decision.label"
                    class="whitespace-normal!"
                    data-testid="development-change-decision"
                  />
                </div>
              </li>
            </ul>
            <p v-else class="m-0 mt-2 text-sm text-on-night-3" data-testid="development-no-pending">
              {{ copy.noPending }}
            </p>
          </div>

          <div class="border-t border-on-night/10 pt-4" data-testid="development-tasks">
            <h3 class="m-0 text-base leading-tight font-semibold">
              {{ fill(copy.tasksTitle, { count: taskRows.length }) }}
            </h3>
            <p class="m-0 mt-1 text-sm leading-normal text-on-night-3">{{ copy.tasksIntro }}</p>
            <ul v-if="taskRows.length > 0" class="m-0 mt-2 list-none p-0">
              <li
                v-for="task in taskRows"
                :key="task.code"
                class="grid gap-1 border-t border-on-night/10 py-2.5"
                data-testid="development-task"
              >
                <p class="m-0 text-[15px] leading-snug wrap-anywhere">
                  <span
                    class="font-mono text-xs text-on-night-2"
                    data-testid="development-task-code"
                    >{{ task.code }}</span
                  >
                  · {{ task.text }}
                </p>
                <div
                  v-if="task.subjects.length > 0"
                  class="flex flex-wrap items-baseline gap-x-2 text-[13px] text-on-night-3"
                >
                  <span>{{ copy.about }}:</span>
                  <ul class="m-0 flex list-none flex-wrap gap-x-3 gap-y-1 p-0">
                    <li
                      v-for="subject in task.subjects"
                      :key="subject.key"
                      data-testid="development-subject"
                    >
                      <span class="font-mono text-xs text-on-night-2">{{ subject.code }}</span>
                      <template v-if="subject.title"> · {{ subject.title }}</template>
                    </li>
                  </ul>
                </div>
              </li>
            </ul>
            <p v-else class="m-0 mt-2 text-sm text-on-night-3" data-testid="development-no-tasks">
              {{ copy.noTasks }}
            </p>
          </div>

          <div class="border-t border-on-night/10 pt-4" data-testid="development-run">
            <h3 class="m-0 text-base leading-tight font-semibold">{{ runHeading }}</h3>
            <p
              v-if="reviewed === null"
              class="m-0 mt-2 text-sm text-on-night-3"
              data-testid="development-no-run"
            >
              {{ copy.noRun }}
            </p>
            <template v-else-if="runView !== null">
              <p
                class="m-0 mt-1 text-sm leading-normal text-on-night-3"
                data-testid="development-run-meta"
              >
                {{ runView.meta }}
              </p>
              <ul class="m-0 mt-3 grid list-none gap-3 p-0">
                <li v-for="critique in runView.critiques" :key="critique.key">
                  <UiClaimFrame
                    status="hypothesis"
                    radius="tile"
                    class="grid gap-2"
                    data-testid="development-critique"
                  >
                    <div class="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                      <h4 class="m-0 text-[15px] leading-snug font-semibold">
                        {{ critique.name }}
                      </h4>
                      <UiStatusChip
                        :status="critique.badge.status"
                        :label="critique.badge.label"
                        class="whitespace-normal!"
                        data-testid="development-critique-verdict"
                      />
                    </div>
                    <p class="m-0 text-sm leading-normal text-on-night-2">{{ critique.summary }}</p>
                    <ul
                      v-if="critique.findings.length > 0"
                      class="m-0 grid list-disc gap-2 pl-5 text-sm leading-normal"
                    >
                      <li
                        v-for="finding in critique.findings"
                        :key="finding.key"
                        data-testid="development-finding"
                      >
                        <span
                          :class="[
                            'mr-1 inline-flex min-h-6 items-center rounded-pill px-[9px] text-xs font-semibold',
                            finding.style,
                          ]"
                          data-testid="development-finding-severity"
                          >{{ finding.severity }}</span
                        >
                        {{ " " }}
                        <span class="wrap-anywhere">{{ finding.text }}</span>
                        <div
                          v-if="finding.subjects.length > 0"
                          class="mt-1 flex flex-wrap items-baseline gap-x-2 text-[13px] text-on-night-3"
                        >
                          <span>{{ copy.about }}:</span>
                          <ul class="m-0 flex list-none flex-wrap gap-x-3 gap-y-1 p-0">
                            <li
                              v-for="subject in finding.subjects"
                              :key="subject.key"
                              data-testid="development-subject"
                            >
                              <code
                                v-if="subject.code === null"
                                class="font-mono text-xs wrap-anywhere text-on-night-2"
                                >{{ subject.title }}</code
                              >
                              <template v-else>
                                <span class="font-mono text-xs text-on-night-2">{{
                                  subject.code
                                }}</span>
                                <template v-if="subject.title"> · {{ subject.title }}</template>
                              </template>
                            </li>
                          </ul>
                        </div>
                        <p v-if="finding.action" class="m-0 mt-1 text-[13px] text-on-night-2">
                          <strong class="font-semibold text-on-night">{{ copy.action }}:</strong>
                          {{ finding.action }}
                        </p>
                      </li>
                    </ul>
                    <p v-else class="m-0 text-sm text-on-night-3">{{ copy.noFindings }}</p>
                  </UiClaimFrame>
                </li>
              </ul>

              <UiClaimFrame
                status="hypothesis"
                radius="tile"
                class="mt-3 grid gap-2"
                data-testid="development-verdict"
              >
                <div class="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                  <h4 class="m-0 text-[15px] leading-snug font-semibold">
                    {{ copy.verdictTitle }}
                  </h4>
                  <UiStatusChip
                    :status="runView.verdict.badge.status"
                    :label="runView.verdict.badge.label"
                    class="whitespace-normal!"
                    data-testid="development-verdict-status"
                  />
                </div>
                <p class="m-0 text-[15px] leading-snug font-semibold">
                  {{ runView.verdict.sentence }}
                </p>
                <p class="m-0 text-sm leading-normal text-on-night-2">
                  {{ runView.verdict.summary }}
                </p>
                <div
                  v-if="runView.verdict.subjects.length > 0"
                  class="flex flex-wrap items-baseline gap-x-2 text-[13px] text-on-night-3"
                >
                  <span>{{ copy.about }}:</span>
                  <ul class="m-0 flex list-none flex-wrap gap-x-3 gap-y-1 p-0">
                    <li
                      v-for="subject in runView.verdict.subjects"
                      :key="subject.key"
                      data-testid="development-subject"
                    >
                      <span class="font-mono text-xs text-on-night-2">{{ subject.code }}</span>
                      <template v-if="subject.title"> · {{ subject.title }}</template>
                    </li>
                  </ul>
                </div>
                <div v-if="runView.verdict.designRequest" data-testid="development-design-request">
                  <p class="m-0 text-xs text-on-night-3">{{ copy.designRequest }}</p>
                  <blockquote
                    class="m-0 mt-1 border-l-2 border-petrol-on-night/60 pl-3 text-sm leading-normal wrap-anywhere text-on-night-2"
                  >
                    {{ runView.verdict.designRequest }}
                  </blockquote>
                </div>
                <div
                  v-if="runView.verdict.requirementsRequest"
                  data-testid="development-requirements-request"
                >
                  <p class="m-0 text-xs text-on-night-3">{{ copy.requirementsRequest }}</p>
                  <blockquote
                    class="m-0 mt-1 border-l-2 border-petrol-on-night/60 pl-3 text-sm leading-normal wrap-anywhere text-on-night-2"
                  >
                    {{ runView.verdict.requirementsRequest }}
                  </blockquote>
                </div>
                <div
                  v-if="runView.verdict.codeTasks.length > 0"
                  data-testid="development-code-tasks"
                >
                  <p class="m-0 text-xs text-on-night-3">{{ copy.codeTasks }}</p>
                  <ul class="m-0 mt-1 grid list-disc gap-1 pl-5 text-sm leading-normal">
                    <li
                      v-for="task in runView.verdict.codeTasks"
                      :key="task"
                      class="wrap-anywhere"
                      data-testid="development-code-task"
                    >
                      {{ task }}
                    </li>
                  </ul>
                  <p class="m-0 mt-1 text-[13px] text-on-night-3">
                    <template v-for="part in commandParts(copy.codeTasksNote)" :key="part.key">
                      <code
                        v-if="part.command"
                        class="rounded-[4px] bg-on-night/8 px-1 font-mono text-xs text-on-night"
                        >{{ part.text }}</code
                      >
                      <template v-else>{{ part.text }}</template>
                    </template>
                  </p>
                </div>
              </UiClaimFrame>
            </template>
            <div
              v-else-if="failure !== null && failure.operation === 'run'"
              class="mt-2 grid gap-1 rounded-field border border-fail-on-night/40 bg-fail-on-night/10 px-4 py-3 text-sm text-fail-on-night"
              role="alert"
              data-testid="development-run-error"
            >
              <p class="m-0 font-semibold">{{ copy.runFailed }}</p>
              <details v-if="failure.code !== null" class="text-xs">
                <summary class="inline-flex min-h-11 cursor-pointer items-center">
                  {{ copy.details }}
                </summary>
                <code class="break-all">{{ failure.code }}</code>
              </details>
            </div>
            <p
              v-else
              class="m-0 mt-2 text-sm text-on-night-3"
              data-testid="development-run-loading"
            >
              {{ runFetched ? copy.runMissing : copy.runLoading }}
            </p>
          </div>
        </template>
      </template>
    </div>

    <UiTechnicalDetails
      v-if="alignment !== null"
      class="mt-5!"
      :summary="copy.technical"
      :rows="technicalRows"
      data-testid="development-technical-details"
    />
  </section>
</template>
