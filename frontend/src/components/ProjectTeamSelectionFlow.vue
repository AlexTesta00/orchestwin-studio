<script setup lang="ts">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  onUpdated,
  provide,
  ref,
  useId,
  watch,
} from "vue";
import { useI18n } from "vue-i18n";

import { apiClient } from "@/api/client";
import type {
  AgentIdentifier,
  AgentTeamApi,
  AgentTeamGateDecisionAction,
  AgentTeamGateDecisionResponse,
  AspectView,
  PerspectiveView,
  RuleEvidenceResponse,
} from "@/api/team-contracts";
import type { HumanGateEventResponse } from "@/api/workflow-contracts";
import { useAuthStore } from "@/stores/auth";
import { useGuidanceStore } from "@/stores/guidance";
import { type TeamAuthorizedRequest, useTeamStore } from "@/stores/team";
import UiButton from "./UiButton.vue";
import UiDecisionBar from "./UiDecisionBar.vue";
import UiStateBlock from "./UiStateBlock.vue";
import UiTechnicalDetails from "./UiTechnicalDetails.vue";
import { surfaceKey, type SurfaceContext } from "./UiSurface.vue";
import { type UpstreamValue, watchUpstream } from "./upstreamChange";

const props = withDefaults(
  defineProps<{
    projectId: string;
    api?: AgentTeamApi;
    authorize?: TeamAuthorizedRequest;
    upstream?: UpstreamValue;
    active?: boolean;
    sectionsMode?: boolean;
  }>(),
  { upstream: null, active: true, sectionsMode: false },
);

const emit = defineEmits<{ "sections-changed": [] }>();

const auth = useAuthStore();
const guidance = useGuidanceStore();
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
        region: "Perspectives",
        prepareText:
          "The perspectives are derived from the approved brief, and you can change them afterwards.",
        prepare: "Prepare the perspectives",
        prepareAgain: "Prepare the perspectives again",
        outdated: "The brief changed: prepare the perspectives again.",
        briefFirst:
          "Approve the brief first: the perspectives are derived from the approved brief.",
        updateStudio: "Update the Studio to see the perspectives.",
        digest: "In short: {n} of 5 perspectives applied.",
        toDecide: "For you to decide: {names}.",
        approved:
          "You already approved the perspectives. You can still change them: each change creates a new version to approve, and the sections that follow are updated with one gesture without losing their content.",
        brings: "What it brings",
        inDefinition: "In Definition",
        inDesign: "In Design & Evaluation",
        wordsFor: "In favour: {words}",
        wordsAgainst: "Against: {words}",
        quotedTerm: "“{term}”",
        termsInFields: "{terms} in {fields}",
        toBeSaved: "To be saved",
        changesPending: "You changed the perspectives: save to create their new version.",
        discardChanges: "Undo the changes",
        save: "Save the changes",
        loading: "Updating the perspectives…",
        preparing: "Preparing the perspectives…",
        refresh: "Refresh",
        retry: "Try again",
        decisionApprove:
          "{n} of 5 perspectives will guide the requirements and the design. You can change them later.",
        decisionApproveUnknown: "You can change the perspectives later.",
        decisionResume: "You paused this decision. Resume it when you are ready.",
        saveFirst: "Save the changes to the perspectives before deciding.",
        requestPlaceholder:
          "Write what you would change in the perspectives: the note stays in the history of the decisions.",
        approve: "Approve the perspectives",
        resume: "Resume the decision",
        otherDecisions: "Other decisions",
        gateReason: "Reason for your decision",
        gateReasonHint: "Needed to reject the perspectives.",
        reject: "Reject the perspectives",
        pause: "Pause the decision",
        cancel: "Cancel the decision",
        gateReasonRequired: "To reject the perspectives or to ask for changes, write a reason.",
        revisionRequested:
          "You asked for changes. Switch the perspectives you want and save: the new version comes back for your approval.",
        revisionNote: "Your note: “{note}”",
        pausedNeedsHuman: "The decision is stopped and needs your intervention.",
        cancelled: "You cancelled this decision. Change the perspectives to prepare a new version.",
        rejected: "You rejected these perspectives. Change them to prepare a new version.",
        technicalSummary: "Version {number} · {state}",
        stateApproved: "approved",
        statePending: "waiting for your decision",
        stateDraft: "being prepared",
        proposalHistory: "Versions of the perspectives",
        eventHistory: "Previous decisions",
        noHistory: "No version of the perspectives is available.",
        noEvents: "No decision on the perspectives has been recorded yet.",
        version: "Version {number}",
        revision: "Revision",
        basedOn: "Based on version",
        briefVersion: "Brief version",
        contentHash: "Content hash",
        constraintsHash: "Constraint hash",
        gateStatus: "Approval",
        decisionCounter: "Decision no. {n}",
        latestOperation: "Latest operation",
        error: "Error in the perspectives: {detail}",
        perspectives: {
          UX: {
            name: "User experience (UX)",
            line: "Looks at the project through the eyes of the people who will use it: goals, context, places where they may get stuck.",
            definition:
              "Stories and scenarios written from each twin's point of view; each requirement says what the person sees.",
            design:
              "Each alternative takes every twin to their goal in few steps and lets them correct a mistake.",
          },
          ACCESSIBILITY: {
            name: "Accessibility",
            line: "Checks that everyone can use it: keyboard, contrast, readable text, clear messages.",
            definition:
              "Requirements and criteria on keyboard, contrast, names of controls and error messages.",
            design:
              "Every action reachable from the keyboard, readable contrast, no information by colour alone.",
          },
          SOFTWARE_ENGINEERING: {
            name: "Software engineering",
            line: "Keeps the project feasible within its technical constraints, time and budget, and verifiable.",
            definition:
              "Requirements feasible within the constraints of the brief and criteria that can be checked by using the application.",
            design:
              "Alternatives that can be built, with the empty, loading and error states of each screen.",
          },
          PRODUCT: {
            name: "Product",
            line: "Keeps the priorities: what the first version needs and what can wait.",
            definition: "The priority of each requirement and what stays out.",
            design: "For each alternative, which goal it serves best and what it gives up.",
          },
          SECURITY: {
            name: "Security",
            line: "Protects data and access: who may see and do what.",
            definition:
              "Data and actions to protect, access, session, what happens with wrong credentials.",
            design:
              "How one sees being signed in and how to sign out, confirmations before deleting, sensitive data not in full.",
          },
        },
        aspects: {
          WEB: {
            name: "Web interface",
            line: "Works in the browser, from phone to desktop.",
          },
          SERVICES: {
            name: "Services and data",
            line: "Data and logic that live on a server.",
          },
          MOBILE: {
            name: "Mobile",
            line: "Use on phones and tablets.",
          },
          INTEGRATIONS: {
            name: "Connections to other systems",
            line: "Data exchanged with outside services.",
          },
        },
        standing: {
          ALWAYS: "Always applied",
          REQUIRED: "The brief asks for it",
          OPTIONAL_ON: "Applied, your choice",
          OPTIONAL_OFF: "Your choice",
          EXCLUDED: "The brief rules it out",
          CONTESTED: "The brief says two different things: you decide",
        },
        alwaysMissing:
          "This version was prepared before this perspective became always applied: prepare the perspectives again.",
        operations: {
          CREATED: "The perspectives have been prepared.",
          UPDATED: "The perspectives have been updated.",
          UNCHANGED: "The perspectives did not change.",
          SUBMITTED: "The perspectives have been sent for approval.",
          ALREADY_PENDING: "The perspectives are already waiting for your approval.",
          ALREADY_APPROVED: "The perspectives are already approved.",
          APPLIED: "Your decision on the perspectives has been recorded.",
          REJECTED: "The request was not accepted: the perspectives stayed as they were.",
          PROJECT_NOT_FOUND: "The project was not found: the perspectives did not change.",
          BRIEF_NOT_FOUND:
            "The brief of the project was not found: the perspectives did not change.",
          BRIEF_NOT_APPROVED: "The brief is not approved yet: the perspectives did not change.",
          BLOCKED_BY_CONSTRAINTS:
            "The perspectives were not prepared: the brief says things that contradict each other.",
          CONTEXT_CHANGED:
            "The project changed during the request: the perspectives did not change. Try again.",
          INVALID_PROPOSAL:
            "The proposal of the model was not valid: the perspectives did not change.",
          PROPOSAL_NOT_FOUND: "There are no perspectives yet.",
          PROPOSAL_STALE:
            "The perspectives were prepared for an earlier brief: prepare them again.",
          NEW_PROPOSAL_REQUIRED:
            "The perspectives have to be prepared again before they can be approved.",
          GATE_BLOCKED:
            "The decision on the perspectives is blocked: they were not sent for approval.",
          ITERATION_LIMIT_REACHED:
            "The perspectives reached the maximum number of revisions: they cannot go back for approval.",
          TRANSITION_REJECTED:
            "In their current state the perspectives cannot be sent for approval.",
          GATE_NOT_FOUND: "There is no open decision on the perspectives.",
          ARTIFACT_STALE:
            "The perspectives changed in the meantime: the decision was not applied. Check the current version.",
        },
        revisions: {
          PROPOSER_GENERATED: "Prepared by the Studio",
          OWNER_EDITED: "Changed by you",
        },
        statuses: {
          CREATED: "Created",
          UPDATED: "Updated",
          UNCHANGED: "Unchanged",
          REJECTED: "Rejected",
          PROJECT_NOT_FOUND: "Project not found",
          BRIEF_NOT_FOUND: "Brief not found",
          BRIEF_NOT_APPROVED: "Brief approval required",
          BLOCKED_BY_CONSTRAINTS: "Blocked by contradictory constraints",
          CONTEXT_CHANGED: "Project context changed",
          INVALID_PROPOSAL: "Invalid model output",
          PROPOSAL_NOT_FOUND: "Perspectives not found",
          PROPOSAL_STALE: "Perspectives of an earlier brief",
          SUBMITTED: "Sent for approval",
          ALREADY_PENDING: "Already pending approval",
          ALREADY_APPROVED: "Already approved",
          NEW_PROPOSAL_REQUIRED: "Perspectives to prepare again",
          GATE_BLOCKED: "Decision blocked",
          GATE_NOT_FOUND: "Decision not found",
          ITERATION_LIMIT_REACHED: "Revision limit reached",
          TRANSITION_REJECTED: "Transition rejected",
          APPLIED: "Applied",
          ARTIFACT_STALE: "Approved version out of date",
          DRAFT: "Draft",
          PENDING_APPROVAL: "Pending approval",
          APPROVED: "Approved",
          REVISION_REQUESTED: "Revision requested",
          PAUSED: "Paused",
          CANCELLED: "Cancelled",
          STALE: "Out of date",
          PAUSED_NEEDS_HUMAN: "Paused — your intervention is needed",
          BRIEF_APPROVAL_REQUIRED: "Brief approval required",
          TEAM_PROPOSAL_REQUIRED: "Perspectives to prepare",
          TEAM_APPROVAL_REQUIRED: "Perspectives approval required",
          READY_FOR_MAIN_WORKFLOW: "Perspectives approved",
          SUBMIT: "Sent for approval",
          APPROVE: "Approved",
          REJECT: "Rejected",
          REQUEST_REVISION: "Revision requested",
          PAUSE: "Paused",
          RESUME: "Resumed",
          CANCEL: "Cancelled",
          ARTIFACT_SUPERSEDED: "Version superseded",
        },
        errors: {
          gate_state_conflict:
            "The approval changed during the request. Refresh the perspectives and check their current state.",
          PROVIDER_UNAVAILABLE:
            "The model that prepares the perspectives is unavailable. Check that the models are available and try again.",
          TIMEOUT: "The model exceeded the time limit: the perspectives did not change.",
          invalid_request: "Check the decision and its reason (at most 2000 characters).",
          unexpected_error: "An unexpected error occurred.",
          unexpected_api_error: "The Studio returned an unexpected response.",
          project_not_found: "The project was not found.",
          team_proposal_not_found: "No perspectives were found.",
          team_proposal_context_not_found:
            "The project or its brief was not found: the perspectives did not change.",
          invalid_team_proposal:
            "The proposal of the model was not valid: the perspectives did not change.",
          agent_team_gate_not_found: "No decision on the perspectives was found.",
          agent_team_gate_context_not_found:
            "The project or its brief was not found: the decision was not recorded.",
          team_proposal_service_unavailable:
            "The service that prepares the perspectives is unavailable.",
          agent_team_service_unavailable:
            "The service that approves the perspectives is unavailable.",
        },
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
      },
    },
    it: {
      flow: {
        region: "Prospettive",
        prepareText: "Le prospettive nascono dal brief approvato, e dopo puoi cambiarle.",
        prepare: "Prepara le prospettive",
        prepareAgain: "Prepara di nuovo le prospettive",
        outdated: "Il brief è cambiato: prepara di nuovo le prospettive.",
        briefFirst: "Approva prima il brief: le prospettive nascono dal brief approvato.",
        updateStudio: "Aggiorna lo Studio per vedere le prospettive.",
        digest:
          "In breve: {n} prospettiva applicata su 5. | In breve: {n} prospettive applicate su 5.",
        toDecide: "Da decidere: {names}.",
        approved:
          "Hai già approvato le prospettive. Puoi ancora cambiarle: ogni cambio crea una versione nuova da approvare, e le sezioni che seguono si aggiornano con un gesto senza perdere i contenuti.",
        brings: "Che cosa porta",
        inDefinition: "In Definizione",
        inDesign: "In Design e valutazione",
        wordsFor: "A favore: {words}",
        wordsAgainst: "Contro: {words}",
        quotedTerm: "«{term}»",
        termsInFields: "{terms} in {fields}",
        toBeSaved: "Da salvare",
        changesPending: "Hai cambiato le prospettive: salva per crearne la nuova versione.",
        discardChanges: "Annulla le modifiche",
        save: "Salva le modifiche",
        loading: "Aggiornamento delle prospettive…",
        preparing: "Preparo le prospettive…",
        refresh: "Aggiorna",
        retry: "Riprova",
        decisionApprove:
          "{n} prospettiva su 5 guiderà requisiti e design. Potrai cambiarle più avanti. | {n} prospettive su 5 guideranno requisiti e design. Potrai cambiarle più avanti.",
        decisionApproveUnknown: "Potrai cambiare le prospettive più avanti.",
        decisionResume: "Hai messo in pausa questa decisione. Riprendila quando sei pronto.",
        saveFirst: "Salva le modifiche alle prospettive prima di decidere.",
        requestPlaceholder:
          "Scrivi che cosa cambieresti nelle prospettive: la nota resta nella cronologia delle decisioni.",
        approve: "Approva le prospettive",
        resume: "Riprendi la decisione",
        otherDecisions: "Altre decisioni",
        gateReason: "Motivazione della decisione",
        gateReasonHint: "Serve per rifiutare le prospettive.",
        reject: "Rifiuta le prospettive",
        pause: "Metti in pausa la decisione",
        cancel: "Annulla la decisione",
        gateReasonRequired:
          "Per rifiutare le prospettive o chiedere modifiche scrivi una motivazione.",
        revisionRequested:
          "Hai chiesto modifiche. Cambia le prospettive che vuoi e salva: la nuova versione tornerà alla tua approvazione.",
        revisionNote: "La tua nota: «{note}»",
        pausedNeedsHuman: "La decisione è ferma e serve il tuo intervento.",
        cancelled:
          "Hai annullato questa decisione. Cambia le prospettive per prepararne una nuova versione.",
        rejected: "Hai rifiutato queste prospettive. Cambiale per prepararne una nuova versione.",
        technicalSummary: "Versione {number} · {state}",
        stateApproved: "approvata",
        statePending: "in attesa della tua decisione",
        stateDraft: "in preparazione",
        proposalHistory: "Versioni delle prospettive",
        eventHistory: "Decisioni precedenti",
        noHistory: "Non è disponibile alcuna versione delle prospettive.",
        noEvents: "Non è stata ancora registrata alcuna decisione sulle prospettive.",
        version: "Versione {number}",
        revision: "Revisione",
        basedOn: "Basata sulla versione",
        briefVersion: "Versione del brief",
        contentHash: "Hash del contenuto",
        constraintsHash: "Hash dei vincoli",
        gateStatus: "Approvazione",
        decisionCounter: "Decisione n. {n}",
        latestOperation: "Ultima operazione",
        error: "Errore nelle prospettive: {detail}",
        perspectives: {
          UX: {
            name: "Esperienza d'uso (UX)",
            line: "Guarda il progetto con gli occhi di chi lo userà: obiettivi, contesto, punti in cui ci si può bloccare.",
            definition:
              "Storie e scenari scritti dal punto di vista di ogni twin; ogni requisito dice che cosa vede la persona.",
            design:
              "Ogni alternativa porta ogni twin al suo obiettivo in pochi passi e lascia correggere un errore.",
          },
          ACCESSIBILITY: {
            name: "Accessibilità",
            line: "Controlla che tutti possano usarlo: tastiera, contrasto, testi leggibili, messaggi chiari.",
            definition:
              "Requisiti e criteri su tastiera, contrasto, nomi dei controlli e messaggi di errore.",
            design:
              "Ogni azione raggiungibile da tastiera, contrasto leggibile, nessuna informazione affidata al solo colore.",
          },
          SOFTWARE_ENGINEERING: {
            name: "Ingegneria del software",
            line: "Tiene il progetto realizzabile entro vincoli tecnici, tempi e budget, e verificabile.",
            definition:
              "Requisiti realizzabili entro i vincoli del brief e criteri che si possono controllare usando l'applicazione.",
            design:
              "Alternative che si possono costruire, con gli stati vuoto, in caricamento e di errore di ogni schermata.",
          },
          PRODUCT: {
            name: "Prodotto",
            line: "Tiene le priorità: che cosa serve nella prima versione e che cosa può aspettare.",
            definition: "Priorità di ogni requisito e ciò che resta fuori.",
            design: "Per ogni alternativa, quale obiettivo serve meglio e a che cosa rinuncia.",
          },
          SECURITY: {
            name: "Sicurezza",
            line: "Protegge dati e accessi: chi può vedere e fare che cosa.",
            definition:
              "Dati e azioni da proteggere, accesso, sessione, che cosa succede con credenziali sbagliate.",
            design:
              "Come si vede di essere entrati e come si esce, conferme prima di cancellare, dati sensibili non in chiaro.",
          },
        },
        aspects: {
          WEB: {
            name: "Interfaccia web",
            line: "Funziona nel browser, dal telefono al computer.",
          },
          SERVICES: {
            name: "Servizi e dati",
            line: "Dati e funzioni che stanno su un server.",
          },
          MOBILE: {
            name: "Mobile",
            line: "Uso su telefono e tablet.",
          },
          INTEGRATIONS: {
            name: "Collegamenti con altri sistemi",
            line: "Scambio di dati con servizi esterni.",
          },
        },
        standing: {
          ALWAYS: "Sempre applicata",
          REQUIRED: "La chiede il brief",
          OPTIONAL_ON: "Applicata, a tua scelta",
          OPTIONAL_OFF: "A scelta",
          EXCLUDED: "Il brief la esclude",
          CONTESTED: "Il brief dice due cose diverse: decidi tu",
        },
        alwaysMissing:
          "Questa versione è stata preparata prima che questa prospettiva diventasse sempre applicata: prepara di nuovo le prospettive.",
        operations: {
          CREATED: "Le prospettive sono state preparate.",
          UPDATED: "Le prospettive sono state aggiornate.",
          UNCHANGED: "Le prospettive non sono cambiate.",
          SUBMITTED: "Le prospettive sono state mandate in approvazione.",
          ALREADY_PENDING: "Le prospettive aspettano già la tua approvazione.",
          ALREADY_APPROVED: "Le prospettive sono già approvate.",
          APPLIED: "La tua decisione sulle prospettive è stata registrata.",
          REJECTED: "La richiesta non è stata accettata: le prospettive sono rimaste com'erano.",
          PROJECT_NOT_FOUND: "Il progetto non è stato trovato: le prospettive non sono cambiate.",
          BRIEF_NOT_FOUND:
            "Il brief del progetto non è stato trovato: le prospettive non sono cambiate.",
          BRIEF_NOT_APPROVED: "Il brief non è ancora approvato: le prospettive non sono cambiate.",
          BLOCKED_BY_CONSTRAINTS:
            "Le prospettive non sono state preparate: il brief dice cose che si contraddicono.",
          CONTEXT_CHANGED:
            "Il progetto è cambiato durante la richiesta: le prospettive non sono cambiate. Riprova.",
          INVALID_PROPOSAL:
            "La proposta del modello non era valida: le prospettive non sono cambiate.",
          PROPOSAL_NOT_FOUND: "Non ci sono ancora prospettive.",
          PROPOSAL_STALE:
            "Le prospettive erano state preparate per un brief precedente: preparale di nuovo.",
          NEW_PROPOSAL_REQUIRED: "Prima di approvare le prospettive bisogna prepararle di nuovo.",
          GATE_BLOCKED:
            "La decisione sulle prospettive è bloccata: non sono state mandate in approvazione.",
          ITERATION_LIMIT_REACHED:
            "Le prospettive hanno raggiunto il numero massimo di revisioni: non possono tornare in approvazione.",
          TRANSITION_REJECTED:
            "Nello stato attuale le prospettive non possono essere mandate in approvazione.",
          GATE_NOT_FOUND: "Non c'è una decisione aperta sulle prospettive.",
          ARTIFACT_STALE:
            "Le prospettive sono cambiate nel frattempo: la decisione non è stata applicata. Controlla la versione attuale.",
        },
        revisions: {
          PROPOSER_GENERATED: "Preparata dallo Studio",
          OWNER_EDITED: "Cambiata da te",
        },
        statuses: {
          CREATED: "Creata",
          UPDATED: "Aggiornata",
          UNCHANGED: "Invariata",
          REJECTED: "Rifiutata",
          PROJECT_NOT_FOUND: "Progetto non trovato",
          BRIEF_NOT_FOUND: "Brief non trovato",
          BRIEF_NOT_APPROVED: "Serve l'approvazione del brief",
          BLOCKED_BY_CONSTRAINTS: "Bloccata da vincoli contraddittori",
          CONTEXT_CHANGED: "Il contesto del progetto è cambiato",
          INVALID_PROPOSAL: "Risposta del modello non valida",
          PROPOSAL_NOT_FOUND: "Prospettive non trovate",
          PROPOSAL_STALE: "Prospettive di un brief precedente",
          SUBMITTED: "Mandata in approvazione",
          ALREADY_PENDING: "Già in attesa di approvazione",
          ALREADY_APPROVED: "Già approvata",
          NEW_PROPOSAL_REQUIRED: "Prospettive da preparare di nuovo",
          GATE_BLOCKED: "Decisione bloccata",
          GATE_NOT_FOUND: "Decisione non trovata",
          ITERATION_LIMIT_REACHED: "Limite di revisioni raggiunto",
          TRANSITION_REJECTED: "Passaggio rifiutato",
          APPLIED: "Applicata",
          ARTIFACT_STALE: "La versione approvata non è più attuale",
          DRAFT: "Bozza",
          PENDING_APPROVAL: "In attesa di approvazione",
          APPROVED: "Approvata",
          REVISION_REQUESTED: "Revisione richiesta",
          PAUSED: "In pausa",
          CANCELLED: "Annullata",
          STALE: "Non più attuale",
          PAUSED_NEEDS_HUMAN: "In pausa — serve il tuo intervento",
          BRIEF_APPROVAL_REQUIRED: "Serve l'approvazione del brief",
          TEAM_PROPOSAL_REQUIRED: "Prospettive da preparare",
          TEAM_APPROVAL_REQUIRED: "Serve l'approvazione delle prospettive",
          READY_FOR_MAIN_WORKFLOW: "Prospettive approvate",
          SUBMIT: "Mandata in approvazione",
          APPROVE: "Approvata",
          REJECT: "Rifiutata",
          REQUEST_REVISION: "Revisione richiesta",
          PAUSE: "Messa in pausa",
          RESUME: "Ripresa",
          CANCEL: "Annullata",
          ARTIFACT_SUPERSEDED: "Versione sostituita",
        },
        errors: {
          gate_state_conflict:
            "L'approvazione è cambiata durante la richiesta. Aggiorna le prospettive e controlla il loro stato attuale.",
          PROVIDER_UNAVAILABLE:
            "Il modello che prepara le prospettive non è disponibile. Verifica lo stato dei modelli e riprova.",
          TIMEOUT: "Il modello ha superato il tempo disponibile: le prospettive non sono cambiate.",
          invalid_request: "Controlla la decisione e la motivazione (massimo 2000 caratteri).",
          unexpected_error: "Si è verificato un errore inatteso.",
          unexpected_api_error: "Lo Studio ha restituito una risposta inattesa.",
          project_not_found: "Il progetto non è stato trovato.",
          team_proposal_not_found: "Non sono state trovate prospettive.",
          team_proposal_context_not_found:
            "Il progetto o il suo brief non è stato trovato: le prospettive non sono cambiate.",
          invalid_team_proposal:
            "La proposta del modello non era valida: le prospettive non sono cambiate.",
          agent_team_gate_not_found: "Non è stata trovata alcuna decisione sulle prospettive.",
          agent_team_gate_context_not_found:
            "Il progetto o il suo brief non è stato trovato: la decisione non è stata registrata.",
          team_proposal_service_unavailable:
            "Il servizio che prepara le prospettive non è disponibile.",
          agent_team_service_unavailable:
            "Il servizio che approva le prospettive non è disponibile.",
        },
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
      },
    },
  },
});

type TeamDecision = "approve" | "resume";
type PerspectiveUnit = PerspectiveView | AspectView;
type PerspectivePart = "name" | "line" | "definition" | "design";
type AspectPart = "name" | "line";

interface BriefWords {
  readonly kind: "requested" | "excluded";
  readonly text: string;
}

const resolvedApi = computed(() => props.api ?? apiClient);
const uid = useId();

const draft = ref<Partial<Record<AgentIdentifier, boolean>>>({});
const openBrings = ref<ReadonlySet<string>>(new Set());
const gateReason = ref("");
const localError = ref<string | null>(null);
const approving = ref(false);
const root = ref<HTMLElement | null>(null);
const barTarget = ref<HTMLElement | null>(null);
const rowTarget = ref<HTMLElement | null>(null);
const decisionBar = ref<InstanceType<typeof UiDecisionBar> | null>(null);
let visibilityObserver: ResizeObserver | null = null;

const perspectives = computed<readonly PerspectiveView[] | null>(
  () => store.currentVersion?.perspectives ?? null,
);
const switchableUnits = computed<readonly PerspectiveUnit[]>(() =>
  (perspectives.value ?? [])
    .flatMap((perspective): PerspectiveUnit[] => [perspective, ...perspective.aspects])
    .filter((unit) => isSwitchable(unit)),
);
const changedUnits = computed(() =>
  switchableUnits.value.filter((unit) => unitApplied(unit) !== unit.applied),
);
const hasChanges = computed(() => changedUnits.value.length > 0);
const appliedCount = computed(
  () => (perspectives.value ?? []).filter((perspective) => unitApplied(perspective)).length,
);
const contestedNames = computed(() =>
  (perspectives.value ?? []).flatMap((perspective) => [
    ...(perspective.standing === "CONTESTED" ? [perspectiveName(perspective.key)] : []),
    ...perspective.aspects
      .filter((aspect) => aspect.standing === "CONTESTED")
      .map((aspect) => aspectName(aspect.key)),
  ]),
);
const digest = computed(() => {
  if (perspectives.value === null) return null;
  return {
    applied: t("flow.digest", { n: appliedCount.value }, appliedCount.value),
    decide:
      contestedNames.value.length === 0
        ? null
        : t("flow.toDecide", { names: contestedNames.value.join(", ") }),
  };
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
const switchesDisabled = computed(
  () => store.busy || proposalOutdated.value || briefApprovalRequired.value,
);
const approvedNote = computed(() =>
  teamApproved.value && props.sectionsMode ? t("flow.approved") : null,
);

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
  if (hasChanges.value) {
    return { primary: t("flow.approve"), description: t("flow.saveFirst") };
  }
  return {
    primary: t("flow.approve"),
    description:
      perspectives.value === null
        ? t("flow.decisionApproveUnknown")
        : t("flow.decisionApprove", { n: appliedCount.value }, appliedCount.value),
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
    { label: t("flow.briefVersion"), value: String(version.brief_version_number) },
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

function discardChanges(): void {
  draft.value = {};
}

watch(() => store.currentVersion, discardChanges, {
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

function revisionText(value: string): string {
  if (value === "OWNER_PROVIDED")
    return locale.value === "it" ? "Fornito dal proprietario" : "Owner supplied";
  return translatedOrFallback(`flow.revisions.${value}`, humanize(value));
}

function errorText(detail: string): string {
  return translatedOrFallback(`flow.errors.${detail}`, t("flow.errors.unexpected_error"));
}

function fieldText(field: string): string {
  return translatedOrFallback(`flow.fields.${field}`, humanize(field));
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(locale.value, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function perspectiveText(key: string, part: PerspectivePart): string | null {
  const path = `flow.perspectives.${key}.${part}`;
  return te(path) ? t(path) : null;
}

function aspectText(key: string, part: AspectPart): string | null {
  const path = `flow.aspects.${key}.${part}`;
  return te(path) ? t(path) : null;
}

function perspectiveName(key: string): string {
  return perspectiveText(key, "name") ?? humanize(key);
}

function aspectName(key: string): string {
  return aspectText(key, "name") ?? humanize(key);
}

function nameId(key: string): string {
  return `${uid}-${key}-name`;
}

function standingId(key: string): string {
  return `${uid}-${key}-standing`;
}

function lineId(key: string): string {
  return `${uid}-${key}-line`;
}

function bringsId(key: string): string {
  return `${uid}-${key}-brings`;
}

function describedBy(key: string, line: string | null): string {
  return line === null ? standingId(key) : `${standingId(key)} ${lineId(key)}`;
}

function isSwitchable(unit: PerspectiveUnit): boolean {
  return unit.editable && unit.agent_id !== null;
}

function unitApplied(unit: PerspectiveUnit): boolean {
  if (!isSwitchable(unit) || unit.agent_id === null) return unit.applied;
  return draft.value[unit.agent_id] ?? unit.applied;
}

function isChanged(unit: PerspectiveUnit): boolean {
  return isSwitchable(unit) && unitApplied(unit) !== unit.applied;
}

function isAlwaysMissing(unit: PerspectiveUnit): boolean {
  return unit.standing === "ALWAYS" && !unit.applied;
}

function standingText(unit: PerspectiveUnit): string {
  if (unit.standing === "OPTIONAL") {
    return unitApplied(unit) ? t("flow.standing.OPTIONAL_ON") : t("flow.standing.OPTIONAL_OFF");
  }
  return translatedOrFallback(`flow.standing.${unit.standing}`, humanize(unit.standing));
}

function uniqueValues<T>(values: readonly T[]): T[] {
  return [...new Set(values)];
}

function evidenceText(evidence: RuleEvidenceResponse | undefined): string | null {
  if (evidence === undefined) return null;
  const terms = uniqueValues(evidence.terms).map((term) => t("flow.quotedTerm", { term }));
  const fields = uniqueValues(evidence.fields).map((field) => fieldText(field));
  if (terms.length === 0 && fields.length === 0) return null;
  if (fields.length === 0) return terms.join(", ");
  if (terms.length === 0) return fields.join(", ");
  return t("flow.termsInFields", { terms: terms.join(", "), fields: fields.join(", ") });
}

function briefWords(unit: PerspectiveUnit): BriefWords[] {
  const requested = evidenceText(unit.requested);
  const excluded = evidenceText(unit.excluded);
  if (unit.standing === "REQUIRED") {
    return requested === null ? [] : [{ kind: "requested", text: requested }];
  }
  if (unit.standing === "EXCLUDED") {
    return excluded === null ? [] : [{ kind: "excluded", text: excluded }];
  }
  if (unit.standing !== "CONTESTED") return [];
  const words: BriefWords[] = [];
  if (requested !== null) {
    words.push({ kind: "requested", text: t("flow.wordsFor", { words: requested }) });
  }
  if (excluded !== null) {
    words.push({ kind: "excluded", text: t("flow.wordsAgainst", { words: excluded }) });
  }
  return words;
}

function setUnit(unit: PerspectiveUnit, event: Event): void {
  const target = event.target;

  if (!(target instanceof HTMLInputElement) || unit.agent_id === null) {
    return;
  }

  const next = { ...draft.value };

  if (target.checked === unit.applied) {
    delete next[unit.agent_id];
  } else {
    next[unit.agent_id] = target.checked;
  }

  draft.value = next;
}

function isBringsOpen(key: string): boolean {
  return openBrings.value.has(key);
}

function toggleBrings(key: string): void {
  const next = new Set(openBrings.value);

  if (next.has(key)) {
    next.delete(key);
  } else {
    next.add(key);
  }

  openBrings.value = next;
}

function draftSelection(): readonly AgentIdentifier[] {
  const current = store.currentVersion?.selected_agent_ids ?? [];
  const removed = new Set<AgentIdentifier>();
  const added: AgentIdentifier[] = [];

  for (const unit of changedUnits.value) {
    if (unit.agent_id === null) {
      continue;
    }

    if (!unitApplied(unit)) {
      removed.add(unit.agent_id);
    } else if (!current.includes(unit.agent_id) && !added.includes(unit.agent_id)) {
      added.push(unit.agent_id);
    }
  }

  return [...current.filter((agentId) => !removed.has(agentId)), ...added];
}

async function generateProposal(): Promise<void> {
  localError.value = null;

  const result = await store.generateProposal(
    props.projectId,
    resolvedApi.value,
    executeAuthorized,
  );

  if (result?.status === "CREATED") {
    emit("sections-changed");
  }
}

async function savePerspectives(): Promise<void> {
  if (store.busy || !hasChanges.value) return;
  localError.value = null;

  const result = await store.editCurrent(
    props.projectId,
    draftSelection(),
    resolvedApi.value,
    executeAuthorized,
  );

  if (result?.status === "UPDATED") {
    emit("sections-changed");
  }
}

async function submitGate(): Promise<boolean> {
  localError.value = null;

  const submission = await store.submitGate(props.projectId, resolvedApi.value, executeAuthorized);

  return submission !== null && gatePending.value;
}

async function decideGate(
  action: AgentTeamGateDecisionAction,
  note?: string,
): Promise<AgentTeamGateDecisionResponse | null> {
  localError.value = null;

  const reason = (note ?? gateReason.value).trim();

  if (["REJECT", "REQUEST_REVISION"].includes(action) && !reason) {
    localError.value = t("flow.gateReasonRequired");

    return null;
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

  return result;
}

async function approvePerspectives(): Promise<void> {
  if (approving.value || store.busy || hasChanges.value) return;
  approving.value = true;
  try {
    if (!gatePending.value && !(await submitGate())) return;
    const result = await decideGate("APPROVE");
    if (result?.status === "APPLIED") {
      emit("sections-changed");
    }
  } finally {
    approving.value = false;
  }
}

async function onPrimary(): Promise<void> {
  if (decision.value === "resume") {
    await decideGate("RESUME");
    return;
  }
  await approvePerspectives();
}

async function onRequest(text: string): Promise<void> {
  if (!requestAvailable.value) return;
  if ((await decideGate("REQUEST_REVISION", text)) !== null) {
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
      :text="
        proposalOutdated ? t('flow.outdated') : guidance.expert ? undefined : t('flow.prepareText')
      "
      data-testid="team-proposal-needed"
    >
      <UiButton
        variant="pill"
        :disabled="store.busy"
        data-testid="generate-team"
        @click="generateProposal"
      >
        {{ t("flow.prepare") }}
      </UiButton>
    </UiStateBlock>

    <template v-if="store.currentVersion !== null">
      <div
        v-if="digest !== null || approvedNote !== null || gateNotice !== null"
        class="grid gap-3"
      >
        <p
          v-if="digest !== null"
          class="m-0 text-base leading-normal text-on-night-3"
          data-testid="perspectives-digest"
        >
          <strong class="font-semibold text-on-night">{{ digest.applied }}</strong>
          {{ digest.decide ?? "" }}
        </p>
        <UiStateBlock
          v-if="approvedNote !== null"
          kind="empty"
          :text="approvedNote"
          data-testid="perspectives-approved"
        />
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

      <UiStateBlock
        v-if="perspectives === null"
        kind="empty"
        :text="t('flow.updateStudio')"
        data-testid="perspectives-unavailable"
      />

      <form
        v-else
        class="grid gap-3"
        data-testid="team-selection-form"
        @submit.prevent="savePerspectives"
      >
        <ul
          class="m-0 list-none overflow-hidden rounded-panel border border-night-line bg-night-raised p-0"
          data-testid="perspective-list"
        >
          <li
            v-for="perspective in perspectives"
            :key="perspective.key"
            class="border-b border-on-night/8 px-4 pt-4 pb-2 last:border-b-0 sm:px-[18px]"
            data-testid="perspective-row"
            :data-perspective="perspective.key"
            :data-standing="perspective.standing"
            :data-applied="unitApplied(perspective) ? 'true' : 'false'"
          >
            <div class="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-x-3 sm:gap-x-4">
              <div class="min-w-0">
                <div class="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                  <h2
                    :id="nameId(perspective.key)"
                    class="m-0 text-base font-semibold"
                    data-testid="unit-name"
                  >
                    {{ perspectiveName(perspective.key) }}
                  </h2>
                  <span
                    v-if="!isAlwaysMissing(perspective)"
                    :id="standingId(perspective.key)"
                    class="text-xs text-on-night-3"
                    data-testid="unit-standing"
                  >
                    {{ standingText(perspective) }}
                  </span>
                  <span
                    v-if="isChanged(perspective)"
                    class="text-xs font-medium text-petrol-on-night-2"
                    data-testid="unit-pending"
                  >
                    {{ t("flow.toBeSaved") }}
                  </span>
                </div>
                <p
                  v-if="perspectiveText(perspective.key, 'line') !== null"
                  :id="lineId(perspective.key)"
                  class="m-0 mt-0.5 text-sm leading-[1.45] text-on-night-3"
                  data-testid="unit-line"
                >
                  {{ perspectiveText(perspective.key, "line") }}
                </p>
                <p
                  v-for="words in briefWords(perspective)"
                  :key="words.kind"
                  class="m-0 mt-1 text-sm leading-[1.45] text-on-night-2"
                  data-testid="unit-brief-words"
                  :data-words="words.kind"
                >
                  {{ words.text }}
                </p>
                <div
                  v-if="isAlwaysMissing(perspective)"
                  class="mt-2 grid justify-items-start gap-2"
                  data-testid="unit-always-missing"
                >
                  <p class="m-0 text-sm leading-[1.45] text-on-night-2">
                    {{ t("flow.alwaysMissing") }}
                  </p>
                  <UiButton
                    variant="secondary"
                    :disabled="store.busy || briefApprovalRequired"
                    :aria-describedby="nameId(perspective.key)"
                    data-testid="perspective-prepare-again"
                    @click="generateProposal"
                  >
                    {{ t("flow.prepareAgain") }}
                  </UiButton>
                </div>
              </div>
              <label
                v-if="isSwitchable(perspective)"
                class="relative inline-flex h-11 w-[52px] shrink-0 cursor-pointer items-center has-disabled:cursor-not-allowed"
              >
                <input
                  type="checkbox"
                  role="switch"
                  class="peer absolute inset-0 m-0 size-full cursor-pointer opacity-0 disabled:cursor-not-allowed"
                  :data-testid="`perspective-switch-${perspective.key}`"
                  :aria-labelledby="nameId(perspective.key)"
                  :aria-describedby="
                    describedBy(perspective.key, perspectiveText(perspective.key, 'line'))
                  "
                  :checked="unitApplied(perspective)"
                  :disabled="switchesDisabled"
                  @change="setUnit(perspective, $event)"
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
            </div>

            <div v-if="perspectiveText(perspective.key, 'definition') !== null">
              <button
                type="button"
                class="inline-flex min-h-11 items-center gap-2.5 text-sm font-medium text-on-night-3 transition-colors duration-150 hover:text-on-night"
                :aria-expanded="isBringsOpen(perspective.key) ? 'true' : 'false'"
                :aria-controls="bringsId(perspective.key)"
                :aria-describedby="nameId(perspective.key)"
                data-testid="perspective-brings-toggle"
                @click="toggleBrings(perspective.key)"
              >
                <span
                  aria-hidden="true"
                  :class="[
                    'inline-block size-2 border-r-[1.5px] border-b-[1.5px] border-current transition-transform duration-150',
                    isBringsOpen(perspective.key) ? '-rotate-135' : 'rotate-45',
                  ]"
                />
                {{ t("flow.brings") }}
              </button>
              <div :id="bringsId(perspective.key)" data-testid="perspective-brings-region">
                <dl
                  v-if="isBringsOpen(perspective.key)"
                  class="m-0 mb-2 grid gap-2.5 rounded-field border border-night-line bg-night px-4 py-3 text-sm leading-[1.45]"
                >
                  <div class="grid gap-0.5" data-testid="perspective-brings-definition">
                    <dt class="font-semibold text-on-night-2">{{ t("flow.inDefinition") }}</dt>
                    <dd class="m-0 text-on-night-3">
                      {{ perspectiveText(perspective.key, "definition") }}
                    </dd>
                  </div>
                  <div class="grid gap-0.5" data-testid="perspective-brings-design">
                    <dt class="font-semibold text-on-night-2">{{ t("flow.inDesign") }}</dt>
                    <dd class="m-0 text-on-night-3">
                      {{ perspectiveText(perspective.key, "design") }}
                    </dd>
                  </div>
                </dl>
              </div>
            </div>

            <ul
              v-if="perspective.aspects.length > 0"
              class="m-0 mb-2 grid list-none border-l-2 border-on-night/10 p-0 pl-4 sm:pl-5"
              data-testid="aspect-list"
            >
              <li
                v-for="aspect in perspective.aspects"
                :key="aspect.key"
                class="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-x-3 border-b border-on-night/8 py-3 last:border-b-0 sm:gap-x-4"
                data-testid="aspect-row"
                :data-aspect="aspect.key"
                :data-standing="aspect.standing"
                :data-applied="unitApplied(aspect) ? 'true' : 'false'"
              >
                <div class="min-w-0">
                  <div class="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                    <h3
                      :id="nameId(aspect.key)"
                      class="m-0 text-[15px] font-semibold"
                      data-testid="unit-name"
                    >
                      {{ aspectName(aspect.key) }}
                    </h3>
                    <span
                      :id="standingId(aspect.key)"
                      class="text-xs text-on-night-3"
                      data-testid="unit-standing"
                    >
                      {{ standingText(aspect) }}
                    </span>
                    <span
                      v-if="isChanged(aspect)"
                      class="text-xs font-medium text-petrol-on-night-2"
                      data-testid="unit-pending"
                    >
                      {{ t("flow.toBeSaved") }}
                    </span>
                  </div>
                  <p
                    v-if="aspectText(aspect.key, 'line') !== null"
                    :id="lineId(aspect.key)"
                    class="m-0 mt-0.5 text-sm leading-[1.45] text-on-night-3"
                    data-testid="unit-line"
                  >
                    {{ aspectText(aspect.key, "line") }}
                  </p>
                  <p
                    v-for="words in briefWords(aspect)"
                    :key="words.kind"
                    class="m-0 mt-1 text-sm leading-[1.45] text-on-night-2"
                    data-testid="unit-brief-words"
                    :data-words="words.kind"
                  >
                    {{ words.text }}
                  </p>
                </div>
                <label
                  v-if="isSwitchable(aspect)"
                  class="relative inline-flex h-11 w-[52px] shrink-0 cursor-pointer items-center has-disabled:cursor-not-allowed"
                >
                  <input
                    type="checkbox"
                    role="switch"
                    class="peer absolute inset-0 m-0 size-full cursor-pointer opacity-0 disabled:cursor-not-allowed"
                    :data-testid="`perspective-switch-${aspect.key}`"
                    :aria-labelledby="nameId(aspect.key)"
                    :aria-describedby="describedBy(aspect.key, aspectText(aspect.key, 'line'))"
                    :checked="unitApplied(aspect)"
                    :disabled="switchesDisabled"
                    @change="setUnit(aspect, $event)"
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
              </li>
            </ul>
          </li>
        </ul>
        <div
          v-if="hasChanges"
          class="flex flex-wrap items-center justify-end gap-3 max-sm:[&>button]:grow"
          data-testid="team-changes"
        >
          <p class="m-0 mr-auto text-sm leading-normal text-on-night-2" role="status">
            {{ t("flow.changesPending") }}
          </p>
          <UiButton
            variant="quiet"
            :disabled="store.busy"
            data-testid="discard-team-changes"
            @click="discardChanges"
          >
            {{ t("flow.discardChanges") }}
          </UiButton>
          <UiButton type="submit" :disabled="store.busy" data-testid="save-team-changes">
            {{ t("flow.save") }}
          </UiButton>
        </div>
      </form>

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
          :disabled="hasChanges"
          @primary="onPrimary"
          @request="onRequest"
        />
      </div>
    </Teleport>

    <Teleport :to="rowTarget" :disabled="rowTarget === null">
      <div v-if="store.currentVersion !== null" data-testid="team-technical-details">
        <UiTechnicalDetails :summary="technicalSummary" :rows="technicalRows">
          <div class="grid gap-5 text-on-night-2">
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
                    {{ formatDate(version.created_at) }}
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
                {{ t("flow.prepareAgain") }}
              </UiButton>
            </div>
          </div>
        </UiTechnicalDetails>
      </div>
    </Teleport>
  </section>
</template>
