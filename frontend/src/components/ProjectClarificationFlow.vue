<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { apiClient } from "@/api/client";
import type { ProjectBriefVersionResponse } from "@/api/contracts";
import {
  BRIEF_FIELDS,
  type BriefAssumptionResponse,
  type BriefField,
  type ProjectBriefGateDecisionAction,
  type ProjectWorkflowApi,
} from "@/api/workflow-contracts";
import { useAuthStore } from "@/stores/auth";
import { type AuthorizedRequest, useClarificationStore } from "@/stores/clarification";
import TwinIdentity from "./TwinIdentity.vue";
import UiButton from "./UiButton.vue";

const props = defineProps<{
  projectId: string;
  currentBrief?: Pick<ProjectBriefVersionResponse, "id" | "version_number" | "content_hash"> | null;
  api?: ProjectWorkflowApi;
  authorize?: AuthorizedRequest;
}>();

const auth = useAuthStore();
const store = useClarificationStore();
const gateTargetsBrief = computed(() => {
  if (store.gate === null) return false;
  if (props.currentBrief === null || props.currentBrief === undefined) return true;
  return (
    store.gate.artifact.artifact_id === props.currentBrief.id &&
    store.gate.artifact.version === props.currentBrief.version_number &&
    store.gate.artifact.content_hash === props.currentBrief.content_hash
  );
});
const canSubmitBrief = computed(
  () =>
    !gateTargetsBrief.value ||
    ["DRAFT", "STALE", "REVISION_REQUESTED", "REJECTED"].includes(store.gate?.status ?? ""),
);

const { t, locale } = useI18n({
  useScope: "local",
  messages: {
    en: {
      flow: {
        title: "Confirm your idea",
        intro: "Review the suggested details, then prepare your project idea for approval.",
        loading: "Updating your project…",
        assumptionsTitle: "Ideas to confirm",
        assumptionsIntro:
          "These are suggestions to fill gaps in your idea. They are only used if you accept them.",
        assumptionField: "Project detail",
        assumptionStatement: "Suggestion",
        assumptionPlaceholder: "Describe the assumption and its intended meaning.",
        createAssumption: "Add a suggestion",
        noAssumptions: "No assumptions have been proposed.",
        decisionReason: "Decision rationale",
        accept: "Accept assumption",
        reject: "Reject assumption",
        rejectIdea: "Reject idea",
        audit: "Version details",
        rejectionReasonRequired: "A rejection rationale is required.",
        gateTitle: "Confirm your project idea",
        noGate: "When your idea is complete, prepare it for your approval.",
        submitGate: "Prepare for approval",
        moreActions: "Other actions",
        gateReason: "Decision rationale",
        approve: "Approve",
        requestRevision: "Request revision",
        pause: "Pause",
        resume: "Resume",
        cancel: "Cancel",
        gateReasonRequired: "Reject and request-revision actions require a rationale.",
        missingForApproval: "Approval is blocked by these missing fields:",
        eventHistory: "Previous decisions",
        noEvents: "No decision has been recorded yet.",
        versionLabel: "Version {version}",
        statusLabel: "Status: {status}",
        error: "Could not complete the action: {detail}",
        fields: {
          name: "Name",
          description: "Description",
          problem: "Problem",
          goals: "Goals",
          target_users: "Target users",
          domain: "Domain",
          technical_constraints: "Technical constraints",
          temporal_constraints: "Temporal constraints",
          budget: "Budget",
          functional_requirements: "Functional requirements",
          non_functional_requirements: "Non-functional requirements",
          risks: "Risks",
          stakeholders: "Stakeholders",
          available_artifacts: "Available artifacts",
          definition_of_done: "When the project is complete",
        },
        statuses: {
          PROPOSED: "Proposed",
          ACCEPTED: "Accepted",
          REJECTED: "Rejected",
          DRAFT: "Draft",
          PENDING_APPROVAL: "Pending approval",
          APPROVED: "Approved",
          REVISION_REQUESTED: "Revision requested",
          PAUSED: "Paused",
          CANCELLED: "Cancelled",
          STALE: "Stale",
          PAUSED_NEEDS_HUMAN: "Paused — human intervention required",
          BRIEF_NOT_FOUND: "Project Brief not found",
          APPLIED: "Applied",
          VERSION_UNCHANGED: "No new version was required",
          CREATED: "Created",
          FIELD_ALREADY_PROVIDED: "The field already contains owner-provided information",
          ASSUMPTION_NOT_FOUND: "Assumption not found",
          ASSUMPTION_NOT_PROPOSED: "The assumption has already been decided",
          ASSUMPTION_STALE: "The assumption refers to an older brief",
          SUBMITTED: "Submitted",
          ALREADY_PENDING: "Already pending",
          ALREADY_APPROVED: "Already approved",
          BRIEF_INCOMPLETE: "Brief incomplete",
          NEW_BRIEF_REQUIRED: "A new brief version is required",
          GATE_BLOCKED: "Gate blocked",
          ITERATION_LIMIT_REACHED: "Gate iteration limit reached",
          TRANSITION_REJECTED: "Transition rejected",
          ARTIFACT_STALE: "Artifact is stale",
        },
        errors: {
          unexpected_error: "An unexpected error occurred.",
          unexpected_api_error: "The service returned an unexpected response. Please try again.",
          clarification_service_unavailable: "The clarification service is unavailable.",
          brief_gate_service_unavailable: "The Project Brief gate service is unavailable.",
        },
      },
    },
    it: {
      flow: {
        title: "Conferma la tua idea",
        intro:
          "Controlla le proposte per i dettagli mancanti, poi prepara la tua idea per l’approvazione.",
        loading: "Aggiornamento del progetto…",
        assumptionsTitle: "Idee da confermare",
        assumptionsIntro:
          "Sono proposte per completare i dettagli mancanti della tua idea. Verranno usate solo se le accetti.",
        assumptionField: "Dettaglio del progetto",
        assumptionStatement: "Proposta",
        assumptionPlaceholder: "Descrivi l'assunzione e il significato previsto.",
        createAssumption: "Aggiungi una proposta",
        noAssumptions: "Non sono state proposte assunzioni.",
        decisionReason: "Motivazione della decisione",
        accept: "Accetta proposta",
        reject: "Rifiuta proposta",
        rejectIdea: "Rifiuta idea",
        audit: "Dettagli di versione",
        rejectionReasonRequired: "Per rifiutare è richiesta una motivazione.",
        gateTitle: "Conferma la tua idea di progetto",
        noGate: "Quando la tua idea è completa, preparala per l’approvazione.",
        submitGate: "Prepara per l’approvazione",
        moreActions: "Altre azioni",
        gateReason: "Motivazione della decisione",
        approve: "Approva",
        requestRevision: "Richiedi revisione",
        pause: "Metti in pausa",
        resume: "Riprendi",
        cancel: "Annulla",
        gateReasonRequired: "Rifiuto e richiesta di revisione richiedono una motivazione.",
        missingForApproval: "L'approvazione è bloccata dai seguenti campi mancanti:",
        eventHistory: "Decisioni precedenti",
        noEvents: "Non è stata ancora registrata alcuna decisione.",
        versionLabel: "Versione {version}",
        statusLabel: "Stato: {status}",
        error: "Impossibile completare l’operazione: {detail}",
        fields: {
          name: "Nome",
          description: "Descrizione",
          problem: "Problema",
          goals: "Obiettivi",
          target_users: "A chi si rivolge",
          domain: "Contesto",
          technical_constraints: "Vincoli tecnici",
          temporal_constraints: "Scadenze",
          budget: "Budget",
          functional_requirements: "Funzionalità desiderate",
          non_functional_requirements: "Qualità attese",
          risks: "Rischi",
          stakeholders: "Persone coinvolte",
          available_artifacts: "Materiali disponibili",
          definition_of_done: "Criteri di completamento",
        },
        statuses: {
          PROPOSED: "Proposta",
          ACCEPTED: "Accettata",
          REJECTED: "Rifiutata",
          DRAFT: "Bozza",
          PENDING_APPROVAL: "In attesa di approvazione",
          APPROVED: "Approvato",
          REVISION_REQUESTED: "Revisione richiesta",
          PAUSED: "In pausa",
          CANCELLED: "Annullato",
          STALE: "Obsoleto",
          PAUSED_NEEDS_HUMAN: "In pausa — intervento umano richiesto",
          BRIEF_NOT_FOUND: "Project Brief non trovato",
          APPLIED: "Applicato",
          VERSION_UNCHANGED: "Non è stata necessaria una nuova versione",
          CREATED: "Creata",
          FIELD_ALREADY_PROVIDED: "Il campo contiene già informazioni fornite dall'owner",
          ASSUMPTION_NOT_FOUND: "Assunzione non trovata",
          ASSUMPTION_NOT_PROPOSED: "L'assunzione è già stata valutata",
          ASSUMPTION_STALE: "L'assunzione appartiene a una versione precedente",
          SUBMITTED: "Sottoposto",
          ALREADY_PENDING: "Già in attesa",
          ALREADY_APPROVED: "Già approvato",
          BRIEF_INCOMPLETE: "Brief incompleto",
          NEW_BRIEF_REQUIRED: "È richiesta una nuova versione del brief",
          GATE_BLOCKED: "Gate bloccato",
          ITERATION_LIMIT_REACHED: "Limite di iterazioni del gate raggiunto",
          TRANSITION_REJECTED: "Transizione rifiutata",
          ARTIFACT_STALE: "Artefatto obsoleto",
        },
        errors: {
          unexpected_error: "Si è verificato un errore inatteso.",
          unexpected_api_error: "Il servizio ha restituito una risposta inattesa. Riprova.",
          clarification_service_unavailable: "Il servizio di chiarificazione non è disponibile.",
          brief_gate_service_unavailable:
            "Il servizio di approvazione non è disponibile. Riprova tra poco.",
        },
      },
    },
  },
});

const resolvedApi = computed(() => props.api ?? apiClient);

const assumptionField = ref<BriefField>("description");
const assumptionStatement = ref("");
const assumptionReasons = ref<Record<string, string>>({});
const gateReason = ref("");
const localError = ref<string | null>(null);

function executeAuthorized<T>(operation: (accessToken: string) => Promise<T>): Promise<T> {
  if (props.authorize !== undefined) {
    return props.authorize(operation);
  }

  return auth.withAccessToken(apiClient, operation);
}

async function load(): Promise<void> {
  localError.value = null;

  await store.load(props.projectId, resolvedApi.value, executeAuthorized);
}

watch(
  () => props.projectId,
  async () => {
    await load();
  },
);

onMounted(load);

function translatedOrFallback(key: string, fallback: string): string {
  const translated = t(key);

  return translated === key ? fallback : translated;
}

function statusText(statusValue: string): string {
  return translatedOrFallback(`flow.statuses.${statusValue}`, statusValue);
}

function errorText(detail: string): string {
  return translatedOrFallback(`flow.errors.${detail}`, detail);
}

function fieldText(field: BriefField): string {
  return t(`flow.fields.${field}`);
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(locale.value, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

async function createAssumption(): Promise<void> {
  localError.value = null;

  const statement = assumptionStatement.value.trim();

  if (!statement) {
    localError.value = t("flow.assumptionPlaceholder");

    return;
  }

  const result = await store.createAssumption(
    props.projectId,
    {
      field: assumptionField.value,
      statement,
    },
    resolvedApi.value,
    executeAuthorized,
  );

  if (result !== null) {
    assumptionStatement.value = "";
  }
}

function assumptionReason(assumption: BriefAssumptionResponse): string {
  return (assumptionReasons.value[assumption.id] ?? "").trim();
}

async function acceptAssumption(assumption: BriefAssumptionResponse): Promise<void> {
  localError.value = null;

  await store.acceptAssumption(
    props.projectId,
    assumption.id,
    assumptionReason(assumption) || null,
    resolvedApi.value,
    executeAuthorized,
  );
}

async function rejectAssumption(assumption: BriefAssumptionResponse): Promise<void> {
  localError.value = null;

  const reason = assumptionReason(assumption);

  if (!reason) {
    localError.value = t("flow.rejectionReasonRequired");

    return;
  }

  await store.rejectAssumption(
    props.projectId,
    assumption.id,
    reason,
    resolvedApi.value,
    executeAuthorized,
  );
}

async function submitGate(): Promise<void> {
  localError.value = null;

  await store.submitGate(props.projectId, resolvedApi.value, executeAuthorized);
}

async function decideGate(action: ProjectBriefGateDecisionAction): Promise<void> {
  localError.value = null;

  const reason = gateReason.value.trim();

  if (["REJECT", "REQUEST_REVISION"].includes(action) && !reason) {
    localError.value = t("flow.gateReasonRequired");

    return;
  }

  const result = await store.decideGate(
    props.projectId,
    action,
    reason || null,
    resolvedApi.value,
    executeAuthorized,
  );

  if (result !== null) {
    gateReason.value = "";
  }
}
</script>

<template>
  <section class="grid gap-5" aria-labelledby="clarification-flow-title">
    <header class="grid gap-2">
      <TwinIdentity
        role="INTAKE_CLARIFICATION_AGENT"
        :locale="locale.startsWith('it') ? 'it' : 'en'"
        compact
      />
      <h2 id="clarification-flow-title" class="text-xl font-bold text-ink">
        {{ t("flow.title") }}
      </h2>

      <p class="m-0 max-w-3xl text-ink-2">
        {{ t("flow.intro") }}
      </p>
    </header>

    <div
      :class="
        store.busy || localError !== null || store.errorDetail !== null ? 'min-h-6' : 'sr-only'
      "
      aria-live="polite"
      aria-atomic="true"
    >
      <p v-if="store.busy" class="m-0 text-sm font-semibold text-ink-2">
        {{ t("flow.loading") }}
      </p>

      <p
        v-else-if="localError !== null || store.errorDetail !== null"
        class="m-0 rounded-panel border border-fail-line bg-fail-bg p-4 text-sm font-semibold text-fail-dark"
        role="alert"
      >
        {{
          t("flow.error", {
            detail: localError ?? errorText(store.errorDetail ?? "unexpected_error"),
          })
        }}
      </p>
    </div>

    <details
      :open="store.assumptions.some((assumption) => assumption.status === 'PROPOSED')"
      class="rounded-panel border border-line bg-white p-4"
      aria-labelledby="assumptions-title"
    >
      <summary id="assumptions-title" class="cursor-pointer font-semibold text-ink">
        {{ t("flow.assumptionsTitle") }}
      </summary>
      <div class="mt-4 grid gap-4">
        <p class="m-0 text-sm text-ink-2">
          {{ t("flow.assumptionsIntro") }}
        </p>

        <form class="grid gap-4 md:grid-cols-2" @submit.prevent="createAssumption">
          <label class="grid gap-2 font-bold text-ink-2">
            {{ t("flow.assumptionField") }}

            <select
              v-model="assumptionField"
              class="min-h-11 rounded-panel border border-field bg-white px-3 py-2 focus-visible:ring-2 focus-visible:ring-action focus-visible:outline-none"
            >
              <option v-for="field in BRIEF_FIELDS" :key="field" :value="field">
                {{ fieldText(field) }}
              </option>
            </select>
          </label>

          <label class="grid gap-2 font-bold text-ink-2">
            {{ t("flow.assumptionStatement") }}

            <textarea
              v-model="assumptionStatement"
              class="min-h-28 rounded-panel border border-field px-3 py-2 focus-visible:ring-2 focus-visible:ring-action focus-visible:outline-none"
              :placeholder="t('flow.assumptionPlaceholder')"
            ></textarea>
          </label>

          <button
            type="submit"
            class="min-h-11 rounded-panel bg-action px-4 py-2 font-bold text-white hover:bg-action-hover focus-visible:ring-2 focus-visible:ring-action focus-visible:ring-offset-2 focus-visible:outline-none disabled:opacity-60 md:col-span-2"
            :disabled="store.busy"
          >
            {{ t("flow.createAssumption") }}
          </button>
        </form>

        <ul v-if="store.assumptions.length > 0" class="grid gap-4">
          <li
            v-for="assumption in store.assumptions"
            :key="assumption.id"
            class="grid gap-3 rounded-panel border border-line p-4"
          >
            <div class="flex flex-wrap items-start justify-between gap-3">
              <div class="grid gap-1">
                <p class="m-0 font-semibold text-ink">
                  {{ fieldText(assumption.field) }}
                </p>

                <p class="m-0 text-ink-2">
                  {{ assumption.statement }}
                </p>
              </div>

              <span class="rounded-full bg-surface-3 px-3 py-1 text-xs font-semibold text-ink-2">
                {{ statusText(assumption.status) }}
              </span>
            </div>

            <template v-if="assumption.status === 'PROPOSED'">
              <label class="grid gap-2 text-sm font-bold text-ink-2">
                {{ t("flow.decisionReason") }}

                <textarea
                  v-model="assumptionReasons[assumption.id]"
                  class="min-h-20 rounded-panel border border-field px-3 py-2 focus-visible:ring-2 focus-visible:ring-action focus-visible:outline-none"
                ></textarea>
              </label>

              <div class="flex flex-wrap gap-3">
                <button
                  type="button"
                  class="min-h-11 rounded-panel bg-ok px-4 py-2 font-bold text-white hover:bg-ok-dark focus-visible:ring-2 focus-visible:ring-ok focus-visible:ring-offset-2 focus-visible:outline-none disabled:opacity-60"
                  :disabled="store.busy"
                  @click="acceptAssumption(assumption)"
                >
                  {{ t("flow.accept") }}
                </button>

                <button
                  type="button"
                  class="min-h-11 rounded-panel border border-fail-line bg-white px-4 py-2 font-bold text-fail-dark hover:bg-fail-bg focus-visible:ring-2 focus-visible:ring-fail focus-visible:ring-offset-2 focus-visible:outline-none disabled:opacity-60"
                  :disabled="store.busy"
                  @click="rejectAssumption(assumption)"
                >
                  {{ t("flow.reject") }}
                </button>
              </div>
            </template>

            <p v-else-if="assumption.decision_reason" class="m-0 text-sm text-ink-2">
              {{ assumption.decision_reason }}
            </p>
          </li>
        </ul>

        <p v-else class="m-0 text-ink-2">
          {{ t("flow.noAssumptions") }}
        </p>
      </div>
    </details>

    <section
      class="grid gap-5 rounded-card border border-line bg-white p-5 shadow-sm"
      aria-labelledby="brief-gate-title"
    >
      <header class="grid gap-1">
        <h3 id="brief-gate-title" class="text-xl font-semibold text-ink">
          {{ t("flow.gateTitle") }}
        </h3>

        <template v-if="store.gate !== null">
          <p class="m-0 text-sm text-ink-2">
            {{
              t("flow.statusLabel", {
                status: statusText(gateTargetsBrief ? store.gate.status : "STALE"),
              })
            }}
          </p>

          <details class="text-xs text-ink-3">
            <summary class="cursor-pointer">{{ t("flow.audit") }}</summary>
            <p class="mt-2 text-sm text-ink-2">
              {{
                t("flow.versionLabel", {
                  version: store.gate.artifact.version,
                })
              }}
              ·
              <code>
                {{ store.gate.artifact.content_hash.slice(0, 12) }}
              </code>
            </p>
          </details>
        </template>

        <p v-else class="m-0 text-sm text-ink-2">
          {{ t("flow.noGate") }}
        </p>
      </header>

      <div
        v-if="store.lastGateSubmission?.missing_fields.length"
        class="rounded-panel border border-line-strong bg-surface-2 p-4 text-warn"
      >
        <p class="m-0 font-bold">
          {{ t("flow.missingForApproval") }}
        </p>

        <ul class="mt-2 list-disc pl-5">
          <li v-for="field in store.lastGateSubmission.missing_fields" :key="field">
            {{ fieldText(field) }}
          </li>
        </ul>
      </div>

      <div v-if="canSubmitBrief">
        <UiButton :disabled="store.busy" @click="submitGate">{{ t("flow.submitGate") }}</UiButton>
      </div>

      <template v-if="store.gate !== null && gateTargetsBrief">
        <div v-if="store.gate.status === 'PENDING_APPROVAL'" class="flex flex-wrap gap-3">
          <UiButton :disabled="store.busy" @click="decideGate('APPROVE')">
            {{ t("flow.approve") }}
          </UiButton>
          <UiButton
            variant="secondary"
            :disabled="store.busy"
            @click="decideGate('REQUEST_REVISION')"
          >
            {{ t("flow.requestRevision") }}
          </UiButton>
        </div>

        <div v-else-if="store.gate.status === 'PAUSED'" class="flex flex-wrap gap-3">
          <UiButton :disabled="store.busy" @click="decideGate('RESUME')">
            {{ t("flow.resume") }}
          </UiButton>
          <UiButton variant="secondary" :disabled="store.busy" @click="decideGate('CANCEL')">
            {{ t("flow.cancel") }}
          </UiButton>
        </div>

        <div v-else-if="['REVISION_REQUESTED', 'PAUSED_NEEDS_HUMAN'].includes(store.gate.status)">
          <UiButton variant="secondary" :disabled="store.busy" @click="decideGate('CANCEL')">
            {{ t("flow.cancel") }}
          </UiButton>
        </div>

        <label
          v-if="['PENDING_APPROVAL', 'PAUSED'].includes(store.gate.status)"
          class="grid gap-2 text-sm font-semibold"
        >
          {{ t("flow.gateReason") }}

          <textarea
            v-model="gateReason"
            class="min-h-24 rounded-control border border-field bg-surface px-3 py-2 text-[15px] font-normal"
          ></textarea>
        </label>

        <details v-if="store.gate.status === 'PENDING_APPROVAL'" class="text-sm">
          <summary class="cursor-pointer font-semibold text-ink-2">
            {{ t("flow.moreActions") }}
          </summary>
          <div class="mt-3 flex flex-wrap gap-3">
            <UiButton variant="danger" :disabled="store.busy" @click="decideGate('REJECT')">
              {{ t("flow.rejectIdea") }}
            </UiButton>
            <UiButton variant="secondary" :disabled="store.busy" @click="decideGate('PAUSE')">
              {{ t("flow.pause") }}
            </UiButton>
          </div>
        </details>
      </template>

      <details class="text-sm">
        <summary class="cursor-pointer font-semibold text-ink-2">
          {{ t("flow.eventHistory") }}
        </summary>

        <ol v-if="store.gateEvents.length > 0" class="grid gap-3">
          <li
            v-for="event in store.gateEvents"
            :key="event.id"
            class="rounded-panel border border-line p-4"
          >
            <p class="m-0 font-bold text-ink">
              {{ statusText(event.kind) }}
            </p>

            <p class="m-0 mt-1 text-sm text-ink-2">
              {{ statusText(event.previous_status) }}
              →
              {{ statusText(event.resulting_status) }}
              ·
              {{ formatDate(event.occurred_at) }}
            </p>

            <p v-if="event.reason" class="m-0 mt-2 text-sm text-ink-2">
              {{ event.reason }}
            </p>
          </li>
        </ol>

        <p v-else class="m-0 text-ink-2">
          {{ t("flow.noEvents") }}
        </p>
      </details>
    </section>
  </section>
</template>
