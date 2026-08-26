<script setup lang="ts">
import { computed, ref, watch } from "vue";

import { apiClient } from "@/api/client";
import { executionApi, type ExecutionApi } from "../api/execution";
import { useAuthStore } from "../stores/auth";
import { type AuthorizedRequest, useExecutionStore } from "../stores/execution";
import type {
  HighImpactDecisionInput,
  HighImpactOperationPayload,
  HumanGateAction,
  JsonValue,
  SandboxRunPayload,
} from "../types/execution";

type Locale = "en" | "it";
type JsonRecord = Record<string, JsonValue>;
type DecisionAction = Exclude<HumanGateAction, "SUBMIT">;

interface LogReferenceView {
  commandId: string;
  stream: "stdout" | "stderr";
  storageKey: string;
  digest: string;
  sizeBytes: number | null;
}

interface ClassificationReasonView {
  key: string;
  code: string;
  message: string;
}

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
const localError = ref<string | null>(null);
const selectedRunId = ref<string | null>(null);
const selectedRequestId = ref<string | null>(null);
const decisionReason = ref("");

const messages = {
  en: {
    eyebrow: "Execution evidence · Gate 7",
    title: "Sandbox evidence and high-impact governance",
    intro:
      "Inspect declared capabilities, immutable sandbox evidence, and owner decisions for exact high-impact operation versions.",
    methodology:
      "Gate 7 approves one exact request version and content hash. It cannot authorize forbidden operations, arbitrary host commands, privileged containers, Docker socket mounts, or host filesystem access.",
    refresh: "Refresh execution state",
    profiles: "Execution profiles",
    noProfiles: "No execution profile is registered.",
    status: "Status",
    targets: "Targets",
    runners: "Required runners",
    images: "Base images",
    approval: "Owner approval",
    required: "Required",
    notRequired: "Not required",
    evidence: "Validation evidence",
    noEvidence: "No Level D validation evidence is registered.",
    runs: "Sandbox runs",
    noRuns: "No sandbox run evidence has been recorded.",
    inspectRun: "Inspect run evidence",
    recorded: "Recorded",
    plan: "Plan",
    image: "Container image",
    runtime: "Runtime",
    failure: "Failure",
    commands: "Command evidence",
    command: "Command",
    exitCode: "Exit code",
    parser: "Parser",
    artifacts: "Artifacts",
    logs: "Raw log references",
    stream: "Stream",
    storageKey: "Storage key",
    digest: "SHA-256",
    size: "Bytes",
    noLogs: "No raw log reference is available for the selected run.",
    operations: "High-impact operation history",
    noOperations: "No high-impact operation request exists.",
    classification: "Classification",
    reasons: "Classification reasons",
    review: "Review Gate 7",
    exactReference: "Exact request reference",
    readiness: "Approval readiness",
    gateStatus: "Gate status",
    eventHistory: "Gate 7 audit events",
    noEvents: "No Gate 7 event has been recorded.",
    submit: "Submit for owner approval",
    approve: "Approve exact request",
    reject: "Reject",
    requestRevision: "Request revision",
    pause: "Pause",
    resume: "Resume",
    cancel: "Cancel",
    reason: "Decision reason",
    reasonRequired: "A reason is required for rejection or revision.",
    forbidden: "This request is forbidden by policy. Owner approval cannot make it executable.",
    approvalNotRequired: "This request does not require Gate 7 approval.",
    loading: "Updating execution governance…",
    loadError: "Execution governance could not be loaded.",
    none: "None",
  },
  it: {
    eyebrow: "Evidenze di esecuzione · Gate 7",
    title: "Evidenze sandbox e governance delle operazioni ad alto impatto",
    intro:
      "Ispeziona le capacità dichiarate, le evidenze immutabili del sandbox e le decisioni del proprietario su versioni esatte delle operazioni ad alto impatto.",
    methodology:
      "Gate 7 approva una versione e un hash esatti della richiesta. Non può autorizzare operazioni vietate, comandi host arbitrari, container privilegiati, mount del Docker socket o accesso al filesystem host.",
    refresh: "Aggiorna stato di esecuzione",
    profiles: "Profili di esecuzione",
    noProfiles: "Nessun profilo di esecuzione è registrato.",
    status: "Stato",
    targets: "Target",
    runners: "Runner richiesti",
    images: "Immagini base",
    approval: "Approvazione proprietario",
    required: "Richiesta",
    notRequired: "Non richiesta",
    evidence: "Evidenze di validazione",
    noEvidence: "Non è registrata alcuna evidenza di validazione Level D.",
    runs: "Esecuzioni sandbox",
    noRuns: "Non è stata registrata alcuna evidenza di esecuzione sandbox.",
    inspectRun: "Ispeziona evidenze run",
    recorded: "Registrata",
    plan: "Piano",
    image: "Immagine container",
    runtime: "Runtime",
    failure: "Errore",
    commands: "Evidenze dei comandi",
    command: "Comando",
    exitCode: "Codice di uscita",
    parser: "Parser",
    artifacts: "Artefatti",
    logs: "Riferimenti ai log grezzi",
    stream: "Stream",
    storageKey: "Chiave di archiviazione",
    digest: "SHA-256",
    size: "Byte",
    noLogs: "Nessun riferimento ai log grezzi è disponibile per il run selezionato.",
    operations: "Cronologia operazioni ad alto impatto",
    noOperations: "Non esiste alcuna richiesta di operazione ad alto impatto.",
    classification: "Classificazione",
    reasons: "Motivi della classificazione",
    review: "Revisiona Gate 7",
    exactReference: "Riferimento esatto della richiesta",
    readiness: "Stato di approvazione",
    gateStatus: "Stato del gate",
    eventHistory: "Eventi di audit Gate 7",
    noEvents: "Non è stato registrato alcun evento Gate 7.",
    submit: "Invia all'approvazione del proprietario",
    approve: "Approva richiesta esatta",
    reject: "Rifiuta",
    requestRevision: "Richiedi revisione",
    pause: "Pausa",
    resume: "Riprendi",
    cancel: "Annulla",
    reason: "Motivazione della decisione",
    reasonRequired: "Per rifiuto o revisione è necessaria una motivazione.",
    forbidden:
      "Questa richiesta è vietata dalla policy. L'approvazione del proprietario non può renderla eseguibile.",
    approvalNotRequired: "Questa richiesta non richiede l'approvazione Gate 7.",
    loading: "Aggiornamento della governance di esecuzione…",
    loadError: "Non è stato possibile caricare la governance di esecuzione.",
    none: "Nessuno",
  },
} as const;

const copy = computed(() => messages[props.locale]);
const api = computed(() => props.api ?? executionApi);
const selectedRun = computed<SandboxRunPayload | null>(() => {
  if (selectedRunId.value === null) {
    return null;
  }
  return store.sandboxRuns.find((run) => run.run_id === selectedRunId.value) ?? null;
});
const selectedOperation = computed<HighImpactOperationPayload | null>(() => {
  if (selectedRequestId.value === null) {
    return null;
  }
  return (
    store.highImpactOperations.find(
      (operation) => operation.version.id === selectedRequestId.value,
    ) ?? null
  );
});
const rawLogReferences = computed(() => parseLogReferences(store.sandboxLogs?.logs ?? []));
const classificationReasons = computed(() =>
  parseClassificationReasons(selectedOperation.value?.classification.reasons ?? []),
);
const gate = computed(() => store.highImpactReadiness?.gate ?? null);
const readinessStatus = computed(() => store.highImpactReadiness?.status ?? null);
const gatePending = computed(() => gate.value?.status === "PENDING_APPROVAL");
const gatePaused = computed(() => gate.value?.status === "PAUSED");
const canSubmit = computed(
  () =>
    readinessStatus.value === "OWNER_APPROVAL_REQUIRED" &&
    selectedOperation.value?.classification.classification === "REQUIRES_OWNER_APPROVAL",
);

function jsonRecord(value: JsonValue | undefined): JsonRecord | null {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value : null;
}

function stringValue(record: JsonRecord | null, key: string): string | null {
  const value = record?.[key];
  return typeof value === "string" ? value : null;
}

function numberValue(record: JsonRecord | null, key: string): number | null {
  const value = record?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function parseLogReferences(
  logs: Array<{ command_id: string; stdout: JsonRecord; stderr: JsonRecord }>,
): LogReferenceView[] {
  const references: LogReferenceView[] = [];

  for (const log of logs) {
    for (const [stream, value] of [
      ["stdout", log.stdout],
      ["stderr", log.stderr],
    ] as const) {
      const storageKey = stringValue(value, "storage_key");
      const digest = stringValue(value, "sha256_digest");
      if (storageKey !== null && digest !== null) {
        references.push({
          commandId: log.command_id,
          stream,
          storageKey,
          digest,
          sizeBytes: numberValue(value, "size_bytes"),
        });
      }
    }
  }

  return references;
}

function parseClassificationReasons(values: JsonRecord[]): ClassificationReasonView[] {
  return values.flatMap((value) => {
    const code = stringValue(value, "code");
    const message = stringValue(value, "message");
    return code === null || message === null ? [] : [{ key: `${code}:${message}`, code, message }];
  });
}

function evidenceValue(run: SandboxRunPayload, key: string): string | null {
  return stringValue(jsonRecord(run.evidence_snapshot["evidence"]), key);
}

function exactReference(operation: HighImpactOperationPayload): string {
  return `${operation.version.id} · v${operation.version.version_number} · ${operation.version.content_hash}`;
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
  await run(() => store.load(props.projectId, authorizedRequest, api.value));
}

async function inspectRun(runId: string): Promise<void> {
  selectedRunId.value = runId;
  await run(() => store.loadSandboxEvidence(props.projectId, runId, authorizedRequest, api.value));
}

async function reviewOperation(requestId: string): Promise<void> {
  selectedRequestId.value = requestId;
  decisionReason.value = "";
  await run(() =>
    store.loadHighImpactReview(props.projectId, requestId, authorizedRequest, api.value),
  );
}

async function submitGate(): Promise<void> {
  const operation = selectedOperation.value;
  if (operation === null) {
    return;
  }
  await run(() =>
    store.submitHighImpactGate(
      props.projectId,
      operation.version.id,
      {
        version_number: operation.version.version_number,
        content_hash: operation.version.content_hash,
      },
      authorizedRequest,
      api.value,
    ),
  );
}

async function decideGate(action: DecisionAction): Promise<void> {
  const operation = selectedOperation.value;
  if (operation === null) {
    return;
  }

  const normalizedReason = decisionReason.value.trim();
  if (["REJECT", "REQUEST_REVISION"].includes(action) && normalizedReason.length === 0) {
    localError.value = copy.value.reasonRequired;
    return;
  }

  const input: HighImpactDecisionInput = {
    version_number: operation.version.version_number,
    content_hash: operation.version.content_hash,
    action,
    reason: normalizedReason.length === 0 ? null : normalizedReason,
  };
  await run(() =>
    store.decideHighImpactGate(
      props.projectId,
      operation.version.id,
      input,
      authorizedRequest,
      api.value,
    ),
  );
}

watch(
  () => props.projectId,
  async () => {
    selectedRunId.value = null;
    selectedRequestId.value = null;
    if (props.autoLoad) {
      await load();
    }
  },
  { immediate: true },
);
</script>

<template>
  <section class="grid gap-6" aria-labelledby="sandbox-governance-title">
    <header class="grid gap-2">
      <p class="m-0 text-sm font-bold tracking-wide text-indigo-700 uppercase">
        {{ copy.eyebrow }}
      </p>
      <h2 id="sandbox-governance-title" class="text-2xl font-black text-slate-950">
        {{ copy.title }}
      </h2>
      <p class="m-0 max-w-4xl text-slate-700">{{ copy.intro }}</p>
      <p class="m-0 rounded-xl border border-indigo-200 bg-indigo-50 p-4 text-sm text-indigo-950">
        {{ copy.methodology }}
      </p>
      <button
        type="button"
        class="justify-self-start rounded-lg border border-slate-300 px-4 py-3 font-bold"
        :disabled="store.pending.load"
        @click="load"
      >
        {{ copy.refresh }}
      </button>
    </header>

    <p
      v-if="localError !== null"
      class="m-0 rounded-xl border border-red-200 bg-red-50 p-4 text-red-900"
      role="alert"
    >
      {{ localError }}
    </p>
    <p v-if="store.isBusy" class="m-0 text-slate-700" aria-live="polite">
      {{ copy.loading }}
    </p>

    <section class="grid gap-4" aria-labelledby="execution-profiles-title">
      <h3 id="execution-profiles-title" class="text-xl font-black text-slate-950">
        {{ copy.profiles }}
      </h3>
      <ul v-if="store.profiles.length > 0" class="grid gap-4 lg:grid-cols-2">
        <li
          v-for="profile in store.profiles"
          :key="`${profile.profile_id}:${profile.version}:${profile.content_hash}`"
          class="grid gap-3 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
        >
          <div class="flex flex-wrap items-start justify-between gap-3">
            <strong class="text-lg text-slate-950">{{ profile.name }}</strong>
            <span
              class="rounded-full border border-slate-300 bg-slate-100 px-3 py-1 text-sm font-black"
            >
              {{ profile.capability_status }}
            </span>
          </div>
          <code class="text-xs break-all text-slate-500">{{ profile.content_hash }}</code>
          <dl class="grid gap-2 text-sm sm:grid-cols-2">
            <div>
              <dt class="font-bold">{{ copy.targets }}</dt>
              <dd class="m-0">{{ profile.supported_targets.join(", ") }}</dd>
            </div>
            <div>
              <dt class="font-bold">{{ copy.runners }}</dt>
              <dd class="m-0">{{ profile.required_runners.join(", ") || copy.none }}</dd>
            </div>
            <div>
              <dt class="font-bold">{{ copy.images }}</dt>
              <dd class="m-0 break-all">{{ profile.base_images.join(", ") || copy.none }}</dd>
            </div>
            <div>
              <dt class="font-bold">{{ copy.approval }}</dt>
              <dd class="m-0">
                {{ profile.requires_owner_approval ? copy.required : copy.notRequired }}
              </dd>
            </div>
          </dl>
          <div>
            <strong>{{ copy.evidence }}</strong>
            <ul v-if="profile.validation_evidence_refs.length > 0" class="mt-2 grid gap-1">
              <li v-for="reference in profile.validation_evidence_refs" :key="reference">
                <code>{{ reference }}</code>
              </li>
            </ul>
            <p v-else class="m-0 mt-2 text-sm text-slate-600">{{ copy.noEvidence }}</p>
          </div>
        </li>
      </ul>
      <p v-else class="m-0 text-slate-600">{{ copy.noProfiles }}</p>
    </section>

    <section class="grid gap-4" aria-labelledby="sandbox-runs-title">
      <h3 id="sandbox-runs-title" class="text-xl font-black text-slate-950">
        {{ copy.runs }}
      </h3>
      <ol v-if="store.sandboxRuns.length > 0" class="grid gap-3 lg:grid-cols-2">
        <li
          v-for="sandboxRun in store.sandboxRuns"
          :key="sandboxRun.run_id"
          class="grid gap-2 rounded-xl border border-slate-200 bg-slate-50 p-4"
        >
          <strong>{{ sandboxRun.run_id }}</strong>
          <span>{{ copy.status }}: {{ evidenceValue(sandboxRun, "status") ?? copy.none }}</span>
          <span>{{ copy.recorded }}: {{ sandboxRun.recorded_at }}</span>
          <code class="text-xs break-all">{{ sandboxRun.evidence_content_hash }}</code>
          <button
            type="button"
            class="justify-self-start rounded-lg border border-slate-300 bg-white px-3 py-2 font-bold"
            :disabled="store.pending['load-sandbox-evidence']"
            @click="inspectRun(sandboxRun.run_id)"
          >
            {{ copy.inspectRun }}
          </button>
        </li>
      </ol>
      <p v-else class="m-0 text-slate-600">{{ copy.noRuns }}</p>

      <article
        v-if="selectedRun !== null"
        class="grid gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
      >
        <dl class="grid gap-3 sm:grid-cols-2">
          <div>
            <dt class="font-bold">{{ copy.plan }}</dt>
            <dd class="m-0 break-all">
              {{ evidenceValue(selectedRun, "plan_id") ?? copy.none }} ·
              {{ evidenceValue(selectedRun, "plan_content_hash") ?? copy.none }}
            </dd>
          </div>
          <div>
            <dt class="font-bold">{{ copy.image }}</dt>
            <dd class="m-0 break-all">
              {{ evidenceValue(selectedRun, "image_reference") ?? copy.none }}
            </dd>
          </div>
          <div>
            <dt class="font-bold">{{ copy.runtime }}</dt>
            <dd class="m-0">{{ evidenceValue(selectedRun, "runtime_reference") ?? copy.none }}</dd>
          </div>
          <div>
            <dt class="font-bold">{{ copy.failure }}</dt>
            <dd class="m-0">{{ evidenceValue(selectedRun, "failure_message") ?? copy.none }}</dd>
          </div>
        </dl>

        <div class="overflow-x-auto rounded-xl border border-slate-200">
          <table class="min-w-full border-collapse text-left text-sm">
            <caption class="p-3 text-left text-base font-black">
              {{
                copy.commands
              }}
            </caption>
            <thead class="bg-slate-100">
              <tr>
                <th class="p-3" scope="col">{{ copy.command }}</th>
                <th class="p-3" scope="col">{{ copy.status }}</th>
                <th class="p-3" scope="col">{{ copy.exitCode }}</th>
                <th class="p-3" scope="col">{{ copy.parser }}</th>
                <th class="p-3" scope="col">{{ copy.artifacts }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="commandResult in selectedRun.command_results"
                :key="commandResult.command_id"
                class="border-t border-slate-200"
              >
                <td class="p-3 font-semibold">{{ commandResult.command_id }}</td>
                <td class="p-3">{{ commandResult.status }}</td>
                <td class="p-3">{{ commandResult.exit_code ?? copy.none }}</td>
                <td class="p-3">{{ commandResult.output_parser_id ?? copy.none }}</td>
                <td class="p-3">{{ commandResult.artifacts.length }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="overflow-x-auto rounded-xl border border-slate-200">
          <table class="min-w-full border-collapse text-left text-sm">
            <caption class="p-3 text-left text-base font-black">
              {{
                copy.logs
              }}
            </caption>
            <thead class="bg-slate-100">
              <tr>
                <th class="p-3" scope="col">{{ copy.command }}</th>
                <th class="p-3" scope="col">{{ copy.stream }}</th>
                <th class="p-3" scope="col">{{ copy.storageKey }}</th>
                <th class="p-3" scope="col">{{ copy.digest }}</th>
                <th class="p-3" scope="col">{{ copy.size }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="reference in rawLogReferences"
                :key="`${reference.commandId}:${reference.stream}`"
                class="border-t border-slate-200"
              >
                <td class="p-3">{{ reference.commandId }}</td>
                <td class="p-3">{{ reference.stream }}</td>
                <td class="p-3">
                  <code class="text-xs break-all">{{ reference.storageKey }}</code>
                </td>
                <td class="p-3">
                  <code class="text-xs break-all">{{ reference.digest }}</code>
                </td>
                <td class="p-3">{{ reference.sizeBytes ?? copy.none }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="rawLogReferences.length === 0" class="m-0 text-slate-600">
          {{ copy.noLogs }}
        </p>
      </article>
    </section>

    <section class="grid gap-4" aria-labelledby="high-impact-operations-title">
      <h3 id="high-impact-operations-title" class="text-xl font-black text-slate-950">
        {{ copy.operations }}
      </h3>
      <ol v-if="store.highImpactOperations.length > 0" class="grid gap-3 lg:grid-cols-2">
        <li
          v-for="operation in store.highImpactOperations"
          :key="operation.version.id"
          class="grid gap-2 rounded-xl border border-slate-200 bg-slate-50 p-4"
        >
          <strong class="break-all">{{ exactReference(operation) }}</strong>
          <span>{{ copy.classification }}: {{ operation.classification.classification }}</span>
          <button
            type="button"
            class="justify-self-start rounded-lg border border-slate-300 bg-white px-3 py-2 font-bold"
            :disabled="store.pending['load-high-impact-review']"
            @click="reviewOperation(operation.version.id)"
          >
            {{ copy.review }}
          </button>
        </li>
      </ol>
      <p v-else class="m-0 text-slate-600">{{ copy.noOperations }}</p>

      <article
        v-if="selectedOperation !== null"
        class="grid gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
      >
        <dl class="grid gap-3 sm:grid-cols-2">
          <div>
            <dt class="font-bold">{{ copy.exactReference }}</dt>
            <dd class="m-0 break-all">{{ exactReference(selectedOperation) }}</dd>
          </div>
          <div>
            <dt class="font-bold">{{ copy.classification }}</dt>
            <dd class="m-0">{{ selectedOperation.classification.classification }}</dd>
          </div>
          <div>
            <dt class="font-bold">{{ copy.readiness }}</dt>
            <dd class="m-0">{{ readinessStatus ?? copy.none }}</dd>
          </div>
          <div>
            <dt class="font-bold">{{ copy.gateStatus }}</dt>
            <dd class="m-0">{{ gate?.status ?? copy.none }}</dd>
          </div>
        </dl>

        <div v-if="classificationReasons.length > 0" class="grid gap-2">
          <strong>{{ copy.reasons }}</strong>
          <ul class="grid gap-2">
            <li
              v-for="reason in classificationReasons"
              :key="reason.key"
              class="rounded-lg border border-amber-200 bg-amber-50 p-3"
            >
              <strong>{{ reason.code }}</strong
              >: {{ reason.message }}
            </li>
          </ul>
        </div>
        <p
          v-if="selectedOperation.classification.classification === 'FORBIDDEN_BY_POLICY'"
          class="m-0 rounded-lg border border-red-200 bg-red-50 p-3 text-red-900"
          role="status"
        >
          {{ copy.forbidden }}
        </p>
        <p
          v-if="readinessStatus === 'APPROVAL_NOT_REQUIRED'"
          class="m-0 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-emerald-950"
          role="status"
        >
          {{ copy.approvalNotRequired }}
        </p>

        <div class="grid gap-2">
          <label for="gate-7-reason" class="font-bold">{{ copy.reason }}</label>
          <textarea
            id="gate-7-reason"
            v-model="decisionReason"
            rows="3"
            class="rounded-lg border border-slate-300 p-3"
          />
        </div>

        <div class="flex flex-wrap gap-2">
          <button
            v-if="canSubmit"
            type="button"
            class="rounded-lg bg-slate-950 px-4 py-3 font-bold text-white"
            :disabled="store.pending['submit-gate']"
            @click="submitGate"
          >
            {{ copy.submit }}
          </button>
          <template v-if="gatePending">
            <button
              type="button"
              class="rounded-lg bg-emerald-700 px-4 py-3 font-bold text-white"
              :disabled="store.pending['decide-gate']"
              @click="decideGate('APPROVE')"
            >
              {{ copy.approve }}
            </button>
            <button
              type="button"
              class="rounded-lg border border-red-300 px-4 py-3 font-bold text-red-800"
              :disabled="store.pending['decide-gate']"
              @click="decideGate('REJECT')"
            >
              {{ copy.reject }}
            </button>
            <button
              type="button"
              class="rounded-lg border border-amber-300 px-4 py-3 font-bold text-amber-900"
              :disabled="store.pending['decide-gate']"
              @click="decideGate('REQUEST_REVISION')"
            >
              {{ copy.requestRevision }}
            </button>
            <button
              type="button"
              class="rounded-lg border border-slate-300 px-4 py-3 font-bold"
              :disabled="store.pending['decide-gate']"
              @click="decideGate('PAUSE')"
            >
              {{ copy.pause }}
            </button>
            <button
              type="button"
              class="rounded-lg border border-slate-300 px-4 py-3 font-bold"
              :disabled="store.pending['decide-gate']"
              @click="decideGate('CANCEL')"
            >
              {{ copy.cancel }}
            </button>
          </template>
          <button
            v-if="gatePaused"
            type="button"
            class="rounded-lg border border-slate-300 px-4 py-3 font-bold"
            :disabled="store.pending['decide-gate']"
            @click="decideGate('RESUME')"
          >
            {{ copy.resume }}
          </button>
        </div>

        <div class="grid gap-2">
          <strong>{{ copy.eventHistory }}</strong>
          <ol v-if="store.highImpactEvents.length > 0" class="grid gap-2">
            <li
              v-for="event in store.highImpactEvents"
              :key="event.id"
              class="rounded-lg border border-slate-200 p-3"
            >
              {{ event.sequence_number }} · {{ event.kind }} · {{ event.previous_status }} →
              {{ event.resulting_status }}
              <span v-if="event.reason !== null"> · {{ event.reason }}</span>
            </li>
          </ol>
          <p v-else class="m-0 text-slate-600">{{ copy.noEvents }}</p>
        </div>
      </article>
    </section>
  </section>
</template>
