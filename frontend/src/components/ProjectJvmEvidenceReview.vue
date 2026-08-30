<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";

import { apiClient } from "@/api/client";
import { jvmExecutionApi, type JvmExecutionApi } from "@/api/jvmExecution";
import { useAuthStore } from "@/stores/auth";
import { type AuthorizedJvmExecutionRequest, useJvmExecutionStore } from "@/stores/jvmExecution";
import type { JvmEvidenceReferencePayload, JvmRepairProposalPayload } from "@/types/jvmExecution";

type Locale = "en" | "it";

interface EvidenceReferenceView extends JvmEvidenceReferencePayload {
  phase: string;
  kind: "stdout" | "stderr" | "artifact";
}

const props = withDefaults(
  defineProps<{
    projectId: string;
    locale?: Locale;
    autoLoad?: boolean;
    authorize?: AuthorizedJvmExecutionRequest;
    api?: JvmExecutionApi;
  }>(),
  { locale: "en", autoLoad: true },
);

const auth = useAuthStore();
const store = useJvmExecutionStore();
const selectedExecutionId = ref<string | null>(null);
const approvalIdByProposal = ref<Record<string, string>>({});
const localError = ref<string | null>(null);
const applyingProposalId = ref<string | null>(null);

const messages = {
  en: {
    eyebrow: "JVM execution · deterministic evidence",
    title: "Execution and bounded repair evidence",
    intro:
      "Inspect phase outcomes, content-addressed logs and artifacts, stable failure signatures, repair budgets, and exact rerun lineage.",
    methodology:
      "Compiler, unit-test, and runtime outputs are deterministic tool evidence. They do not by themselves establish general LLM generation quality or empirical User Twin validation.",
    refresh: "Refresh execution history",
    attempts: "Execution attempts",
    noAttempts: "No JVM execution attempt has been recorded.",
    inspect: "Inspect attempt",
    attempt: "Attempt",
    trigger: "Trigger",
    sourceRevision: "Source revision",
    reportStatus: "Report status",
    profile: "Profile",
    runner: "Runner image digest",
    policy: "Policy hash",
    phases: "Phase results",
    phase: "Phase",
    status: "Status",
    summary: "Summary",
    failure: "Failure",
    exitCodes: "Exit codes",
    evidence: "Raw log and artifact references",
    noEvidence: "No raw evidence reference is recorded for this attempt.",
    kind: "Kind",
    storageKey: "Storage key",
    digest: "SHA-256",
    mediaType: "Media type",
    bytes: "Bytes",
    signatures: "Stable failure signatures",
    noSignatures: "No failure signature is present.",
    repairs: "Bounded repair proposals",
    noRepairs: "No repair proposal is recorded.",
    proposalAttempt: "Repair attempt",
    repeated: "Identical failure occurrences",
    changes: "Typed changes",
    approvalId: "Gate 7 approval ID, when required",
    apply: "Apply exact repair proposal",
    applying: "Applying repair…",
    loading: "Loading JVM evidence…",
    loadError: "JVM execution evidence could not be loaded.",
    unavailableHash: "Proposal hash unavailable",
  },
  it: {
    eyebrow: "Esecuzione JVM · evidenze deterministiche",
    title: "Evidenze di esecuzione e repair limitato",
    intro:
      "Ispeziona esiti delle fasi, log e artefatti content-addressed, firme stabili degli errori, budget di repair e lineage esatto dei rerun.",
    methodology:
      "Gli output di compilatore, unit test e runtime sono evidenze deterministiche degli strumenti. Da soli non dimostrano qualità generale della generazione LLM o validazione empirica dei User Twin.",
    refresh: "Aggiorna cronologia esecuzioni",
    attempts: "Tentativi di esecuzione",
    noAttempts: "Non è stato registrato alcun tentativo di esecuzione JVM.",
    inspect: "Ispeziona tentativo",
    attempt: "Tentativo",
    trigger: "Trigger",
    sourceRevision: "Revisione sorgente",
    reportStatus: "Stato report",
    profile: "Profilo",
    runner: "Digest immagine runner",
    policy: "Hash policy",
    phases: "Risultati delle fasi",
    phase: "Fase",
    status: "Stato",
    summary: "Riepilogo",
    failure: "Errore",
    exitCodes: "Codici di uscita",
    evidence: "Riferimenti a log grezzi e artefatti",
    noEvidence: "Per questo tentativo non è registrato alcun riferimento a evidenze grezze.",
    kind: "Tipo",
    storageKey: "Chiave di archiviazione",
    digest: "SHA-256",
    mediaType: "Media type",
    bytes: "Byte",
    signatures: "Firme stabili degli errori",
    noSignatures: "Non è presente alcuna firma di errore.",
    repairs: "Proposte di repair limitate",
    noRepairs: "Non è registrata alcuna proposta di repair.",
    proposalAttempt: "Tentativo di repair",
    repeated: "Occorrenze dell'errore identico",
    changes: "Modifiche tipizzate",
    approvalId: "ID approvazione Gate 7, quando richiesta",
    apply: "Applica proposta di repair esatta",
    applying: "Applicazione repair…",
    loading: "Caricamento evidenze JVM…",
    loadError: "Non è stato possibile caricare le evidenze di esecuzione JVM.",
    unavailableHash: "Hash proposta non disponibile",
  },
} as const;

const copy = computed(() => messages[props.locale]);
const api = computed(() => props.api ?? jvmExecutionApi);
const evidenceReferences = computed<EvidenceReferenceView[]>(() => {
  const report = store.selectedReport;
  if (report === null) return [];
  return report.phase_results.flatMap((phase) => [
    ...phase.stdout_refs.map((reference) => ({
      ...reference,
      phase: phase.phase,
      kind: "stdout" as const,
    })),
    ...phase.stderr_refs.map((reference) => ({
      ...reference,
      phase: phase.phase,
      kind: "stderr" as const,
    })),
    ...phase.artifact_refs.map((reference) => ({
      ...reference,
      phase: phase.phase,
      kind: "artifact" as const,
    })),
  ]);
});

function authorized<T>(operation: (accessToken: string) => Promise<T>): Promise<T> {
  return props.authorize?.(operation) ?? auth.withAccessToken(apiClient, operation);
}

function proposalHash(proposal: JvmRepairProposalPayload): string | null {
  return proposal.change_set?.content_hash ?? proposal.content_hash ?? null;
}

function proposalChanges(proposal: JvmRepairProposalPayload) {
  return proposal.change_set?.changes ?? proposal.changes ?? [];
}

async function loadProject(): Promise<void> {
  localError.value = null;
  try {
    await store.loadProject(props.projectId, authorized, api.value);
    selectedExecutionId.value = store.currentExecution?.id ?? null;
    if (selectedExecutionId.value !== null) await loadExecution(selectedExecutionId.value);
  } catch (error: unknown) {
    localError.value = error instanceof Error ? error.message : copy.value.loadError;
  }
}

async function loadExecution(executionId: string): Promise<void> {
  localError.value = null;
  try {
    await store.loadExecution(props.projectId, executionId, authorized, api.value);
  } catch (error: unknown) {
    localError.value = error instanceof Error ? error.message : copy.value.loadError;
  }
}

async function applyRepair(proposal: JvmRepairProposalPayload): Promise<void> {
  if (store.selectedExecution === null) return;
  const contentHash = proposalHash(proposal);
  if (contentHash === null) {
    localError.value = copy.value.unavailableHash;
    return;
  }
  applyingProposalId.value = proposal.id;
  localError.value = null;
  const approval = approvalIdByProposal.value[proposal.id]?.trim() ?? "";
  try {
    await store.applyRepairProposal(
      props.projectId,
      store.selectedExecution.id,
      proposal.id,
      {
        base_revision_content_hash: proposal.base_revision.content_hash,
        proposal_content_hash: contentHash,
        approval_id: approval.length === 0 ? null : approval,
      },
      authorized,
      api.value,
    );
  } catch (error: unknown) {
    localError.value = error instanceof Error ? error.message : copy.value.loadError;
  } finally {
    applyingProposalId.value = null;
  }
}

watch(selectedExecutionId, async (executionId) => {
  if (executionId !== null && executionId !== store.selectedExecution?.id) {
    await loadExecution(executionId);
  }
});
watch(
  () => props.projectId,
  async () => {
    if (props.autoLoad) await loadProject();
  },
);
onMounted(async () => {
  if (props.autoLoad) await loadProject();
});
</script>

<template>
  <section class="grid gap-6" aria-labelledby="jvm-evidence-review-title">
    <header class="grid gap-2">
      <p class="m-0 text-sm font-bold tracking-wide text-violet-700 uppercase">
        {{ copy.eyebrow }}
      </p>
      <h2 id="jvm-evidence-review-title" class="m-0 text-2xl font-black text-slate-950">
        {{ copy.title }}
      </h2>
      <p class="m-0 max-w-4xl text-slate-700">{{ copy.intro }}</p>
      <p class="m-0 rounded-xl border border-violet-200 bg-violet-50 p-4 text-sm text-violet-950">
        {{ copy.methodology }}
      </p>
      <button
        type="button"
        class="w-fit rounded-lg border border-slate-300 bg-white px-4 py-2 font-bold"
        :disabled="store.isBusy"
        @click="loadProject"
      >
        {{ copy.refresh }}
      </button>
    </header>

    <p v-if="store.isBusy" aria-live="polite">{{ copy.loading }}</p>
    <p
      v-if="localError !== null || store.errorCode !== null"
      class="rounded-xl border border-red-200 bg-red-50 p-4 font-semibold text-red-800"
      role="alert"
    >
      {{ localError ?? store.errorCode ?? copy.loadError }}
    </p>

    <section class="grid gap-3" aria-labelledby="jvm-execution-attempts-title">
      <h3 id="jvm-execution-attempts-title" class="m-0 text-xl font-black">{{ copy.attempts }}</h3>
      <label v-if="store.executions.length > 0" class="grid max-w-xl gap-1 font-bold">
        {{ copy.inspect }}
        <select v-model="selectedExecutionId" class="rounded-lg border border-slate-300 p-2">
          <option v-for="attempt in store.executions" :key="attempt.id" :value="attempt.id">
            #{{ attempt.attempt_number }} · {{ attempt.trigger }} · {{ attempt.report.status }}
          </option>
        </select>
      </label>
      <p v-else>{{ copy.noAttempts }}</p>
    </section>

    <template v-if="store.selectedExecution !== null && store.selectedReport !== null">
      <section class="grid gap-3" aria-labelledby="jvm-attempt-summary-title">
        <h3 id="jvm-attempt-summary-title" class="m-0 text-xl font-black">
          {{ copy.attempt }} #{{ store.selectedExecution.attempt_number }}
        </h3>
        <dl class="grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-3">
          <div>
            <dt class="font-bold">{{ copy.trigger }}</dt>
            <dd class="m-0">{{ store.selectedExecution.trigger }}</dd>
          </div>
          <div>
            <dt class="font-bold">{{ copy.sourceRevision }}</dt>
            <dd class="m-0">v{{ store.selectedExecution.source_revision.version_number }}</dd>
          </div>
          <div>
            <dt class="font-bold">{{ copy.reportStatus }}</dt>
            <dd class="m-0">{{ store.selectedReport.status }}</dd>
          </div>
          <div>
            <dt class="font-bold">{{ copy.profile }}</dt>
            <dd class="m-0">
              {{ store.selectedExecution.profile_id }} ·
              {{ store.selectedExecution.profile_version }}
            </dd>
          </div>
          <div>
            <dt class="font-bold">{{ copy.runner }}</dt>
            <dd class="m-0 break-all">
              <code>{{ store.selectedExecution.runner_image_digest }}</code>
            </dd>
          </div>
          <div>
            <dt class="font-bold">{{ copy.policy }}</dt>
            <dd class="m-0 break-all">
              <code>{{ store.selectedExecution.policy_content_hash }}</code>
            </dd>
          </div>
        </dl>
      </section>

      <section class="grid gap-3" aria-labelledby="jvm-phase-results-title">
        <h3 id="jvm-phase-results-title" class="m-0 text-xl font-black">{{ copy.phases }}</h3>
        <div class="overflow-x-auto">
          <table class="w-full border-collapse text-left text-sm">
            <thead>
              <tr>
                <th class="border-b p-2">{{ copy.phase }}</th>
                <th class="border-b p-2">{{ copy.status }}</th>
                <th class="border-b p-2">{{ copy.summary }}</th>
                <th class="border-b p-2">{{ copy.failure }}</th>
                <th class="border-b p-2">{{ copy.exitCodes }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="phase in store.selectedReport.phase_results" :key="phase.phase">
                <th scope="row" class="border-b p-2">{{ phase.phase }}</th>
                <td class="border-b p-2">{{ phase.status }}</td>
                <td class="border-b p-2">{{ phase.normalized_summary }}</td>
                <td class="border-b p-2">{{ phase.failure_code ?? "—" }}</td>
                <td class="border-b p-2">{{ phase.exit_codes.join(", ") || "—" }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="grid gap-3" aria-labelledby="jvm-raw-evidence-title">
        <h3 id="jvm-raw-evidence-title" class="m-0 text-xl font-black">{{ copy.evidence }}</h3>
        <div v-if="evidenceReferences.length > 0" class="overflow-x-auto">
          <table class="w-full border-collapse text-left text-sm">
            <thead>
              <tr>
                <th class="border-b p-2">{{ copy.phase }}</th>
                <th class="border-b p-2">{{ copy.kind }}</th>
                <th class="border-b p-2">{{ copy.storageKey }}</th>
                <th class="border-b p-2">{{ copy.digest }}</th>
                <th class="border-b p-2">{{ copy.mediaType }}</th>
                <th class="border-b p-2">{{ copy.bytes }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="reference in evidenceReferences"
                :key="`${reference.phase}:${reference.kind}:${reference.storage_key}`"
              >
                <td class="border-b p-2">{{ reference.phase }}</td>
                <td class="border-b p-2">{{ reference.kind }}</td>
                <td class="border-b p-2">
                  <code class="text-xs break-all">{{ reference.storage_key }}</code>
                </td>
                <td class="border-b p-2">
                  <code class="text-xs break-all">{{ reference.sha256_digest }}</code>
                </td>
                <td class="border-b p-2">{{ reference.media_type }}</td>
                <td class="border-b p-2">{{ reference.size_bytes }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else>{{ copy.noEvidence }}</p>
      </section>

      <section class="grid gap-3" aria-labelledby="jvm-failure-signatures-title">
        <h3 id="jvm-failure-signatures-title" class="m-0 text-xl font-black">
          {{ copy.signatures }}
        </h3>
        <ul v-if="store.selectedReport.failure_signatures.length > 0" class="grid gap-3">
          <li
            v-for="signature in store.selectedReport.failure_signatures"
            :key="signature.signature"
            class="rounded-xl border border-rose-200 bg-rose-50 p-4"
          >
            <strong>{{ signature.failure_code }} · {{ signature.phase }}</strong>
            <p class="mb-1">{{ signature.normalized_message }}</p>
            <code class="text-xs break-all">{{ signature.signature }}</code>
          </li>
        </ul>
        <p v-else>{{ copy.noSignatures }}</p>
      </section>

      <section class="grid gap-3" aria-labelledby="jvm-repair-proposals-title">
        <h3 id="jvm-repair-proposals-title" class="m-0 text-xl font-black">{{ copy.repairs }}</h3>
        <ul v-if="store.repairProposals.length > 0" class="grid gap-4">
          <li
            v-for="proposal in store.repairProposals"
            :key="proposal.id"
            class="grid gap-3 rounded-xl border border-slate-200 p-4"
          >
            <p class="m-0">
              <strong>{{ copy.proposalAttempt }}:</strong> {{ proposal.attempt_number }} ·
              <strong>{{ copy.repeated }}:</strong> {{ proposal.identical_failure_occurrences }}
            </p>
            <div>
              <p class="m-0 font-bold">{{ copy.changes }}</p>
              <ul class="mt-1 grid gap-1 pl-5">
                <li
                  v-for="change in proposalChanges(proposal)"
                  :key="`${change.operation}:${change.normalized_path}`"
                >
                  {{ change.operation }} · {{ change.normalized_path }}
                </li>
              </ul>
            </div>
            <label class="grid gap-1 font-bold"
              >{{ copy.approvalId
              }}<input
                v-model="approvalIdByProposal[proposal.id]"
                class="rounded-lg border border-slate-300 p-2"
                type="text"
            /></label>
            <button
              type="button"
              class="w-fit rounded-lg bg-slate-950 px-4 py-2 font-bold text-white"
              :disabled="applyingProposalId !== null || proposalHash(proposal) === null"
              @click="applyRepair(proposal)"
            >
              {{ applyingProposalId === proposal.id ? copy.applying : copy.apply }}
            </button>
          </li>
        </ul>
        <p v-else>{{ copy.noRepairs }}</p>
      </section>
    </template>
  </section>
</template>
