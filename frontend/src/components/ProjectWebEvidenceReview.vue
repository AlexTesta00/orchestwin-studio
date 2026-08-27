<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";

import { apiClient } from "@/api/client";
import { webExecutionApi, type WebExecutionApi } from "@/api/webExecution";
import { useAuthStore } from "@/stores/auth";
import { type AuthorizedWebExecutionRequest, useWebExecutionStore } from "@/stores/webExecution";
import type { WebEvidenceReferencePayload, WebRepairProposalPayload } from "@/types/webExecution";

type Locale = "en" | "it";

interface EvidenceReferenceView extends WebEvidenceReferencePayload {
  phase: string;
  kind: "stdout" | "stderr" | "artifact";
}

const props = withDefaults(
  defineProps<{
    projectId: string;
    locale?: Locale;
    autoLoad?: boolean;
    authorize?: AuthorizedWebExecutionRequest;
    api?: WebExecutionApi;
  }>(),
  {
    locale: "en",
    autoLoad: true,
  },
);

const auth = useAuthStore();
const store = useWebExecutionStore();
const selectedExecutionId = ref<string | null>(null);
const approvalIdByProposal = ref<Record<string, string>>({});
const localError = ref<string | null>(null);
const applyingProposalId = ref<string | null>(null);

const messages = {
  en: {
    eyebrow: "Web execution · deterministic evidence",
    title: "Execution, browser, and repair evidence",
    intro:
      "Inspect phase outcomes, raw content-addressed evidence, stable failure signatures, bounded repair proposals, and exact rerun lineage.",
    methodology:
      "Playwright and axe results are deterministic tool evidence, not complete WCAG certification, simulated User Twin feedback, or empirical validation. Those evidence families must remain distinguishable.",
    refresh: "Refresh execution history",
    attempts: "Execution attempts",
    noAttempts: "No Web execution attempt has been recorded.",
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
    browser: "Browser and accessibility evidence",
    noBrowser: "No browser evidence is available for this attempt.",
    route: "Route",
    consoleErrors: "Console messages",
    failedRequests: "Failed local requests",
    axeFindings: "axe findings",
    screenshot: "Screenshot reference",
    dom: "DOM snapshot reference",
    repairs: "Bounded repair proposals",
    noRepairs: "No repair proposal is recorded.",
    proposalAttempt: "Repair attempt",
    repeated: "Identical failure occurrences",
    changes: "Typed changes",
    approvalId: "Gate 7 approval ID, when required",
    apply: "Apply exact repair proposal",
    applying: "Applying repair…",
    applied: "The repair created a new immutable source revision.",
    loading: "Loading Web evidence…",
    loadError: "Web execution evidence could not be loaded.",
    none: "None",
  },
  it: {
    eyebrow: "Esecuzione Web · evidenze deterministiche",
    title: "Evidenze di esecuzione, browser e repair",
    intro:
      "Ispeziona esiti delle fasi, evidenze content-addressed grezze, firme stabili degli errori, proposte di repair limitate e lineage esatto dei rerun.",
    methodology:
      "I risultati Playwright e axe sono evidenze deterministiche degli strumenti, non una certificazione WCAG completa, feedback simulato dei User Twin o validazione empirica. Queste famiglie di evidenze devono restare distinguibili.",
    refresh: "Aggiorna cronologia esecuzioni",
    attempts: "Tentativi di esecuzione",
    noAttempts: "Non è stato registrato alcun tentativo di esecuzione Web.",
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
    browser: "Evidenze browser e accessibilità",
    noBrowser: "Per questo tentativo non sono disponibili evidenze browser.",
    route: "Route",
    consoleErrors: "Messaggi console",
    failedRequests: "Richieste locali fallite",
    axeFindings: "Finding axe",
    screenshot: "Riferimento screenshot",
    dom: "Riferimento snapshot DOM",
    repairs: "Proposte di repair limitate",
    noRepairs: "Non è registrata alcuna proposta di repair.",
    proposalAttempt: "Tentativo di repair",
    repeated: "Occorrenze dell'errore identico",
    changes: "Modifiche tipizzate",
    approvalId: "ID approvazione Gate 7, quando richiesta",
    apply: "Applica proposta di repair esatta",
    applying: "Applicazione repair…",
    applied: "Il repair ha creato una nuova revisione immutabile del sorgente.",
    loading: "Caricamento evidenze Web…",
    loadError: "Non è stato possibile caricare le evidenze di esecuzione Web.",
    none: "Nessuno",
  },
} as const;

const copy = computed(() => messages[props.locale]);
const api = computed(() => props.api ?? webExecutionApi);
const evidenceReferences = computed<EvidenceReferenceView[]>(() => {
  const report = store.selectedReport;
  if (report === null) {
    return [];
  }
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
  if (props.authorize !== undefined) {
    return props.authorize(operation);
  }
  return auth.withAccessToken(apiClient, operation);
}

async function loadProject(): Promise<void> {
  localError.value = null;
  try {
    await store.loadProject(props.projectId, authorized, api.value);
    selectedExecutionId.value = store.currentExecution?.id ?? null;
    if (selectedExecutionId.value !== null) {
      await loadExecution(selectedExecutionId.value);
    }
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

async function applyRepair(proposal: WebRepairProposalPayload): Promise<void> {
  if (store.selectedExecution === null) {
    return;
  }
  applyingProposalId.value = proposal.id;
  localError.value = null;
  const enteredApproval = approvalIdByProposal.value[proposal.id]?.trim() ?? "";
  try {
    await store.applyRepairProposal(
      props.projectId,
      store.selectedExecution.id,
      proposal.id,
      {
        base_revision_content_hash: proposal.base_revision.content_hash,
        proposal_content_hash: proposal.change_set.content_hash,
        approval_id: enteredApproval.length === 0 ? null : enteredApproval,
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
    if (props.autoLoad) {
      await loadProject();
    }
  },
);

onMounted(async () => {
  if (props.autoLoad) {
    await loadProject();
  }
});
</script>

<template>
  <section class="grid gap-6" aria-labelledby="web-evidence-review-title">
    <header class="grid gap-2">
      <p class="m-0 text-sm font-bold tracking-wide text-violet-700 uppercase">
        {{ copy.eyebrow }}
      </p>
      <h2 id="web-evidence-review-title" class="m-0 text-2xl font-black text-slate-950">
        {{ copy.title }}
      </h2>
      <p class="m-0 max-w-4xl text-slate-700">{{ copy.intro }}</p>
      <p class="m-0 rounded-xl border border-violet-200 bg-violet-50 p-4 text-sm text-violet-950">
        {{ copy.methodology }}
      </p>
      <button
        type="button"
        class="w-fit rounded-lg border border-slate-300 bg-white px-4 py-2 font-bold text-slate-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-700"
        :disabled="store.isBusy"
        @click="loadProject"
      >
        {{ copy.refresh }}
      </button>
    </header>

    <p v-if="store.isBusy" class="m-0 text-slate-700" aria-live="polite">
      {{ copy.loading }}
    </p>
    <p
      v-if="localError !== null || store.errorCode !== null"
      class="m-0 rounded-xl border border-red-200 bg-red-50 p-4 font-semibold text-red-800"
      role="alert"
    >
      {{ localError ?? store.errorCode ?? copy.loadError }}
    </p>

    <section class="grid gap-3" aria-labelledby="web-attempt-list-title">
      <h3 id="web-attempt-list-title" class="m-0 text-xl font-black text-slate-950">
        {{ copy.attempts }}
      </h3>
      <label
        v-if="store.executions.length > 0"
        class="grid max-w-xl gap-1 font-bold text-slate-900"
      >
        {{ copy.inspect }}
        <select
          v-model="selectedExecutionId"
          class="rounded-lg border border-slate-300 bg-white p-2"
        >
          <option v-for="attempt in store.executions" :key="attempt.id" :value="attempt.id">
            {{ copy.attempt }} {{ attempt.attempt_number }} · {{ attempt.report.status }} ·
            {{ attempt.trigger }}
          </option>
        </select>
      </label>
      <p v-else class="m-0 text-slate-600">{{ copy.noAttempts }}</p>
    </section>

    <template v-if="store.selectedExecution !== null && store.selectedReport !== null">
      <section
        class="grid gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4"
        aria-labelledby="web-report-summary-title"
      >
        <h3 id="web-report-summary-title" class="m-0 text-xl font-black text-slate-950">
          {{ copy.reportStatus }}: {{ store.selectedReport.status }}
        </h3>
        <dl class="grid gap-2 text-sm sm:grid-cols-2">
          <div>
            <dt class="font-bold">{{ copy.attempt }}</dt>
            <dd class="m-0">{{ store.selectedExecution.attempt_number }}</dd>
          </div>
          <div>
            <dt class="font-bold">{{ copy.trigger }}</dt>
            <dd class="m-0">{{ store.selectedExecution.trigger }}</dd>
          </div>
          <div>
            <dt class="font-bold">{{ copy.sourceRevision }}</dt>
            <dd class="m-0">v{{ store.selectedExecution.source_revision.version_number }}</dd>
          </div>
          <div>
            <dt class="font-bold">{{ copy.profile }}</dt>
            <dd class="m-0">
              {{ store.selectedReport.profile_id }}@{{ store.selectedReport.profile_version }}
            </dd>
          </div>
          <div class="sm:col-span-2">
            <dt class="font-bold">{{ copy.runner }}</dt>
            <dd class="m-0 break-all">
              <code>{{ store.selectedReport.runner_image_digest }}</code>
            </dd>
          </div>
          <div class="sm:col-span-2">
            <dt class="font-bold">{{ copy.policy }}</dt>
            <dd class="m-0 break-all">
              <code>{{ store.selectedReport.policy_content_hash }}</code>
            </dd>
          </div>
        </dl>
      </section>

      <section class="grid gap-3" aria-labelledby="web-phase-results-title">
        <h3 id="web-phase-results-title" class="m-0 text-xl font-black text-slate-950">
          {{ copy.phases }}
        </h3>
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
                <th scope="row" class="border-b p-2 font-bold">{{ phase.phase }}</th>
                <td class="border-b p-2">
                  <strong>{{ phase.status }}</strong>
                </td>
                <td class="border-b p-2">{{ phase.normalized_summary }}</td>
                <td class="border-b p-2">{{ phase.failure_code ?? copy.none }}</td>
                <td class="border-b p-2">{{ phase.exit_codes.join(", ") || copy.none }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="grid gap-3" aria-labelledby="web-raw-evidence-title">
        <h3 id="web-raw-evidence-title" class="m-0 text-xl font-black text-slate-950">
          {{ copy.evidence }}
        </h3>
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
                <th scope="row" class="border-b p-2 font-bold">{{ reference.phase }}</th>
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
        <p v-else class="m-0 text-slate-600">{{ copy.noEvidence }}</p>
      </section>

      <section class="grid gap-3" aria-labelledby="web-failure-signatures-title">
        <h3 id="web-failure-signatures-title" class="m-0 text-xl font-black text-slate-950">
          {{ copy.signatures }}
        </h3>
        <ul v-if="store.selectedReport.failure_signatures.length > 0" class="grid gap-3">
          <li
            v-for="signature in store.selectedReport.failure_signatures"
            :key="signature.digest"
            class="rounded-xl border border-red-200 bg-red-50 p-4"
          >
            <p class="m-0 font-black text-red-950">
              {{ signature.phase }} · {{ signature.category }} · {{ signature.failure_code }}
            </p>
            <p class="mt-1 mb-0 text-sm text-red-900">{{ signature.normalized_message }}</p>
            <code class="mt-2 block text-xs break-all">{{ signature.digest }}</code>
          </li>
        </ul>
        <p v-else class="m-0 text-slate-600">{{ copy.noSignatures }}</p>
      </section>

      <section class="grid gap-3" aria-labelledby="web-browser-evidence-title">
        <h3 id="web-browser-evidence-title" class="m-0 text-xl font-black text-slate-950">
          {{ copy.browser }}
        </h3>
        <div v-if="store.browserEvidence !== null" class="grid gap-4">
          <p class="m-0 font-bold">{{ copy.status }}: {{ store.browserEvidence.status }}</p>
          <article
            v-for="route in store.browserEvidence.routes"
            :key="route.route.route_id"
            class="grid gap-2 rounded-xl border border-slate-200 bg-white p-4"
          >
            <h4 class="m-0 font-black text-slate-950">
              {{ copy.route }} {{ route.route.path }} · {{ route.status }}
            </h4>
            <p class="m-0 text-sm">{{ copy.consoleErrors }}: {{ route.console_messages.length }}</p>
            <p class="m-0 text-sm">{{ copy.failedRequests }}: {{ route.failed_requests.length }}</p>
            <p class="m-0 text-sm">
              {{ copy.axeFindings }}: {{ route.accessibility_findings.length }}
            </p>
            <p class="m-0 text-xs break-all">
              {{ copy.screenshot }}:
              <code>{{ route.screenshot_ref?.storage_key ?? copy.none }}</code>
            </p>
            <p class="m-0 text-xs break-all">
              {{ copy.dom }}: <code>{{ route.dom_snapshot_ref?.storage_key ?? copy.none }}</code>
            </p>
            <ul v-if="route.accessibility_findings.length > 0" class="grid gap-2 pl-5 text-sm">
              <li
                v-for="finding in route.accessibility_findings"
                :key="`${finding.rule_id}:${finding.targets.join(',')}`"
              >
                <strong>{{ finding.impact }} · {{ finding.rule_id }}</strong
                >: {{ finding.description }}
              </li>
            </ul>
          </article>
        </div>
        <p v-else class="m-0 text-slate-600">{{ copy.noBrowser }}</p>
      </section>

      <section class="grid gap-3" aria-labelledby="web-repair-proposals-title">
        <h3 id="web-repair-proposals-title" class="m-0 text-xl font-black text-slate-950">
          {{ copy.repairs }}
        </h3>
        <ol v-if="store.repairProposals.length > 0" class="grid gap-4">
          <li
            v-for="proposal in store.repairProposals"
            :key="proposal.id"
            class="grid gap-3 rounded-xl border border-amber-300 bg-amber-50 p-4"
          >
            <p class="m-0 font-black text-amber-950">
              {{ copy.proposalAttempt }} {{ proposal.attempt_number }} ·
              {{ proposal.failure_signature.failure_code }}
            </p>
            <p class="m-0 text-sm text-amber-950">
              {{ copy.repeated }}: {{ proposal.identical_failure_occurrences }}
            </p>
            <p class="m-0 text-sm text-amber-950">{{ proposal.change_set.rationale }}</p>
            <ul class="grid gap-2 pl-5 text-sm">
              <li v-for="change in proposal.change_set.changes" :key="change.normalized_path">
                <strong>{{ change.operation }}</strong> · {{ change.normalized_path }} ·
                <code>{{ change.content_sha256 ?? copy.none }}</code>
              </li>
            </ul>
            <label class="grid gap-1 font-bold text-amber-950">
              {{ copy.approvalId }}
              <input
                v-model="approvalIdByProposal[proposal.id]"
                type="text"
                class="rounded-lg border border-amber-400 bg-white p-2"
                autocomplete="off"
              />
            </label>
            <button
              type="button"
              class="w-fit rounded-lg bg-amber-900 px-4 py-2 font-bold text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-950"
              :disabled="applyingProposalId !== null"
              @click="applyRepair(proposal)"
            >
              {{ applyingProposalId === proposal.id ? copy.applying : copy.apply }}
            </button>
          </li>
        </ol>
        <p v-else class="m-0 text-slate-600">{{ copy.noRepairs }}</p>
      </section>
    </template>
  </section>
</template>
