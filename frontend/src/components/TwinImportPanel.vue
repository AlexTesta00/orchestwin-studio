<script setup lang="ts">
import { computed, nextTick, ref, useId } from "vue";

import UiButton from "./UiButton.vue";
import { useSurface } from "./UiSurface.vue";

import { ApiError, apiClient } from "../api/client";
import { ApiRequestError } from "../api/requestError";
import { twinImportsApi, type TwinImportsApi } from "../api/twinImports";
import { useAuthStore } from "../stores/auth";
import type {
  ImportableTwinPayload,
  TwinImportCandidatePayload,
  TwinImportPayload,
  TwinImportSourcePayload,
} from "../types/twinImports";

type Locale = "en" | "it";
type Step = 1 | 2 | 3;
type Busy = "projects" | "source" | "file" | "import";
type FileProblem = "FILE_NOT_JSON" | "FILE_NOT_TWIN";
type AuthorizedRequest = <T>(operation: (accessToken: string) => Promise<T>) => Promise<T>;

interface TwinFile {
  document: Record<string, unknown>;
  fileName: string;
  twinName: string;
  projectName: string;
}

interface ProjectChoice {
  twin: string;
  project: string;
  sourceProjectId: string;
  twinId: string;
}

interface FileChoice {
  twin: string;
  project: string;
  document: Record<string, unknown>;
}

const props = withDefaults(
  defineProps<{
    projectId: string;
    locale?: Locale;
    authorize?: AuthorizedRequest | undefined;
    api?: TwinImportsApi | undefined;
    readFile?: ((file: File) => Promise<string>) | undefined;
  }>(),
  {
    locale: "en",
    authorize: undefined,
    api: undefined,
    readFile: undefined,
  },
);

const emit = defineEmits<{ imported: [payload: TwinImportPayload] }>();

const messages = {
  en: {
    title: "Add a twin from another project",
    intro:
      "A twin you already refined elsewhere can be reused here: it keeps its profile and the record of where it comes from.",
    open: "Reuse a twin from another project",
    cancel: "Cancel",
    stepProject: "Choose the project",
    stepTwin: "Choose the twin",
    stepConfirm: "Confirm",
    change: "Change",
    changeProject: "Change the project",
    changeFile: "Change the file",
    changeTwin: "Change the twin",
    projectLabel: "Your other projects",
    projectPlaceholder: "Choose a project",
    sourceOption: {
      one: "{project} · 1 twin · approved on {date}",
      other: "{project} · {count} twins · approved on {date}",
    },
    sourceTwins: { one: "Twin: {names}", other: "Twins: {names}" },
    showTwins: "Show its twins",
    fileAlternative: "or load the twin file of a knowledge folder",
    fileLabel: "Twin file (twin.json)",
    noSources:
      "None of your other projects has approved twins. You can still upload the file of a twin.",
    projectsFailed:
      "Your projects with approved twins could not be loaded. Try again, or upload the file of a twin.",
    retry: "Try again",
    projectSummary: "Project: {project}",
    fileSummary: "Twin file: {file}",
    twinSummary: "Twin: {twin}",
    fileTwinSummary: "{twin}, read from the file",
    twinsOf: "Twins of {project}",
    approvedOn:
      "Approved on {date}. For a twin that cannot be added here, the reason is written under its name.",
    unavailable: "Not available.",
    noneAvailable: "None of these twins can be added to this project. Choose another project.",
    continue: "Continue",
    confirmation:
      "{twin} will be added to this project as a new twin. Its profile stays the same and every observation keeps the note that it comes from {project}. After the import you approve the twins of this project again.",
    add: "Add the twin",
    added: "{twin} was added. Now approve the twins again at the bottom of the page.",
    loadingProjects: "Loading your projects…",
    loadingTwins: "Loading the twins of {project}…",
    readingFile: "Reading the file…",
    adding: "Adding {twin} to this project…",
    fileNotJson:
      "This file cannot be read as a twin. Choose the twin.json file of a knowledge folder.",
    fileNotTwin:
      "This file does not describe a twin: the name of the twin or of its project is missing.",
    sourceFailed: "The twins of that project could not be loaded. Try again in a moment.",
    importFailed: "The twin could not be added. Try again in a moment.",
    issueFallback: "This twin cannot be added here.",
    details: "Details",
    codes: {
      TWIN_ALREADY_IMPORTED: "This twin was already added to this project.",
      TWIN_NAME_ALREADY_USED: "This project already has a twin with this name.",
      TWIN_LIMIT_REACHED: "This project already has eight twins, the maximum.",
      TWIN_BELONGS_TO_PROJECT: "This twin comes from this same project.",
      USER_TWINS_REQUIRED: "This project has no twins yet: create them first.",
      USER_TWINS_OUTDATED:
        "The Brief or the Perspectives of this project changed: update its twins first.",
      SOURCE_TWINS_NOT_APPROVED: "The twins of that project are not approved yet.",
      SOURCE_PROJECT_NOT_FOUND: "That project cannot be found, or it has no brief yet.",
      SOURCE_TWIN_NOT_FOUND: "That twin is no longer among the approved twins of its project.",
      PROJECT_NOT_FOUND: "This project cannot be found. Reload the page.",
      BRIEF_APPROVAL_REQUIRED: "Approve the Brief of this project first.",
      TEAM_APPROVAL_REQUIRED: "Approve the Perspectives of this project first.",
      TWIN_DOCUMENT_INVALID: "The twin file is damaged or incomplete.",
      TWIN_DOCUMENT_UNSUPPORTED:
        "The twin file comes from a different version of the Studio and cannot be used.",
      TWIN_IMPORT_REQUEST_INVALID:
        "The request could not be understood. Reload the page and try again.",
      TWIN_IMPORT_TOO_LARGE: "The twin file is too large: the limit is 1 MB.",
      CONTEXT_CHANGED: "The twins of this project changed in the meantime. Try again.",
      PERSISTENCE_REJECTED: "The twin could not be saved. Try again.",
    },
  },
  it: {
    title: "Aggiungi un twin da un altro progetto",
    intro:
      "Un twin che hai già messo a punto altrove si può riusare qui: mantiene il suo profilo e la traccia di dove arriva.",
    open: "Riusa un twin da un altro progetto",
    cancel: "Annulla",
    stepProject: "Scegli il progetto",
    stepTwin: "Scegli il twin",
    stepConfirm: "Conferma",
    change: "Cambia",
    changeProject: "Cambia il progetto",
    changeFile: "Cambia il file",
    changeTwin: "Cambia il twin",
    projectLabel: "I tuoi altri progetti",
    projectPlaceholder: "Scegli un progetto",
    sourceOption: {
      one: "{project} · 1 twin · approvato il {date}",
      other: "{project} · {count} twin · approvati il {date}",
    },
    sourceTwins: { one: "Twin: {names}", other: "Twin: {names}" },
    showTwins: "Mostra i suoi twin",
    fileAlternative: "oppure carica il file del twin di una cartella di conoscenza",
    fileLabel: "File del twin (twin.json)",
    noSources:
      "Nessun altro tuo progetto ha twin approvati. Puoi comunque caricare il file di un twin.",
    projectsFailed:
      "Non è stato possibile caricare i tuoi progetti con twin approvati. Riprova, oppure carica il file di un twin.",
    retry: "Riprova",
    projectSummary: "Progetto: {project}",
    fileSummary: "File del twin: {file}",
    twinSummary: "Twin: {twin}",
    fileTwinSummary: "Twin letto dal file: {twin}",
    twinsOf: "Twin di {project}",
    approvedOn:
      "Approvati il {date}. Se un twin non si può aggiungere qui, il motivo è scritto sotto il suo nome.",
    unavailable: "Non disponibile.",
    noneAvailable:
      "Nessuno di questi twin si può aggiungere a questo progetto. Scegli un altro progetto.",
    continue: "Continua",
    confirmation:
      "Il twin «{twin}» sarà aggiunto a questo progetto. Il suo profilo resta lo stesso e ogni osservazione conserva la nota che arriva da {project}. Dopo l'aggiunta approvi di nuovo i twin di questo progetto.",
    add: "Aggiungi il twin",
    added: "Il twin «{twin}» è stato aggiunto. Ora approva di nuovo i twin in fondo alla pagina.",
    loadingProjects: "Carico i tuoi progetti…",
    loadingTwins: "Carico i twin di {project}…",
    readingFile: "Leggo il file…",
    adding: "Aggiungo {twin} a questo progetto…",
    fileNotJson:
      "Questo file non si può leggere come twin. Scegli il file twin.json di una cartella di conoscenza.",
    fileNotTwin: "Questo file non descrive un twin: manca il nome del twin o del suo progetto.",
    sourceFailed: "Non è stato possibile caricare i twin di quel progetto. Riprova tra poco.",
    importFailed: "Non è stato possibile aggiungere il twin. Riprova tra poco.",
    issueFallback: "Questo twin non si può aggiungere qui.",
    details: "Dettagli",
    codes: {
      TWIN_ALREADY_IMPORTED: "Questo twin è già stato aggiunto a questo progetto.",
      TWIN_NAME_ALREADY_USED: "Questo progetto ha già un twin con questo nome.",
      TWIN_LIMIT_REACHED: "Questo progetto ha già otto twin, il massimo.",
      TWIN_BELONGS_TO_PROJECT: "Questo twin viene proprio da questo progetto.",
      USER_TWINS_REQUIRED: "Questo progetto non ha ancora twin: creali prima.",
      USER_TWINS_OUTDATED:
        "Il Brief o le Prospettive di questo progetto sono cambiati: prima aggiorna i suoi twin.",
      SOURCE_TWINS_NOT_APPROVED: "I twin di quel progetto non sono ancora approvati.",
      SOURCE_PROJECT_NOT_FOUND: "Quel progetto non si trova, oppure non ha ancora un brief.",
      SOURCE_TWIN_NOT_FOUND: "Quel twin non è più tra i twin approvati del suo progetto.",
      PROJECT_NOT_FOUND: "Questo progetto non si trova. Ricarica la pagina.",
      BRIEF_APPROVAL_REQUIRED: "Prima approva il Brief di questo progetto.",
      TEAM_APPROVAL_REQUIRED: "Prima approva le Prospettive di questo progetto.",
      TWIN_DOCUMENT_INVALID: "Il file del twin è danneggiato o incompleto.",
      TWIN_DOCUMENT_UNSUPPORTED:
        "Il file del twin viene da un'altra versione dello Studio e non si può usare.",
      TWIN_IMPORT_REQUEST_INVALID:
        "La richiesta non è stata compresa. Ricarica la pagina e riprova.",
      TWIN_IMPORT_TOO_LARGE: "Il file del twin è troppo grande: il limite è 1 MB.",
      CONTEXT_CHANGED: "Nel frattempo i twin di questo progetto sono cambiati. Riprova.",
      PERSISTENCE_REJECTED: "Non è stato possibile salvare il twin. Riprova.",
    },
  },
} as const;

const auth = useAuthStore();
const uid = useId();
const titleId = `${uid}-title`;
const selectId = `${uid}-project`;
const sourceTwinsId = `${uid}-project-twins`;
const fileId = `${uid}-file`;
const twinGroup = `${uid}-twin`;

const copy = computed(() => messages[props.locale]);
const api = computed(() => props.api ?? twinImportsApi);

const opened = ref(false);
const step = ref<Step>(1);
const path = ref<"project" | "file">("project");
const busy = ref<Busy | null>(null);
const candidates = ref<readonly TwinImportCandidatePayload[]>([]);
const candidatesLoaded = ref(false);
const candidatesProblem = ref<string | null>(null);
const selectedProjectId = ref("");
const source = ref<TwinImportSourcePayload | null>(null);
const selectedTwinId = ref("");
const twinFile = ref<TwinFile | null>(null);
const sourceProblem = ref<string | null>(null);
const fileProblem = ref<FileProblem | null>(null);
const importProblem = ref<string | null>(null);
const addedTwin = ref<string | null>(null);

const root = ref<HTMLElement | null>(null);
const projectHeading = ref<HTMLElement | null>(null);
const twinHeading = ref<HTMLElement | null>(null);
const confirmHeading = ref<HTMLElement | null>(null);

const context = useSurface(() => undefined);

const palettes = {
  light: {
    panel: "border-line bg-surface-2",
    heading: "text-ink",
    text: "text-ink-2",
    muted: "text-ink-3",
    step: "border-line bg-white",
    current: "border-action-soft-line bg-white",
    badge: "border-line bg-surface-3 text-ink",
    link: "text-action hover:text-action-hover disabled:text-ink-3",
    field: "border-field bg-white text-ink",
    file: "text-ink-2 file:border-button-line file:bg-surface file:text-ink",
    option: "border-line bg-white",
    optionDisabled: "border-line bg-surface-3",
    error: "border-fail-line bg-fail-bg text-fail-dark",
    success: "border-ok-line bg-ok-bg text-ok-dark",
    issue: "text-warn",
    radio: "accent-action",
  },
  night: {
    panel: "border-night-line bg-night-raised",
    heading: "text-on-night",
    text: "text-on-night-2",
    muted: "text-on-night-3",
    step: "border-night-line bg-night-panel",
    current: "border-petrol-on-night/60 bg-night-panel",
    badge: "border-night-line-strong bg-night-raised text-on-night",
    link: "text-petrol-on-night-2 hover:text-on-night disabled:text-on-night-3",
    field: "border-night-line-strong bg-night-raised text-on-night",
    file: "text-on-night-2 file:border-night-line-strong file:bg-night-raised file:text-on-night",
    option: "border-night-line bg-night-raised",
    optionDisabled: "border-night-line bg-night-deep",
    error: "border-fail-on-night/40 bg-fail-on-night/10 text-fail-on-night",
    success: "border-petrol-on-night/50 bg-petrol-on-night/10 text-petrol-on-night-2",
    issue: "text-warn-on-night",
    radio: "accent-petrol-on-night",
  },
};

const palette = computed(() => palettes[context.value]);

async function focusOpenButton(): Promise<void> {
  await nextTick();
  root.value?.querySelector<HTMLElement>('[data-testid="twin-import-open"]')?.focus();
}

const selectedCandidate = computed(
  () =>
    candidates.value.find((candidate) => candidate.project_id === selectedProjectId.value) ?? null,
);

const selectedProjectName = computed(() => selectedCandidate.value?.project_name ?? "");

const selectedCandidateTwins = computed(() => {
  const names = selectedCandidate.value?.twin_names ?? [];
  const template = names.length === 1 ? copy.value.sourceTwins.one : copy.value.sourceTwins.other;
  return fill(template, { names: names.join(", ") });
});

const choice = computed<ProjectChoice | FileChoice | null>(() => {
  if (path.value === "file") {
    const file = twinFile.value;
    return file === null
      ? null
      : { twin: file.twinName, project: file.projectName, document: file.document };
  }
  const current = source.value;
  const twin = current?.twins.find(
    (candidate) => candidate.twin_id === selectedTwinId.value && candidate.issue === null,
  );
  return current === null || twin === undefined
    ? null
    : {
        twin: twin.name,
        project: current.project_name,
        sourceProjectId: current.project_id,
        twinId: twin.twin_id,
      };
});

const anyAvailable = computed(
  () => source.value?.twins.some((twin) => twin.issue === null) ?? false,
);

const approvedOn = computed(() =>
  source.value === null ? "" : formattedDate(source.value.approved_at, "long"),
);

const projectSummary = computed(() =>
  path.value === "file"
    ? fill(copy.value.fileSummary, { file: twinFile.value?.fileName ?? "" })
    : fill(copy.value.projectSummary, {
        project: selectedProjectName.value || (source.value?.project_name ?? ""),
      }),
);

const twinSummary = computed(() =>
  fill(path.value === "file" ? copy.value.fileTwinSummary : copy.value.twinSummary, {
    twin: choice.value?.twin ?? "",
  }),
);

const busyText = computed(() => {
  switch (busy.value) {
    case "projects":
      return copy.value.loadingProjects;
    case "source":
      return fill(copy.value.loadingTwins, { project: selectedProjectName.value });
    case "file":
      return copy.value.readingFile;
    case "import":
      return fill(copy.value.adding, { twin: choice.value?.twin ?? "" });
    default:
      return "";
  }
});

const fileProblemText = computed(() => {
  if (fileProblem.value === null) return null;
  return fileProblem.value === "FILE_NOT_JSON" ? copy.value.fileNotJson : copy.value.fileNotTwin;
});

const candidatesFailure = computed(() =>
  failureView(candidatesProblem.value, copy.value.projectsFailed),
);

const sourceFailure = computed(() => failureView(sourceProblem.value, copy.value.sourceFailed));

const importFailure = computed(() => failureView(importProblem.value, copy.value.importFailed));

function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_match, key: string) => String(values[key] ?? ""));
}

function formattedDate(value: string, dateStyle: "medium" | "long"): string {
  return new Intl.DateTimeFormat(props.locale === "it" ? "it-IT" : "en-GB", { dateStyle }).format(
    new Date(value),
  );
}

function candidateOption(candidate: TwinImportCandidatePayload): string {
  const count = candidate.twin_names.length;
  return fill(count === 1 ? copy.value.sourceOption.one : copy.value.sourceOption.other, {
    project: candidate.project_name,
    count,
    date: formattedDate(candidate.approved_at, "medium"),
  });
}

function summaryOf(twin: ImportableTwinPayload): string | null {
  const summary = twin.summary?.trim() ?? "";
  return summary.length > 0 && summary.toLowerCase() !== twin.name.trim().toLowerCase()
    ? summary
    : null;
}

function knownCode(code: string): string | null {
  const codes: Readonly<Record<string, string>> = copy.value.codes;
  return codes[code] ?? null;
}

function issueText(issue: string): string {
  return knownCode(issue) ?? copy.value.issueFallback;
}

function failureView(
  code: string | null,
  fallback: string,
): { text: string; code: string | null } | null {
  if (code === null) return null;
  const known = knownCode(code);
  return known === null ? { text: fallback, code } : { text: known, code: null };
}

function optionNotes(twin: ImportableTwinPayload, index: number): string | undefined {
  const ids = [
    summaryOf(twin) !== null ? `${twinGroup}-${index}-summary` : null,
    twin.issue !== null ? `${twinGroup}-${index}-issue` : null,
  ].filter((id): id is string => id !== null);
  return ids.length > 0 ? ids.join(" ") : undefined;
}

function failureCode(error: unknown): string {
  if (error instanceof ApiRequestError) return error.code ?? `HTTP_${error.status}`;
  if (error instanceof ApiError) return error.detail;
  return error instanceof Error && error.message.length > 0 ? error.message : "UNEXPECTED_ERROR";
}

function authorized<T>(operation: (accessToken: string) => Promise<T>): Promise<T> {
  return props.authorize ? props.authorize(operation) : auth.withAccessToken(apiClient, operation);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function textAt(value: unknown, keys: readonly string[]): string | null {
  let current = value;
  for (const key of keys) {
    if (!isRecord(current)) return null;
    current = current[key];
  }
  return typeof current === "string" && current.trim().length > 0 ? current.trim() : null;
}

function twinFileOf(text: string, fileName: string): TwinFile | FileProblem {
  let document: unknown;
  try {
    document = JSON.parse(text);
  } catch {
    return "FILE_NOT_JSON";
  }
  const twinName = textAt(document, ["twin", "profile", "name"]);
  const projectName = textAt(document, ["origin", "project_name"]);
  if (!isRecord(document) || twinName === null || projectName === null) {
    return "FILE_NOT_TWIN";
  }
  return { document, fileName, twinName, projectName };
}

function readText(file: File): Promise<string> {
  return file.text();
}

async function focusStep(next: Step): Promise<void> {
  step.value = next;
  await nextTick();
  const headings = { 1: projectHeading, 2: twinHeading, 3: confirmHeading };
  headings[next].value?.focus();
}

function resetChoices(): void {
  step.value = 1;
  path.value = "project";
  selectedProjectId.value = "";
  source.value = null;
  selectedTwinId.value = "";
  twinFile.value = null;
  sourceProblem.value = null;
  fileProblem.value = null;
  importProblem.value = null;
}

async function loadCandidates(): Promise<void> {
  if (busy.value !== null) return;
  busy.value = "projects";
  candidatesProblem.value = null;
  try {
    const result = await authorized((token) => api.value.sources(props.projectId, token));
    candidates.value = result.sources;
    candidatesLoaded.value = true;
  } catch (error) {
    candidatesProblem.value = failureCode(error);
  } finally {
    busy.value = null;
  }
}

async function retryCandidates(): Promise<void> {
  await loadCandidates();
  await focusStep(1);
}

async function openPanel(): Promise<void> {
  resetChoices();
  addedTwin.value = null;
  candidates.value = [];
  candidatesLoaded.value = false;
  candidatesProblem.value = null;
  opened.value = true;
  await focusStep(1);
  await loadCandidates();
}

async function closePanel(): Promise<void> {
  if (busy.value !== null) return;
  resetChoices();
  opened.value = false;
  await focusOpenButton();
}

async function goBack(target: Step): Promise<void> {
  if (busy.value !== null) return;
  importProblem.value = null;
  await focusStep(target);
}

async function showTwins(): Promise<void> {
  const sourceProjectId = selectedProjectId.value;
  if (sourceProjectId === "" || busy.value !== null) return;
  busy.value = "source";
  sourceProblem.value = null;
  fileProblem.value = null;
  try {
    const result = await authorized((token) =>
      api.value.source(props.projectId, sourceProjectId, token),
    );
    const keepsTwin = result.twins.some(
      (twin) => twin.twin_id === selectedTwinId.value && twin.issue === null,
    );
    source.value = result;
    path.value = "project";
    if (!keepsTwin) selectedTwinId.value = "";
    busy.value = null;
    await focusStep(2);
  } catch (error) {
    sourceProblem.value = failureCode(error);
  } finally {
    busy.value = null;
  }
}

async function continueToConfirm(): Promise<void> {
  if (choice.value === null || busy.value !== null) return;
  importProblem.value = null;
  await focusStep(3);
}

async function chooseFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (file === undefined || busy.value !== null) return;
  busy.value = "file";
  fileProblem.value = null;
  sourceProblem.value = null;
  try {
    const parsed = twinFileOf(await (props.readFile ?? readText)(file), file.name);
    if (typeof parsed === "string") {
      fileProblem.value = parsed;
      return;
    }
    twinFile.value = parsed;
    path.value = "file";
    importProblem.value = null;
    busy.value = null;
    await focusStep(3);
  } catch {
    fileProblem.value = "FILE_NOT_JSON";
  } finally {
    busy.value = null;
  }
}

async function addTwin(): Promise<void> {
  const current = choice.value;
  if (current === null || busy.value !== null) return;
  const projectId = props.projectId;
  busy.value = "import";
  importProblem.value = null;
  try {
    const result = await authorized((token) =>
      "document" in current
        ? api.value.importDocument(projectId, current.document, token)
        : api.value.importFromProject(projectId, current.sourceProjectId, current.twinId, token),
    );
    resetChoices();
    opened.value = false;
    addedTwin.value = result.twin.name;
    busy.value = null;
    emit("imported", result);
    await focusOpenButton();
  } catch (error) {
    importProblem.value = failureCode(error);
  } finally {
    busy.value = null;
  }
}
</script>

<template>
  <section
    ref="root"
    :class="[
      'grid gap-3',
      opened ? ['basis-full rounded-tile border p-5', palette.panel] : 'justify-items-start',
    ]"
    :aria-labelledby="titleId"
    :data-opened="opened ? 'true' : 'false'"
    data-testid="twin-import"
  >
    <div :class="opened ? 'grid gap-1' : 'contents'">
      <h2
        :id="titleId"
        :class="opened ? ['m-0 text-[17px] font-semibold', palette.heading] : 'sr-only'"
      >
        {{ copy.title }}
      </h2>
      <p v-if="opened" :class="['m-0 max-w-2xl text-sm leading-6', palette.text]">
        {{ copy.intro }}
      </p>
    </div>
    <UiButton v-if="!opened" variant="secondary" data-testid="twin-import-open" @click="openPanel">
      {{ copy.open }}
    </UiButton>

    <p
      v-if="addedTwin !== null"
      :class="['m-0 max-w-md rounded-panel border p-3 text-sm font-semibold', palette.success]"
      role="status"
      data-testid="twin-import-success"
    >
      <span aria-hidden="true">✓</span> {{ fill(copy.added, { twin: addedTwin }) }}
    </p>

    <template v-if="opened">
      <ol class="m-0 grid list-none gap-3 p-0">
        <li
          :class="[
            'grid gap-3 rounded-panel border p-4',
            step === 1 ? palette.current : palette.step,
          ]"
          :aria-current="step === 1 ? 'step' : undefined"
          data-testid="twin-import-step-1"
        >
          <div class="flex flex-wrap items-center justify-between gap-2">
            <h3
              ref="projectHeading"
              tabindex="-1"
              :class="[
                'm-0 flex items-center gap-2 text-sm font-semibold outline-none',
                palette.heading,
              ]"
            >
              <span
                :class="[
                  'inline-flex size-6 items-center justify-center rounded-pill border font-mono text-xs',
                  palette.badge,
                ]"
                >1</span
              >
              {{ copy.stepProject }}
            </h3>
            <button
              v-if="step > 1"
              type="button"
              :class="[
                'inline-flex min-h-11 items-center text-sm font-semibold underline underline-offset-2 disabled:cursor-not-allowed',
                palette.link,
              ]"
              :aria-label="path === 'file' ? copy.changeFile : copy.changeProject"
              :disabled="busy !== null"
              data-testid="twin-import-change-project"
              @click="goBack(1)"
            >
              {{ copy.change }}
            </button>
          </div>
          <p
            v-if="step > 1"
            :class="['m-0 text-sm', palette.text]"
            data-testid="twin-import-project-summary"
          >
            <span aria-hidden="true">✓</span> {{ projectSummary }}
          </p>
          <template v-else>
            <form v-if="candidates.length > 0" class="grid gap-2" @submit.prevent="showTwins">
              <label :for="selectId" :class="['text-sm font-semibold', palette.text]">
                {{ copy.projectLabel }}
              </label>
              <select
                :id="selectId"
                v-model="selectedProjectId"
                :class="[
                  'min-h-11 w-full max-w-md rounded-control border px-3 py-2 text-sm',
                  palette.field,
                ]"
                :disabled="busy !== null"
                :aria-describedby="selectedCandidate !== null ? sourceTwinsId : undefined"
                data-testid="twin-import-project"
              >
                <option value="" disabled>{{ copy.projectPlaceholder }}</option>
                <option
                  v-for="candidate in candidates"
                  :key="candidate.project_id"
                  :value="candidate.project_id"
                >
                  {{ candidateOption(candidate) }}
                </option>
              </select>
              <p
                v-if="selectedCandidate !== null"
                :id="sourceTwinsId"
                :class="['m-0 text-sm leading-6', palette.text]"
                data-testid="twin-import-source-twins"
              >
                {{ selectedCandidateTwins }}
              </p>
              <div class="flex">
                <UiButton
                  type="submit"
                  :disabled="busy !== null || selectedProjectId === ''"
                  data-testid="twin-import-show-twins"
                >
                  {{ copy.showTwins }}
                </UiButton>
              </div>
            </form>
            <div
              v-else-if="candidatesFailure"
              :class="['grid gap-2 rounded-panel border p-3 text-sm', palette.error]"
              role="alert"
              data-testid="twin-import-projects-error"
            >
              <p class="m-0 font-semibold">{{ candidatesFailure.text }}</p>
              <details v-if="candidatesFailure.code !== null" class="text-xs">
                <summary class="flex min-h-11 cursor-pointer items-center">
                  {{ copy.details }}
                </summary>
                <code class="break-all">{{ candidatesFailure.code }}</code>
              </details>
              <div class="flex">
                <UiButton
                  variant="secondary"
                  :disabled="busy !== null"
                  data-testid="twin-import-sources-retry"
                  @click="retryCandidates"
                >
                  {{ copy.retry }}
                </UiButton>
              </div>
            </div>
            <p
              v-else-if="candidatesLoaded"
              :class="['m-0 text-sm leading-6', palette.text]"
              data-testid="twin-import-no-sources"
            >
              {{ copy.noSources }}
            </p>
            <div
              v-if="sourceFailure"
              :class="['grid gap-1 rounded-panel border p-3 text-sm', palette.error]"
              role="alert"
              data-testid="twin-import-source-error"
            >
              <p class="m-0 font-semibold">{{ sourceFailure.text }}</p>
              <details v-if="sourceFailure.code !== null" class="text-xs">
                <summary class="flex min-h-11 cursor-pointer items-center">
                  {{ copy.details }}
                </summary>
                <code class="break-all">{{ sourceFailure.code }}</code>
              </details>
            </div>
            <div
              :class="[
                'grid gap-2 border-t pt-3',
                context === 'night' ? 'border-night-line' : 'border-line',
              ]"
            >
              <p
                v-if="candidates.length > 0"
                :class="['m-0 text-sm', palette.text]"
                data-testid="twin-import-file-alternative"
              >
                {{ copy.fileAlternative }}
              </p>
              <label :for="fileId" :class="['text-sm font-semibold', palette.text]">
                {{ copy.fileLabel }}
              </label>
              <input
                :id="fileId"
                type="file"
                accept=".json,application/json"
                :class="[
                  'min-h-11 w-full max-w-md min-w-0 text-sm file:mr-3 file:min-h-11 file:rounded-pill file:border file:px-4 file:py-2 file:text-sm file:font-semibold',
                  palette.file,
                ]"
                :disabled="busy !== null"
                data-testid="twin-import-file"
                @change="chooseFile"
              />
              <p
                v-if="fileProblemText"
                :class="['m-0 rounded-panel border p-3 text-sm', palette.error]"
                role="alert"
                data-testid="twin-import-file-error"
              >
                {{ fileProblemText }}
              </p>
            </div>
          </template>
        </li>

        <li
          :class="[
            'grid gap-3 rounded-panel border p-4',
            step === 2 ? palette.current : palette.step,
          ]"
          :aria-current="step === 2 ? 'step' : undefined"
          data-testid="twin-import-step-2"
        >
          <div class="flex flex-wrap items-center justify-between gap-2">
            <h3
              ref="twinHeading"
              tabindex="-1"
              :class="[
                'm-0 flex items-center gap-2 text-sm font-semibold outline-none',
                step >= 2 ? palette.heading : palette.muted,
              ]"
            >
              <span
                :class="[
                  'inline-flex size-6 items-center justify-center rounded-pill border font-mono text-xs',
                  palette.badge,
                ]"
                >2</span
              >
              {{ copy.stepTwin }}
            </h3>
            <button
              v-if="step > 2"
              type="button"
              :class="[
                'inline-flex min-h-11 items-center text-sm font-semibold underline underline-offset-2 disabled:cursor-not-allowed',
                palette.link,
              ]"
              :aria-label="copy.changeTwin"
              :disabled="busy !== null"
              data-testid="twin-import-change-twin"
              @click="goBack(path === 'file' ? 1 : 2)"
            >
              {{ copy.change }}
            </button>
          </div>
          <p
            v-if="step > 2"
            :class="['m-0 text-sm', palette.text]"
            data-testid="twin-import-twin-summary"
          >
            <span aria-hidden="true">✓</span> {{ twinSummary }}
          </p>
          <form
            v-else-if="step === 2 && source !== null"
            class="grid gap-3"
            @submit.prevent="continueToConfirm"
          >
            <fieldset class="m-0 grid min-w-0 gap-2 border-0 p-0">
              <legend :class="['mb-1 p-0 text-sm font-semibold', palette.text]">
                {{ fill(copy.twinsOf, { project: selectedProjectName || source.project_name }) }}
              </legend>
              <p :class="['m-0 text-xs leading-5', palette.muted]">
                {{ fill(copy.approvedOn, { date: approvedOn }) }}
              </p>
              <label
                v-for="(twin, index) in source.twins"
                :key="twin.twin_id"
                :class="[
                  'flex items-start gap-3 rounded-panel border p-3',
                  twin.issue === null
                    ? ['cursor-pointer', palette.option]
                    : ['cursor-not-allowed', palette.optionDisabled],
                ]"
                data-testid="twin-import-option"
              >
                <input
                  v-model="selectedTwinId"
                  type="radio"
                  :class="['mt-1 size-4 shrink-0', palette.radio]"
                  :name="twinGroup"
                  :value="twin.twin_id"
                  :disabled="twin.issue !== null || busy !== null"
                  :aria-label="twin.name"
                  :aria-describedby="optionNotes(twin, index)"
                  data-testid="twin-import-twin"
                />
                <span class="grid min-w-0 gap-1">
                  <span :class="['text-sm font-semibold', palette.heading]">{{ twin.name }}</span>
                  <span
                    v-if="summaryOf(twin) !== null"
                    :id="`${twinGroup}-${index}-summary`"
                    :class="['text-sm leading-6', palette.text]"
                  >
                    {{ summaryOf(twin) }}
                  </span>
                  <span
                    v-if="twin.issue !== null"
                    :id="`${twinGroup}-${index}-issue`"
                    :class="['text-sm leading-6', palette.issue]"
                    data-testid="twin-import-issue"
                  >
                    <strong>{{ copy.unavailable }}</strong> {{ issueText(twin.issue) }}
                  </span>
                </span>
              </label>
            </fieldset>
            <p
              v-if="!anyAvailable"
              :class="['m-0 text-sm', palette.text]"
              data-testid="twin-import-none"
            >
              {{ copy.noneAvailable }}
            </p>
            <div class="flex">
              <UiButton
                type="submit"
                :disabled="choice === null || busy !== null"
                data-testid="twin-import-continue"
              >
                {{ copy.continue }}
              </UiButton>
            </div>
          </form>
        </li>

        <li
          :class="[
            'grid gap-3 rounded-panel border p-4',
            step === 3 ? palette.current : palette.step,
          ]"
          :aria-current="step === 3 ? 'step' : undefined"
          data-testid="twin-import-step-3"
        >
          <h3
            ref="confirmHeading"
            tabindex="-1"
            :class="[
              'm-0 flex items-center gap-2 text-sm font-semibold outline-none',
              step === 3 ? palette.heading : palette.muted,
            ]"
          >
            <span
              :class="[
                'inline-flex size-6 items-center justify-center rounded-pill border font-mono text-xs',
                palette.badge,
              ]"
              >3</span
            >
            {{ copy.stepConfirm }}
          </h3>
          <template v-if="step === 3 && choice !== null">
            <p
              :class="['m-0 text-sm leading-6', palette.heading]"
              data-testid="twin-import-confirmation"
            >
              {{ fill(copy.confirmation, { twin: choice.twin, project: choice.project }) }}
            </p>
            <div class="flex">
              <UiButton :disabled="busy !== null" data-testid="twin-import-add" @click="addTwin">
                {{ copy.add }}
              </UiButton>
            </div>
            <div
              v-if="importFailure"
              :class="['grid gap-1 rounded-panel border p-3 text-sm', palette.error]"
              role="alert"
              data-testid="twin-import-error"
            >
              <p class="m-0 font-semibold">{{ importFailure.text }}</p>
              <details v-if="importFailure.code !== null" class="text-xs">
                <summary class="flex min-h-11 cursor-pointer items-center">
                  {{ copy.details }}
                </summary>
                <code class="break-all">{{ importFailure.code }}</code>
              </details>
            </div>
          </template>
        </li>
      </ol>

      <p
        v-if="busy !== null"
        :class="['m-0 text-sm font-medium', palette.text]"
        role="status"
        data-testid="twin-import-busy"
      >
        {{ busyText }}
      </p>

      <div class="flex">
        <UiButton
          variant="secondary"
          :disabled="busy !== null"
          data-testid="twin-import-cancel"
          @click="closePanel"
        >
          {{ copy.cancel }}
        </UiButton>
      </div>
    </template>
  </section>
</template>
