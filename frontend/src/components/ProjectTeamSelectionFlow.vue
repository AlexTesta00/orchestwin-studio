<script setup lang="ts">
import {
  computed,
  onMounted,
  ref,
  watch,
} from "vue";
import {
  useI18n,
} from "vue-i18n";

import {
  apiClient,
} from "@/api/client";
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
import type {
  HumanGateEventResponse,
} from "@/api/workflow-contracts";
import {
  useAuthStore,
} from "@/stores/auth";
import {
  type TeamAuthorizedRequest,
  useTeamStore,
} from "@/stores/team";

const props = defineProps<{
  projectId: string;
  api?: AgentTeamApi;
  authorize?: TeamAuthorizedRequest;
}>();

const auth = useAuthStore();
const store = useTeamStore();

const {
  t,
  locale,
} = useI18n({
  useScope: "local",
  messages: {
    en: {
      flow: {
        title: "Agent Team selection and approval",
        intro:
          "Review deterministic constraints, adjust compatible specialists, and approve the exact team version.",
        loading: "Updating Agent Team workflow…",
        refresh: "Refresh team workflow",
        generate: "Generate team proposal",
        noProposal:
          "No team proposal has been generated.",
        currentProposal: "Current team proposal",
        version: "Version {number}",
        basedOn: "Based on version {number}",
        provider: "Provider",
        briefVersion: "Project Brief version",
        catalogVersion: "Agent catalog version",
        contentHash: "Team content hash",
        constraintsHash: "Constraint hash",
        readiness: "Project readiness",
        ready:
          "Gate 2 approves the current team. The project is ready for the future main workflow.",
        notStarted:
          "This status does not start the main workflow automatically.",
        constraintIssues:
          "The brief contains contradictory role signals.",
        teamEditor: "Agent catalog and current selection",
        teamEditorIntro:
          "Mandatory roles cannot be removed. Impossible or conflicting roles cannot be added.",
        selected: "Selected",
        notSelected: "Not selected",
        ownerRationale: "Owner rationale",
        rationalePlaceholder:
          "Explain why this optional role should be added.",
        rationaleRequired:
          "Every newly added optional role requires an owner rationale.",
        saveTeam: "Save team as a new version",
        proposalHistory: "Team proposal history",
        noHistory:
          "No team proposal version is available.",
        gateTitle: "Gate 2 — Agent Team",
        noGate:
          "The Agent Team has not been submitted for approval.",
        submitGate: "Submit current team for approval",
        gateReason: "Decision rationale",
        approve: "Approve",
        reject: "Reject",
        requestRevision: "Request revision",
        pause: "Pause",
        resume: "Resume",
        cancel: "Cancel",
        gateReasonRequired:
          "Reject and request-revision actions require a rationale.",
        eventHistory: "Gate 2 audit history",
        noEvents:
          "No Gate 2 event has been recorded.",
        evidenceFields: "Brief fields",
        evidenceTerms: "Matched terms",
        capabilities: "Capabilities",
        source: "Source",
        status: "Status: {status}",
        latestOperation:
          "Latest operation: {status}",
        error: "Agent Team error: {detail}",
        constraints: {
          MANDATORY: "Mandatory",
          OPTIONAL: "Optional",
          IMPOSSIBLE: "Impossible",
          CONFLICT: "Conflict",
          NOT_EVALUATED: "Not evaluated",
        },
        sources: {
          DETERMINISTIC_MANDATORY:
            "Deterministic mandatory role",
          PROPOSER_SUGGESTED:
            "Proposal adapter suggestion",
          OWNER_ADDED: "Added by the owner",
        },
        revisions: {
          PROPOSER_GENERATED:
            "Generated proposal",
          OWNER_EDITED: "Owner edited",
        },
        statuses: {
          CREATED: "Created",
          UPDATED: "Updated",
          UNCHANGED: "Unchanged",
          REJECTED: "Rejected",
          PROJECT_NOT_FOUND:
            "Project not found",
          BRIEF_NOT_FOUND:
            "Project Brief not found",
          BRIEF_NOT_APPROVED:
            "Gate 1 approval required",
          BLOCKED_BY_CONSTRAINTS:
            "Blocked by contradictory constraints",
          CONTEXT_CHANGED:
            "Project context changed",
          INVALID_PROPOSAL:
            "Invalid provider output",
          PROPOSAL_NOT_FOUND:
            "Team proposal not found",
          PROPOSAL_STALE:
            "Team proposal is stale",
          SUBMITTED: "Submitted",
          ALREADY_PENDING:
            "Already pending approval",
          ALREADY_APPROVED:
            "Already approved",
          NEW_PROPOSAL_REQUIRED:
            "A new proposal is required",
          GATE_BLOCKED: "Gate blocked",
          ITERATION_LIMIT_REACHED:
            "Gate iteration limit reached",
          TRANSITION_REJECTED:
            "Transition rejected",
          APPLIED: "Applied",
          ARTIFACT_STALE:
            "Approved artifact is stale",
          DRAFT: "Draft",
          PENDING_APPROVAL:
            "Pending approval",
          APPROVED: "Approved",
          REVISION_REQUESTED:
            "Revision requested",
          PAUSED: "Paused",
          CANCELLED: "Cancelled",
          STALE: "Stale",
          PAUSED_NEEDS_HUMAN:
            "Paused — human intervention required",
          BRIEF_APPROVAL_REQUIRED:
            "Project Brief approval required",
          TEAM_PROPOSAL_REQUIRED:
            "Team proposal required",
          TEAM_APPROVAL_REQUIRED:
            "Agent Team approval required",
          READY_FOR_MAIN_WORKFLOW:
            "Ready for the main workflow",
          SUBMIT: "Submitted",
          APPROVE: "Approved",
          REJECT: "Rejected",
          REQUEST_REVISION:
            "Revision requested",
          PAUSE: "Paused",
          RESUME: "Resumed",
          CANCEL: "Cancelled",
          ARTIFACT_SUPERSEDED:
            "Artifact superseded",
        },
        errors: {
          unexpected_error:
            "An unexpected error occurred.",
          unexpected_api_error:
            "The API returned an unexpected response.",
          team_proposal_not_found:
            "No team proposal was found.",
          agent_team_gate_not_found:
            "No Agent Team gate was found.",
          team_proposal_service_unavailable:
            "The team-proposal service is unavailable.",
          agent_team_service_unavailable:
            "The Agent Team service is unavailable.",
        },
        reasons: {
          CATALOG_ALWAYS_PRESENT:
            "Always-present platform component",
          CATALOG_MODE_INCOMPATIBLE:
            "Incompatible with the project mode",
          CORE_REQUIREMENTS_DISCIPLINE:
            "Core requirements discipline",
          CORE_USER_CENTERED_DESIGN:
            "Core user-centered design discipline",
          CORE_ARCHITECTURE_DISCIPLINE:
            "Core architecture discipline",
          CORE_QUALITY_DISCIPLINE:
            "Core quality and testing discipline",
          BROWNFIELD_INTEGRATION:
            "Brownfield integration is required",
          USER_INTERFACE_SIGNAL:
            "The brief requires a user interface",
          WEB_DELIVERY_SIGNAL:
            "The brief requires web delivery",
          BACKEND_DELIVERY_SIGNAL:
            "The brief requires backend delivery",
          MOBILE_DELIVERY_SIGNAL:
            "The brief requires mobile delivery",
          EXTERNAL_INTEGRATION_SIGNAL:
            "The brief requires external integration",
          SECURITY_SENSITIVITY_SIGNAL:
            "The brief contains security-sensitive requirements",
          ACCESSIBILITY_REQUIREMENT_SIGNAL:
            "The brief contains accessibility requirements",
          EXPLICIT_SCOPE_EXCLUSION:
            "The brief explicitly excludes this role",
        },
        capabilitiesMap: {
          WORKFLOW_ORCHESTRATION:
            "Workflow orchestration",
          GOVERNED_ROUTING: "Governed routing",
          PROJECT_INTAKE: "Project intake",
          BRIEF_CLARIFICATION:
            "Brief clarification",
          TEAM_SELECTION: "Team selection",
          HUMAN_APPROVAL: "Human approval",
          ARTIFACT_MANAGEMENT:
            "Artifact management",
          PROVENANCE_MANAGEMENT:
            "Provenance management",
          SANDBOX_CONTROL: "Sandbox control",
          REQUIREMENTS_ANALYSIS:
            "Requirements analysis",
          ACCEPTANCE_CRITERIA:
            "Acceptance criteria",
          USER_RESEARCH: "User research",
          USER_MODELING: "User modeling",
          UX_DESIGN: "UX design",
          UI_DESIGN: "UI design",
          SOFTWARE_ARCHITECTURE:
            "Software architecture",
          FRONTEND_ENGINEERING:
            "Frontend engineering",
          BACKEND_ENGINEERING:
            "Backend engineering",
          MOBILE_ENGINEERING:
            "Mobile engineering",
          QUALITY_ASSURANCE:
            "Quality assurance",
          TEST_ENGINEERING:
            "Test engineering",
          SECURITY_REVIEW: "Security review",
          ACCESSIBILITY_REVIEW:
            "Accessibility review",
          SYSTEM_INTEGRATION:
            "System integration",
        },
      },
      agentCatalog: {
        roles: {
          workflow_orchestrator: {
            name: "Workflow Orchestrator",
            description:
              "Coordinates governed workflow transitions and typed artifacts.",
          },
          intake_clarification_agent: {
            name: "Intake and Clarification Agent",
            description:
              "Guides Project Brief intake and focused clarification.",
          },
          team_selector: {
            name: "Team Selector",
            description:
              "Builds typed team proposals from deterministic constraints.",
          },
          human_gate_controller: {
            name: "Human Gate Controller",
            description:
              "Enforces explicit owner approval and audit events.",
          },
          artifact_manager: {
            name: "Artifact Manager",
            description:
              "Manages immutable artifacts, versions, and provenance.",
          },
          sandbox_controller: {
            name: "Sandbox Controller",
            description:
              "Controls isolated execution and validated operations.",
          },
          requirements_analyst: {
            name: "Requirements Analyst",
            description:
              "Structures requirements, acceptance criteria, and scope.",
          },
          ux_researcher_user_modeler: {
            name: "UX Researcher / User Modeler",
            description:
              "Models users, contexts, goals, and evidence needs.",
          },
          ux_ui_designer: {
            name: "UX/UI Designer",
            description:
              "Explores interaction flows and accessible interface design.",
          },
          software_architect: {
            name: "Software Architect",
            description:
              "Defines architecture boundaries, technologies, and trade-offs.",
          },
          frontend_engineer: {
            name: "Frontend Engineer",
            description:
              "Implements browser-based user interfaces.",
          },
          backend_engineer: {
            name: "Backend Engineer",
            description:
              "Implements APIs, persistence, and server-side behavior.",
          },
          mobile_engineer: {
            name: "Mobile Engineer",
            description:
              "Implements native or cross-platform mobile applications.",
          },
          qa_test_engineer: {
            name: "QA/Test Engineer",
            description:
              "Defines and executes automated quality strategies.",
          },
          security_reviewer: {
            name: "Security Reviewer",
            description:
              "Reviews authentication, authorization, privacy, and risks.",
          },
          accessibility_reviewer: {
            name: "Accessibility Reviewer",
            description:
              "Reviews accessibility requirements and interaction barriers.",
          },
          integration_engineer: {
            name: "Integration Engineer",
            description:
              "Coordinates external services and brownfield integration.",
          },
        },
      },
    },
    it: {
      flow: {
        title: "Selezione e approvazione dell'Agent Team",
        intro:
          "Esamina i vincoli deterministici, modifica gli specialisti compatibili e approva la versione esatta del team.",
        loading: "Aggiornamento del workflow Agent Team…",
        refresh: "Aggiorna workflow del team",
        generate: "Genera proposta del team",
        noProposal:
          "Non è stata ancora generata una proposta del team.",
        currentProposal: "Proposta corrente del team",
        version: "Versione {number}",
        basedOn: "Basata sulla versione {number}",
        provider: "Provider",
        briefVersion: "Versione del Project Brief",
        catalogVersion: "Versione del catalogo agenti",
        contentHash: "Hash del contenuto del team",
        constraintsHash: "Hash dei vincoli",
        readiness: "Stato di preparazione del progetto",
        ready:
          "Gate 2 approva il team corrente. Il progetto è pronto per il futuro workflow principale.",
        notStarted:
          "Questo stato non avvia automaticamente il workflow principale.",
        constraintIssues:
          "Il brief contiene segnali contraddittori relativi ai ruoli.",
        teamEditor: "Catalogo agenti e selezione corrente",
        teamEditorIntro:
          "I ruoli obbligatori non possono essere rimossi. I ruoli impossibili o in conflitto non possono essere aggiunti.",
        selected: "Selezionato",
        notSelected: "Non selezionato",
        ownerRationale: "Motivazione dell'owner",
        rationalePlaceholder:
          "Spiega perché questo ruolo opzionale deve essere aggiunto.",
        rationaleRequired:
          "Ogni nuovo ruolo opzionale richiede una motivazione dell'owner.",
        saveTeam: "Salva il team come nuova versione",
        proposalHistory: "Cronologia delle proposte del team",
        noHistory:
          "Non è disponibile alcuna versione della proposta del team.",
        gateTitle: "Gate 2 — Agent Team",
        noGate:
          "L'Agent Team non è ancora stato sottoposto ad approvazione.",
        submitGate: "Sottoponi il team corrente ad approvazione",
        gateReason: "Motivazione della decisione",
        approve: "Approva",
        reject: "Rifiuta",
        requestRevision: "Richiedi revisione",
        pause: "Metti in pausa",
        resume: "Riprendi",
        cancel: "Annulla",
        gateReasonRequired:
          "Rifiuto e richiesta di revisione richiedono una motivazione.",
        eventHistory: "Cronologia audit di Gate 2",
        noEvents:
          "Non è stato ancora registrato alcun evento Gate 2.",
        evidenceFields: "Campi del brief",
        evidenceTerms: "Termini rilevati",
        capabilities: "Capacità",
        source: "Origine",
        status: "Stato: {status}",
        latestOperation:
          "Ultima operazione: {status}",
        error: "Errore dell'Agent Team: {detail}",
        constraints: {
          MANDATORY: "Obbligatorio",
          OPTIONAL: "Opzionale",
          IMPOSSIBLE: "Impossibile",
          CONFLICT: "Conflitto",
          NOT_EVALUATED: "Non valutato",
        },
        sources: {
          DETERMINISTIC_MANDATORY:
            "Ruolo obbligatorio deterministico",
          PROPOSER_SUGGESTED:
            "Suggerito dal proposal adapter",
          OWNER_ADDED: "Aggiunto dall'owner",
        },
        revisions: {
          PROPOSER_GENERATED:
            "Proposta generata",
          OWNER_EDITED:
            "Modificata dall'owner",
        },
        statuses: {
          CREATED: "Creata",
          UPDATED: "Aggiornata",
          UNCHANGED: "Invariata",
          REJECTED: "Rifiutata",
          PROJECT_NOT_FOUND:
            "Progetto non trovato",
          BRIEF_NOT_FOUND:
            "Project Brief non trovato",
          BRIEF_NOT_APPROVED:
            "È richiesta l'approvazione di Gate 1",
          BLOCKED_BY_CONSTRAINTS:
            "Bloccata da vincoli contraddittori",
          CONTEXT_CHANGED:
            "Il contesto del progetto è cambiato",
          INVALID_PROPOSAL:
            "Output del provider non valido",
          PROPOSAL_NOT_FOUND:
            "Proposta del team non trovata",
          PROPOSAL_STALE:
            "La proposta del team è obsoleta",
          SUBMITTED: "Sottoposto",
          ALREADY_PENDING:
            "Già in attesa di approvazione",
          ALREADY_APPROVED:
            "Già approvato",
          NEW_PROPOSAL_REQUIRED:
            "È richiesta una nuova proposta",
          GATE_BLOCKED: "Gate bloccato",
          ITERATION_LIMIT_REACHED:
            "Limite di iterazioni del gate raggiunto",
          TRANSITION_REJECTED:
            "Transizione rifiutata",
          APPLIED: "Applicata",
          ARTIFACT_STALE:
            "L'artefatto approvato è obsoleto",
          DRAFT: "Bozza",
          PENDING_APPROVAL:
            "In attesa di approvazione",
          APPROVED: "Approvato",
          REVISION_REQUESTED:
            "Revisione richiesta",
          PAUSED: "In pausa",
          CANCELLED: "Annullato",
          STALE: "Obsoleto",
          PAUSED_NEEDS_HUMAN:
            "In pausa — intervento umano richiesto",
          BRIEF_APPROVAL_REQUIRED:
            "È richiesta l'approvazione del Project Brief",
          TEAM_PROPOSAL_REQUIRED:
            "È richiesta una proposta del team",
          TEAM_APPROVAL_REQUIRED:
            "È richiesta l'approvazione dell'Agent Team",
          READY_FOR_MAIN_WORKFLOW:
            "Pronto per il workflow principale",
          SUBMIT: "Sottoposto",
          APPROVE: "Approvato",
          REJECT: "Rifiutato",
          REQUEST_REVISION:
            "Revisione richiesta",
          PAUSE: "Messo in pausa",
          RESUME: "Ripreso",
          CANCEL: "Annullato",
          ARTIFACT_SUPERSEDED:
            "Artefatto sostituito",
        },
        errors: {
          unexpected_error:
            "Si è verificato un errore inatteso.",
          unexpected_api_error:
            "L'API ha restituito una risposta inattesa.",
          team_proposal_not_found:
            "Non è stata trovata alcuna proposta del team.",
          agent_team_gate_not_found:
            "Non è stato trovato alcun Gate 2.",
          team_proposal_service_unavailable:
            "Il servizio di proposta del team non è disponibile.",
          agent_team_service_unavailable:
            "Il servizio Agent Team non è disponibile.",
        },
        reasons: {
          CATALOG_ALWAYS_PRESENT:
            "Componente di piattaforma sempre presente",
          CATALOG_MODE_INCOMPATIBLE:
            "Incompatibile con la modalità del progetto",
          CORE_REQUIREMENTS_DISCIPLINE:
            "Disciplina fondamentale dei requisiti",
          CORE_USER_CENTERED_DESIGN:
            "Disciplina fondamentale di User-Centered Design",
          CORE_ARCHITECTURE_DISCIPLINE:
            "Disciplina fondamentale di architettura",
          CORE_QUALITY_DISCIPLINE:
            "Disciplina fondamentale di qualità e testing",
          BROWNFIELD_INTEGRATION:
            "È richiesta l'integrazione brownfield",
          USER_INTERFACE_SIGNAL:
            "Il brief richiede un'interfaccia utente",
          WEB_DELIVERY_SIGNAL:
            "Il brief richiede una soluzione web",
          BACKEND_DELIVERY_SIGNAL:
            "Il brief richiede un backend",
          MOBILE_DELIVERY_SIGNAL:
            "Il brief richiede una soluzione mobile",
          EXTERNAL_INTEGRATION_SIGNAL:
            "Il brief richiede integrazioni esterne",
          SECURITY_SENSITIVITY_SIGNAL:
            "Il brief contiene requisiti sensibili per la sicurezza",
          ACCESSIBILITY_REQUIREMENT_SIGNAL:
            "Il brief contiene requisiti di accessibilità",
          EXPLICIT_SCOPE_EXCLUSION:
            "Il brief esclude esplicitamente questo ruolo",
        },
        capabilitiesMap: {
          WORKFLOW_ORCHESTRATION:
            "Orchestrazione del workflow",
          GOVERNED_ROUTING:
            "Routing governato",
          PROJECT_INTAKE:
            "Acquisizione del progetto",
          BRIEF_CLARIFICATION:
            "Chiarificazione del brief",
          TEAM_SELECTION:
            "Selezione del team",
          HUMAN_APPROVAL:
            "Approvazione umana",
          ARTIFACT_MANAGEMENT:
            "Gestione degli artefatti",
          PROVENANCE_MANAGEMENT:
            "Gestione della provenienza",
          SANDBOX_CONTROL:
            "Controllo della sandbox",
          REQUIREMENTS_ANALYSIS:
            "Analisi dei requisiti",
          ACCEPTANCE_CRITERIA:
            "Criteri di accettazione",
          USER_RESEARCH:
            "Ricerca con gli utenti",
          USER_MODELING:
            "Modellazione degli utenti",
          UX_DESIGN: "Progettazione UX",
          UI_DESIGN: "Progettazione UI",
          SOFTWARE_ARCHITECTURE:
            "Architettura software",
          FRONTEND_ENGINEERING:
            "Sviluppo frontend",
          BACKEND_ENGINEERING:
            "Sviluppo backend",
          MOBILE_ENGINEERING:
            "Sviluppo mobile",
          QUALITY_ASSURANCE:
            "Assicurazione della qualità",
          TEST_ENGINEERING:
            "Ingegneria del testing",
          SECURITY_REVIEW:
            "Revisione della sicurezza",
          ACCESSIBILITY_REVIEW:
            "Revisione dell'accessibilità",
          SYSTEM_INTEGRATION:
            "Integrazione dei sistemi",
        },
      },
      agentCatalog: {
        roles: {
          workflow_orchestrator: {
            name: "Workflow Orchestrator",
            description:
              "Coordina transizioni governate e artefatti tipizzati.",
          },
          intake_clarification_agent: {
            name: "Intake and Clarification Agent",
            description:
              "Guida l'acquisizione e la chiarificazione del Project Brief.",
          },
          team_selector: {
            name: "Team Selector",
            description:
              "Costruisce proposte tipizzate a partire dai vincoli deterministici.",
          },
          human_gate_controller: {
            name: "Human Gate Controller",
            description:
              "Applica approvazioni esplicite e audit degli eventi.",
          },
          artifact_manager: {
            name: "Artifact Manager",
            description:
              "Gestisce artefatti immutabili, versioni e provenienza.",
          },
          sandbox_controller: {
            name: "Sandbox Controller",
            description:
              "Controlla esecuzioni isolate e operazioni validate.",
          },
          requirements_analyst: {
            name: "Requirements Analyst",
            description:
              "Struttura requisiti, criteri di accettazione e ambito.",
          },
          ux_researcher_user_modeler: {
            name: "UX Researcher / User Modeler",
            description:
              "Modella utenti, contesti, obiettivi e necessità di evidenza.",
          },
          ux_ui_designer: {
            name: "UX/UI Designer",
            description:
              "Esplora flussi di interazione e interfacce accessibili.",
          },
          software_architect: {
            name: "Software Architect",
            description:
              "Definisce confini architetturali, tecnologie e trade-off.",
          },
          frontend_engineer: {
            name: "Frontend Engineer",
            description:
              "Implementa interfacce utente per browser.",
          },
          backend_engineer: {
            name: "Backend Engineer",
            description:
              "Implementa API, persistenza e comportamento server-side.",
          },
          mobile_engineer: {
            name: "Mobile Engineer",
            description:
              "Implementa applicazioni mobile native o multipiattaforma.",
          },
          qa_test_engineer: {
            name: "QA/Test Engineer",
            description:
              "Definisce ed esegue strategie di qualità automatizzate.",
          },
          security_reviewer: {
            name: "Security Reviewer",
            description:
              "Esamina autenticazione, autorizzazione, privacy e rischi.",
          },
          accessibility_reviewer: {
            name: "Accessibility Reviewer",
            description:
              "Esamina requisiti di accessibilità e barriere di interazione.",
          },
          integration_engineer: {
            name: "Integration Engineer",
            description:
              "Coordina servizi esterni e integrazione brownfield.",
          },
        },
      },
    },
  },
});

const resolvedApi = computed(
  () => props.api ?? apiClient,
);

const selectedDraft =
  ref<
    Partial<
      Record<AgentIdentifier, boolean>
    >
  >({});
const rationaleDraft =
  ref<
    Partial<
      Record<AgentIdentifier, string>
    >
  >({});
const gateReason = ref("");
const localError =
  ref<string | null>(null);

const initialSelected = computed(
  () =>
    new Set(
      store.currentVersion
        ?.selected_agent_ids ?? [],
    ),
);

const latestOperationStatus =
  computed(
    () =>
      store.lastGateDecision?.status ??
      store.lastGateSubmission
        ?.status ??
      store.lastEdit?.status ??
      store.lastGeneration?.status ??
      null,
  );

function executeAuthorized<T>(
  operation: (
    accessToken: string,
  ) => Promise<T>,
): Promise<T> {
  if (props.authorize !== undefined) {
    return props.authorize(operation);
  }

  return auth.withAccessToken(
    apiClient,
    operation,
  );
}

async function load(): Promise<void> {
  localError.value = null;

  await store.load(
    props.projectId,
    resolvedApi.value,
    executeAuthorized,
  );
}

watch(
  () => store.currentVersion,
  (version) => {
    const nextSelection:
      Partial<
        Record<
          AgentIdentifier,
          boolean
        >
      > = {};

    for (const entry of
      store.catalog?.agents ?? []) {
      nextSelection[entry.agent_id] =
        version?.selected_agent_ids.includes(
          entry.agent_id,
        ) ?? false;
    }

    selectedDraft.value =
      nextSelection;
    rationaleDraft.value = {};
  },
  {
    immediate: true,
  },
);

watch(
  () => props.projectId,
  async () => {
    await load();
  },
);

onMounted(load);

function translatedOrFallback(
  key: string,
  fallback: string,
): string {
  const translated = t(key);

  return translated === key
    ? fallback
    : translated;
}

function humanize(
  value: string,
): string {
  return value
    .toLocaleLowerCase()
    .replaceAll("_", " ")
    .replace(
      /^./,
      (character) =>
        character.toLocaleUpperCase(),
    );
}

function statusText(
  value: string,
): string {
  return translatedOrFallback(
    `flow.statuses.${value}`,
    humanize(value),
  );
}

function constraintText(
  value: string,
): string {
  return translatedOrFallback(
    `flow.constraints.${value}`,
    humanize(value),
  );
}

function sourceText(
  value: string,
): string {
  return translatedOrFallback(
    `flow.sources.${value}`,
    humanize(value),
  );
}

function revisionText(
  value: string,
): string {
  return translatedOrFallback(
    `flow.revisions.${value}`,
    humanize(value),
  );
}

function capabilityText(
  value: string,
): string {
  return translatedOrFallback(
    `flow.capabilitiesMap.${value}`,
    humanize(value),
  );
}

function reasonText(
  reason: TeamSelectionReasonResponse,
): string {
  return translatedOrFallback(
    `flow.reasons.${reason.code}`,
    humanize(reason.code),
  );
}

function errorText(
  detail: string,
): string {
  return translatedOrFallback(
    `flow.errors.${detail}`,
    detail,
  );
}

function roleName(
  entry: AgentCatalogEntryResponse,
): string {
  return translatedOrFallback(
    entry.name_key,
    humanize(entry.agent_id),
  );
}

function roleDescription(
  entry: AgentCatalogEntryResponse,
): string {
  return translatedOrFallback(
    entry.description_key,
    roleName(entry),
  );
}

function formatDate(
  value: string,
): string {
  return new Intl.DateTimeFormat(
    locale.value,
    {
      dateStyle: "medium",
      timeStyle: "short",
    },
  ).format(new Date(value));
}

function constraintFor(
  agentId: AgentIdentifier,
): TeamRoleConstraintResponse | null {
  return (
    store.currentVersion
      ?.role_constraints.find(
        (constraint) =>
          constraint.agent_id ===
          agentId,
      ) ?? null
  );
}

function memberFor(
  agentId: AgentIdentifier,
): ProposedTeamMemberResponse | null {
  return (
    store.currentVersion?.members.find(
      (member) =>
        member.agent_id === agentId,
    ) ?? null
  );
}

function isSelected(
  agentId: AgentIdentifier,
): boolean {
  return (
    selectedDraft.value[agentId] ??
    false
  );
}

function canEditRole(
  agentId: AgentIdentifier,
): boolean {
  return (
    store.currentVersion !== null &&
    constraintFor(agentId)
      ?.owner_editable === true
  );
}

function requiresRationale(
  agentId: AgentIdentifier,
): boolean {
  return (
    isSelected(agentId) &&
    !initialSelected.value.has(agentId)
  );
}

function setSelected(
  agentId: AgentIdentifier,
  event: Event,
): void {
  const target =
    event.target;

  if (
    !(target instanceof HTMLInputElement)
  ) {
    return;
  }

  selectedDraft.value[agentId] =
    target.checked;

  if (!target.checked) {
    delete rationaleDraft.value[
      agentId
    ];
  }
}

function setRationale(
  agentId: AgentIdentifier,
  event: Event,
): void {
  const target =
    event.target;

  if (
    !(target instanceof HTMLTextAreaElement)
  ) {
    return;
  }

  rationaleDraft.value[agentId] =
    target.value;
}

async function generateProposal(): Promise<void> {
  localError.value = null;

  await store.generateProposal(
    props.projectId,
    resolvedApi.value,
    executeAuthorized,
  );
}

function selectedAgentIds(
): readonly AgentIdentifier[] {
  return (
    store.catalog?.agents
      .map((entry) => entry.agent_id)
      .filter((agentId) =>
        isSelected(agentId),
      ) ?? []
  );
}

function ownerRationales(
): readonly OwnerAgentRationaleInput[] | null {
  const rationales:
    OwnerAgentRationaleInput[] = [];

  for (const agentId of
    selectedAgentIds()) {
    if (!requiresRationale(agentId)) {
      continue;
    }

    const statement = (
      rationaleDraft.value[
        agentId
      ] ?? ""
    ).trim();

    if (!statement) {
      localError.value =
        t("flow.rationaleRequired");

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
  localError.value = null;

  const rationales =
    ownerRationales();

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

async function submitGate(): Promise<void> {
  localError.value = null;

  await store.submitGate(
    props.projectId,
    resolvedApi.value,
    executeAuthorized,
  );
}

async function decideGate(
  action: AgentTeamGateDecisionAction,
): Promise<void> {
  localError.value = null;

  const reason =
    gateReason.value.trim();

  if (
    ["REJECT", "REQUEST_REVISION"].includes(
      action,
    ) &&
    !reason
  ) {
    localError.value =
      t("flow.gateReasonRequired");

    return;
  }

  const result =
    await store.decideGate(
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

function eventLabel(
  event: HumanGateEventResponse,
): string {
  return statusText(event.kind);
}
</script>

<template>
  <section
    class="grid gap-8"
    aria-labelledby="team-selection-title"
  >
    <header class="grid gap-2">
      <h2
        id="team-selection-title"
        class="text-2xl font-black text-slate-950"
      >
        {{ t("flow.title") }}
      </h2>

      <p class="m-0 max-w-3xl text-slate-600">
        {{ t("flow.intro") }}
      </p>
    </header>

    <div
      class="min-h-6"
      aria-live="polite"
      aria-atomic="true"
    >
      <p
        v-if="store.busy"
        class="m-0 text-sm font-semibold text-slate-700"
      >
        {{ t("flow.loading") }}
      </p>

      <p
        v-else-if="
          localError !== null ||
          store.errorDetail !== null
        "
        class="m-0 rounded-xl border border-red-200 bg-red-50 p-4 text-sm font-semibold text-red-800"
        role="alert"
      >
        {{
          t("flow.error", {
            detail:
              localError ??
              errorText(
                store.errorDetail ??
                  "unexpected_error",
              ),
          })
        }}
      </p>

      <p
        v-else-if="
          latestOperationStatus !== null
        "
        class="m-0 rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm font-semibold text-blue-900"
      >
        {{
          t("flow.latestOperation", {
            status: statusText(
              latestOperationStatus,
            ),
          })
        }}
      </p>
    </div>

    <div class="flex flex-wrap gap-3">
      <button
        type="button"
        class="min-h-11 rounded-xl border border-slate-300 bg-white px-4 py-2 font-bold text-slate-900 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 disabled:opacity-60"
        :disabled="store.busy"
        @click="load"
      >
        {{ t("flow.refresh") }}
      </button>

      <button
        type="button"
        class="min-h-11 rounded-xl bg-slate-950 px-4 py-2 font-bold text-white hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2 disabled:opacity-60"
        :disabled="store.busy"
        @click="generateProposal"
      >
        {{ t("flow.generate") }}
      </button>
    </div>

    <section
      class="grid gap-3 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
      aria-labelledby="project-readiness-title"
    >
      <h3
        id="project-readiness-title"
        class="text-xl font-black text-slate-950"
      >
        {{ t("flow.readiness") }}
      </h3>

      <p
        v-if="store.readiness !== null"
        class="m-0 text-lg font-black"
        :class="
          store.readiness.status ===
          'READY_FOR_MAIN_WORKFLOW'
            ? 'text-emerald-700'
            : 'text-amber-800'
        "
      >
        {{
          statusText(
            store.readiness.status,
          )
        }}
      </p>

      <p
        v-if="
          store.readiness?.status ===
          'READY_FOR_MAIN_WORKFLOW'
        "
        class="m-0 text-slate-700"
      >
        {{ t("flow.ready") }}
      </p>

      <p class="m-0 text-sm text-slate-600">
        {{ t("flow.notStarted") }}
      </p>
    </section>

    <section
      class="grid gap-5 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
      aria-labelledby="current-team-proposal-title"
    >
      <template
        v-if="
          store.currentVersion !== null
        "
      >
        <header class="grid gap-2">
          <h3
            id="current-team-proposal-title"
            class="text-xl font-black text-slate-950"
          >
            {{ t("flow.currentProposal") }}
          </h3>

          <p class="m-0 font-bold text-slate-800">
            {{
              t("flow.version", {
                number:
                  store.currentVersion
                    .version_number,
              })
            }}
            ·
            {{
              revisionText(
                store.currentVersion
                  .revision_kind,
              )
            }}
          </p>

          <p
            v-if="
              store.currentVersion
                .based_on_version_number !==
              null
            "
            class="m-0 text-sm text-slate-600"
          >
            {{
              t("flow.basedOn", {
                number:
                  store.currentVersion
                    .based_on_version_number,
              })
            }}
          </p>
        </header>

        <dl
          class="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-3"
        >
          <div class="grid gap-1">
            <dt class="font-black text-slate-800">
              {{ t("flow.provider") }}
            </dt>
            <dd class="m-0 text-slate-600">
              {{
                store.currentVersion
                  .provider_kind
              }}
              ·
              {{
                store.currentVersion
                  .provider_id
              }}
            </dd>
          </div>

          <div class="grid gap-1">
            <dt class="font-black text-slate-800">
              {{ t("flow.briefVersion") }}
            </dt>
            <dd class="m-0 text-slate-600">
              {{
                store.currentVersion
                  .brief_version_number
              }}
            </dd>
          </div>

          <div class="grid gap-1">
            <dt class="font-black text-slate-800">
              {{ t("flow.catalogVersion") }}
            </dt>
            <dd class="m-0 text-slate-600">
              {{
                store.currentVersion
                  .catalog_version
              }}
            </dd>
          </div>

          <div class="grid gap-1 sm:col-span-2 lg:col-span-3">
            <dt class="font-black text-slate-800">
              {{ t("flow.contentHash") }}
            </dt>
            <dd class="m-0 break-all font-mono text-xs text-slate-600">
              {{
                store.currentVersion
                  .content_hash
              }}
            </dd>
          </div>

          <div class="grid gap-1 sm:col-span-2 lg:col-span-3">
            <dt class="font-black text-slate-800">
              {{ t("flow.constraintsHash") }}
            </dt>
            <dd class="m-0 break-all font-mono text-xs text-slate-600">
              {{
                store.currentVersion
                  .constraints_content_hash
              }}
            </dd>
          </div>
        </dl>
      </template>

      <p
        v-else
        id="current-team-proposal-title"
        class="m-0 text-slate-600"
      >
        {{ t("flow.noProposal") }}
      </p>
    </section>

    <section
      v-if="
        store.lastGeneration?.issues.length ||
        store.currentVersion
          ?.constraint_issues.length
      "
      class="grid gap-3 rounded-2xl border border-red-200 bg-red-50 p-5 text-red-900"
      aria-labelledby="team-constraint-issues-title"
    >
      <h3
        id="team-constraint-issues-title"
        class="text-lg font-black"
      >
        {{ t("flow.constraintIssues") }}
      </h3>

      <ul class="grid gap-2">
        <li
          v-for="issue in (
            store.lastGeneration?.issues ??
            store.currentVersion
              ?.constraint_issues ??
            []
          )"
          :key="`${issue.code}:${issue.agent_id}`"
          class="font-semibold"
        >
          {{ humanize(issue.agent_id) }}
          ·
          {{ humanize(issue.code) }}
        </li>
      </ul>
    </section>

    <form
      class="grid gap-5 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
      data-testid="team-selection-form"
      @submit.prevent="saveTeam"
    >
      <fieldset class="grid gap-4">
        <legend
          class="text-xl font-black text-slate-950"
        >
          {{ t("flow.teamEditor") }}
        </legend>

        <p class="m-0 text-sm text-slate-600">
          {{ t("flow.teamEditorIntro") }}
        </p>

        <div
          class="grid gap-4 lg:grid-cols-2"
        >
          <article
            v-for="entry in store.catalog?.agents ?? []"
            :key="entry.agent_id"
            class="grid gap-4 rounded-xl border border-slate-200 p-4"
          >
            <header
              class="flex items-start justify-between gap-4"
            >
              <div class="grid gap-1">
                <h4 class="font-black text-slate-950">
                  {{ roleName(entry) }}
                </h4>

                <p class="m-0 text-sm text-slate-600">
                  {{ roleDescription(entry) }}
                </p>
              </div>

              <span
                class="shrink-0 rounded-full px-3 py-1 text-xs font-black"
                :class="{
                  'bg-emerald-100 text-emerald-800':
                    constraintFor(
                      entry.agent_id,
                    )?.kind ===
                    'MANDATORY',
                  'bg-blue-100 text-blue-800':
                    constraintFor(
                      entry.agent_id,
                    )?.kind ===
                    'OPTIONAL',
                  'bg-slate-200 text-slate-700':
                    constraintFor(
                      entry.agent_id,
                    ) === null,
                  'bg-red-100 text-red-800':
                    [
                      'IMPOSSIBLE',
                      'CONFLICT',
                    ].includes(
                      constraintFor(
                        entry.agent_id,
                      )?.kind ?? '',
                    ),
                }"
              >
                {{
                  constraintText(
                    constraintFor(
                      entry.agent_id,
                    )?.kind ??
                      "NOT_EVALUATED",
                  )
                }}
              </span>
            </header>

            <label
              class="flex min-h-11 items-center gap-3 rounded-lg border border-slate-200 p-3 font-bold text-slate-800"
            >
              <input
                type="checkbox"
                :data-testid="`role-${entry.agent_id}`"
                :checked="
                  isSelected(
                    entry.agent_id,
                  )
                "
                :disabled="
                  !canEditRole(
                    entry.agent_id,
                  )
                "
                @change="
                  setSelected(
                    entry.agent_id,
                    $event,
                  )
                "
              />

              {{
                isSelected(
                  entry.agent_id,
                )
                  ? t("flow.selected")
                  : t("flow.notSelected")
              }}
            </label>

            <div
              v-if="
                entry.capabilities.length >
                0
              "
              class="grid gap-2"
            >
              <p class="m-0 text-sm font-black text-slate-800">
                {{ t("flow.capabilities") }}
              </p>

              <ul class="flex flex-wrap gap-2">
                <li
                  v-for="capability in entry.capabilities"
                  :key="capability"
                  class="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700"
                >
                  {{
                    capabilityText(
                      capability,
                    )
                  }}
                </li>
              </ul>
            </div>

            <div
              v-if="
                constraintFor(
                  entry.agent_id,
                )?.reasons.length
              "
              class="grid gap-3"
            >
              <div
                v-for="reason in constraintFor(
                  entry.agent_id,
                )?.reasons ?? []"
                :key="reason.code"
                class="rounded-lg bg-slate-50 p-3 text-sm"
              >
                <p class="m-0 font-black text-slate-800">
                  {{ reasonText(reason) }}
                </p>

                <p
                  v-if="
                    reason.evidence
                      .fields.length > 0
                  "
                  class="m-0 mt-2 text-slate-600"
                >
                  {{ t("flow.evidenceFields") }}:
                  {{
                    reason.evidence.fields
                      .join(", ")
                  }}
                </p>

                <p
                  v-if="
                    reason.evidence
                      .terms.length > 0
                  "
                  class="m-0 mt-1 text-slate-600"
                >
                  {{ t("flow.evidenceTerms") }}:
                  {{
                    reason.evidence.terms
                      .join(", ")
                  }}
                </p>
              </div>
            </div>

            <p
              v-if="
                memberFor(
                  entry.agent_id,
                ) !== null
              "
              class="m-0 text-sm font-semibold text-slate-700"
            >
              {{ t("flow.source") }}:
              {{
                sourceText(
                  memberFor(
                    entry.agent_id,
                  )?.source ?? '',
                )
              }}
            </p>

            <label
              v-if="
                requiresRationale(
                  entry.agent_id,
                )
              "
              class="grid gap-2 text-sm font-bold text-slate-800"
            >
              {{ t("flow.ownerRationale") }}

              <textarea
                :data-testid="`rationale-${entry.agent_id}`"
                class="min-h-24 rounded-xl border border-slate-300 px-3 py-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950"
                :placeholder="
                  t(
                    'flow.rationalePlaceholder',
                  )
                "
                :value="
                  rationaleDraft[
                    entry.agent_id
                  ] ?? ''
                "
                @input="
                  setRationale(
                    entry.agent_id,
                    $event,
                  )
                "
              ></textarea>
            </label>
          </article>
        </div>
      </fieldset>

      <button
        v-if="
          store.currentVersion !== null
        "
        type="submit"
        class="min-h-12 rounded-xl bg-slate-950 px-5 py-3 font-bold text-white hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2 disabled:opacity-60"
        :disabled="store.busy"
      >
        {{ t("flow.saveTeam") }}
      </button>
    </form>

    <section
      class="grid gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
      aria-labelledby="team-proposal-history-title"
    >
      <h3
        id="team-proposal-history-title"
        class="text-xl font-black text-slate-950"
      >
        {{ t("flow.proposalHistory") }}
      </h3>

      <ol
        v-if="store.history.length > 0"
        class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3"
      >
        <li
          v-for="version in store.history"
          :key="version.id"
          class="grid gap-2 rounded-xl border border-slate-200 p-4"
        >
          <p class="m-0 font-black text-slate-900">
            {{
              t("flow.version", {
                number:
                  version.version_number,
              })
            }}
          </p>

          <p class="m-0 text-sm text-slate-600">
            {{
              revisionText(
                version.revision_kind,
              )
            }}
          </p>

          <p class="m-0 text-sm text-slate-600">
            {{ formatDate(version.created_at) }}
          </p>

          <p class="m-0 text-sm text-slate-600">
            {{
              version.selected_agent_ids
                .length
            }}
            agents
          </p>

          <code class="break-all text-xs text-slate-500">
            {{ version.content_hash }}
          </code>
        </li>
      </ol>

      <p
        v-else
        class="m-0 text-slate-600"
      >
        {{ t("flow.noHistory") }}
      </p>
    </section>

    <section
      class="grid gap-5 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
      aria-labelledby="agent-team-gate-title"
    >
      <header class="grid gap-2">
        <h3
          id="agent-team-gate-title"
          class="text-xl font-black text-slate-950"
        >
          {{ t("flow.gateTitle") }}
        </h3>

        <template
          v-if="store.gate !== null"
        >
          <p class="m-0 text-sm text-slate-600">
            {{
              t("flow.status", {
                status: statusText(
                  store.gate.status,
                ),
              })
            }}
          </p>

          <p class="m-0 text-sm text-slate-600">
            {{
              t("flow.version", {
                number:
                  store.gate.artifact
                    .version,
              })
            }}
            ·
            <code>
              {{
                store.gate.artifact
                  .content_hash
                  .slice(0, 12)
              }}
            </code>
          </p>
        </template>

        <p
          v-else
          class="m-0 text-sm text-slate-600"
        >
          {{ t("flow.noGate") }}
        </p>
      </header>

      <button
        type="button"
        class="min-h-11 rounded-xl bg-slate-950 px-4 py-2 font-bold text-white hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2 disabled:opacity-60"
        :disabled="
          store.busy ||
          store.currentVersion === null
        "
        @click="submitGate"
      >
        {{ t("flow.submitGate") }}
      </button>

      <template
        v-if="store.gate !== null"
      >
        <label class="grid gap-2 font-bold text-slate-800">
          {{ t("flow.gateReason") }}

          <textarea
            v-model="gateReason"
            class="min-h-24 rounded-xl border border-slate-300 px-3 py-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950"
          ></textarea>
        </label>

        <div
          v-if="
            store.gate.status ===
            'PENDING_APPROVAL'
          "
          class="flex flex-wrap gap-3"
        >
          <button
            type="button"
            class="min-h-11 rounded-xl bg-emerald-700 px-4 py-2 font-bold text-white hover:bg-emerald-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-700 focus-visible:ring-offset-2 disabled:opacity-60"
            :disabled="store.busy"
            @click="decideGate('APPROVE')"
          >
            {{ t("flow.approve") }}
          </button>

          <button
            type="button"
            class="min-h-11 rounded-xl border border-red-300 bg-white px-4 py-2 font-bold text-red-800 hover:bg-red-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-700 focus-visible:ring-offset-2 disabled:opacity-60"
            :disabled="store.busy"
            @click="decideGate('REJECT')"
          >
            {{ t("flow.reject") }}
          </button>

          <button
            type="button"
            class="min-h-11 rounded-xl border border-amber-300 bg-white px-4 py-2 font-bold text-amber-900 hover:bg-amber-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-700 focus-visible:ring-offset-2 disabled:opacity-60"
            :disabled="store.busy"
            @click="
              decideGate(
                'REQUEST_REVISION',
              )
            "
          >
            {{ t("flow.requestRevision") }}
          </button>

          <button
            type="button"
            class="min-h-11 rounded-xl border border-slate-300 bg-white px-4 py-2 font-bold text-slate-800 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 disabled:opacity-60"
            :disabled="store.busy"
            @click="decideGate('PAUSE')"
          >
            {{ t("flow.pause") }}
          </button>
        </div>

        <div
          v-else-if="
            store.gate.status === 'PAUSED'
          "
          class="flex flex-wrap gap-3"
        >
          <button
            type="button"
            class="min-h-11 rounded-xl bg-slate-950 px-4 py-2 font-bold text-white hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2 disabled:opacity-60"
            :disabled="store.busy"
            @click="decideGate('RESUME')"
          >
            {{ t("flow.resume") }}
          </button>

          <button
            type="button"
            class="min-h-11 rounded-xl border border-red-300 bg-white px-4 py-2 font-bold text-red-800 hover:bg-red-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-700 focus-visible:ring-offset-2 disabled:opacity-60"
            :disabled="store.busy"
            @click="decideGate('CANCEL')"
          >
            {{ t("flow.cancel") }}
          </button>
        </div>

        <button
          v-else-if="
            [
              'REVISION_REQUESTED',
              'PAUSED_NEEDS_HUMAN',
            ].includes(
              store.gate.status,
            )
          "
          type="button"
          class="min-h-11 rounded-xl border border-red-300 bg-white px-4 py-2 font-bold text-red-800 hover:bg-red-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-700 focus-visible:ring-offset-2 disabled:opacity-60"
          :disabled="store.busy"
          @click="decideGate('CANCEL')"
        >
          {{ t("flow.cancel") }}
        </button>
      </template>

      <div class="grid gap-3">
        <h4 class="text-lg font-black text-slate-900">
          {{ t("flow.eventHistory") }}
        </h4>

        <ol
          v-if="store.gateEvents.length > 0"
          class="grid gap-3"
        >
          <li
            v-for="event in store.gateEvents"
            :key="event.id"
            class="rounded-xl border border-slate-200 p-4"
          >
            <p class="m-0 font-bold text-slate-900">
              {{ eventLabel(event) }}
            </p>

            <p class="m-0 mt-1 text-sm text-slate-600">
              {{
                statusText(
                  event.previous_status,
                )
              }}
              →
              {{
                statusText(
                  event.resulting_status,
                )
              }}
              ·
              {{ formatDate(event.occurred_at) }}
            </p>

            <p
              v-if="event.reason"
              class="m-0 mt-2 text-sm text-slate-700"
            >
              {{ event.reason }}
            </p>
          </li>
        </ol>

        <p
          v-else
          class="m-0 text-slate-600"
        >
          {{ t("flow.noEvents") }}
        </p>
      </div>
    </section>
  </section>
</template>