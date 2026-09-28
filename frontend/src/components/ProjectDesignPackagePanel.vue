<script setup lang="ts">
import { computed, ref, watch } from "vue";

import DeclarativePrototypePreview from "./DeclarativePrototypePreview.vue";
import DesignStyleTile from "./DesignStyleTile.vue";
import UiButton from "./UiButton.vue";

import { apiClient } from "../api/client";
import type { KnowledgePackagesApi } from "../api/knowledgePackages";
import { useAuthStore } from "../stores/auth";
import { useDesignStore } from "../stores/design";
import { useKnowledgePackagesStore, type AuthorizedRequest } from "../stores/knowledgePackages";
import { useUserModelingStore } from "../stores/userModeling";
import type { KnowledgePackageVersionPayload } from "../types/knowledgePackages";

type Locale = "en" | "it";

const props = withDefaults(
  defineProps<{
    projectId: string;
    stages: readonly { label: string; version: number | null; approved: boolean }[];
    locale?: Locale;
    authorize?: AuthorizedRequest;
    api?: KnowledgePackagesApi;
    saveExport?: (blob: Blob, fileName: string) => void;
  }>(),
  {
    locale: "en",
  },
);

const messages = {
  en: {
    eyebrow: "Knowledge folder",
    title: "Your project is ready to be built",
    intro:
      "The five steps are approved. The knowledge folder holds the brief, the team, the twins, the requirements and the chosen design as text, tables and diagrams. Put it inside the project you will build with your own tools.",
    notReady:
      "The folder can be prepared when all five steps are approved. Complete the steps marked as pending below.",
    prepare: "Prepare and download the folder",
    preparing: "Preparing the folder…",
    created: "Version {number} of the folder is ready and downloaded: {file}",
    reused: "Nothing changed since version {number}: the same folder was downloaded again: {file}",
    failed: "The folder could not be prepared.",
    downloadFailed: "The folder could not be downloaded.",
    outdated: {
      TEAM_OUTDATED:
        "The team follows an earlier version of the brief. Open the Team step, update the team and approve it again.",
      USER_TWINS_OUTDATED:
        "The twins follow an earlier version of the brief or of the team. Open the User Twins step and approve them again.",
      REQUIREMENTS_OUTDATED:
        "The requirements follow an earlier version of the twins. Open the Requirements step, update them to the current twins and approve them again.",
      DESIGN_OUTDATED:
        "The design follows an earlier version of the requirements. Open the Design step, regenerate the alternatives and approve the design again.",
    },
    history: "Versions of the folder",
    historyIntro:
      "A new version is created only when something changed. Every version can be downloaded again exactly as it was.",
    noHistory: "No version has been prepared yet.",
    version: "Version {number}",
    download: "Download",
    downloadVersion: "Download version {number}",
    contents: "What the folder contains",
    files: "{count} files",
    twinsCount: "{count} twins, each with its own reusable file",
    views: "{diagrams} diagrams and {tables} tables of requirements and design",
    feedback:
      "{reviews} twin reviews, {decisions} decisions of yours, {discussions} approved discussions",
    schema: "An index, ORCHESTWIN.md, and the description of every file",
    path: "The path you approved",
    stageVersion: "version {number}",
    noVersion: "no version",
    approved: "approved",
    pending: "pending",
    design: "The design you chose",
    noDesign: "The chosen design appears here once the design step is approved.",
    mockup: "Mockup of the chosen design",
    noMockup: "No mockup was saved for the chosen alternative.",
    twins: "The people it is built for",
    noTwins: "No user twin is available yet.",
    next: "How to use it",
    steps: [
      "Extract the archive inside your project, for example in a folder named orchestwin.",
      "Open ORCHESTWIN.md: it is the index and explains every file.",
      "Build with your own tools. Requirements, screens and elements have stable codes to quote in your work.",
      "When the scope changes, come back to the Studio, approve the new version and download the folder again.",
    ],
  },
  it: {
    eyebrow: "Cartella di conoscenza",
    title: "Il tuo progetto è pronto per essere realizzato",
    intro:
      "I cinque passi sono approvati. La cartella di conoscenza raccoglie brief, squadra, twin, requisiti e design scelto in forma di testo, tabelle e diagrammi. Mettila dentro il progetto che realizzerai con i tuoi strumenti.",
    notReady:
      "La cartella si può preparare quando tutti e cinque i passi sono approvati. Completa i passi segnati qui sotto come in attesa.",
    prepare: "Prepara e scarica la cartella",
    preparing: "Preparo la cartella…",
    created: "La versione {number} della cartella è pronta ed è stata scaricata: {file}",
    reused:
      "Non è cambiato nulla dalla versione {number}: ho scaricato di nuovo la stessa cartella: {file}",
    failed: "Non è stato possibile preparare la cartella.",
    downloadFailed: "Non è stato possibile scaricare la cartella.",
    outdated: {
      TEAM_OUTDATED:
        "La squadra segue una versione precedente del brief. Apri il passo Squadra, aggiorna la squadra e approvala di nuovo.",
      USER_TWINS_OUTDATED:
        "I twin seguono una versione precedente del brief o della squadra. Apri il passo User Twin e approvali di nuovo.",
      REQUIREMENTS_OUTDATED:
        "I requisiti seguono una versione precedente dei twin. Apri il passo Requisiti, aggiornali ai twin attuali e approvali di nuovo.",
      DESIGN_OUTDATED:
        "Il design segue una versione precedente dei requisiti. Apri il passo Design, rigenera le alternative e approva di nuovo il design.",
    },
    history: "Versioni della cartella",
    historyIntro:
      "Una nuova versione nasce solo quando è cambiato qualcosa. Ogni versione si può scaricare di nuovo esattamente com'era.",
    noHistory: "Non hai ancora preparato nessuna versione.",
    version: "Versione {number}",
    download: "Scarica",
    downloadVersion: "Scarica la versione {number}",
    contents: "Che cosa contiene la cartella",
    files: "{count} file",
    twinsCount: "{count} twin, ciascuno con un proprio file riutilizzabile",
    views: "{diagrams} diagrammi e {tables} tabelle di requisiti e design",
    feedback:
      "{reviews} revisioni dei twin, {decisions} tue decisioni, {discussions} discussioni approvate",
    schema: "Un indice, ORCHESTWIN.md, e la descrizione di ogni file",
    path: "Il percorso che hai approvato",
    stageVersion: "versione {number}",
    noVersion: "nessuna versione",
    approved: "approvato",
    pending: "in attesa",
    design: "Il design che hai scelto",
    noDesign: "Il design scelto compare qui dopo l'approvazione del passo Design.",
    mockup: "Mockup del design scelto",
    noMockup: "Nessun mockup è stato salvato per l'alternativa scelta.",
    twins: "Le persone per cui è pensato",
    noTwins: "Nessun user twin è ancora disponibile.",
    next: "Come usarla",
    steps: [
      "Estrai l'archivio dentro il tuo progetto, per esempio in una cartella chiamata orchestwin.",
      "Apri ORCHESTWIN.md: è l'indice e spiega ogni file.",
      "Realizza il progetto con i tuoi strumenti. Requisiti, schermate ed elementi hanno codici stabili da citare nel lavoro.",
      "Quando lo scopo cambia, torna nello Studio, approva la nuova versione e scarica di nuovo la cartella.",
    ],
  },
} as const;

const auth = useAuthStore();
const design = useDesignStore();
const modeling = useUserModelingStore();
const packages = useKnowledgePackagesStore();

const copy = computed(() => messages[props.locale]);
const busy = ref(false);
const error = ref<string | null>(null);
const outcome = ref<{ reused: boolean; number: number; file: string } | null>(null);

const ready = computed(
  () => props.stages.length > 0 && props.stages.every((stage) => stage.approved),
);
const versions = computed<KnowledgePackageVersionPayload[]>(() =>
  packages.projectId === props.projectId ? packages.versions : [],
);
const latest = computed(() => versions.value[0] ?? null);
const selectedAlternative = computed(() =>
  design.projectId === props.projectId ? design.selectedAlternative : null,
);
const prototype = computed(() => {
  const candidate = design.current?.package.prototype ?? null;
  return candidate && candidate.design_alternative_id === selectedAlternative.value?.id
    ? candidate
    : null;
});
const twins = computed(() => (modeling.projectId === props.projectId ? modeling.currentTwins : []));
const dateFormat = computed(
  () =>
    new Intl.DateTimeFormat(props.locale === "it" ? "it-IT" : "en-GB", {
      dateStyle: "medium",
      timeStyle: "short",
    }),
);

function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_match, key: string) => String(values[key] ?? ""));
}

function authorizedRequest<T>(operation: (accessToken: string) => Promise<T>): Promise<T> {
  return props.authorize ? props.authorize(operation) : auth.withAccessToken(apiClient, operation);
}

function saveBlob(blob: Blob, fileName: string): void {
  if (props.saveExport !== undefined) {
    props.saveExport(blob, fileName);
    return;
  }

  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.click();
  URL.revokeObjectURL(url);
}

function failureMessage(fallback: string): string {
  const code = packages.error?.code ?? null;
  if (code === null) {
    return fallback;
  }
  if (code.endsWith("_APPROVAL_REQUIRED")) {
    return copy.value.notReady;
  }
  const outdated: Readonly<Record<string, string>> = copy.value.outdated;
  return outdated[code] ?? fallback;
}

async function fetchVersion(number: number): Promise<string> {
  const result = await packages.download(props.projectId, number, authorizedRequest, props.api);
  saveBlob(result.blob, result.fileName);
  return result.fileName;
}

async function prepare(): Promise<void> {
  busy.value = true;
  error.value = null;
  outcome.value = null;

  try {
    const publication = await packages.publish(props.projectId, authorizedRequest, props.api);
    const file = await fetchVersion(publication.version.version_number);
    outcome.value = {
      reused: publication.reused,
      number: publication.version.version_number,
      file,
    };
  } catch {
    error.value = failureMessage(copy.value.failed);
  } finally {
    busy.value = false;
  }
}

async function download(version: KnowledgePackageVersionPayload): Promise<void> {
  busy.value = true;
  error.value = null;

  try {
    await fetchVersion(version.version_number);
  } catch {
    error.value = failureMessage(copy.value.downloadFailed);
  } finally {
    busy.value = false;
  }
}

async function loadHistory(): Promise<void> {
  try {
    await packages.load(props.projectId, authorizedRequest, props.api);
  } catch {
    error.value = null;
  }
}

watch(() => props.projectId, loadHistory, { immediate: true });
</script>

<template>
  <section class="space-y-8" aria-labelledby="design-package-title" data-testid="design-package">
    <header class="rounded-card border border-line bg-white p-5 shadow-sm sm:p-6">
      <p class="m-0 font-mono text-[11px] tracking-wide text-ink-3 uppercase">
        {{ copy.eyebrow }}
      </p>
      <h2 id="design-package-title" class="mt-2 text-2xl font-semibold tracking-title">
        {{ copy.title }}
      </h2>
      <p class="mt-3 max-w-2xl text-sm leading-6 text-ink-2">{{ copy.intro }}</p>
      <p
        v-if="!ready"
        class="mt-4 rounded-panel border border-line-soft bg-surface-2 p-4 text-sm text-ink-2"
        data-testid="package-not-ready"
      >
        {{ copy.notReady }}
      </p>
      <div class="mt-5 flex flex-wrap items-center gap-3">
        <UiButton :disabled="busy || !ready" data-testid="download-package" @click="prepare">
          {{ busy ? copy.preparing : copy.prepare }}
        </UiButton>
      </div>
      <p
        v-if="outcome"
        class="mt-4 rounded-panel border border-ok-line bg-ok-bg p-4 text-sm font-semibold text-ok-dark"
        data-testid="download-done"
        aria-live="polite"
      >
        {{
          fill(outcome.reused ? copy.reused : copy.created, {
            number: outcome.number,
            file: outcome.file,
          })
        }}
      </p>
      <p
        v-if="error"
        class="mt-4 rounded-panel border border-fail-line bg-fail-bg p-4 font-semibold text-fail-dark"
        role="alert"
        data-testid="download-error"
      >
        {{ error }}
      </p>
    </header>

    <section
      class="rounded-card border border-line bg-white p-5 shadow-sm sm:p-6"
      data-testid="package-history"
    >
      <h3 class="m-0 text-lg font-semibold tracking-block">{{ copy.history }}</h3>
      <p class="mt-2 text-sm leading-6 text-ink-2">{{ copy.historyIntro }}</p>
      <ol v-if="versions.length > 0" class="mt-4 grid list-none gap-2 p-0">
        <li
          v-for="version in versions"
          :key="version.id"
          class="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-3 text-sm"
          data-testid="package-version"
        >
          <div class="grid gap-1">
            <span class="font-semibold" data-testid="package-version-title">
              {{ fill(copy.version, { number: version.version_number }) }}
            </span>
            <span class="font-mono text-xs text-ink-3">
              {{ dateFormat.format(new Date(version.created_at)) }} ·
              {{ fill(copy.files, { count: version.file_count }) }}
            </span>
          </div>
          <UiButton
            variant="secondary"
            :disabled="busy"
            :aria-label="fill(copy.downloadVersion, { number: version.version_number })"
            data-testid="download-version"
            @click="download(version)"
          >
            {{ copy.download }}
          </UiButton>
        </li>
      </ol>
      <p v-else class="mt-3 text-sm text-ink-3" data-testid="package-no-history">
        {{ copy.noHistory }}
      </p>
    </section>

    <section
      v-if="latest"
      class="rounded-card border border-line bg-white p-5 shadow-sm sm:p-6"
      data-testid="package-contents"
    >
      <h3 class="m-0 text-lg font-semibold tracking-block">{{ copy.contents }}</h3>
      <ul class="mt-3 grid list-disc gap-1 pl-5 text-sm leading-6 text-ink-2">
        <li>{{ copy.schema }}</li>
        <li>{{ fill(copy.twinsCount, { count: latest.twins.length }) }}</li>
        <li>
          {{ fill(copy.views, { diagrams: latest.diagram_count, tables: latest.table_count }) }}
        </li>
        <li>
          {{
            fill(copy.feedback, {
              reviews: latest.feedback.reviews,
              decisions: latest.feedback.decisions,
              discussions: latest.feedback.discussions,
            })
          }}
        </li>
      </ul>
    </section>

    <section class="rounded-card border border-line bg-white p-5 shadow-sm sm:p-6">
      <h3 class="m-0 text-lg font-semibold tracking-block">{{ copy.path }}</h3>
      <ol class="mt-4 grid list-none gap-2 p-0">
        <li
          v-for="(stage, index) in stages"
          :key="stage.label"
          class="flex flex-wrap items-baseline justify-between gap-2 border-b border-line pb-2 text-sm"
          data-testid="package-stage"
        >
          <span class="font-semibold">{{ index + 1 }}. {{ stage.label }}</span>
          <span class="font-mono text-xs text-ink-3">
            {{
              stage.version === null
                ? copy.noVersion
                : fill(copy.stageVersion, { number: stage.version })
            }}
            · {{ stage.approved ? copy.approved : copy.pending }}
          </span>
        </li>
      </ol>
    </section>

    <section class="rounded-card border border-line bg-white p-5 shadow-sm sm:p-6">
      <h3 class="m-0 text-lg font-semibold tracking-block">{{ copy.design }}</h3>
      <template v-if="selectedAlternative">
        <p class="mt-3 text-base font-semibold" data-testid="package-alternative">
          {{ selectedAlternative.code }} · {{ selectedAlternative.title }}
        </p>
        <p class="mt-2 text-sm leading-6 text-ink-2">{{ selectedAlternative.summary }}</p>
        <DesignStyleTile
          v-if="selectedAlternative.visual_language"
          class="mt-4"
          :visual="selectedAlternative.visual_language"
          :locale="locale"
        />
        <h4 class="mt-5 text-sm font-semibold text-ink-2">{{ copy.mockup }}</h4>
        <DeclarativePrototypePreview
          v-if="prototype"
          class="mt-3"
          :prototype="prototype"
          :visual="selectedAlternative.visual_language"
          :locale="locale"
        />
        <p v-else class="mt-2 text-sm text-ink-3">{{ copy.noMockup }}</p>
      </template>
      <p v-else class="mt-3 text-sm text-ink-3">{{ copy.noDesign }}</p>
    </section>

    <section class="rounded-card border border-line bg-white p-5 shadow-sm sm:p-6">
      <h3 class="m-0 text-lg font-semibold tracking-block">{{ copy.twins }}</h3>
      <ul v-if="twins.length > 0" class="mt-3 grid list-none gap-1 p-0 text-sm">
        <li v-for="twin in twins" :key="twin.id" data-testid="package-twin">
          {{ twin.profile.name }}
        </li>
      </ul>
      <p v-else class="mt-3 text-sm text-ink-3">{{ copy.noTwins }}</p>
    </section>

    <section class="rounded-card border border-line bg-white p-5 shadow-sm sm:p-6">
      <h3 class="m-0 text-lg font-semibold tracking-block">{{ copy.next }}</h3>
      <ol class="mt-3 grid list-decimal gap-2 pl-5 text-sm leading-6 text-ink-2">
        <li v-for="step in copy.steps" :key="step" data-testid="package-step">{{ step }}</li>
      </ol>
    </section>
  </section>
</template>
