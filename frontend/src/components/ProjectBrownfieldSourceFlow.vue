<script setup lang="ts">
import { computed, ref, watch } from "vue";

import { apiClient } from "@/api/client";
import { executionApi, type ExecutionApi } from "../api/execution";
import { useAuthStore } from "../stores/auth";
import { type AuthorizedRequest, useExecutionStore } from "../stores/execution";
import type {
  ExecutionCapabilityStatus,
  ExecutionTarget,
  JsonValue,
  SourceArchiveUploadOptions,
} from "../types/execution";

type Locale = "en" | "it";
type InventoryFilter = "ALL" | "INCLUDE" | "IGNORE";
type JsonRecord = Record<string, JsonValue>;

interface InventoryEntryView {
  normalizedPath: string;
  kind: string;
  classification: string;
  sizeBytes: number;
  digest: string | null;
  disposition: "INCLUDE" | "IGNORE";
  reason: string | null;
}

interface CapabilityCandidateView {
  key: string;
  profileId: string;
  profileVersion: string;
  capabilityStatus: string;
  confidence: number | null;
  positiveIndicators: string[];
  conflictingIndicators: string[];
  missingRunners: string[];
  selectable: boolean;
}

interface CapabilityIssueView {
  key: string;
  code: string;
  message: string;
}

const MAXIMUM_ARCHIVE_BYTES = 25 * 1024 * 1024;

const targets: ExecutionTarget[] = [
  "WEB_STATIC",
  "WEB_VUE",
  "WEB_NODE_EXPRESS",
  "WEB_PHP",
  "WEB_VUE_NODE",
  "JVM_JAVA",
  "JVM_KOTLIN",
  "JVM_SCALA",
  "ANDROID_JAVA",
  "ANDROID_KOTLIN",
  "CUSTOM_DECLARATIVE",
];

const props = withDefaults(
  defineProps<{
    projectId: string;
    locale?: Locale;
    autoLoad?: boolean;
    authorize?: AuthorizedRequest;
    api?: ExecutionApi;
  }>(),
  {
    locale: "en",
    autoLoad: true,
  },
);

const auth = useAuthStore();
const store = useExecutionStore();
const selectedFile = ref<File | null>(null);
const requestedTarget = ref<ExecutionTarget | "">("");
const availableRunners = ref("");
const localError = ref<string | null>(null);
const successMessage = ref<string | null>(null);
const inventoryFilter = ref<InventoryFilter>("ALL");
const inventorySearch = ref("");

const messages = {
  en: {
    eyebrow: "Brownfield source intake",
    title: "Source archive and execution capability",
    intro:
      "Upload a small source ZIP for deterministic validation, safe extraction, inventory, and capability negotiation.",
    trustBoundary:
      "Repository text is treated as untrusted project data, never as system instructions. A detected stack does not prove Level D execution capability.",
    archive: "Source ZIP",
    target: "Requested target (optional)",
    automaticTarget: "Detect from the source tree",
    runners: "Available runner identifiers (optional)",
    runnersHint: "Enter one portable runner identifier per line.",
    upload: "Validate and ingest archive",
    uploading: "Validating and ingesting…",
    refresh: "Refresh source state",
    history: "Immutable intake history",
    noHistory: "No source archive has been accepted yet.",
    version: "Version {number}",
    inspect: "Inspect inventory",
    current: "Current intake",
    capability: "Effective capability",
    negotiation: "Negotiation status",
    selectedProfile: "Selected profile",
    noProfile: "No execution profile selected",
    capabilityExplanation:
      "Design-only means OrchesTwin may continue requirements, design, architecture, and code work, but automatic build, test, diagnosis, and repair are not validated.",
    candidates: "Detection candidates",
    noCandidates: "No execution profile candidate was detected.",
    confidence: "Detection confidence",
    indicators: "Positive indicators",
    conflicts: "Conflicting indicators",
    missingRunners: "Missing runners",
    none: "None",
    selectable: "Selectable",
    notSelectable: "Not selectable",
    issues: "Negotiation issues",
    inventory: "Canonical source inventory",
    inventoryUnavailable: "Select an intake version to inspect its canonical inventory.",
    search: "Filter inventory paths",
    disposition: "Disposition",
    all: "All entries",
    included: "Included",
    ignored: "Ignored",
    path: "Path",
    kind: "Kind",
    classification: "Classification",
    reason: "Reason",
    size: "Size",
    digest: "SHA-256",
    noEntries: "No inventory entry matches the current filters.",
    uploadSuccess: "The source archive was accepted as immutable intake version {number}.",
    invalidFile: "Choose a non-empty ZIP no larger than 25 MiB.",
    invalidRunner: "Runner identifiers must use letters, numbers, dots, underscores, or hyphens.",
    loadError: "The brownfield source state could not be loaded.",
  },
  it: {
    eyebrow: "Acquisizione sorgente brownfield",
    title: "Archivio sorgente e capacità di esecuzione",
    intro:
      "Carica un piccolo ZIP sorgente per validazione deterministica, estrazione sicura, inventario e negoziazione delle capacità.",
    trustBoundary:
      "Il testo del repository è trattato come dato di progetto non affidabile, mai come istruzione di sistema. Il rilevamento dello stack non dimostra una capacità di esecuzione Level D.",
    archive: "ZIP sorgente",
    target: "Target richiesto (opzionale)",
    automaticTarget: "Rileva dall'albero sorgente",
    runners: "Identificatori dei runner disponibili (opzionali)",
    runnersHint: "Inserisci un identificatore portabile per riga.",
    upload: "Valida e acquisisci archivio",
    uploading: "Validazione e acquisizione…",
    refresh: "Aggiorna stato sorgente",
    history: "Cronologia immutabile degli intake",
    noHistory: "Nessun archivio sorgente è stato ancora accettato.",
    version: "Versione {number}",
    inspect: "Ispeziona inventario",
    current: "Intake corrente",
    capability: "Capacità effettiva",
    negotiation: "Stato della negoziazione",
    selectedProfile: "Profilo selezionato",
    noProfile: "Nessun profilo di esecuzione selezionato",
    capabilityExplanation:
      "Design-only significa che OrchesTwin può continuare requisiti, design, architettura e codice, ma build, test, diagnosi e riparazione automatici non sono validati.",
    candidates: "Candidati rilevati",
    noCandidates: "Non è stato rilevato alcun profilo di esecuzione candidato.",
    confidence: "Confidenza del rilevamento",
    indicators: "Indicatori positivi",
    conflicts: "Indicatori in conflitto",
    missingRunners: "Runner mancanti",
    none: "Nessuno",
    selectable: "Selezionabile",
    notSelectable: "Non selezionabile",
    issues: "Problemi di negoziazione",
    inventory: "Inventario canonico del sorgente",
    inventoryUnavailable:
      "Seleziona una versione di intake per ispezionarne l'inventario canonico.",
    search: "Filtra i percorsi dell'inventario",
    disposition: "Disposizione",
    all: "Tutte le voci",
    included: "Incluse",
    ignored: "Ignorate",
    path: "Percorso",
    kind: "Tipo",
    classification: "Classificazione",
    reason: "Motivo",
    size: "Dimensione",
    digest: "SHA-256",
    noEntries: "Nessuna voce corrisponde ai filtri correnti.",
    uploadSuccess: "L'archivio sorgente è stato accettato come versione immutabile {number}.",
    invalidFile: "Seleziona uno ZIP non vuoto e non superiore a 25 MiB.",
    invalidRunner:
      "Gli identificatori dei runner possono contenere lettere, numeri, punti, underscore o trattini.",
    loadError: "Non è stato possibile caricare lo stato del sorgente brownfield.",
  },
} as const;

const copy = computed(() => messages[props.locale]);
const api = computed(() => props.api ?? executionApi);
const currentIntake = computed(() => store.currentIntake);
const capabilityStatus = computed(
  () => store.capability?.intake.effective_capability_status ?? null,
);
const negotiationStatus = computed(() => store.capability?.intake.capability_status ?? null);
const selectedProfile = computed(() => store.capability?.intake.selected_profile_reference ?? null);
const inventoryEntries = computed(() =>
  recordArray(store.inventory?.inventory["entries"]).map(parseInventoryEntry).filter(isDefined),
);
const visibleInventoryEntries = computed(() => {
  const query = inventorySearch.value.trim().toLocaleLowerCase();

  return inventoryEntries.value.filter((entry) => {
    const matchesDisposition =
      inventoryFilter.value === "ALL" || entry.disposition === inventoryFilter.value;
    const matchesQuery =
      query.length === 0 || entry.normalizedPath.toLocaleLowerCase().includes(query);
    return matchesDisposition && matchesQuery;
  });
});
const capabilityCandidates = computed(() =>
  recordArray(store.capability?.capability["candidates"])
    .map(parseCapabilityCandidate)
    .filter(isDefined),
);
const capabilityIssues = computed(() =>
  recordArray(store.capability?.capability["issues"]).map(parseCapabilityIssue).filter(isDefined),
);

function isDefined<T>(value: T | null): value is T {
  return value !== null;
}

function jsonRecord(value: JsonValue | undefined): JsonRecord | null {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value : null;
}

function recordArray(value: JsonValue | undefined): JsonRecord[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.map((item) => jsonRecord(item)).filter(isDefined);
}

function stringValue(record: JsonRecord | null, key: string): string | null {
  const value = record?.[key];
  return typeof value === "string" ? value : null;
}

function numberValue(record: JsonRecord | null, key: string): number | null {
  const value = record?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function booleanValue(record: JsonRecord | null, key: string): boolean {
  return record?.[key] === true;
}

function stringArray(record: JsonRecord | null, key: string): string[] {
  const value = record?.[key];
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function parseInventoryEntry(record: JsonRecord): InventoryEntryView | null {
  const normalizedPath = stringValue(record, "normalized_path");
  const disposition = stringValue(record, "disposition");

  if (normalizedPath === null || (disposition !== "INCLUDE" && disposition !== "IGNORE")) {
    return null;
  }

  return {
    normalizedPath,
    kind: stringValue(record, "kind") ?? "UNKNOWN",
    classification: stringValue(record, "classification") ?? "UNKNOWN",
    sizeBytes: numberValue(record, "size_bytes") ?? 0,
    digest: stringValue(record, "sha256_digest"),
    disposition,
    reason: stringValue(record, "disposition_reason"),
  };
}

function parseCapabilityCandidate(record: JsonRecord): CapabilityCandidateView | null {
  const reference = jsonRecord(record["profile_reference"]);
  const detection = jsonRecord(record["detection"]);
  const profileId = stringValue(reference, "profile_id");
  const profileVersion = stringValue(reference, "profile_version");

  if (profileId === null || profileVersion === null) {
    return null;
  }

  return {
    key: `${profileId}:${profileVersion}:${stringValue(reference, "content_hash") ?? ""}`,
    profileId,
    profileVersion,
    capabilityStatus: stringValue(record, "capability_status") ?? "DESIGN_ONLY_LEVEL_C",
    confidence: numberValue(detection, "confidence"),
    positiveIndicators: stringArray(detection, "positive_indicators"),
    conflictingIndicators: stringArray(detection, "conflicting_indicators"),
    missingRunners: stringArray(record, "missing_runners"),
    selectable: booleanValue(record, "selectable"),
  };
}

function parseCapabilityIssue(record: JsonRecord): CapabilityIssueView | null {
  const code = stringValue(record, "code");
  const message = stringValue(record, "message");

  return code === null || message === null ? null : { key: `${code}:${message}`, code, message };
}

function capabilityClass(status: ExecutionCapabilityStatus | null): string {
  const classes: Record<ExecutionCapabilityStatus, string> = {
    VALIDATED_LEVEL_D: "border-emerald-300 bg-emerald-50 text-emerald-900",
    EXPERIMENTAL_LEVEL_D: "border-amber-300 bg-amber-50 text-amber-950",
    DESIGN_ONLY_LEVEL_C: "border-slate-300 bg-slate-100 text-slate-900",
  };

  return status === null ? classes.DESIGN_ONLY_LEVEL_C : classes[status];
}

function formatBytes(value: number): string {
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KiB`;
  }
  return `${(value / (1024 * 1024)).toFixed(1)} MiB`;
}

function normalizedRunners(): string[] | null {
  const values = availableRunners.value
    .split(/\r?\n/u)
    .map((value) => value.trim())
    .filter((value) => value.length > 0);
  const unique = [...new Set(values)].sort();
  const pattern = /^[A-Za-z][A-Za-z0-9]*(?:[._-][A-Za-z0-9]+)*$/u;

  return unique.every((value) => pattern.test(value)) ? unique : null;
}

function authorizedRequest<T>(operation: (accessToken: string) => Promise<T>): Promise<T> {
  if (props.authorize !== undefined) {
    return props.authorize(operation);
  }
  return auth.withAccessToken(apiClient, operation);
}

async function run(operation: () => Promise<unknown>): Promise<boolean> {
  localError.value = null;

  try {
    await operation();
    return true;
  } catch (error) {
    localError.value = error instanceof Error ? error.message : copy.value.loadError;
    return false;
  }
}

async function load(): Promise<void> {
  if (props.projectId.trim().length === 0) {
    return;
  }
  successMessage.value = null;
  await run(() => store.load(props.projectId, authorizedRequest, api.value));
}

async function inspectInventory(intakeId: string): Promise<void> {
  await run(() => store.loadInventory(props.projectId, intakeId, authorizedRequest, api.value));
}

function selectArchive(event: Event): void {
  const input = event.target as HTMLInputElement;
  selectedFile.value = input.files?.[0] ?? null;
  localError.value = null;
  successMessage.value = null;
}

async function upload(): Promise<void> {
  const archive = selectedFile.value;
  const runners = normalizedRunners();

  if (
    archive === null ||
    archive.size < 1 ||
    archive.size > MAXIMUM_ARCHIVE_BYTES ||
    !archive.name.toLocaleLowerCase().endsWith(".zip")
  ) {
    localError.value = copy.value.invalidFile;
    return;
  }
  if (runners === null) {
    localError.value = copy.value.invalidRunner;
    return;
  }

  const options: SourceArchiveUploadOptions = {};
  if (requestedTarget.value !== "") {
    options.requestedTarget = requestedTarget.value;
  }
  if (runners.length > 0) {
    options.availableRunners = runners;
  }

  const succeeded = await run(async () => {
    const intake = await store.uploadSourceArchive(
      props.projectId,
      archive,
      options,
      authorizedRequest,
      api.value,
    );
    successMessage.value = copy.value.uploadSuccess.replace(
      "{number}",
      String(intake.version_number),
    );
  });

  if (succeeded) {
    selectedFile.value = null;
  }
}

watch(
  () => props.projectId,
  async () => {
    if (props.autoLoad) {
      await load();
    }
  },
  { immediate: true },
);
</script>

<template>
  <section class="grid gap-6" aria-labelledby="brownfield-source-title">
    <header class="grid gap-2">
      <p class="m-0 text-sm font-bold tracking-wide text-indigo-700 uppercase">
        {{ copy.eyebrow }}
      </p>
      <h2 id="brownfield-source-title" class="text-2xl font-black text-slate-950">
        {{ copy.title }}
      </h2>
      <p class="m-0 max-w-4xl text-slate-700">{{ copy.intro }}</p>
      <p class="m-0 rounded-xl border border-indigo-200 bg-indigo-50 p-4 text-sm text-indigo-950">
        {{ copy.trustBoundary }}
      </p>
    </header>

    <p
      v-if="localError !== null"
      class="m-0 rounded-xl border border-red-200 bg-red-50 p-4 text-red-900"
      role="alert"
    >
      {{ localError }}
    </p>
    <p
      v-if="successMessage !== null"
      class="m-0 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-emerald-950"
      role="status"
    >
      {{ successMessage }}
    </p>

    <form
      class="grid gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
      @submit.prevent="upload"
    >
      <div class="grid gap-2">
        <label for="brownfield-archive" class="font-bold text-slate-900">{{ copy.archive }}</label>
        <input
          id="brownfield-archive"
          type="file"
          accept=".zip,application/zip"
          class="rounded-lg border border-slate-300 p-3"
          @change="selectArchive"
        />
      </div>

      <div class="grid gap-2 sm:grid-cols-2">
        <div class="grid gap-2">
          <label for="brownfield-target" class="font-bold text-slate-900">{{ copy.target }}</label>
          <select
            id="brownfield-target"
            v-model="requestedTarget"
            class="rounded-lg border border-slate-300 bg-white p-3"
          >
            <option value="">{{ copy.automaticTarget }}</option>
            <option v-for="target in targets" :key="target" :value="target">{{ target }}</option>
          </select>
        </div>
        <div class="grid gap-2">
          <label for="brownfield-runners" class="font-bold text-slate-900">{{
            copy.runners
          }}</label>
          <textarea
            id="brownfield-runners"
            v-model="availableRunners"
            rows="3"
            class="rounded-lg border border-slate-300 p-3"
            :aria-describedby="`${props.projectId}-runner-hint`"
          />
          <p :id="`${props.projectId}-runner-hint`" class="m-0 text-sm text-slate-600">
            {{ copy.runnersHint }}
          </p>
        </div>
      </div>

      <div class="flex flex-wrap gap-3">
        <button
          type="submit"
          class="rounded-lg bg-slate-950 px-4 py-3 font-bold text-white disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="store.pending.upload"
        >
          {{ store.pending.upload ? copy.uploading : copy.upload }}
        </button>
        <button
          type="button"
          class="rounded-lg border border-slate-300 px-4 py-3 font-bold text-slate-900"
          :disabled="store.pending.load"
          @click="load"
        >
          {{ copy.refresh }}
        </button>
      </div>
    </form>

    <section class="grid gap-4" aria-labelledby="brownfield-history-title">
      <h3 id="brownfield-history-title" class="text-xl font-black text-slate-950">
        {{ copy.history }}
      </h3>
      <ol v-if="store.intakes.length > 0" class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <li
          v-for="intake in store.intakes"
          :key="intake.id"
          class="grid gap-2 rounded-xl border border-slate-200 bg-slate-50 p-4"
        >
          <strong>{{ copy.version.replace("{number}", String(intake.version_number)) }}</strong>
          <span class="text-sm text-slate-700">{{ intake.effective_capability_status }}</span>
          <code class="text-xs break-all text-slate-500">{{ intake.content_hash }}</code>
          <button
            type="button"
            class="justify-self-start rounded-lg border border-slate-300 bg-white px-3 py-2 font-bold"
            :disabled="store.pending['load-inventory']"
            @click="inspectInventory(intake.id)"
          >
            {{ copy.inspect }}
          </button>
        </li>
      </ol>
      <p v-else class="m-0 text-slate-600">{{ copy.noHistory }}</p>
    </section>

    <section
      v-if="currentIntake !== null"
      class="grid gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
      aria-labelledby="brownfield-capability-title"
    >
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div class="grid gap-1">
          <p class="m-0 text-sm font-bold text-slate-600">{{ copy.current }}</p>
          <h3 id="brownfield-capability-title" class="text-xl font-black text-slate-950">
            {{ copy.capability }}
          </h3>
        </div>
        <span
          class="rounded-full border px-3 py-1 text-sm font-black"
          :class="capabilityClass(capabilityStatus)"
        >
          {{ capabilityStatus ?? "DESIGN_ONLY_LEVEL_C" }}
        </span>
      </div>

      <dl class="grid gap-3 sm:grid-cols-2">
        <div class="grid gap-1">
          <dt class="font-bold">{{ copy.negotiation }}</dt>
          <dd class="m-0 break-all">{{ negotiationStatus }}</dd>
        </div>
        <div class="grid gap-1">
          <dt class="font-bold">{{ copy.selectedProfile }}</dt>
          <dd class="m-0 break-all">
            {{
              selectedProfile === null
                ? copy.noProfile
                : `${selectedProfile.profile_id} · ${selectedProfile.profile_version}`
            }}
          </dd>
        </div>
      </dl>
      <p class="m-0 text-sm text-slate-700">{{ copy.capabilityExplanation }}</p>

      <div class="grid gap-3">
        <h4 class="font-black text-slate-950">{{ copy.candidates }}</h4>
        <ul v-if="capabilityCandidates.length > 0" class="grid gap-3 lg:grid-cols-2">
          <li
            v-for="candidate in capabilityCandidates"
            :key="candidate.key"
            class="grid gap-2 rounded-xl border border-slate-200 p-4"
          >
            <strong>{{ candidate.profileId }} · {{ candidate.profileVersion }}</strong>
            <span>{{ candidate.capabilityStatus }}</span>
            <span>{{ copy.confidence }}: {{ candidate.confidence ?? copy.none }}</span>
            <span>{{ candidate.selectable ? copy.selectable : copy.notSelectable }}</span>
            <span
              >{{ copy.indicators }}:
              {{ candidate.positiveIndicators.join(", ") || copy.none }}</span
            >
            <span
              >{{ copy.conflicts }}:
              {{ candidate.conflictingIndicators.join(", ") || copy.none }}</span
            >
            <span
              >{{ copy.missingRunners }}:
              {{ candidate.missingRunners.join(", ") || copy.none }}</span
            >
          </li>
        </ul>
        <p v-else class="m-0 text-slate-600">{{ copy.noCandidates }}</p>
      </div>

      <div v-if="capabilityIssues.length > 0" class="grid gap-2">
        <h4 class="font-black text-slate-950">{{ copy.issues }}</h4>
        <ul class="grid gap-2">
          <li
            v-for="issue in capabilityIssues"
            :key="issue.key"
            class="rounded-lg border border-amber-200 bg-amber-50 p-3 text-amber-950"
          >
            <strong>{{ issue.code }}</strong
            >: {{ issue.message }}
          </li>
        </ul>
      </div>
    </section>

    <section class="grid gap-4" aria-labelledby="brownfield-inventory-title">
      <h3 id="brownfield-inventory-title" class="text-xl font-black text-slate-950">
        {{ copy.inventory }}
      </h3>
      <template v-if="store.inventory !== null">
        <div class="grid gap-3 sm:grid-cols-2">
          <div class="grid gap-2">
            <label for="inventory-search" class="font-bold">{{ copy.search }}</label
            ><input
              id="inventory-search"
              v-model="inventorySearch"
              type="search"
              class="rounded-lg border border-slate-300 p-3"
            />
          </div>
          <div class="grid gap-2">
            <label for="inventory-disposition" class="font-bold">{{ copy.disposition }}</label
            ><select
              id="inventory-disposition"
              v-model="inventoryFilter"
              class="rounded-lg border border-slate-300 bg-white p-3"
            >
              <option value="ALL">{{ copy.all }}</option>
              <option value="INCLUDE">{{ copy.included }}</option>
              <option value="IGNORE">{{ copy.ignored }}</option>
            </select>
          </div>
        </div>
        <div class="overflow-x-auto rounded-xl border border-slate-200">
          <table class="min-w-full border-collapse text-left text-sm">
            <thead class="bg-slate-100">
              <tr>
                <th class="p-3">{{ copy.path }}</th>
                <th class="p-3">{{ copy.classification }}</th>
                <th class="p-3">{{ copy.kind }}</th>
                <th class="p-3">{{ copy.disposition }}</th>
                <th class="p-3">{{ copy.reason }}</th>
                <th class="p-3">{{ copy.size }}</th>
                <th class="p-3">{{ copy.digest }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="entry in visibleInventoryEntries"
                :key="entry.normalizedPath"
                class="border-t border-slate-200"
              >
                <td class="p-3 font-semibold">{{ entry.normalizedPath }}</td>
                <td class="p-3">{{ entry.classification }}</td>
                <td class="p-3">{{ entry.kind }}</td>
                <td class="p-3">{{ entry.disposition }}</td>
                <td class="p-3">{{ entry.reason ?? copy.none }}</td>
                <td class="p-3">{{ formatBytes(entry.sizeBytes) }}</td>
                <td class="p-3">
                  <code class="text-xs break-all">{{ entry.digest ?? copy.none }}</code>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="visibleInventoryEntries.length === 0" class="m-0 text-slate-600">
          {{ copy.noEntries }}
        </p>
      </template>
      <p v-else class="m-0 text-slate-600">{{ copy.inventoryUnavailable }}</p>
    </section>
  </section>
</template>
