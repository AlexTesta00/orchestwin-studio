<script setup lang="ts">
import { computed, ref } from "vue";

import DeclarativePrototypePreview from "./DeclarativePrototypePreview.vue";
import DesignStyleTile from "./DesignStyleTile.vue";
import UiButton from "./UiButton.vue";

import { apiClient } from "../api/client";
import { designPackageApi, type DesignPackageApi } from "../api/designPackage";
import { useAuthStore } from "../stores/auth";
import { useDesignStore, type AuthorizedRequest } from "../stores/design";
import { useUserModelingStore } from "../stores/userModeling";

type Locale = "en" | "it";

const props = withDefaults(
  defineProps<{
    projectId: string;
    stages: readonly { label: string; version: number | null; approved: boolean }[];
    locale?: Locale;
    authorize?: AuthorizedRequest;
    api?: DesignPackageApi;
    saveExport?: (blob: Blob, fileName: string) => void;
  }>(),
  {
    locale: "en",
  },
);

const messages = {
  en: {
    eyebrow: "Design package",
    title: "Your project is ready to be built",
    intro:
      "The five steps are approved. Download the package and continue in your own development environment: it holds the brief, the team, the twins, the requirements and the chosen design, as Markdown and JSON.",
    path: "The path you approved",
    version: "version {number}",
    noVersion: "no version",
    approved: "approved",
    pending: "pending",
    design: "The design you chose",
    noDesign: "The chosen design appears here once the design step is approved.",
    mockup: "Mockup of the chosen design",
    noMockup: "No mockup was saved for the chosen alternative.",
    twins: "The people it is built for",
    noTwins: "No user twin is available yet.",
    download: "Download the design package",
    downloading: "Preparing the package…",
    downloaded: "Package downloaded: {file}",
    downloadError: "The package could not be downloaded.",
    next: "What happens next",
    nextText:
      "Open the package in your editor: ORCHESTWIN.md is the index. From here the project continues with your own tools, while the Studio keeps the approved versions.",
  },
  it: {
    eyebrow: "Pacchetto di design",
    title: "Il tuo progetto è pronto per essere realizzato",
    intro:
      "I cinque passi sono approvati. Scarica il pacchetto e continua nel tuo ambiente di sviluppo: contiene brief, squadra, twin, requisiti e il design scelto, in Markdown e JSON.",
    path: "Il percorso che hai approvato",
    version: "versione {number}",
    noVersion: "nessuna versione",
    approved: "approvato",
    pending: "in attesa",
    design: "Il design che hai scelto",
    noDesign: "Il design scelto compare qui dopo l'approvazione del passo Design.",
    mockup: "Mockup del design scelto",
    noMockup: "Nessun mockup è stato salvato per l'alternativa scelta.",
    twins: "Le persone per cui è pensato",
    noTwins: "Nessun user twin è ancora disponibile.",
    download: "Scarica il pacchetto di design",
    downloading: "Preparazione del pacchetto…",
    downloaded: "Pacchetto scaricato: {file}",
    downloadError: "Non è stato possibile scaricare il pacchetto.",
    next: "Cosa succede adesso",
    nextText:
      "Apri il pacchetto nel tuo editor: ORCHESTWIN.md è l'indice. Da qui il progetto prosegue con i tuoi strumenti, mentre lo Studio conserva le versioni approvate.",
  },
} as const;

const auth = useAuthStore();
const design = useDesignStore();
const modeling = useUserModelingStore();

const copy = computed(() => messages[props.locale]);
const api = computed(() => props.api ?? designPackageApi);
const busy = ref(false);
const error = ref<string | null>(null);
const downloadedFile = ref<string | null>(null);

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

async function download(): Promise<void> {
  busy.value = true;
  error.value = null;
  downloadedFile.value = null;

  try {
    const result = await authorizedRequest((token) => api.value.download(props.projectId, token));
    saveBlob(result.blob, result.fileName);
    downloadedFile.value = result.fileName;
  } catch (failure) {
    error.value =
      failure instanceof Error && failure.message.length > 0
        ? failure.message
        : copy.value.downloadError;
  } finally {
    busy.value = false;
  }
}
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
      <div class="mt-5 flex flex-wrap items-center gap-3">
        <UiButton :disabled="busy" data-testid="download-package" @click="download">
          {{ busy ? copy.downloading : copy.download }}
        </UiButton>
        <p
          v-if="downloadedFile"
          class="m-0 text-sm text-ink-2"
          data-testid="download-done"
          aria-live="polite"
        >
          {{ fill(copy.downloaded, { file: downloadedFile }) }}
        </p>
      </div>
      <p
        v-if="error"
        class="mt-4 rounded-panel border border-fail-line bg-fail-bg p-4 font-semibold text-fail-dark"
        role="alert"
        data-testid="download-error"
      >
        {{ error }}
      </p>
    </header>

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
                : fill(copy.version, { number: stage.version })
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
      <p class="mt-3 text-sm leading-6 text-ink-2">{{ copy.nextText }}</p>
    </section>
  </section>
</template>
