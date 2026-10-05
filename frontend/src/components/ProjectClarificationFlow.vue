<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, onUpdated, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { apiClient } from "@/api/client";
import type { ProjectBriefResponse, ProjectBriefVersionResponse } from "@/api/contracts";
import {
  BRIEF_FIELDS,
  type BriefAssumptionResponse,
  type BriefField,
  type ProjectBriefGateDecisionAction,
  type ProjectWorkflowApi,
} from "@/api/workflow-contracts";
import { useAuthStore } from "@/stores/auth";
import { type AuthorizedRequest, useClarificationStore } from "@/stores/clarification";
import UiButton from "./UiButton.vue";
import UiClaimLabel from "./UiClaimLabel.vue";
import UiDecisionBar from "./UiDecisionBar.vue";
import UiTechnicalDetails from "./UiTechnicalDetails.vue";

type BriefReference = Pick<
  ProjectBriefVersionResponse,
  "id" | "version_number" | "content_hash"
> & {
  brief?: ProjectBriefResponse;
};

type BriefVersionSummary = Pick<
  ProjectBriefVersionResponse,
  "id" | "version_number" | "content_hash" | "created_at"
>;

const props = withDefaults(
  defineProps<{
    projectId: string;
    currentBrief?: BriefReference | null;
    history?: readonly BriefVersionSummary[];
    api?: ProjectWorkflowApi;
    authorize?: AuthorizedRequest;
    active?: boolean;
    sectionsMode?: boolean;
  }>(),
  { history: () => [], active: true, sectionsMode: false },
);

const emit = defineEmits<{ "sections-changed": [] }>();

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

const { t, te, locale } = useI18n({
  useScope: "local",
  messages: {
    en: {
      flow: {
        ideaTitle: "Your idea",
        loading: "Updating your project…",
        assumptionsTitle: "Proposals to decide",
        pendingRow: "Proposal waiting for your decision",
        acceptedRow: "AI proposal accepted by you",
        rejectedRow: "Left open: you will complete it later.",
        openRow: "Open point: you will complete it later.",
        counter: "Proposal {current} of {total}",
        proposalNote: "This was missing from the brief. It is used only if you accept it.",
        addReason: "Add a reason",
        hideReason: "Hide the reason",
        decisionReason: "Reason for your decision",
        reasonHint: "Optional to accept, required to leave the proposal open.",
        accept: "Accept",
        reject: "Leave open",
        acceptAll: "Accept all proposals",
        acceptAllDone: "Accepted proposals: {count}. The brief is now version {version}.",
        acceptAllSkipped: "Proposals left to decide: {count}.",
        acceptAllNothing: "There are no proposals to accept.",
        allDecided: "You decided every proposal",
        decidedSummary: "{accepted} accepted · {rejected} left open.",
        rejectionReasonRequired: "To leave a proposal open, write the reason.",
        createTitle: "Add a point yourself",
        assumptionField: "Point of the brief",
        assumptionStatement: "What you propose",
        assumptionPlaceholder: "Describe the proposal and its intended meaning.",
        createAssumption: "Add the proposal",
        gateTitle: "Your approval",
        approveInBar: "When the brief convinces you, approve it in the bar at the bottom.",
        pendingInBar: "The brief is ready: approve it or ask for changes in the bar at the bottom.",
        revisionRequested:
          "You asked for changes: update the brief and approve it again in the bar at the bottom.",
        needsHuman: "The approval has stopped because the maximum number of revisions was reached.",
        pausedText: "This step is paused.",
        pausedSection: "This section is paused.",
        moreActions: "Other decisions",
        gateReason: "Reason for your decision",
        approveBrief: "Approve the brief",
        requestPlaceholder:
          "The request is recorded with this note as its reason: then you update the brief and approve it again.",
        approveAfterPrepareFailed:
          "The brief was prepared for approval, but the approval did not go through. Press “Approve the brief” again.",
        notApproved: "The brief could not be approved: {reason}.",
        blocked: {
          GATE_BLOCKED: "a cancelled or stopped approval blocks it",
          ITERATION_LIMIT_REACHED: "the maximum number of approval attempts was reached",
          NEW_BRIEF_REQUIRED: "a new version of the brief is needed",
          TRANSITION_REJECTED: "the operation is not allowed at this point",
          BRIEF_NOT_FOUND: "the brief was not found",
        },
        barPending:
          "{count} proposals are still to decide: if you approve now, those points stay open.",
        barPendingOne: "1 proposal is still to decide: if you approve now, that point stays open.",
        barReady: "The brief is complete. Once you approve it, you can prepare the perspectives.",
        requestRevision: "Ask for changes",
        pause: "Pause",
        resume: "Resume",
        cancel: "Cancel",
        rejectIdea: "Reject the idea",
        gateReasonRequired: "Rejecting and asking for changes need a reason.",
        missingForApproval: "Approval is blocked by these missing fields:",
        eventHistory: "Previous decisions",
        noEvents: "No decision has been recorded yet.",
        versionLabel: "The decision refers to version {version} · {hash}",
        statusLabel: "Status: {status}",
        technicalSummary: "Version {number} · {state}",
        technicalApproved: "approved by you",
        technicalPending: "waiting for your decision",
        contentHash: "Content hash",
        briefVersions: "Brief versions",
        briefVersion: "Version {number} · {date}",
        error: "Could not complete the action: {detail}",
        fields: {
          name: "Name",
          description: "The idea",
          problem: "The problem",
          goals: "Goals",
          target_users: "For whom",
          domain: "Context",
          technical_constraints: "Technical constraints",
          temporal_constraints: "Timing",
          budget: "Budget",
          functional_requirements: "What it must do",
          non_functional_requirements: "Expected qualities",
          risks: "Risks",
          stakeholders: "People involved",
          available_artifacts: "Available materials",
          definition_of_done: "When it is done",
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
          SUBMITTED: "Submitted",
          ALREADY_PENDING: "Already pending",
          ALREADY_APPROVED: "Already approved",
          BRIEF_INCOMPLETE: "Brief incomplete",
          NEW_BRIEF_REQUIRED: "A new brief version is required",
          GATE_BLOCKED: "Gate blocked",
          ITERATION_LIMIT_REACHED: "Gate iteration limit reached",
          TRANSITION_REJECTED: "Transition rejected",
          ARTIFACT_STALE: "Artifact is stale",
          SUBMIT: "Prepared for approval",
          APPROVE: "Approved",
          REJECT: "Rejected",
          REQUEST_REVISION: "Changes requested",
          PAUSE: "Paused",
          RESUME: "Resumed",
          CANCEL: "Cancelled",
          ARTIFACT_SUPERSEDED: "Replaced by a new version",
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
        ideaTitle: "La tua idea",
        loading: "Aggiornamento del progetto…",
        assumptionsTitle: "Proposte da decidere",
        pendingRow: "Proposta in attesa della tua decisione",
        acceptedRow: "Proposta dell'AI accettata da te",
        rejectedRow: "Lasciato aperto: lo completerai più avanti.",
        openRow: "Punto aperto: lo completerai più avanti.",
        counter: "Proposta {current} di {total}",
        proposalNote: "Nel brief mancava questa informazione. Verrà usata solo se la accetti.",
        addReason: "Aggiungi una motivazione",
        hideReason: "Nascondi la motivazione",
        decisionReason: "Motivazione della decisione",
        reasonHint: "Facoltativa per accettare, necessaria per lasciare aperta la proposta.",
        accept: "Accetta",
        reject: "Lascia aperto",
        acceptAll: "Accetta tutte le proposte",
        acceptAllDone: "Proposte accettate: {count}. Il brief è alla versione {version}.",
        acceptAllSkipped: "Proposte lasciate da decidere: {count}.",
        acceptAllNothing: "Non ci sono proposte da accettare.",
        allDecided: "Hai deciso tutte le proposte",
        decidedSummary: "{accepted} accettate · {rejected} lasciate aperte.",
        rejectionReasonRequired: "Per lasciare aperta una proposta scrivi il motivo.",
        createTitle: "Aggiungi un punto tu",
        assumptionField: "Punto del brief",
        assumptionStatement: "Che cosa proponi",
        assumptionPlaceholder: "Descrivi la proposta e il significato previsto.",
        createAssumption: "Aggiungi la proposta",
        gateTitle: "La tua approvazione",
        approveInBar: "Quando il brief ti convince, approvalo dalla barra in fondo.",
        pendingInBar: "Il brief è pronto: approvalo o chiedi modifiche nella barra in fondo.",
        revisionRequested:
          "Hai chiesto modifiche: aggiorna il brief e approvalo di nuovo dalla barra in fondo.",
        needsHuman:
          "L'approvazione si è fermata perché è stato raggiunto il numero massimo di revisioni.",
        pausedText: "Questo passo è in pausa.",
        pausedSection: "Questa sezione è in pausa.",
        moreActions: "Altre decisioni",
        gateReason: "Motivazione della decisione",
        approveBrief: "Approva il brief",
        requestPlaceholder:
          "La richiesta resta registrata con questa nota come motivazione: poi aggiorni tu il brief e lo approvi di nuovo.",
        approveAfterPrepareFailed:
          "Il brief è stato preparato per l'approvazione, ma l'approvazione non è riuscita. Premi di nuovo «Approva il brief».",
        notApproved: "Non è stato possibile approvare il brief: {reason}.",
        blocked: {
          GATE_BLOCKED: "lo blocca un'approvazione annullata o ferma",
          ITERATION_LIMIT_REACHED:
            "è stato raggiunto il numero massimo di tentativi di approvazione",
          NEW_BRIEF_REQUIRED: "serve una nuova versione del brief",
          TRANSITION_REJECTED: "l'operazione non è ammessa in questo momento",
          BRIEF_NOT_FOUND: "il brief non è stato trovato",
        },
        barPending:
          "Restano {count} proposte da decidere: se approvi ora, quei punti restano aperti.",
        barPendingOne: "Resta 1 proposta da decidere: se approvi ora, quel punto resta aperto.",
        barReady: "Il brief è completo. Approvandolo, potrai preparare le prospettive.",
        requestRevision: "Chiedi modifiche",
        pause: "Metti in pausa",
        resume: "Riprendi",
        cancel: "Annulla",
        rejectIdea: "Rifiuta l'idea",
        gateReasonRequired: "Per rifiutare o chiedere modifiche serve una motivazione.",
        missingForApproval: "L'approvazione è bloccata dai seguenti campi mancanti:",
        eventHistory: "Decisioni precedenti",
        noEvents: "Non è stata ancora registrata alcuna decisione.",
        versionLabel: "La decisione riguarda la versione {version} · {hash}",
        statusLabel: "Stato: {status}",
        technicalSummary: "Versione {number} · {state}",
        technicalApproved: "approvata da te",
        technicalPending: "in attesa della tua decisione",
        contentHash: "Hash del contenuto",
        briefVersions: "Versioni del brief",
        briefVersion: "Versione {number} · {date}",
        error: "Impossibile completare l'operazione: {detail}",
        fields: {
          name: "Nome",
          description: "L'idea",
          problem: "Il problema",
          goals: "Obiettivi",
          target_users: "Per chi",
          domain: "Contesto",
          technical_constraints: "Vincoli tecnici",
          temporal_constraints: "Tempi",
          budget: "Budget",
          functional_requirements: "Cosa deve fare",
          non_functional_requirements: "Qualità attese",
          risks: "Rischi",
          stakeholders: "Persone coinvolte",
          available_artifacts: "Materiali disponibili",
          definition_of_done: "Quando sarà finito",
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
          FIELD_ALREADY_PROVIDED: "Il campo contiene già informazioni fornite dal proprietario",
          ASSUMPTION_NOT_FOUND: "Assunzione non trovata",
          ASSUMPTION_NOT_PROPOSED: "L'assunzione è già stata valutata",
          SUBMITTED: "Sottoposto",
          ALREADY_PENDING: "Già in attesa",
          ALREADY_APPROVED: "Già approvato",
          BRIEF_INCOMPLETE: "Brief incompleto",
          NEW_BRIEF_REQUIRED: "È richiesta una nuova versione del brief",
          GATE_BLOCKED: "Gate bloccato",
          ITERATION_LIMIT_REACHED: "Limite di iterazioni del gate raggiunto",
          TRANSITION_REJECTED: "Transizione rifiutata",
          ARTIFACT_STALE: "Artefatto obsoleto",
          SUBMIT: "Preparato per l'approvazione",
          APPROVE: "Approvato",
          REJECT: "Rifiutato",
          REQUEST_REVISION: "Modifiche richieste",
          PAUSE: "Messo in pausa",
          RESUME: "Ripreso",
          CANCEL: "Annullato",
          ARTIFACT_SUPERSEDED: "Sostituito da una nuova versione",
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
const focusId = ref<string | null>(null);
const reasonOpen = ref(false);
const focusHeading = ref<HTMLElement | null>(null);
const decisionBar = ref<InstanceType<typeof UiDecisionBar> | null>(null);
const approving = ref(false);
const errorFromBar = ref(false);
const barError = ref<string | null>(null);
const missingFields = ref<readonly BriefField[]>([]);
const root = ref<HTMLElement | null>(null);
const barTarget = ref<HTMLElement | null>(null);
const rowTarget = ref<HTMLElement | null>(null);
let visibilityObserver: ResizeObserver | null = null;

const displayOrder: readonly BriefField[] = [
  "name",
  "description",
  "problem",
  "target_users",
  "goals",
  "functional_requirements",
  "domain",
  "temporal_constraints",
  "technical_constraints",
  "budget",
  "non_functional_requirements",
  "risks",
  "stakeholders",
  "available_artifacts",
  "definition_of_done",
];

const proposed = computed(() =>
  store.assumptions.filter((assumption) => assumption.status === "PROPOSED"),
);
const proposedCount = computed(() => proposed.value.length);
const acceptedCount = computed(
  () => store.assumptions.filter((assumption) => assumption.status === "ACCEPTED").length,
);
const rejectedCount = computed(
  () => store.assumptions.filter((assumption) => assumption.status === "REJECTED").length,
);
const focus = computed<BriefAssumptionResponse | null>(
  () =>
    proposed.value.find((assumption) => assumption.id === focusId.value) ??
    proposed.value[0] ??
    null,
);
const focusPosition = computed(() =>
  focus.value === null
    ? 0
    : store.assumptions.findIndex((assumption) => assumption.id === focus.value?.id) + 1,
);
const showDecision = computed(
  () => gateTargetsBrief.value && store.gate?.status === "PENDING_APPROVAL",
);
const approvable = computed(() => showDecision.value || canSubmitBrief.value);
const contentErrorText = computed(() => {
  if (localError.value !== null) return localError.value;
  if (errorFromBar.value || store.errorDetail === null) return null;
  return t("flow.error", { detail: errorText(store.errorDetail) });
});
const decisionText = computed(() => {
  if (proposedCount.value === 0) return t("flow.barReady");
  if (proposedCount.value === 1) return t("flow.barPendingOne");
  return t("flow.barPending", { count: proposedCount.value });
});

const briefRows = computed(() => {
  const brief = props.currentBrief?.brief;
  const rows: {
    field: BriefField;
    lines: readonly string[];
    accepted: boolean;
  }[] = [];
  if (brief === undefined) return rows;
  for (const field of displayOrder) {
    const value = brief[field];
    const lines = Array.isArray(value)
      ? value
      : typeof value === "string" && value.trim() !== ""
        ? [value]
        : [];
    if (lines.length === 0) continue;
    rows.push({
      field,
      lines,
      accepted: store.assumptions.some(
        (assumption) => assumption.field === field && assumption.status === "ACCEPTED",
      ),
    });
  }
  return rows;
});
const filledFields = computed(() => new Set(briefRows.value.map((row) => row.field)));
const proposalRows = computed(() =>
  store.assumptions.filter(
    (assumption) =>
      assumption.status === "PROPOSED" ||
      (assumption.status === "REJECTED" && !filledFields.value.has(assumption.field)),
  ),
);
const openRows = computed(() => {
  const brief = props.currentBrief?.brief;
  if (brief === undefined) return [];
  const withProposal = new Set(proposalRows.value.map((assumption) => assumption.field));
  return displayOrder.filter(
    (field) =>
      !filledFields.value.has(field) &&
      !withProposal.has(field) &&
      (brief.unknown_fields.includes(field) || brief.missing_fields.includes(field)),
  );
});

const technicalSummary = computed(() => {
  const brief = props.currentBrief;
  if (brief === null || brief === undefined) return "";
  const approved = gateTargetsBrief.value && store.gate?.status === "APPROVED";
  return t("flow.technicalSummary", {
    number: brief.version_number,
    state: approved ? t("flow.technicalApproved") : t("flow.technicalPending"),
  });
});
const technicalRows = computed(() =>
  props.currentBrief
    ? [{ label: t("flow.contentHash"), value: props.currentBrief.content_hash }]
    : [],
);

const bulkAcceptanceText = computed(() => {
  const result = store.lastBulkAcceptance;

  if (result === null) return null;

  if (result.status !== "ACCEPTED" || result.brief_version === null) {
    return t("flow.acceptAllNothing");
  }

  const accepted = t("flow.acceptAllDone", {
    count: result.accepted.length,
    version: result.brief_version.version_number,
  });

  if (result.skipped.length === 0) return accepted;

  return `${accepted} ${t("flow.acceptAllSkipped", { count: result.skipped.length })}`;
});

function executeAuthorized<T>(operation: (accessToken: string) => Promise<T>): Promise<T> {
  if (props.authorize !== undefined) {
    return props.authorize(operation);
  }

  return auth.withAccessToken(apiClient, operation);
}

function changed(): void {
  emit("sections-changed");
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

watch(
  () => focus.value?.id,
  () => {
    reasonOpen.value = false;
  },
);

function shown(element: Element): boolean {
  return typeof element.checkVisibility !== "function" || element.checkVisibility();
}

function refreshBarTarget(): void {
  const element = root.value;
  const visible = element !== null && element.isConnected && shown(element);
  const target = document.getElementById("step-decision-bar");
  const row = document.getElementById("step-technical-row");
  const next = visible && target !== null && shown(target) ? target : null;
  const nextRow = visible && row !== null && shown(row) ? row : null;
  if (barTarget.value !== next) barTarget.value = next;
  if (rowTarget.value !== nextRow) rowTarget.value = nextRow;
}

async function refreshAfterRender(): Promise<void> {
  await nextTick();
  refreshBarTarget();
}

onMounted(() => {
  refreshBarTarget();
  void refreshAfterRender();
  if (typeof ResizeObserver !== "undefined" && root.value !== null) {
    visibilityObserver = new ResizeObserver(refreshBarTarget);
    visibilityObserver.observe(root.value);
  }
  void load();
});

onUpdated(refreshBarTarget);

watch(() => props.active, refreshAfterRender);

onBeforeUnmount(() => {
  visibilityObserver?.disconnect();
  visibilityObserver = null;
});

function translatedOrFallback(key: string, fallback: string): string {
  return te(key) ? t(key) : fallback;
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

async function showProposal(assumption: BriefAssumptionResponse): Promise<void> {
  focusId.value = assumption.id;
  await nextTick();
  focusHeading.value?.focus();
}

function segmentClass(assumption: BriefAssumptionResponse): string {
  if (assumption.status === "ACCEPTED") return "bg-petrol-on-night";
  if (assumption.status === "REJECTED") return "bg-on-night-3";
  if (assumption.id === focus.value?.id) return "bg-violet-on-night";
  return "bg-on-night/12";
}

async function createAssumption(): Promise<void> {
  startContentAction();
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
    changed();
  }
}

function assumptionReason(assumption: BriefAssumptionResponse): string {
  return (assumptionReasons.value[assumption.id] ?? "").trim();
}

async function acceptAssumption(assumption: BriefAssumptionResponse): Promise<void> {
  startContentAction();
  localError.value = null;

  const result = await store.acceptAssumption(
    props.projectId,
    assumption.id,
    assumptionReason(assumption) || null,
    resolvedApi.value,
    executeAuthorized,
  );

  if (result !== null) {
    changed();
  }
}

async function acceptAllAssumptions(): Promise<void> {
  startContentAction();
  localError.value = null;

  const result = await store.acceptAllAssumptions(
    props.projectId,
    null,
    resolvedApi.value,
    executeAuthorized,
  );

  if (result !== null) {
    changed();
  }
}

async function rejectAssumption(assumption: BriefAssumptionResponse): Promise<void> {
  startContentAction();
  localError.value = null;

  const reason = assumptionReason(assumption);

  if (!reason) {
    localError.value = t("flow.rejectionReasonRequired");
    reasonOpen.value = true;

    return;
  }

  const result = await store.rejectAssumption(
    props.projectId,
    assumption.id,
    reason,
    resolvedApi.value,
    executeAuthorized,
  );

  if (result !== null) {
    changed();
  }
}

async function decideGate(
  action: ProjectBriefGateDecisionAction,
  reasonText: string = gateReason.value,
): Promise<boolean> {
  localError.value = null;

  const reason = reasonText.trim();

  if (["REJECT", "REQUEST_REVISION"].includes(action) && !reason) {
    localError.value = t("flow.gateReasonRequired");

    return false;
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
    changed();
  }

  return result !== null;
}

function startContentAction(): void {
  errorFromBar.value = false;
  barError.value = null;
  missingFields.value = [];
}

function startBarAction(): void {
  localError.value = null;
  errorFromBar.value = true;
  barError.value = null;
  missingFields.value = [];
}

function storeErrorText(): string {
  return t("flow.error", { detail: errorText(store.errorDetail ?? "unexpected_error") });
}

async function decideFromCard(action: ProjectBriefGateDecisionAction): Promise<void> {
  startContentAction();
  await decideGate(action);
}

async function approveBrief(): Promise<void> {
  if (approving.value) return;
  startBarAction();
  approving.value = true;
  let prepared = false;
  try {
    if (!showDecision.value) {
      const submission = await store.submitGate(
        props.projectId,
        resolvedApi.value,
        executeAuthorized,
      );
      if (submission === null) {
        barError.value = storeErrorText();
        return;
      }
      if (!showDecision.value) {
        if (submission.status === "BRIEF_INCOMPLETE") {
          missingFields.value = submission.missing_fields;
        } else if (submission.status !== "ALREADY_APPROVED") {
          barError.value = t("flow.notApproved", {
            reason: translatedOrFallback(
              `flow.blocked.${submission.status}`,
              statusText(submission.status),
            ),
          });
        }
        return;
      }
      prepared = true;
    }
    if (!(await decideGate("APPROVE"))) {
      barError.value = prepared ? t("flow.approveAfterPrepareFailed") : storeErrorText();
    }
  } finally {
    approving.value = false;
  }
}

async function requestRevision(text: string): Promise<void> {
  startBarAction();
  if (await decideGate("REQUEST_REVISION", text)) {
    await decisionBar.value?.completeRequest();
    return;
  }
  barError.value = localError.value ?? storeErrorText();
  localError.value = null;
}
</script>

<template>
  <section
    ref="root"
    class="flex min-w-0 flex-col gap-6"
    aria-labelledby="clarification-flow-title"
  >
    <div class="flex flex-wrap items-start gap-6">
      <section
        class="min-w-0 flex-[1_1_440px] rounded-tile border border-night-line bg-night-raised px-5 py-6 sm:p-7"
        data-testid="brief-summary"
      >
        <div class="mb-5 grid gap-3">
          <h2
            id="clarification-flow-title"
            class="text-[22px] leading-tight font-semibold tracking-block text-on-night"
          >
            {{ t("flow.ideaTitle") }}
          </h2>
          <div class="flex flex-wrap gap-2">
            <UiClaimLabel kind="confirmed" />
            <UiClaimLabel v-if="proposedCount > 0" kind="hypothesis" />
          </div>
        </div>
        <dl class="flex flex-col">
          <div
            v-for="row in briefRows"
            :key="row.field"
            class="grid gap-1 border-t border-on-night/8 py-3.5 sm:grid-cols-[minmax(100px,150px)_minmax(0,1fr)] sm:gap-4"
            :data-brief-field="row.field"
          >
            <dt class="text-sm font-semibold text-on-night-3">{{ fieldText(row.field) }}</dt>
            <dd class="flex min-w-0 flex-col gap-1 text-[15px] leading-[1.55] text-on-night">
              <span v-for="(line, index) in row.lines" :key="index" class="break-words">
                {{ line }}
              </span>
              <span
                v-if="row.accepted"
                class="mt-0.5 text-[13px] font-medium text-petrol-on-night-2"
                data-testid="brief-accepted-proposal"
              >
                {{ t("flow.acceptedRow") }}
              </span>
            </dd>
          </div>
          <div
            v-for="assumption in proposalRows"
            :key="assumption.id"
            class="grid gap-1 border-t border-on-night/8 py-3.5 sm:grid-cols-[minmax(100px,150px)_minmax(0,1fr)] sm:gap-4"
            :data-brief-field="assumption.field"
          >
            <dt class="text-sm font-semibold text-on-night-3">
              {{ fieldText(assumption.field) }}
            </dt>
            <dd class="min-w-0 text-[15px] leading-[1.55]">
              <button
                v-if="assumption.status === 'PROPOSED'"
                type="button"
                :class="[
                  'min-h-11 w-full rounded-control border-[1.5px] border-dashed border-violet-on-night/70 px-3.5 py-2.5 text-left text-sm font-medium text-violet-on-night-2 transition-colors duration-150 hover:bg-violet-on-night/12',
                  assumption.id === focus?.id ? 'bg-violet-on-night/12' : 'bg-transparent',
                ]"
                :aria-current="assumption.id === focus?.id ? 'true' : undefined"
                data-testid="assumption-pending"
                @click="showProposal(assumption)"
              >
                {{ t("flow.pendingRow") }}
              </button>
              <span v-else class="block text-on-night-3" data-testid="assumption-left-open">
                {{ t("flow.rejectedRow") }}
                <span v-if="assumption.decision_reason" class="mt-1 block text-[13px]">
                  {{ assumption.decision_reason }}
                </span>
              </span>
            </dd>
          </div>
          <div
            v-for="field in openRows"
            :key="field"
            class="grid gap-1 border-t border-on-night/8 py-3.5 sm:grid-cols-[minmax(100px,150px)_minmax(0,1fr)] sm:gap-4"
            :data-brief-field="field"
          >
            <dt class="text-sm font-semibold text-on-night-3">{{ fieldText(field) }}</dt>
            <dd class="text-[15px] leading-[1.55] text-on-night-3">{{ t("flow.openRow") }}</dd>
          </div>
        </dl>
      </section>

      <aside
        class="flex min-w-0 flex-[1_1_300px] flex-col gap-3 lg:sticky lg:top-24 lg:max-w-[420px]"
        aria-labelledby="assumptions-title"
      >
        <h2 id="assumptions-title" class="sr-only">{{ t("flow.assumptionsTitle") }}</h2>

        <div
          :class="store.busy || contentErrorText !== null ? 'min-h-6' : 'sr-only'"
          aria-live="polite"
          aria-atomic="true"
        >
          <p v-if="store.busy" class="py-1 text-sm font-semibold text-on-night-2">
            {{ t("flow.loading") }}
          </p>

          <p
            v-else-if="contentErrorText !== null"
            class="rounded-field border border-fail-on-night/40 bg-fail-on-night/10 px-4 py-3 text-sm font-semibold text-fail-on-night"
            role="alert"
          >
            {{ contentErrorText }}
          </p>
        </div>

        <div
          v-if="focus !== null"
          class="grid gap-3.5 rounded-tile border-[1.5px] border-dashed border-violet-on-night/70 bg-night-raised p-5 sm:p-[22px]"
          data-claim-status="hypothesis"
          data-testid="assumption-focus"
        >
          <p class="font-mono text-xs tracking-[0.06em] text-violet-on-night-2 uppercase">
            {{ t("flow.counter", { current: focusPosition, total: store.assumptions.length }) }}
          </p>
          <div class="flex gap-1" aria-hidden="true">
            <span
              v-for="assumption in store.assumptions"
              :key="assumption.id"
              :class="['h-1.5 flex-1 rounded-[3px]', segmentClass(assumption)]"
            />
          </div>
          <h3
            ref="focusHeading"
            tabindex="-1"
            class="text-xl font-semibold tracking-[-0.01em] text-on-night"
          >
            {{ fieldText(focus.field) }}
          </h3>
          <p class="text-base leading-[1.55] break-words text-on-night">{{ focus.statement }}</p>
          <p class="text-[13px] leading-normal text-on-night-3">{{ t("flow.proposalNote") }}</p>
          <div class="grid gap-2">
            <button
              type="button"
              class="inline-flex min-h-11 items-center self-start text-sm font-semibold text-petrol-on-night-2 underline-offset-4 hover:underline"
              :aria-expanded="reasonOpen ? 'true' : 'false'"
              :aria-controls="`assumption-reason-${focus.id}`"
              data-testid="assumption-reason-toggle"
              @click="reasonOpen = !reasonOpen"
            >
              {{ reasonOpen ? t("flow.hideReason") : t("flow.addReason") }}
            </button>
            <label
              v-show="reasonOpen"
              :id="`assumption-reason-${focus.id}`"
              class="grid gap-2 text-sm font-semibold text-on-night"
            >
              {{ t("flow.decisionReason") }}
              <span class="text-[13px] font-normal text-on-night-3">
                {{ t("flow.reasonHint") }}
              </span>
              <textarea
                v-model="assumptionReasons[focus.id]"
                rows="3"
                class="min-h-20 resize-y rounded-control border border-night-line-strong bg-night-raised px-3 py-2.5 text-[15px] font-normal text-on-night placeholder:text-on-night-3"
                data-testid="assumption-reason"
              ></textarea>
            </label>
          </div>
          <div class="grid gap-2">
            <UiButton
              variant="pill"
              size="lg"
              full
              :disabled="store.busy"
              data-testid="assumption-accept"
              @click="acceptAssumption(focus)"
            >
              {{ t("flow.accept") }}
            </UiButton>
            <UiButton
              variant="outline"
              full
              :disabled="store.busy"
              data-testid="assumption-reject"
              @click="rejectAssumption(focus)"
            >
              {{ t("flow.reject") }}
            </UiButton>
          </div>
        </div>

        <div
          v-else-if="store.assumptions.length > 0"
          class="grid gap-2 rounded-tile border border-night-line-strong bg-night-raised p-5 sm:p-[22px]"
          data-testid="assumptions-decided"
        >
          <span
            aria-hidden="true"
            class="flex h-8 w-8 items-center justify-center rounded-full bg-on-night font-semibold text-ink"
          >
            ✓
          </span>
          <h3 class="mt-1.5 text-lg font-semibold text-on-night">{{ t("flow.allDecided") }}</h3>
          <p class="text-sm leading-normal text-on-night-3">
            {{ t("flow.decidedSummary", { accepted: acceptedCount, rejected: rejectedCount }) }}
          </p>
        </div>

        <button
          v-if="proposedCount >= 2"
          type="button"
          class="inline-flex min-h-11 items-center justify-center rounded-pill border border-violet-on-night bg-night-raised px-[18px] py-2 text-sm font-semibold text-violet-on-night-2 transition-colors duration-150 hover:bg-violet-on-night/14 disabled:cursor-not-allowed disabled:border-night-line disabled:text-on-night-3"
          data-testid="accept-all-assumptions"
          :disabled="store.busy"
          @click="acceptAllAssumptions"
        >
          {{ t("flow.acceptAll") }}
        </button>

        <p
          :class="
            bulkAcceptanceText === null ? 'sr-only' : 'text-sm leading-normal text-on-night-2'
          "
          data-testid="accept-all-outcome"
          aria-live="polite"
          aria-atomic="true"
        >
          {{ bulkAcceptanceText }}
        </p>

        <section
          class="grid gap-3 rounded-tile border border-night-line bg-night-raised p-5 sm:p-[22px]"
          aria-labelledby="brief-gate-title"
        >
          <h3 id="brief-gate-title" class="text-base font-semibold text-on-night">
            {{ t("flow.gateTitle") }}
          </h3>

          <p v-if="store.gate !== null" class="font-mono text-xs text-on-night-3">
            {{
              t("flow.statusLabel", {
                status: statusText(gateTargetsBrief ? store.gate.status : "STALE"),
              })
            }}
          </p>

          <p class="text-sm leading-normal text-on-night-2" data-testid="brief-gate-text">
            <template v-if="showDecision">{{ t("flow.pendingInBar") }}</template>
            <template v-else-if="gateTargetsBrief && store.gate?.status === 'REVISION_REQUESTED'">
              {{ t("flow.revisionRequested") }}
            </template>
            <template v-else-if="gateTargetsBrief && store.gate?.status === 'PAUSED_NEEDS_HUMAN'">
              {{ t("flow.needsHuman") }}
            </template>
            <template v-else-if="gateTargetsBrief && store.gate?.status === 'PAUSED'">
              {{ sectionsMode ? t("flow.pausedSection") : t("flow.pausedText") }}
            </template>
            <template v-else-if="canSubmitBrief">{{ t("flow.approveInBar") }}</template>
          </p>

          <template v-if="store.gate !== null && gateTargetsBrief">
            <div v-if="store.gate.status === 'PAUSED'" class="flex flex-wrap gap-3">
              <UiButton :disabled="store.busy" @click="decideFromCard('RESUME')">
                {{ t("flow.resume") }}
              </UiButton>
              <UiButton variant="outline" :disabled="store.busy" @click="decideFromCard('CANCEL')">
                {{ t("flow.cancel") }}
              </UiButton>
            </div>

            <div
              v-else-if="['REVISION_REQUESTED', 'PAUSED_NEEDS_HUMAN'].includes(store.gate.status)"
            >
              <UiButton variant="outline" :disabled="store.busy" @click="decideFromCard('CANCEL')">
                {{ t("flow.cancel") }}
              </UiButton>
            </div>

            <label
              v-if="store.gate.status === 'PAUSED'"
              class="grid gap-2 text-sm font-semibold text-on-night"
            >
              {{ t("flow.gateReason") }}

              <textarea
                v-model="gateReason"
                class="min-h-24 resize-y rounded-control border border-night-line-strong bg-night-raised px-3 py-2.5 text-[15px] font-normal text-on-night"
              ></textarea>
            </label>

            <details v-if="store.gate.status === 'PENDING_APPROVAL'" class="group text-sm">
              <summary
                class="flex min-h-11 cursor-pointer list-none items-center gap-2 font-semibold text-on-night-2 hover:text-on-night [&::-webkit-details-marker]:hidden"
              >
                <span
                  aria-hidden="true"
                  class="inline-block h-1.5 w-1.5 shrink-0 -rotate-45 border-r-[1.5px] border-b-[1.5px] border-on-night-3 transition-transform duration-150 group-open:rotate-45"
                />
                {{ t("flow.moreActions") }}
              </summary>
              <div class="mt-2 grid gap-3">
                <label class="grid gap-2 text-sm font-semibold text-on-night">
                  {{ t("flow.gateReason") }}

                  <textarea
                    v-model="gateReason"
                    class="min-h-24 resize-y rounded-control border border-night-line-strong bg-night-raised px-3 py-2.5 text-[15px] font-normal text-on-night"
                  ></textarea>
                </label>
                <div class="flex flex-wrap gap-3">
                  <UiButton
                    variant="danger"
                    :disabled="store.busy"
                    @click="decideFromCard('REJECT')"
                  >
                    {{ t("flow.rejectIdea") }}
                  </UiButton>
                  <UiButton
                    variant="outline"
                    :disabled="store.busy"
                    @click="decideFromCard('PAUSE')"
                  >
                    {{ t("flow.pause") }}
                  </UiButton>
                </div>
              </div>
            </details>
          </template>
        </section>

        <details
          class="group rounded-tile border border-night-line"
          data-testid="assumption-create"
        >
          <summary
            class="flex min-h-11 cursor-pointer list-none items-center gap-2 rounded-tile px-5 py-3 text-sm font-semibold text-on-night-2 hover:text-on-night [&::-webkit-details-marker]:hidden"
          >
            <span
              aria-hidden="true"
              class="inline-block h-1.5 w-1.5 shrink-0 -rotate-45 border-r-[1.5px] border-b-[1.5px] border-on-night-3 transition-transform duration-150 group-open:rotate-45"
            />
            {{ t("flow.createTitle") }}
          </summary>
          <form
            class="grid gap-4 border-t border-night-line p-5"
            @submit.prevent="createAssumption"
          >
            <label class="grid gap-2 text-sm font-semibold text-on-night">
              {{ t("flow.assumptionField") }}

              <select
                v-model="assumptionField"
                class="min-h-11 rounded-control border border-night-line-strong bg-night-panel px-3 py-2 text-[15px] font-normal text-on-night"
              >
                <option v-for="field in BRIEF_FIELDS" :key="field" :value="field">
                  {{ fieldText(field) }}
                </option>
              </select>
            </label>

            <label class="grid gap-2 text-sm font-semibold text-on-night">
              {{ t("flow.assumptionStatement") }}

              <textarea
                v-model="assumptionStatement"
                class="min-h-24 resize-y rounded-control border border-night-line-strong bg-night-raised px-3 py-2.5 text-[15px] font-normal text-on-night placeholder:text-on-night-3"
                :placeholder="t('flow.assumptionPlaceholder')"
              ></textarea>
            </label>

            <div>
              <UiButton type="submit" variant="outline" :disabled="store.busy">
                {{ t("flow.createAssumption") }}
              </UiButton>
            </div>
          </form>
        </details>
      </aside>
    </div>

    <Teleport :to="barTarget" :disabled="barTarget === null">
      <UiDecisionBar
        v-if="approvable"
        ref="decisionBar"
        :description="decisionText"
        :primary-label="t('flow.approveBrief')"
        :secondary-label="showDecision ? undefined : null"
        :request-placeholder="t('flow.requestPlaceholder')"
        :busy="store.busy || approving"
        @primary="approveBrief"
        @request="requestRevision"
      >
        <div
          v-if="barError !== null || missingFields.length > 0"
          class="mt-3 grid gap-1.5 rounded-field border border-warn-on-night/50 bg-warn-on-night/10 px-4 py-3 text-sm text-warn-on-night"
          role="alert"
          data-testid="brief-decision-problem"
        >
          <p v-if="barError !== null" class="font-semibold">{{ barError }}</p>
          <template v-if="missingFields.length > 0">
            <p class="font-semibold">{{ t("flow.missingForApproval") }}</p>
            <ul class="list-disc pl-5">
              <li v-for="field in missingFields" :key="field">{{ fieldText(field) }}</li>
            </ul>
          </template>
        </div>
      </UiDecisionBar>
    </Teleport>

    <Teleport :to="rowTarget" :disabled="rowTarget === null">
      <div v-if="currentBrief" data-testid="brief-technical-details">
        <UiTechnicalDetails :summary="technicalSummary" :rows="technicalRows">
          <div class="grid gap-5 text-on-night-2">
            <section v-if="history.length > 0" class="grid gap-2">
              <h3 class="m-0 font-mono text-[11px] tracking-label text-on-night-3 uppercase">
                {{ t("flow.briefVersions") }}
              </h3>
              <ol class="m-0 grid list-none gap-1.5 p-0">
                <li
                  v-for="version in history"
                  :key="version.id"
                  class="grid gap-0.5 sm:grid-cols-[180px_minmax(0,1fr)] sm:gap-x-5"
                  data-testid="brief-version"
                >
                  <span class="text-on-night-2">
                    {{
                      t("flow.briefVersion", {
                        number: version.version_number,
                        date: formatDate(version.created_at),
                      })
                    }}
                  </span>
                  <code class="font-mono text-xs leading-[1.6] wrap-anywhere">
                    {{ version.content_hash }}
                  </code>
                </li>
              </ol>
            </section>
            <section class="grid gap-2" data-testid="brief-decision-history">
              <h3 class="m-0 font-mono text-[11px] tracking-label text-on-night-3 uppercase">
                {{ t("flow.eventHistory") }}
              </h3>
              <p v-if="store.gate !== null" class="m-0 font-mono text-xs text-on-night-3">
                {{
                  t("flow.versionLabel", {
                    version: store.gate.artifact.version,
                    hash: store.gate.artifact.content_hash.slice(0, 12),
                  })
                }}
              </p>
              <ol v-if="store.gateEvents.length > 0" class="m-0 grid list-none gap-1.5 p-0">
                <li v-for="event in store.gateEvents" :key="event.id" class="grid gap-0.5">
                  <p class="m-0">
                    <span class="font-semibold text-on-night">{{ statusText(event.kind) }}</span>
                    · {{ statusText(event.previous_status) }} →
                    {{ statusText(event.resulting_status) }} · {{ formatDate(event.occurred_at) }}
                  </p>
                  <p v-if="event.reason" class="m-0 text-on-night-3">{{ event.reason }}</p>
                </li>
              </ol>
              <p v-else class="m-0">{{ t("flow.noEvents") }}</p>
            </section>
          </div>
        </UiTechnicalDetails>
      </div>
    </Teleport>
  </section>
</template>
