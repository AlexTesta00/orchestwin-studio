<script setup lang="ts">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  onUpdated,
  provide,
  ref,
  watch,
} from "vue";
import { useI18n } from "vue-i18n";

import { apiClient } from "@/api/client";
import type {
  AgentCatalogEntryResponse,
  AgentIdentifier,
  AgentTeamApi,
  AgentTeamGateDecisionAction,
  OwnerAgentRationaleInput,
  ProposedTeamMemberResponse,
  TeamRoleConstraintResponse,
  TeamSelectionReasonResponse,
} from "@/api/team-contracts";
import type { HumanGateEventResponse } from "@/api/workflow-contracts";
import { useAuthStore } from "@/stores/auth";
import { type TeamAuthorizedRequest, useTeamStore } from "@/stores/team";
import UiButton from "./UiButton.vue";
import UiDecisionBar from "./UiDecisionBar.vue";
import UiStateBlock from "./UiStateBlock.vue";
import UiTechnicalDetails from "./UiTechnicalDetails.vue";
import { surfaceKey, type SurfaceContext } from "./UiSurface.vue";
import { roleAvatar, roleSteps, twinIdentity } from "./twinIdentity";
import { type UpstreamValue, watchUpstream } from "./upstreamChange";

const props = withDefaults(
  defineProps<{
    projectId: string;
    api?: AgentTeamApi;
    authorize?: TeamAuthorizedRequest;
    upstream?: UpstreamValue;
    active?: boolean;
  }>(),
  { upstream: null, active: true },
);

const auth = useAuthStore();
const store = useTeamStore();

provide(
  surfaceKey,
  computed<SurfaceContext>(() => "night"),
);

const { t, te, locale } = useI18n({
  useScope: "local",
  messages: {
    en: {
      flow: {
        region: "Project team",
        countOne: "1 assistant in the team",
        countOther: "{n} assistants in the team",
        intro: "The essential roles are already included; you can add other specialists.",
        core: "Always present",
        extra: "You can add",
        worksIn: "Works in: {steps}",
        why: "Why: {reason}",
        stepNames: {
          s1: "Brief",
          s2: "Team",
          s3: "User Twins",
          s4: "Requirements",
          s5: "Design",
          s6: "Package",
        },
        tagOwner: "Added by you",
        tagSuggested: "Suggested for this project",
        tagOptional: "Optional",
        tagNew: "To be saved",
        tagRemoved: "Will be removed",
        ownerRationale: "Why would you like this specialist?",
        rationalePlaceholder: "Explain why this optional role should be added.",
        rationaleRequired: "Every newly added optional role requires an owner rationale.",
        changesPending: "You changed the team: save to create its new version.",
        discardChanges: "Undo the changes",
        saveTeam: "Save the changes",
        loading: "Updating your team…",
        preparing: "Preparing your team…",
        noProposalTitle: "The team is not ready yet",
        noProposalText: "Ask the Studio to propose the assistants that suit your brief.",
        outdatedTitle: "The brief changed",
        outdatedText: "The team was chosen for an earlier brief: propose it again.",
        briefFirst: "Approve the brief first: the team is chosen from the approved brief.",
        generate: "Propose the team",
        regenerate: "Propose the team again",
        refresh: "Refresh",
        retry: "Try again",
        constraintIssues: "The brief contains contradictory role signals.",
        workersOne: "1 assistant will work on the project.",
        workersOther: "{n} assistants will work on the project.",
        decisionApprove: "{workers} You can change the team later.",
        decisionResume: "You paused this decision. Resume it when you are ready.",
        saveFirst: "Save the changes to the team before deciding.",
        requestPlaceholder:
          "Write what you would change in the team: the note stays in the history of the decisions.",
        approve: "Approve the team",
        resume: "Resume the decision",
        otherDecisions: "Other decisions",
        gateReason: "Reason for your decision",
        gateReasonHint: "Needed to reject the team.",
        reject: "Reject the team",
        pause: "Pause the decision",
        cancel: "Cancel the decision",
        gateReasonRequired: "Reject and request-revision actions require a rationale.",
        revisionRequested:
          "You asked for changes. Switch the optional specialists and save: the new version comes back for your approval.",
        revisionNote: "Your note: “{note}”",
        pausedNeedsHuman: "The decision is stopped and needs your intervention.",
        cancelled: "You cancelled this decision. Change the team to prepare a new one.",
        rejected: "You rejected this team. Change it to prepare a new version.",
        technicalSummary: "Version {number} · {state}",
        stateApproved: "approved",
        statePending: "waiting for your decision",
        stateDraft: "being prepared",
        platform: "Always active in the Studio",
        reasonsTitle: "Why these roles",
        unavailable: "Not available for this project",
        proposalHistory: "Team proposal history",
        eventHistory: "Previous decisions",
        noHistory: "No team proposal version is available.",
        noEvents: "No Gate 2 event has been recorded.",
        agentsCount: "{n} roles",
        version: "Version {number}",
        revision: "Revision",
        basedOn: "Based on version",
        provider: "Provider",
        briefVersion: "Project Brief version",
        catalogVersion: "Agent catalog version",
        contentHash: "Team content hash",
        constraintsHash: "Constraint hash",
        gateStatus: "Approval",
        decisionCounter: "Decision {n} of {max}",
        evidenceFields: "Brief fields",
        evidenceTerms: "Matched terms",
        capabilities: "Capabilities",
        source: "Source",
        latestOperation: "Latest operation",
        operations: {
          CREATED: "The team has been prepared.",
          UPDATED: "The team has been updated.",
          UNCHANGED: "The team did not change.",
          SUBMITTED: "The team has been sent for approval.",
          ALREADY_PENDING: "The team is already waiting for your approval.",
          ALREADY_APPROVED: "The team is already approved.",
          APPLIED: "Your decision on the team has been recorded.",
          REJECTED: "The request was not accepted: the team stayed as it was.",
          PROJECT_NOT_FOUND: "The project was not found: the team did not change.",
          BRIEF_NOT_FOUND: "The brief of the project was not found: the team did not change.",
          BRIEF_NOT_APPROVED: "The brief is not approved yet: the team did not change.",
          BLOCKED_BY_CONSTRAINTS:
            "The team was not prepared: the brief asks for roles that contradict each other.",
          CONTEXT_CHANGED:
            "The project changed during the request: the team did not change. Try again.",
          INVALID_PROPOSAL: "The proposal of the model was not valid: the team did not change.",
          PROPOSAL_NOT_FOUND: "There is no proposed team yet.",
          PROPOSAL_STALE: "The team was prepared for an earlier brief: propose it again.",
          NEW_PROPOSAL_REQUIRED: "The team needs a new proposal before it can be approved.",
          GATE_BLOCKED: "The decision on the team is blocked: the team was not sent for approval.",
          ITERATION_LIMIT_REACHED:
            "The team reached the maximum number of revisions: it cannot go back for approval.",
          TRANSITION_REJECTED: "In its current state the team cannot be sent for approval.",
          GATE_NOT_FOUND: "There is no open decision on the team.",
          ARTIFACT_STALE:
            "The team changed in the meantime: the decision was not applied. Check the current version.",
        },
        error: "Agent Team error: {detail}",
        constraints: {
          MANDATORY: "Essential",
          OPTIONAL: "Optional",
          IMPOSSIBLE: "Not available for this project",
          CONFLICT: "Conflict",
          NOT_EVALUATED: "Not evaluated",
        },
        sources: {
          DETERMINISTIC_MANDATORY: "Required by the project",
          PROPOSER_SUGGESTED: "Suggested by the model",
          OWNER_ADDED: "Added by you",
        },
        revisions: {
          PROPOSER_GENERATED: "Generated proposal",
          OWNER_EDITED: "Owner edited",
        },
        statuses: {
          CREATED: "Created",
          UPDATED: "Updated",
          UNCHANGED: "Unchanged",
          REJECTED: "Rejected",
          PROJECT_NOT_FOUND: "Project not found",
          BRIEF_NOT_FOUND: "Project Brief not found",
          BRIEF_NOT_APPROVED: "Gate 1 approval required",
          BLOCKED_BY_CONSTRAINTS: "Blocked by contradictory constraints",
          CONTEXT_CHANGED: "Project context changed",
          INVALID_PROPOSAL: "Invalid provider output",
          PROPOSAL_NOT_FOUND: "Team proposal not found",
          PROPOSAL_STALE: "Team proposal is stale",
          SUBMITTED: "Submitted",
          ALREADY_PENDING: "Already pending approval",
          ALREADY_APPROVED: "Already approved",
          NEW_PROPOSAL_REQUIRED: "A new proposal is required",
          GATE_BLOCKED: "Gate blocked",
          GATE_NOT_FOUND: "Gate not found",
          ITERATION_LIMIT_REACHED: "Gate iteration limit reached",
          TRANSITION_REJECTED: "Transition rejected",
          APPLIED: "Applied",
          ARTIFACT_STALE: "Approved artifact is stale",
          DRAFT: "Draft",
          PENDING_APPROVAL: "Pending approval",
          APPROVED: "Approved",
          REVISION_REQUESTED: "Revision requested",
          PAUSED: "Paused",
          CANCELLED: "Cancelled",
          STALE: "Stale",
          PAUSED_NEEDS_HUMAN: "Paused — human intervention required",
          BRIEF_APPROVAL_REQUIRED: "Project Brief approval required",
          TEAM_PROPOSAL_REQUIRED: "Team proposal required",
          TEAM_APPROVAL_REQUIRED: "Agent Team approval required",
          READY_FOR_MAIN_WORKFLOW: "Team approved",
          SUBMIT: "Submitted",
          APPROVE: "Approved",
          REJECT: "Rejected",
          REQUEST_REVISION: "Revision requested",
          PAUSE: "Paused",
          RESUME: "Resumed",
          CANCEL: "Cancelled",
          ARTIFACT_SUPERSEDED: "Artifact superseded",
        },
        errors: {
          gate_state_conflict:
            "The gate changed during the request. Refresh the team and review its current state.",
          PROVIDER_UNAVAILABLE:
            "The proposal model is unavailable. Check model availability and try again.",
          TIMEOUT: "The model exceeded the time limit. No proposal was substituted.",
          invalid_request: "Check the decision and its reason (at most 2000 characters).",
          unexpected_error: "An unexpected error occurred.",
          unexpected_api_error: "The API returned an unexpected response.",
          team_proposal_not_found: "No team proposal was found.",
          agent_team_gate_not_found: "No Agent Team gate was found.",
          team_proposal_service_unavailable: "The team-proposal service is unavailable.",
          agent_team_service_unavailable: "The Agent Team service is unavailable.",
        },
        reasons: {
          CATALOG_ALWAYS_PRESENT: "Always-present platform component",
          CATALOG_MODE_INCOMPATIBLE: "Incompatible with the project mode",
          CORE_REQUIREMENTS_DISCIPLINE: "Core requirements discipline",
          CORE_USER_CENTERED_DESIGN: "Core user-centered design discipline",
          CORE_ARCHITECTURE_DISCIPLINE: "Core architecture discipline",
          CORE_QUALITY_DISCIPLINE: "Core quality and testing discipline",
          CORE_ACCESSIBILITY_DISCIPLINE: "Accessibility is part of every project",
          BROWNFIELD_INTEGRATION: "Brownfield integration is required",
          USER_INTERFACE_SIGNAL: "The brief requires a user interface",
          WEB_DELIVERY_SIGNAL: "The brief requires web delivery",
          BACKEND_DELIVERY_SIGNAL: "The brief requires backend delivery",
          MOBILE_DELIVERY_SIGNAL: "The brief requires mobile delivery",
          EXTERNAL_INTEGRATION_SIGNAL: "The brief requires external integration",
          SECURITY_SENSITIVITY_SIGNAL: "The brief contains security-sensitive requirements",
          ACCESSIBILITY_REQUIREMENT_SIGNAL: "The brief contains accessibility requirements",
          EXPLICIT_SCOPE_EXCLUSION: "The brief explicitly excludes this role",
        },
        capabilitiesMap: {
          WORKFLOW_ORCHESTRATION: "Workflow orchestration",
          GOVERNED_ROUTING: "Governed routing",
          PROJECT_INTAKE: "Project intake",
          BRIEF_CLARIFICATION: "Brief clarification",
          TEAM_SELECTION: "Team selection",
          HUMAN_APPROVAL: "Human approval",
          ARTIFACT_MANAGEMENT: "Artifact management",
          PROVENANCE_MANAGEMENT: "Provenance management",
          SANDBOX_CONTROL: "Sandbox control",
          REQUIREMENTS_ANALYSIS: "Requirements analysis",
          ACCEPTANCE_CRITERIA: "Acceptance criteria",
          USER_RESEARCH: "User research",
          USER_MODELING: "User modeling",
          UX_DESIGN: "UX design",
          UI_DESIGN: "UI design",
          SOFTWARE_ARCHITECTURE: "Software architecture",
          FRONTEND_ENGINEERING: "Frontend engineering",
          BACKEND_ENGINEERING: "Backend engineering",
          MOBILE_ENGINEERING: "Mobile engineering",
          QUALITY_ASSURANCE: "Quality assurance",
          TEST_ENGINEERING: "Test engineering",
          SECURITY_REVIEW: "Security review",
          ACCESSIBILITY_REVIEW: "Accessibility review",
          SYSTEM_INTEGRATION: "System integration",
        },
      },
    },
    it: {
      flow: {
        region: "Squadra del progetto",
        countOne: "1 assistente nella squadra",
        countOther: "{n} assistenti nella squadra",
        intro: "I ruoli essenziali sono già inclusi; puoi aggiungere altri specialisti.",
        core: "Sempre presenti",
        extra: "Puoi aggiungere",
        worksIn: "Lavora in: {steps}",
        why: "Perché: {reason}",
        stepNames: {
          s1: "Brief",
          s2: "Squadra",
          s3: "User Twin",
          s4: "Requisiti",
          s5: "Design",
          s6: "Pacchetto",
        },
        tagOwner: "Aggiunto da te",
        tagSuggested: "Suggerito per questo progetto",
        tagOptional: "Facoltativo",
        tagNew: "Da salvare",
        tagRemoved: "Verrà tolto",
        ownerRationale: "Perché vuoi questo specialista?",
        rationalePlaceholder: "Spiega perché questo ruolo opzionale deve essere aggiunto.",
        rationaleRequired: "Ogni nuovo ruolo opzionale richiede una motivazione dell'owner.",
        changesPending: "Hai cambiato la squadra: salva per crearne la nuova versione.",
        discardChanges: "Annulla le modifiche",
        saveTeam: "Salva le modifiche",
        loading: "Aggiornamento della squadra…",
        preparing: "Preparo la squadra…",
        noProposalTitle: "La squadra non è ancora pronta",
        noProposalText: "Chiedi allo Studio di proporre gli assistenti adatti al tuo brief.",
        outdatedTitle: "Il brief è cambiato",
        outdatedText: "La squadra era stata scelta per un brief precedente: proponila di nuovo.",
        briefFirst: "Approva prima il brief: la squadra nasce dal brief approvato.",
        generate: "Proponi la squadra",
        regenerate: "Proponi di nuovo la squadra",
        refresh: "Aggiorna",
        retry: "Riprova",
        constraintIssues: "Il brief contiene segnali contraddittori relativi ai ruoli.",
        workersOne: "1 assistente lavorerà al progetto.",
        workersOther: "{n} assistenti lavoreranno al progetto.",
        decisionApprove: "{workers} Potrai cambiare la squadra più avanti.",
        decisionResume: "Hai messo in pausa questa decisione. Riprendila quando sei pronto.",
        saveFirst: "Salva le modifiche alla squadra prima di decidere.",
        requestPlaceholder:
          "Scrivi che cosa cambieresti nella squadra: la nota resta nella cronologia delle decisioni.",
        approve: "Approva la squadra",
        resume: "Riprendi la decisione",
        otherDecisions: "Altre decisioni",
        gateReason: "Motivazione della decisione",
        gateReasonHint: "Serve per rifiutare la squadra.",
        reject: "Rifiuta la squadra",
        pause: "Metti in pausa la decisione",
        cancel: "Annulla la decisione",
        gateReasonRequired: "Rifiuto e richiesta di revisione richiedono una motivazione.",
        revisionRequested:
          "Hai chiesto modifiche. Cambia gli specialisti facoltativi e salva: la nuova versione tornerà alla tua approvazione.",
        revisionNote: "La tua nota: «{note}»",
        pausedNeedsHuman: "La decisione è ferma e serve il tuo intervento.",
        cancelled: "Hai annullato questa decisione. Cambia la squadra per prepararne una nuova.",
        rejected: "Hai rifiutato questa squadra. Cambiala per prepararne una nuova versione.",
        technicalSummary: "Versione {number} · {state}",
        stateApproved: "approvata",
        statePending: "in attesa della tua decisione",
        stateDraft: "in preparazione",
        platform: "Sempre attivi nello Studio",
        reasonsTitle: "Perché questi ruoli",
        unavailable: "Non disponibili per questo progetto",
        proposalHistory: "Cronologia delle proposte del team",
        eventHistory: "Decisioni precedenti",
        noHistory: "Non è disponibile alcuna versione della proposta del team.",
        noEvents: "Non è stato ancora registrato alcun evento Gate 2.",
        agentsCount: "{n} ruoli",
        version: "Versione {number}",
        revision: "Revisione",
        basedOn: "Basata sulla versione",
        provider: "Provider",
        briefVersion: "Versione del Project Brief",
        catalogVersion: "Versione del catalogo agenti",
        contentHash: "Hash del contenuto del team",
        constraintsHash: "Hash dei vincoli",
        gateStatus: "Approvazione",
        decisionCounter: "Decisione {n} di {max}",
        evidenceFields: "Campi del brief",
        evidenceTerms: "Termini rilevati",
        capabilities: "Capacità",
        source: "Origine",
        latestOperation: "Ultima operazione",
        operations: {
          CREATED: "La squadra è stata preparata.",
          UPDATED: "La squadra è stata aggiornata.",
          UNCHANGED: "La squadra non è cambiata.",
          SUBMITTED: "La squadra è stata mandata in approvazione.",
          ALREADY_PENDING: "La squadra aspetta già la tua approvazione.",
          ALREADY_APPROVED: "La squadra è già approvata.",
          APPLIED: "La tua decisione sulla squadra è stata registrata.",
          REJECTED: "La richiesta non è stata accettata: la squadra è rimasta com'era.",
          PROJECT_NOT_FOUND: "Il progetto non è stato trovato: la squadra non è cambiata.",
          BRIEF_NOT_FOUND: "Il brief del progetto non è stato trovato: la squadra non è cambiata.",
          BRIEF_NOT_APPROVED: "Il brief non è ancora approvato: la squadra non è cambiata.",
          BLOCKED_BY_CONSTRAINTS:
            "La squadra non è stata preparata: il brief chiede ruoli che si contraddicono.",
          CONTEXT_CHANGED:
            "Il progetto è cambiato durante la richiesta: la squadra non è cambiata. Riprova.",
          INVALID_PROPOSAL: "La proposta del modello non era valida: la squadra non è cambiata.",
          PROPOSAL_NOT_FOUND: "Non c'è ancora una squadra proposta.",
          PROPOSAL_STALE:
            "La squadra era stata preparata per un brief precedente: proponila di nuovo.",
          NEW_PROPOSAL_REQUIRED: "Prima di approvare la squadra serve una nuova proposta.",
          GATE_BLOCKED:
            "La decisione sulla squadra è bloccata: la squadra non è stata mandata in approvazione.",
          ITERATION_LIMIT_REACHED:
            "La squadra ha raggiunto il numero massimo di revisioni: non può tornare in approvazione.",
          TRANSITION_REJECTED:
            "Nello stato attuale la squadra non può essere mandata in approvazione.",
          GATE_NOT_FOUND: "Non c'è una decisione aperta sulla squadra.",
          ARTIFACT_STALE:
            "La squadra è cambiata nel frattempo: la decisione non è stata applicata. Controlla la versione attuale.",
        },
        error: "Errore dell'Agent Team: {detail}",
        constraints: {
          MANDATORY: "Essenziale",
          OPTIONAL: "Opzionale",
          IMPOSSIBLE: "Non disponibile per questo progetto",
          CONFLICT: "Conflitto",
          NOT_EVALUATED: "Non valutato",
        },
        sources: {
          DETERMINISTIC_MANDATORY: "Richiesto dal progetto",
          PROPOSER_SUGGESTED: "Suggerito dal modello",
          OWNER_ADDED: "Aggiunto da te",
        },
        revisions: {
          PROPOSER_GENERATED: "Proposta generata",
          OWNER_EDITED: "Modificata dall'owner",
        },
        statuses: {
          CREATED: "Creata",
          UPDATED: "Aggiornata",
          UNCHANGED: "Invariata",
          REJECTED: "Rifiutata",
          PROJECT_NOT_FOUND: "Progetto non trovato",
          BRIEF_NOT_FOUND: "Project Brief non trovato",
          BRIEF_NOT_APPROVED: "È richiesta l'approvazione di Gate 1",
          BLOCKED_BY_CONSTRAINTS: "Bloccata da vincoli contraddittori",
          CONTEXT_CHANGED: "Il contesto del progetto è cambiato",
          INVALID_PROPOSAL: "Output del provider non valido",
          PROPOSAL_NOT_FOUND: "Proposta del team non trovata",
          PROPOSAL_STALE: "La proposta del team è obsoleta",
          SUBMITTED: "Sottoposto",
          ALREADY_PENDING: "Già in attesa di approvazione",
          ALREADY_APPROVED: "Già approvato",
          NEW_PROPOSAL_REQUIRED: "È richiesta una nuova proposta",
          GATE_BLOCKED: "Gate bloccato",
          GATE_NOT_FOUND: "Gate non trovato",
          ITERATION_LIMIT_REACHED: "Limite di iterazioni del gate raggiunto",
          TRANSITION_REJECTED: "Transizione rifiutata",
          APPLIED: "Applicata",
          ARTIFACT_STALE: "L'artefatto approvato è obsoleto",
          DRAFT: "Bozza",
          PENDING_APPROVAL: "In attesa di approvazione",
          APPROVED: "Approvato",
          REVISION_REQUESTED: "Revisione richiesta",
          PAUSED: "In pausa",
          CANCELLED: "Annullato",
          STALE: "Obsoleto",
          PAUSED_NEEDS_HUMAN: "In pausa — intervento umano richiesto",
          BRIEF_APPROVAL_REQUIRED: "È richiesta l'approvazione del Project Brief",
          TEAM_PROPOSAL_REQUIRED: "È richiesta una proposta del team",
          TEAM_APPROVAL_REQUIRED: "È richiesta l'approvazione dell'Agent Team",
          READY_FOR_MAIN_WORKFLOW: "Team approvato",
          SUBMIT: "Sottoposto",
          APPROVE: "Approvato",
          REJECT: "Rifiutato",
          REQUEST_REVISION: "Revisione richiesta",
          PAUSE: "Messo in pausa",
          RESUME: "Ripreso",
          CANCEL: "Annullato",
          ARTIFACT_SUPERSEDED: "Artefatto sostituito",
        },
        errors: {
          gate_state_conflict:
            "Il gate è cambiato durante la richiesta. Aggiorna il team e controlla lo stato corrente.",
          PROVIDER_UNAVAILABLE:
            "Il modello delle proposte non è disponibile. Verifica lo stato dei modelli e riprova.",
          TIMEOUT:
            "Il modello ha superato il tempo disponibile. Non è stata sostituita alcuna proposta.",
          invalid_request: "Controlla la decisione e la motivazione (massimo 2000 caratteri).",
          unexpected_error: "Si è verificato un errore inatteso.",
          unexpected_api_error: "L'API ha restituito una risposta inattesa.",
          team_proposal_not_found: "Non è stata trovata alcuna proposta del team.",
          agent_team_gate_not_found: "Non è stato trovato alcun Gate 2.",
          team_proposal_service_unavailable: "Il servizio di proposta del team non è disponibile.",
          agent_team_service_unavailable: "Il servizio Agent Team non è disponibile.",
        },
        reasons: {
          CATALOG_ALWAYS_PRESENT: "Componente di piattaforma sempre presente",
          CATALOG_MODE_INCOMPATIBLE: "Incompatibile con la modalità del progetto",
          CORE_REQUIREMENTS_DISCIPLINE: "Disciplina fondamentale dei requisiti",
          CORE_USER_CENTERED_DESIGN: "Disciplina fondamentale di User-Centered Design",
          CORE_ARCHITECTURE_DISCIPLINE: "Disciplina fondamentale di architettura",
          CORE_QUALITY_DISCIPLINE: "Disciplina fondamentale di qualità e testing",
          CORE_ACCESSIBILITY_DISCIPLINE: "L'accessibilità fa parte di ogni progetto",
          BROWNFIELD_INTEGRATION: "È richiesta l'integrazione brownfield",
          USER_INTERFACE_SIGNAL: "Il brief richiede un'interfaccia utente",
          WEB_DELIVERY_SIGNAL: "Il brief richiede una soluzione web",
          BACKEND_DELIVERY_SIGNAL: "Il brief richiede un backend",
          MOBILE_DELIVERY_SIGNAL: "Il brief richiede una soluzione mobile",
          EXTERNAL_INTEGRATION_SIGNAL: "Il brief richiede integrazioni esterne",
          SECURITY_SENSITIVITY_SIGNAL: "Il brief contiene requisiti sensibili per la sicurezza",
          ACCESSIBILITY_REQUIREMENT_SIGNAL: "Il brief contiene requisiti di accessibilità",
          EXPLICIT_SCOPE_EXCLUSION: "Il brief esclude esplicitamente questo ruolo",
        },
        capabilitiesMap: {
          WORKFLOW_ORCHESTRATION: "Orchestrazione del workflow",
          GOVERNED_ROUTING: "Routing governato",
          PROJECT_INTAKE: "Acquisizione del progetto",
          BRIEF_CLARIFICATION: "Chiarificazione del brief",
          TEAM_SELECTION: "Selezione del team",
          HUMAN_APPROVAL: "Approvazione umana",
          ARTIFACT_MANAGEMENT: "Gestione degli artefatti",
          PROVENANCE_MANAGEMENT: "Gestione della provenienza",
          SANDBOX_CONTROL: "Controllo della sandbox",
          REQUIREMENTS_ANALYSIS: "Analisi dei requisiti",
          ACCEPTANCE_CRITERIA: "Criteri di accettazione",
          USER_RESEARCH: "Ricerca con gli utenti",
          USER_MODELING: "Modellazione degli utenti",
          UX_DESIGN: "Progettazione UX",
          UI_DESIGN: "Progettazione UI",
          SOFTWARE_ARCHITECTURE: "Architettura software",
          FRONTEND_ENGINEERING: "Sviluppo frontend",
          BACKEND_ENGINEERING: "Sviluppo backend",
          MOBILE_ENGINEERING: "Sviluppo mobile",
          QUALITY_ASSURANCE: "Assicurazione della qualità",
          TEST_ENGINEERING: "Ingegneria del testing",
          SECURITY_REVIEW: "Revisione della sicurezza",
          ACCESSIBILITY_REVIEW: "Revisione dell'accessibilità",
          SYSTEM_INTEGRATION: "Integrazione dei sistemi",
        },
      },
    },
  },
});

type TeamDecision = "approve" | "resume";

const SIGNAL_REASONS = new Set([
  "BROWNFIELD_INTEGRATION",
  "USER_INTERFACE_SIGNAL",
  "WEB_DELIVERY_SIGNAL",
  "BACKEND_DELIVERY_SIGNAL",
  "MOBILE_DELIVERY_SIGNAL",
  "EXTERNAL_INTEGRATION_SIGNAL",
  "SECURITY_SENSITIVITY_SIGNAL",
  "ACCESSIBILITY_REQUIREMENT_SIGNAL",
]);

const resolvedApi = computed(() => props.api ?? apiClient);

const selectedDraft = ref<Partial<Record<AgentIdentifier, boolean>>>({});
const rationaleDraft = ref<Partial<Record<AgentIdentifier, string>>>({});
const gateReason = ref("");
const localError = ref<string | null>(null);
const approving = ref(false);
const root = ref<HTMLElement | null>(null);
const barTarget = ref<HTMLElement | null>(null);
const rowTarget = ref<HTMLElement | null>(null);
const decisionBar = ref<InstanceType<typeof UiDecisionBar> | null>(null);
let visibilityObserver: ResizeObserver | null = null;

const uiLocale = computed<"it" | "en">(() => (locale.value.startsWith("it") ? "it" : "en"));

const initialSelected = computed(() => new Set(store.currentVersion?.selected_agent_ids ?? []));
const hasTeamChanges = computed(() => {
  if (store.currentVersion === null) return false;
  const selected = selectedAgentIds();
  return (
    selected.length !== initialSelected.value.size ||
    selected.some((id) => !initialSelected.value.has(id))
  );
});
const gateTargetsCurrentVersion = computed(() => {
  const version = store.currentVersion;
  const artifact = store.gate?.artifact;
  return (
    version !== null &&
    artifact !== undefined &&
    artifact.artifact_id === version.id &&
    artifact.version === version.version_number &&
    artifact.content_hash === version.content_hash
  );
});
const canSubmitGate = computed(() => {
  if (store.currentVersion === null) return false;
  if (store.gate === null) return true;
  if (["CANCELLED", "PAUSED_NEEDS_HUMAN"].includes(store.gate.status)) return false;
  return !gateTargetsCurrentVersion.value || store.gate.status === "DRAFT";
});

const latestOperationStatus = computed(
  () =>
    store.lastGateDecision?.status ??
    store.lastGateSubmission?.status ??
    store.lastEdit?.status ??
    store.lastGeneration?.status ??
    null,
);

const specialists = computed(
  () => store.catalog?.agents.filter((entry) => entry.kind === "SPECIALIST") ?? [],
);
const platformAgents = computed(
  () => store.catalog?.agents.filter((entry) => entry.kind !== "SPECIALIST") ?? [],
);
const coreRoles = computed(() =>
  specialists.value.filter((entry) => isSelected(entry.agent_id) && !canEditRole(entry.agent_id)),
);
const extraRoles = computed(() => specialists.value.filter((entry) => canEditRole(entry.agent_id)));
const unavailableRoles = computed(() =>
  specialists.value.filter((entry) => !isSelected(entry.agent_id) && !canEditRole(entry.agent_id)),
);
const teamCount = computed(
  () => specialists.value.filter((entry) => isSelected(entry.agent_id)).length,
);
const countLabel = computed(() =>
  teamCount.value === 1 ? t("flow.countOne") : t("flow.countOther", { n: teamCount.value }),
);

const briefApprovalRequired = computed(() => store.readiness?.status === "BRIEF_APPROVAL_REQUIRED");
const proposalOutdated = computed(
  () => store.currentVersion !== null && store.readiness?.status === "TEAM_PROPOSAL_REQUIRED",
);
const teamApproved = computed(
  () =>
    store.readiness?.status === "READY_FOR_MAIN_WORKFLOW" &&
    store.gate?.status === "APPROVED" &&
    gateTargetsCurrentVersion.value,
);
const initialLoading = computed(() => store.busy && store.catalog === null);

const gatePending = computed(
  () => store.gate?.status === "PENDING_APPROVAL" && gateTargetsCurrentVersion.value,
);
const gatePaused = computed(
  () => store.gate?.status === "PAUSED" && gateTargetsCurrentVersion.value,
);

const decision = computed<TeamDecision | null>(() => {
  if (store.currentVersion === null || proposalOutdated.value || briefApprovalRequired.value) {
    return null;
  }
  if (gatePending.value) return "approve";
  if (gatePaused.value) return "resume";
  return canSubmitGate.value ? "approve" : null;
});

const requestAvailable = computed(() => decision.value === "approve" && gatePending.value);

const barBusy = computed(() => store.busy || approving.value);

const decisionCopy = computed(() => {
  if (decision.value === "resume") {
    return { primary: t("flow.resume"), description: t("flow.decisionResume") };
  }
  const n = teamCount.value;
  const workers = n === 1 ? t("flow.workersOne") : t("flow.workersOther", { n });
  return {
    primary: t("flow.approve"),
    description: hasTeamChanges.value
      ? t("flow.saveFirst")
      : t("flow.decisionApprove", { workers }),
  };
});

const gateNotice = computed(() => {
  const gate = store.gate;
  if (gate === null || decision.value !== null) return null;
  const notices: Record<string, string> = {
    REVISION_REQUESTED: t("flow.revisionRequested"),
    PAUSED_NEEDS_HUMAN: t("flow.pausedNeedsHuman"),
    CANCELLED: t("flow.cancelled"),
    REJECTED: t("flow.rejected"),
  };
  return notices[gate.status] ?? null;
});

const revisionNote = computed(() => {
  if (store.gate?.status !== "REVISION_REQUESTED") return null;
  const event = [...store.gateEvents].reverse().find((item) => item.kind === "REQUEST_REVISION");
  return event?.reason ?? null;
});

const cancelAvailable = computed(
  () =>
    store.gate !== null &&
    ["PAUSED", "REVISION_REQUESTED", "PAUSED_NEEDS_HUMAN"].includes(store.gate.status),
);

const resumeElsewhere = computed(
  () => store.gate?.status === "PAUSED" && decision.value !== "resume",
);

const reasonAvailable = computed(
  () =>
    gateTargetsCurrentVersion.value &&
    ["PENDING_APPROVAL", "PAUSED"].includes(store.gate?.status ?? ""),
);

const operationSentence = computed(() => {
  const status = latestOperationStatus.value;
  if (status === null || !te(`flow.operations.${status}`)) return null;
  return t(`flow.operations.${status}`);
});

const technicalSummary = computed(() => {
  const version = store.currentVersion;
  if (version === null) return "";
  const state = teamApproved.value
    ? t("flow.stateApproved")
    : decision.value !== null
      ? t("flow.statePending")
      : t("flow.stateDraft");
  return t("flow.technicalSummary", { number: version.version_number, state });
});

const technicalRows = computed(() => {
  const version = store.currentVersion;
  if (version === null) return [];
  const rows = [
    { label: t("flow.revision"), value: revisionText(version.revision_kind) },
    { label: t("flow.provider"), value: `${version.provider_kind} · ${version.provider_id}` },
    { label: t("flow.briefVersion"), value: String(version.brief_version_number) },
    { label: t("flow.catalogVersion"), value: String(version.catalog_version) },
    { label: t("flow.contentHash"), value: version.content_hash },
    { label: t("flow.constraintsHash"), value: version.constraints_content_hash },
  ];
  if (version.based_on_version_number !== null) {
    rows.splice(1, 0, {
      label: t("flow.basedOn"),
      value: String(version.based_on_version_number),
    });
  }
  if (store.gate !== null) {
    rows.push({
      label: t("flow.gateStatus"),
      value: `${statusText(store.gate.status)} · ${t("flow.decisionCounter", {
        n: store.gate.iteration,
        max: store.gate.max_iterations,
      })}`,
    });
  }
  if (latestOperationStatus.value !== null) {
    rows.push({
      label: t("flow.latestOperation"),
      value: statusText(latestOperationStatus.value),
    });
  }
  return rows;
});

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

function resetDraft(): void {
  const version = store.currentVersion;
  const nextSelection: Partial<Record<AgentIdentifier, boolean>> = {};

  for (const entry of store.catalog?.agents ?? []) {
    nextSelection[entry.agent_id] = version?.selected_agent_ids.includes(entry.agent_id) ?? false;
  }

  selectedDraft.value = nextSelection;
  rationaleDraft.value = {};
}

watch(() => store.currentVersion, resetDraft, {
  immediate: true,
});

watch(
  () => props.projectId,
  async () => {
    await load();
  },
);

let reloadWhenIdle = false;

watchUpstream(
  () => props.upstream,
  (changed) => {
    if (!changed) return;
    if (store.busy) {
      reloadWhenIdle = true;
      return;
    }
    void load();
  },
);

watch(
  () => store.busy,
  (busy) => {
    if (busy || !reloadWhenIdle) return;
    reloadWhenIdle = false;
    void load();
  },
);

function visibleTarget(id: string): HTMLElement | null {
  const candidates = document.querySelectorAll<HTMLElement>(`#${id}`);
  for (const candidate of candidates) {
    if (typeof candidate.checkVisibility !== "function" || candidate.checkVisibility()) {
      return candidate;
    }
  }
  return null;
}

function refreshBarTarget(): void {
  const element = root.value;
  const shown =
    element !== null &&
    element.isConnected &&
    (typeof element.checkVisibility !== "function" || element.checkVisibility());
  const target = shown ? visibleTarget("step-decision-bar") : null;
  const row = shown ? visibleTarget("step-technical-row") : null;
  if (barTarget.value !== target) barTarget.value = target;
  if (rowTarget.value !== row) rowTarget.value = row;
}

async function refreshAfterRender(): Promise<void> {
  await nextTick();
  refreshBarTarget();
}

onMounted(() => {
  void load();
  refreshBarTarget();
  void refreshAfterRender();
  if (typeof ResizeObserver !== "undefined" && root.value !== null) {
    visibilityObserver = new ResizeObserver(refreshBarTarget);
    visibilityObserver.observe(root.value);
  }
});

onUpdated(refreshBarTarget);

watch(() => props.active, refreshAfterRender);

onBeforeUnmount(() => {
  visibilityObserver?.disconnect();
  visibilityObserver = null;
});

function translatedOrFallback(key: string, fallback: string): string {
  const translated = t(key);

  return translated === key ? fallback : translated;
}

function humanize(value: string): string {
  return value
    .toLocaleLowerCase()
    .replaceAll("_", " ")
    .replace(/^./, (character) => character.toLocaleUpperCase());
}

function statusText(value: string): string {
  return translatedOrFallback(`flow.statuses.${value}`, humanize(value));
}

function constraintText(value: string): string {
  return translatedOrFallback(`flow.constraints.${value}`, humanize(value));
}

function sourceText(value: string): string {
  return translatedOrFallback(`flow.sources.${value}`, humanize(value));
}

function revisionText(value: string): string {
  return translatedOrFallback(`flow.revisions.${value}`, humanize(value));
}

function capabilityText(value: string): string {
  return translatedOrFallback(`flow.capabilitiesMap.${value}`, humanize(value));
}

function reasonText(reason: TeamSelectionReasonResponse): string {
  return translatedOrFallback(`flow.reasons.${reason.code}`, humanize(reason.code));
}

function errorText(detail: string): string {
  return translatedOrFallback(`flow.errors.${detail}`, detail);
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(locale.value, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function constraintFor(agentId: AgentIdentifier): TeamRoleConstraintResponse | null {
  return (
    store.currentVersion?.role_constraints.find((constraint) => constraint.agent_id === agentId) ??
    null
  );
}

function memberFor(agentId: AgentIdentifier): ProposedTeamMemberResponse | null {
  return store.currentVersion?.members.find((member) => member.agent_id === agentId) ?? null;
}

function isSelected(agentId: AgentIdentifier): boolean {
  return selectedDraft.value[agentId] ?? false;
}

function canEditRole(agentId: AgentIdentifier): boolean {
  return store.currentVersion !== null && constraintFor(agentId)?.owner_editable === true;
}

function requiresRationale(agentId: AgentIdentifier): boolean {
  return isSelected(agentId) && !initialSelected.value.has(agentId);
}

function roleName(entry: AgentCatalogEntryResponse): string {
  return twinIdentity(entry.agent_id, "", uiLocale.value).name;
}

function roleDescription(entry: AgentCatalogEntryResponse): string {
  return twinIdentity(entry.agent_id, "", uiLocale.value).description;
}

function roleStepsText(entry: AgentCatalogEntryResponse): string {
  const steps = roleSteps(entry.agent_id).map((step) => t(`flow.stepNames.s${step}`));
  return steps.length === 0 ? "" : t("flow.worksIn", { steps: steps.join(" · ") });
}

function signalReason(agentId: AgentIdentifier): string | null {
  const reason = constraintFor(agentId)?.reasons.find((item) => SIGNAL_REASONS.has(item.code));
  return reason === undefined ? null : t("flow.why", { reason: reasonText(reason) });
}

function roleTag(agentId: AgentIdentifier): string {
  const selected = isSelected(agentId);
  const initially = initialSelected.value.has(agentId);
  if (selected && !initially) return t("flow.tagNew");
  if (!selected && initially) return t("flow.tagRemoved");
  if (!selected) return t("flow.tagOptional");
  return memberFor(agentId)?.source === "OWNER_ADDED" ? t("flow.tagOwner") : t("flow.tagSuggested");
}

function roleMessages(agentId: AgentIdentifier): string[] {
  const constraint = constraintFor(agentId);
  return constraint === null ? [] : constraint.reasons.map((reason) => reasonText(reason));
}

function setSelected(agentId: AgentIdentifier, event: Event): void {
  const target = event.target;

  if (!(target instanceof HTMLInputElement)) {
    return;
  }

  selectedDraft.value[agentId] = target.checked;

  if (!target.checked) {
    delete rationaleDraft.value[agentId];
  }
}

function setRationale(agentId: AgentIdentifier, event: Event): void {
  const target = event.target;

  if (!(target instanceof HTMLTextAreaElement)) {
    return;
  }

  rationaleDraft.value[agentId] = target.value;
}

async function generateProposal(): Promise<void> {
  localError.value = null;

  await store.generateProposal(props.projectId, resolvedApi.value, executeAuthorized);
}

function selectedAgentIds(): readonly AgentIdentifier[] {
  return (
    store.catalog?.agents.map((entry) => entry.agent_id).filter((agentId) => isSelected(agentId)) ??
    []
  );
}

function ownerRationales(): readonly OwnerAgentRationaleInput[] | null {
  const rationales: OwnerAgentRationaleInput[] = [];

  for (const agentId of selectedAgentIds()) {
    if (!requiresRationale(agentId)) {
      continue;
    }

    const statement = (rationaleDraft.value[agentId] ?? "").trim();

    if (!statement) {
      localError.value = t("flow.rationaleRequired");

      return null;
    }

    rationales.push({
      agent_id: agentId,
      statement,
    });
  }

  return rationales;
}

async function saveTeam(): Promise<void> {
  if (store.busy || !hasTeamChanges.value) return;
  localError.value = null;

  const rationales = ownerRationales();

  if (rationales === null) {
    return;
  }

  await store.editCurrent(
    props.projectId,
    selectedAgentIds(),
    rationales,
    resolvedApi.value,
    executeAuthorized,
  );
}

async function submitGate(): Promise<boolean> {
  localError.value = null;

  const submission = await store.submitGate(props.projectId, resolvedApi.value, executeAuthorized);

  return submission !== null && gatePending.value;
}

async function decideGate(action: AgentTeamGateDecisionAction, note?: string): Promise<boolean> {
  localError.value = null;

  const reason = (note ?? gateReason.value).trim();

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

  if (result !== null && note === undefined) {
    gateReason.value = "";
  }

  return result !== null;
}

async function approveTeam(): Promise<void> {
  if (approving.value || store.busy || hasTeamChanges.value) return;
  approving.value = true;
  try {
    if (!gatePending.value && !(await submitGate())) return;
    await decideGate("APPROVE");
  } finally {
    approving.value = false;
  }
}

async function onPrimary(): Promise<void> {
  if (decision.value === "resume") {
    await decideGate("RESUME");
    return;
  }
  await approveTeam();
}

async function onRequest(text: string): Promise<void> {
  if (!requestAvailable.value) return;
  if (await decideGate("REQUEST_REVISION", text)) {
    await decisionBar.value?.completeRequest();
  }
}

function eventLabel(event: HumanGateEventResponse): string {
  return statusText(event.kind);
}
</script>

<template>
  <section
    ref="root"
    class="grid gap-8 text-on-night"
    data-surface="night"
    :aria-label="t('flow.region')"
    data-testid="team-step"
  >
    <p class="sr-only" aria-live="polite" aria-atomic="true" data-testid="team-operation-live">
      {{ store.busy ? t("flow.loading") : (operationSentence ?? "") }}
    </p>

    <UiStateBlock v-if="initialLoading" kind="loading" :title="t('flow.preparing')" />

    <UiStateBlock
      v-if="localError !== null || store.errorDetail !== null"
      kind="error"
      :text="
        t('flow.error', {
          detail: localError ?? errorText(store.errorDetail ?? 'unexpected_error'),
        })
      "
    >
      <UiButton
        v-if="store.errorDetail !== null"
        variant="secondary"
        :disabled="store.busy"
        @click="load"
      >
        {{ t("flow.retry") }}
      </UiButton>
    </UiStateBlock>
    <UiStateBlock
      v-else-if="operationSentence !== null"
      kind="empty"
      :text="operationSentence"
      data-testid="team-operation-status"
    />

    <UiStateBlock
      v-if="briefApprovalRequired"
      kind="empty"
      :text="t('flow.briefFirst')"
      data-testid="team-brief-first"
    />

    <UiStateBlock
      v-else-if="!initialLoading && (store.currentVersion === null || proposalOutdated)"
      kind="empty"
      :title="proposalOutdated ? t('flow.outdatedTitle') : t('flow.noProposalTitle')"
      :text="proposalOutdated ? t('flow.outdatedText') : t('flow.noProposalText')"
      data-testid="team-proposal-needed"
    >
      <UiButton
        variant="pill"
        :disabled="store.busy"
        data-testid="generate-team"
        @click="generateProposal"
      >
        {{ proposalOutdated ? t("flow.regenerate") : t("flow.generate") }}
      </UiButton>
    </UiStateBlock>

    <UiStateBlock
      v-if="store.lastGeneration?.issues.length || store.currentVersion?.constraint_issues.length"
      kind="error"
      :title="t('flow.constraintIssues')"
    >
      <ul class="m-0 grid list-none gap-1 p-0">
        <li
          v-for="issue in store.lastGeneration?.issues ??
          store.currentVersion?.constraint_issues ??
          []"
          :key="`${issue.code}:${issue.agent_id}`"
          class="font-semibold"
        >
          {{ twinIdentity(issue.agent_id, "", uiLocale).name }}
          ·
          {{ humanize(issue.code) }}
        </li>
      </ul>
    </UiStateBlock>

    <template v-if="store.currentVersion !== null">
      <div class="grid gap-3">
        <p class="m-0 text-base leading-normal text-on-night-3" data-testid="team-count">
          <strong class="font-semibold text-on-night">{{ countLabel }}.</strong>
          {{ t("flow.intro") }}
        </p>
        <div
          v-if="gateNotice !== null"
          class="grid gap-1 rounded-panel border border-warn-on-night/40 bg-warn-on-night/8 px-5 py-4 text-[15px] leading-normal"
          role="status"
          data-testid="team-gate-notice"
        >
          <p class="m-0 font-semibold text-warn-on-night">{{ gateNotice }}</p>
          <p v-if="revisionNote" class="m-0 text-on-night-2">
            {{ t("flow.revisionNote", { note: revisionNote }) }}
          </p>
        </div>
      </div>

      <section v-if="coreRoles.length > 0" aria-labelledby="team-core-title">
        <h2 id="team-core-title" class="m-0 mb-3 text-[17px] font-semibold">
          {{ t("flow.core") }}
        </h2>
        <ul
          class="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(min(100%,250px),1fr))] gap-3 p-0"
        >
          <li
            v-for="entry in coreRoles"
            :key="entry.agent_id"
            class="flex flex-col gap-2.5 rounded-panel border border-night-line bg-night-raised p-[18px]"
            data-testid="team-member"
            :data-agent-id="entry.agent_id"
            data-team-group="core"
          >
            <div class="flex items-center gap-3">
              <img
                :src="roleAvatar(entry.agent_id)"
                alt=""
                width="56"
                height="56"
                decoding="async"
                class="size-14 shrink-0 rounded-panel border border-night-line bg-night object-cover"
              />
              <h3 class="m-0 text-base leading-tight font-semibold">{{ roleName(entry) }}</h3>
            </div>
            <p class="m-0 text-sm leading-normal text-on-night-3">{{ roleDescription(entry) }}</p>
            <p
              v-if="signalReason(entry.agent_id)"
              class="m-0 text-sm leading-normal text-on-night-2"
            >
              {{ signalReason(entry.agent_id) }}
            </p>
            <p
              v-if="roleStepsText(entry)"
              class="m-0 mt-auto pt-1 font-mono text-xs leading-normal text-on-night-3"
            >
              {{ roleStepsText(entry) }}
            </p>
          </li>
        </ul>
      </section>

      <section v-if="extraRoles.length > 0" aria-labelledby="team-extra-title">
        <h2 id="team-extra-title" class="m-0 mb-3 text-[17px] font-semibold">
          {{ t("flow.extra") }}
        </h2>
        <form class="grid gap-3" data-testid="team-selection-form" @submit.prevent="saveTeam">
          <ul
            class="m-0 list-none overflow-hidden rounded-panel border border-night-line bg-night-raised p-0"
          >
            <li
              v-for="entry in extraRoles"
              :key="entry.agent_id"
              class="grid grid-cols-[40px_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-3 border-b border-on-night/8 px-4 py-4 last:border-b-0 sm:grid-cols-[56px_minmax(0,1fr)_auto] sm:gap-x-4 sm:px-[18px]"
              data-testid="team-member"
              :data-agent-id="entry.agent_id"
              data-team-group="extra"
              :data-selected="isSelected(entry.agent_id) ? 'true' : 'false'"
            >
              <img
                :src="roleAvatar(entry.agent_id)"
                alt=""
                width="56"
                height="56"
                decoding="async"
                :class="[
                  'size-10 shrink-0 rounded-panel border border-night-line bg-night object-cover transition-opacity duration-150 sm:size-14',
                  isSelected(entry.agent_id) ? 'opacity-100' : 'opacity-55',
                ]"
              />
              <div class="min-w-0">
                <div class="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                  <h3 :id="`team-role-${entry.agent_id}`" class="m-0 text-base font-semibold">
                    {{ roleName(entry) }}
                  </h3>
                  <span class="text-xs text-on-night-3" data-testid="team-role-tag">
                    {{ roleTag(entry.agent_id) }}
                  </span>
                </div>
                <p
                  :id="`team-role-why-${entry.agent_id}`"
                  class="m-0 mt-0.5 text-sm leading-[1.45] text-on-night-3"
                >
                  {{ signalReason(entry.agent_id) ?? roleDescription(entry) }}
                </p>
              </div>
              <label
                class="relative inline-flex h-11 w-[52px] shrink-0 cursor-pointer items-center has-disabled:cursor-not-allowed"
              >
                <input
                  type="checkbox"
                  role="switch"
                  class="peer absolute inset-0 m-0 size-full cursor-pointer opacity-0 disabled:cursor-not-allowed"
                  :data-testid="`role-${entry.agent_id}`"
                  :aria-labelledby="`team-role-${entry.agent_id}`"
                  :aria-describedby="`team-role-why-${entry.agent_id}`"
                  :checked="isSelected(entry.agent_id)"
                  :disabled="store.busy || !canEditRole(entry.agent_id)"
                  @change="setSelected(entry.agent_id, $event)"
                />
                <span
                  aria-hidden="true"
                  class="pointer-events-none ml-auto block h-7 w-12 rounded-[14px] bg-on-night-3 transition-colors duration-150 peer-checked:bg-petrol-on-night peer-focus-visible:outline-3 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-(--focus-ring) peer-disabled:opacity-50"
                />
                <span
                  aria-hidden="true"
                  class="pointer-events-none absolute top-1/2 left-1.5 size-6 -translate-y-1/2 rounded-full bg-night transition-[left] duration-150 peer-checked:left-[26px]"
                />
              </label>
              <label
                v-if="requiresRationale(entry.agent_id)"
                class="col-span-3 grid gap-2 text-sm font-semibold text-on-night-2"
              >
                {{ t("flow.ownerRationale") }}
                <textarea
                  :data-testid="`rationale-${entry.agent_id}`"
                  class="min-h-24 rounded-field border border-night-line-strong bg-night-raised px-3 py-2 text-[15px] font-normal text-on-night placeholder:text-on-night-3"
                  :placeholder="t('flow.rationalePlaceholder')"
                  :value="rationaleDraft[entry.agent_id] ?? ''"
                  @input="setRationale(entry.agent_id, $event)"
                ></textarea>
              </label>
            </li>
          </ul>
          <div
            v-if="hasTeamChanges"
            class="flex flex-wrap items-center justify-end gap-3 max-sm:[&>button]:grow"
            data-testid="team-changes"
          >
            <p class="m-0 mr-auto text-sm leading-normal text-on-night-2" role="status">
              {{ t("flow.changesPending") }}
            </p>
            <UiButton variant="quiet" :disabled="store.busy" @click="resetDraft">
              {{ t("flow.discardChanges") }}
            </UiButton>
            <UiButton
              type="submit"
              :disabled="store.busy || !hasTeamChanges"
              data-testid="save-team-changes"
            >
              {{ t("flow.saveTeam") }}
            </UiButton>
          </div>
        </form>
      </section>

      <details
        v-if="gatePending || cancelAvailable"
        class="group -mt-4"
        data-testid="team-other-decisions"
      >
        <summary
          class="inline-flex min-h-11 cursor-pointer list-none items-center gap-2.5 text-sm font-medium text-on-night-3 transition-colors duration-150 hover:text-on-night [&::-webkit-details-marker]:hidden"
        >
          <span
            aria-hidden="true"
            class="inline-block size-2 rotate-45 border-r-[1.5px] border-b-[1.5px] border-current transition-transform duration-150 group-open:-rotate-135"
          />
          {{ t("flow.otherDecisions") }}
        </summary>
        <div
          class="mt-2 grid gap-3 rounded-field border border-night-line bg-night-raised px-5 py-4"
        >
          <label v-if="reasonAvailable" class="grid gap-2 text-sm font-semibold text-on-night-2">
            {{ t("flow.gateReason") }}
            <textarea
              v-model="gateReason"
              data-testid="team-gate-reason"
              class="min-h-20 rounded-field border border-night-line-strong bg-night-raised px-3 py-2 text-[15px] font-normal text-on-night"
            ></textarea>
            <span class="text-xs font-normal text-on-night-3">{{ t("flow.gateReasonHint") }}</span>
          </label>
          <div class="flex flex-wrap gap-3">
            <UiButton
              v-if="gatePending"
              variant="danger"
              :disabled="store.busy || gateReason.trim().length === 0"
              data-testid="team-reject"
              @click="decideGate('REJECT')"
            >
              {{ t("flow.reject") }}
            </UiButton>
            <UiButton
              v-if="gatePending"
              variant="secondary"
              :disabled="store.busy"
              data-testid="team-pause"
              @click="decideGate('PAUSE')"
            >
              {{ t("flow.pause") }}
            </UiButton>
            <UiButton
              v-if="resumeElsewhere"
              variant="secondary"
              :disabled="store.busy"
              data-testid="team-resume"
              @click="decideGate('RESUME')"
            >
              {{ t("flow.resume") }}
            </UiButton>
            <UiButton
              v-if="cancelAvailable"
              variant="secondary"
              :disabled="store.busy"
              data-testid="team-cancel"
              @click="decideGate('CANCEL')"
            >
              {{ t("flow.cancel") }}
            </UiButton>
          </div>
        </div>
      </details>
    </template>

    <Teleport :to="barTarget" :disabled="barTarget === null">
      <div
        v-if="decision !== null"
        class="contents"
        data-testid="team-decision"
        :data-decision="decision"
        :data-gate-pending="gatePending ? 'true' : 'false'"
      >
        <UiDecisionBar
          ref="decisionBar"
          :primary-label="decisionCopy.primary"
          :description="decisionCopy.description"
          :secondary-label="requestAvailable ? undefined : null"
          :request-placeholder="t('flow.requestPlaceholder')"
          :busy="barBusy"
          :disabled="hasTeamChanges"
          @primary="onPrimary"
          @request="onRequest"
        />
      </div>
    </Teleport>

    <Teleport :to="rowTarget" :disabled="rowTarget === null">
      <div v-if="store.currentVersion !== null" data-testid="team-technical-details">
        <UiTechnicalDetails :summary="technicalSummary" :rows="technicalRows">
          <div class="grid gap-5 text-on-night-2">
            <section v-if="platformAgents.length > 0" class="grid gap-1.5">
              <h3 class="m-0 font-mono text-[11px] tracking-label text-on-night-3 uppercase">
                {{ t("flow.platform") }}
              </h3>
              <p class="m-0 leading-relaxed">
                {{ platformAgents.map((entry) => roleName(entry)).join(" · ") }}
              </p>
            </section>

            <section class="grid gap-2">
              <h3 class="m-0 font-mono text-[11px] tracking-label text-on-night-3 uppercase">
                {{ t("flow.reasonsTitle") }}
              </h3>
              <ul class="m-0 grid list-none gap-2 p-0">
                <li v-for="entry in specialists" :key="entry.agent_id" class="grid gap-0.5">
                  <p class="m-0 font-semibold text-on-night">
                    {{ roleName(entry) }}
                    <span class="font-normal text-on-night-3">
                      · {{ constraintText(constraintFor(entry.agent_id)?.kind ?? "NOT_EVALUATED") }}
                      <template v-if="memberFor(entry.agent_id) !== null">
                        · {{ t("flow.source") }}:
                        {{ sourceText(memberFor(entry.agent_id)?.source ?? "") }}
                      </template>
                    </span>
                  </p>
                  <p v-if="roleMessages(entry.agent_id).length > 0" class="m-0">
                    {{ roleMessages(entry.agent_id).join(" · ") }}
                  </p>
                  <template
                    v-for="reason in constraintFor(entry.agent_id)?.reasons ?? []"
                    :key="reason.code"
                  >
                    <p v-if="reason.evidence.fields.length > 0" class="m-0 text-on-night-3">
                      {{ t("flow.evidenceFields") }}: {{ reason.evidence.fields.join(", ") }}
                    </p>
                    <p v-if="reason.evidence.terms.length > 0" class="m-0 text-on-night-3">
                      {{ t("flow.evidenceTerms") }}: {{ reason.evidence.terms.join(", ") }}
                    </p>
                  </template>
                  <p class="m-0 text-on-night-3">
                    {{ t("flow.capabilities") }}:
                    {{
                      entry.capabilities.map((capability) => capabilityText(capability)).join(", ")
                    }}
                  </p>
                </li>
              </ul>
              <p v-if="unavailableRoles.length > 0" class="m-0 text-on-night-3">
                {{ t("flow.unavailable") }}:
                {{ unavailableRoles.map((entry) => roleName(entry)).join(" · ") }}
              </p>
            </section>

            <section class="grid gap-2">
              <h3 class="m-0 font-mono text-[11px] tracking-label text-on-night-3 uppercase">
                {{ t("flow.proposalHistory") }}
              </h3>
              <ol v-if="store.history.length > 0" class="m-0 grid list-none gap-1.5 p-0">
                <li v-for="version in store.history" :key="version.id" class="grid gap-0.5">
                  <p class="m-0">
                    <span class="font-semibold text-on-night">
                      {{ t("flow.version", { number: version.version_number }) }}
                    </span>
                    · {{ revisionText(version.revision_kind) }} ·
                    {{ formatDate(version.created_at) }} ·
                    {{ t("flow.agentsCount", { n: version.selected_agent_ids.length }) }}
                  </p>
                  <code class="font-mono text-xs break-all text-on-night-3">{{
                    version.content_hash
                  }}</code>
                </li>
              </ol>
              <p v-else class="m-0">{{ t("flow.noHistory") }}</p>
            </section>

            <section class="grid gap-2">
              <h3 class="m-0 font-mono text-[11px] tracking-label text-on-night-3 uppercase">
                {{ t("flow.eventHistory") }}
              </h3>
              <ol v-if="store.gateEvents.length > 0" class="m-0 grid list-none gap-1.5 p-0">
                <li v-for="event in store.gateEvents" :key="event.id" class="grid gap-0.5">
                  <p class="m-0">
                    <span class="font-semibold text-on-night">{{ eventLabel(event) }}</span>
                    · {{ statusText(event.previous_status) }} →
                    {{ statusText(event.resulting_status) }} · {{ formatDate(event.occurred_at) }}
                  </p>
                  <p v-if="event.reason" class="m-0 text-on-night-3">{{ event.reason }}</p>
                </li>
              </ol>
              <p v-else class="m-0">{{ t("flow.noEvents") }}</p>
            </section>

            <div class="flex flex-wrap gap-2">
              <UiButton
                variant="quiet"
                :disabled="store.busy"
                data-testid="team-refresh"
                @click="load"
              >
                {{ t("flow.refresh") }}
              </UiButton>
              <UiButton
                variant="quiet"
                :disabled="store.busy"
                data-testid="team-regenerate"
                @click="generateProposal"
              >
                {{ t("flow.regenerate") }}
              </UiButton>
            </div>
          </div>
        </UiTechnicalDetails>
      </div>
    </Teleport>
  </section>
</template>
