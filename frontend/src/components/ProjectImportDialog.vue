<script setup lang="ts">
import { computed, ref, useId } from "vue";

import UiButton from "./UiButton.vue";

import { apiClient } from "@/api/client";
import {
  ProjectImportsApiError,
  projectImportsApi,
  type ProjectImportsApi,
} from "@/api/projectImports";
import { useAuthStore } from "@/stores/auth";
import type { AuthorizedRequest } from "@/stores/requirements";
import type { ProjectImportPayload } from "@/types/projectImports";

type Locale = "en" | "it";

interface ImportFailure {
  code: string | null;
  location: string | null;
}

const MAX_ARCHIVE_SIZE = 16 * 1024 * 1024;
const NAME_LIMIT = 120;
const MOCKUP_LOCATION = "design: package.generated_mockup";

const props = withDefaults(
  defineProps<{
    locale?: Locale;
    authorize?: AuthorizedRequest | undefined;
    api?: ProjectImportsApi | undefined;
  }>(),
  {
    locale: "en",
    authorize: undefined,
    api: undefined,
  },
);

const emit = defineEmits<{ imported: [payload: ProjectImportPayload]; cancel: [] }>();

const messages = {
  en: {
    dropBefore: "Drag the .zip archive of the knowledge folder here, or ",
    dropChoose: "choose it from your computer",
    dropAfter: ".",
    chosen: "Chosen archive: {file}",
    name: "Name of the new project (optional)",
    nameHint: "Leave it empty to keep the name of the original project.",
    submit: "Create the project",
    cancel: "Cancel",
    running: "Reading the folder and creating the project…",
    failed: "The project could not be created. Try again.",
    tamperedFile: "The file {file} was changed after the export, so the folder cannot be trusted.",
    mockupRefused:
      "The mockup inside this folder contains something that the Studio does not accept, so the folder was not imported.",
    errors: {
      FOLDER_ARCHIVE_TOO_LARGE: "The archive is larger than 16 MB, the most the Studio accepts.",
      FOLDER_ARCHIVE_INVALID:
        "This file is not a knowledge folder of the Studio. Choose the .zip archive that you downloaded at the end of a project.",
      FOLDER_DOCUMENT_MISSING:
        "Some files of the folder are missing, so a project cannot start from it. Export the folder again from the Studio.",
      FOLDER_DOCUMENT_INVALID:
        "Some files of the folder cannot be read, so a project cannot start from it. Export the folder again from the Studio.",
      FOLDER_SCHEMA_UNSUPPORTED:
        "This folder was written by another version of the Studio, so it cannot be read here.",
      FOLDER_TAMPERED:
        "A file of the folder was changed after the export, so the folder cannot be trusted.",
      FOLDER_INCONSISTENT:
        "The parts of this folder do not belong together, so a project cannot start from it. Export the folder again from the Studio.",
      PROJECT_NAME_INVALID:
        "The name of the new project is not valid. Use at most 120 characters, or leave it empty.",
      PROJECT_IMPORT_REJECTED:
        "The project could not be created from this folder. Try again; if it happens again, export the folder again from the Studio.",
    },
    details: "Details",
  },
  it: {
    dropBefore: "Trascina qui l'archivio .zip della cartella di conoscenza, oppure ",
    dropChoose: "sceglilo dal computer",
    dropAfter: ".",
    chosen: "Archivio scelto: {file}",
    name: "Nome del nuovo progetto (facoltativo)",
    nameHint: "Lascialo vuoto per tenere il nome del progetto originale.",
    submit: "Crea il progetto",
    cancel: "Annulla",
    running: "Leggo la cartella e creo il progetto…",
    failed: "Non è stato possibile creare il progetto. Riprova.",
    tamperedFile:
      "Il file {file} è stato modificato dopo l'esportazione, quindi la cartella non è affidabile.",
    mockupRefused:
      "Il mockup dentro questa cartella contiene qualcosa che lo Studio non accetta, quindi la cartella non è stata importata.",
    errors: {
      FOLDER_ARCHIVE_TOO_LARGE: "L'archivio supera i 16 MB, il massimo che lo Studio accetta.",
      FOLDER_ARCHIVE_INVALID:
        "Questo file non è una cartella di conoscenza dello Studio. Scegli l'archivio .zip che hai scaricato alla fine di un progetto.",
      FOLDER_DOCUMENT_MISSING:
        "Mancano alcuni file della cartella, quindi non può nascerne un progetto. Esporta di nuovo la cartella dallo Studio.",
      FOLDER_DOCUMENT_INVALID:
        "Alcuni file della cartella non si possono leggere, quindi non può nascerne un progetto. Esporta di nuovo la cartella dallo Studio.",
      FOLDER_SCHEMA_UNSUPPORTED:
        "Questa cartella è stata scritta da un'altra versione dello Studio, quindi qui non si può leggere.",
      FOLDER_TAMPERED:
        "Un file della cartella è stato modificato dopo l'esportazione, quindi la cartella non è affidabile.",
      FOLDER_INCONSISTENT:
        "Le parti di questa cartella non appartengono allo stesso progetto approvato, quindi non può nascerne un progetto. Esporta di nuovo la cartella dallo Studio.",
      PROJECT_NAME_INVALID:
        "Il nome del nuovo progetto non è valido. Usa al massimo 120 caratteri, oppure lascialo vuoto.",
      PROJECT_IMPORT_REJECTED:
        "Non è stato possibile creare il progetto da questa cartella. Riprova; se succede di nuovo, esporta di nuovo la cartella dallo Studio.",
    },
    details: "Dettagli",
  },
} as const;

const auth = useAuthStore();
const id = useId();
const fileId = `project-import-file-${id}`;
const nameId = `project-import-name-${id}`;
const hintId = `project-import-hint-${id}`;
const copy = computed(() => messages[props.locale]);
const api = computed(() => props.api ?? projectImportsApi);
const file = ref<File | null>(null);
const name = ref("");
const busy = ref(false);
const dragging = ref(false);
const failure = ref<ImportFailure | null>(null);

const failureText = computed(() => {
  const current = failure.value;
  if (current === null) return "";
  if (current.code === "FOLDER_TAMPERED" && current.location) {
    return fill(copy.value.tamperedFile, { file: current.location });
  }
  if (
    current.code === "FOLDER_DOCUMENT_INVALID" &&
    current.location?.startsWith(MOCKUP_LOCATION) === true
  ) {
    return copy.value.mockupRefused;
  }
  const errors: Record<string, string> = copy.value.errors;
  const code = current.code;
  return (
    (code !== null && Object.hasOwn(errors, code) ? errors[code] : undefined) ?? copy.value.failed
  );
});
const failureDetail = computed(() =>
  [failure.value?.code, failure.value?.location].filter(Boolean).join(" · "),
);
const dropClasses = computed(() => [
  "block cursor-pointer rounded-panel border-[1.5px] px-5 py-[22px] text-center text-sm leading-normal text-ink-3 transition-colors duration-150 peer-focus-visible:outline-3 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-action peer-disabled:cursor-not-allowed peer-disabled:opacity-60",
  dragging.value
    ? "border-dashed border-action bg-action-soft"
    : file.value !== null
      ? "border-solid border-action bg-action-soft/50"
      : "border-dashed border-line-strong hover:border-action/60",
]);

defineExpose({ busy });

function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_match, key: string) => String(values[key] ?? ""));
}

function authorizedRequest<T>(operation: (accessToken: string) => Promise<T>): Promise<T> {
  return props.authorize ? props.authorize(operation) : auth.withAccessToken(apiClient, operation);
}

function failureOf(error: unknown): ImportFailure {
  if (error instanceof ProjectImportsApiError) {
    return { code: error.code, location: error.location };
  }
  return { code: null, location: null };
}

function accept(chosen: File | null): boolean {
  failure.value = null;
  if (chosen !== null && chosen.size > MAX_ARCHIVE_SIZE) {
    file.value = null;
    failure.value = { code: "FOLDER_ARCHIVE_TOO_LARGE", location: null };
    return false;
  }
  file.value = chosen;
  return true;
}

function chooseFile(event: Event): void {
  const input = event.target as HTMLInputElement;
  if (!accept(input.files?.[0] ?? null)) {
    input.value = "";
  }
}

function dragOver(): void {
  if (!busy.value) dragging.value = true;
}

function dragLeave(event: DragEvent): void {
  const zone = event.currentTarget as HTMLElement | null;
  if (zone !== null && event.relatedTarget instanceof Node && zone.contains(event.relatedTarget)) {
    return;
  }
  dragging.value = false;
}

function drop(event: DragEvent): void {
  dragging.value = false;
  const dropped = event.dataTransfer?.files?.[0] ?? null;
  if (busy.value || dropped === null) return;
  accept(dropped);
}

async function submit(): Promise<void> {
  const chosen = file.value;
  if (chosen === null || busy.value) return;
  const displayName = name.value.trim();
  busy.value = true;
  failure.value = null;
  try {
    const payload = await authorizedRequest((token) =>
      api.value.importArchive(
        chosen,
        chosen.name,
        displayName.length > 0 ? displayName : null,
        token,
      ),
    );
    emit("imported", payload);
  } catch (error) {
    failure.value = failureOf(error);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <form class="flex flex-col gap-5" data-testid="project-import-dialog" @submit.prevent="submit">
    <div>
      <input
        :id="fileId"
        type="file"
        accept=".zip"
        class="peer sr-only"
        :disabled="busy"
        data-testid="project-import-file"
        @change="chooseFile"
      />
      <label
        :for="fileId"
        :class="dropClasses"
        :data-dragging="dragging ? 'true' : undefined"
        data-testid="project-import-drop"
        @dragenter.prevent="dragOver"
        @dragover.prevent="dragOver"
        @dragleave="dragLeave"
        @drop.prevent="drop"
      >
        <span class="block"
          >{{ copy.dropBefore
          }}<span class="font-semibold text-action underline underline-offset-[3px]">{{
            copy.dropChoose
          }}</span
          >{{ copy.dropAfter }}</span
        >
        <span
          v-if="file"
          class="mt-2 block font-semibold break-all text-ink"
          data-testid="project-import-chosen"
        >
          {{ fill(copy.chosen, { file: file.name }) }}
        </span>
      </label>
    </div>

    <div class="flex flex-col gap-2">
      <label class="text-sm font-semibold" :for="nameId">{{ copy.name }}</label>
      <input
        :id="nameId"
        v-model="name"
        type="text"
        :maxlength="NAME_LIMIT"
        autocomplete="off"
        class="h-12 rounded-control border border-field bg-surface px-3.5 text-base text-ink disabled:bg-surface-3"
        :aria-describedby="hintId"
        :disabled="busy"
        data-testid="project-import-name"
      />
      <p :id="hintId" class="m-0 text-xs text-ink-3">{{ copy.nameHint }}</p>
    </div>

    <p
      v-if="busy"
      class="m-0 text-sm font-semibold text-ink-2"
      role="status"
      data-testid="project-import-running"
    >
      {{ copy.running }}
    </p>

    <div
      v-if="failure"
      class="grid gap-1 rounded-panel border border-fail-line bg-fail-bg p-3 text-sm text-fail-dark"
      role="alert"
      data-testid="project-import-error"
    >
      <p class="m-0 font-semibold">{{ failureText }}</p>
      <details v-if="failureDetail" class="text-xs">
        <summary class="cursor-pointer">{{ copy.details }}</summary>
        <code class="break-all">{{ failureDetail }}</code>
      </details>
    </div>

    <div class="flex flex-wrap justify-end gap-2.5">
      <UiButton
        variant="secondary"
        :disabled="busy"
        data-testid="project-import-cancel"
        @click="emit('cancel')"
      >
        {{ copy.cancel }}
      </UiButton>
      <UiButton type="submit" :disabled="file === null || busy" data-testid="project-import-submit">
        {{ copy.submit }}
      </UiButton>
    </div>
  </form>
</template>
