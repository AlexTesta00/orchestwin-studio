<script setup lang="ts">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  onUpdated,
  provide,
  reactive,
  ref,
  watch,
} from "vue";

import UserModelingEpistemicBadge from "./UserModelingEpistemicBadge.vue";
import ArchetypeEditor from "./ArchetypeEditor.vue";
import TwinPersonaView from "./TwinPersonaView.vue";
import ArtifactWhy from "./ArtifactWhy.vue";
import { twinClaimCode } from "./whyContext";
import {
  archetypeOf,
  claimText,
  observationDisplayStatus,
  twinRepresentation,
} from "./twinRepresentation";
import UserModelingProvenanceInspector from "./UserModelingProvenanceInspector.vue";
import TwinIdentity from "./TwinIdentity.vue";
import TwinImportPanel from "./TwinImportPanel.vue";
import GenerationJobNotice from "./GenerationJobNotice.vue";
import { workflowStatusLabel } from "./workflowLabels";
import UiButton from "./UiButton.vue";
import UiClaimFrame from "./UiClaimFrame.vue";
import UiDecisionBar from "./UiDecisionBar.vue";
import UiSidePanel from "./UiSidePanel.vue";
import UiStateBlock from "./UiStateBlock.vue";
import UiStatusChip from "./UiStatusChip.vue";
import UiTechnicalDetails from "./UiTechnicalDetails.vue";
import { surfaceKey, type SurfaceContext } from "./UiSurface.vue";
import { twinPeers } from "./twinIdentity";
import { type UpstreamValue, watchUpstream } from "./upstreamChange";

import { isGenerationInterrupted } from "../api/generationJobs";
import { useGenerationResume } from "../stores/generationJobs";
import { useTeamStore } from "../stores/team";
import { useUserModelingStore } from "../stores/userModeling";

import type {
  ArchetypeInput,
  ArchetypePayload,
  GateDecisionAction,
  HumanGateEventPayload,
  ObservationValueKind,
  PersonaOwnerDecision,
  PersonaVersionPayload,
  ProfileObservationPayload,
  ProfileReplacementRequest,
  ProfileRevisionDecision,
  UserTwinField,
  UserTwinProfileDiffPayload,
  UserTwinVersionPayload,
} from "../types/userModeling";

type Locale = "en" | "it";
type Phase = "empty" | "profiles" | "twins";
type TwinsDecision = "generate" | "approve" | "resume";
type ProfileTarget = { kind: "persona" | "twin"; id: string };

const props = withDefaults(
  defineProps<{
    projectId: string;
    accessToken: string;
    authorize?: <T>(operation: (token: string) => Promise<T>) => Promise<T>;
    locale?: Locale;
    autoLoad?: boolean;
    upstream?: UpstreamValue;
    active?: boolean;
    sectionsMode?: boolean;
  }>(),
  {
    locale: "en",
    autoLoad: true,
    upstream: null,
    active: true,
    sectionsMode: false,
  },
);

const store = useUserModelingStore();

const team = useTeamStore();

provide(
  surfaceKey,
  computed<SurfaceContext>(() => "night"),
);

const loadedProjectId = ref<string | null>(null);

const autoProposalAttempted = ref(false);

const proposalFollowsApproval = ref(false);

const emit = defineEmits<{
  "open-chat": [twin: UserTwinVersionPayload];
  "sections-changed": [];
}>();

const personaReasons = reactive<Record<string, string>>({});

const diffReasons = reactive<Record<string, string>>({});

const gateReason = ref("");

const localError = ref<string | null>(null);

const editingTwinId = ref<string | null>(null);

const editingField = ref<UserTwinField | null>(null);

const editingOriginalKind = ref<ObservationValueKind>("TEXT");

const editingValue = ref("");

const revisionEpistemicStatus = ref<"USER_PROVIDED" | "HUMAN_VALIDATED" | "CONTESTED">(
  "USER_PROVIDED",
);
const revisionRationale = ref("");
const archetypeEditorOpen = ref(false);
const editingArchetype = ref<ArchetypePayload | null>(null);
const removingArchetype = ref<ArchetypePayload | null>(null);

const rejectingPersonaId = ref<string | null>(null);

const profileTarget = ref<ProfileTarget | null>(null);

const root = ref<HTMLElement | null>(null);

const barTarget = ref<HTMLElement | null>(null);

const rowTarget = ref<HTMLElement | null>(null);

const decisionBar = ref<InstanceType<typeof UiDecisionBar> | null>(null);

const approving = ref(false);

const generationSeen = new Set<string>();

const {
  job: modelingJob,
  checked: modelingChecked,
  failure: modelingJobFailure,
  dismiss: dismissModelingJob,
} = useGenerationResume({
  projectId: () => props.projectId,
  operations: ["PERSONA_PROPOSAL", "USER_TWIN_GENERATION"],
  authorize: authorizedJobs,
  onSettled: reloadAndTell,
});

watch(modelingJob, (running) => {
  if (running !== null) {
    generationSeen.add(props.projectId);
  }
});

let visibilityObserver: ResizeObserver | null = null;

const userTwinFields = new Set<UserTwinField>([
  "role",
  "age_range",
  "expertise",
  "goals",
  "recurring_tasks",
  "context_of_use",
  "information_needs",
  "decision_criteria",
  "preferred_vocabulary",
  "frustrations",
  "pain_points",
  "trust_concerns",
  "accessibility_needs",
  "operational_constraints",
  "technical_literacy",
  "risk_sensitivity",
  "assumptions",
  "description",
  "represents",
  "does_not_represent",
  "evidence_gaps",
]);

const multiValueFields = new Set<UserTwinField>([
  "expertise",
  "goals",
  "recurring_tasks",
  "information_needs",
  "decision_criteria",
  "preferred_vocabulary",
  "frustrations",
  "pain_points",
  "trust_concerns",
  "accessibility_needs",
  "operational_constraints",
  "assumptions",
  "represents",
  "does_not_represent",
  "evidence_gaps",
]);

const APPROVED_LIFECYCLES = new Set([
  "OWNER_APPROVED_UT",
  "EMPIRICALLY_GROUNDED_UT",
  "EMPIRICALLY_VALIDATED_UT",
]);

const disclosureSummary =
  "inline-flex min-h-11 cursor-pointer list-none items-center gap-2.5 text-sm font-medium text-on-night-3 transition-colors duration-150 hover:text-on-night [&::-webkit-details-marker]:hidden";

const disclosureChevron =
  "inline-block size-2 rotate-45 border-r-[1.5px] border-b-[1.5px] border-current transition-transform duration-150 group-open:-rotate-135";

const IMPORTED_PREFIX = "user-twin:";

const IMPORTED_SUMMARY = "Imported from the project ";

const fieldLabels: Record<Locale, Record<UserTwinField, string>> = {
  en: {
    role: "Role",
    age_range: "Age range",
    expertise: "Expertise",
    goals: "Goals",
    recurring_tasks: "Recurring tasks",
    context_of_use: "Context of use",
    information_needs: "Information needs",
    decision_criteria: "Decision criteria",
    preferred_vocabulary: "Preferred vocabulary",
    frustrations: "Frustrations",
    pain_points: "Pain points",
    trust_concerns: "Trust concerns",
    accessibility_needs: "Accessibility needs",
    operational_constraints: "Operational constraints",
    technical_literacy: "Technical literacy",
    risk_sensitivity: "Risk sensitivity",
    assumptions: "Assumptions",
    description: "Description",
    represents: "Represents",
    does_not_represent: "Does not represent",
    evidence_gaps: "Evidence gaps",
  },

  it: {
    role: "Ruolo",
    age_range: "Fascia di età",
    expertise: "Competenze",
    goals: "Obiettivi",
    recurring_tasks: "Attività ricorrenti",
    context_of_use: "Contesto d'uso",
    information_needs: "Bisogni informativi",
    decision_criteria: "Criteri decisionali",
    preferred_vocabulary: "Vocabolario preferito",
    frustrations: "Frustrazioni",
    pain_points: "Pain point",
    trust_concerns: "Preoccupazioni sulla fiducia",
    accessibility_needs: "Esigenze di accessibilità",
    operational_constraints: "Vincoli operativi",
    technical_literacy: "Competenza tecnica",
    risk_sensitivity: "Sensibilità al rischio",
    assumptions: "Assunzioni",
    description: "Descrizione",
    represents: "Rappresenta",
    does_not_represent: "Non rappresenta",
    evidence_gaps: "Limiti delle evidenze",
  },
};

const messages = {
  en: {
    region: "User Twin",

    loading: "Updating user profiles…",
    generating: "Preparing the profiles. This may take a few minutes; keep this page open.",

    error: "User Modeling operation failed.",

    personasHeading: "Archetypes",

    twinsHeading: "The twins of your project",

    profilesCount: "{confirmed} of {total} archetypes confirmed",

    profilesSentence: "Confirm the archetypes that describe who will use the product.",

    twinsCountOne: "1 twin to approve",

    twinsCountOther: "{n} twins to approve",

    twinsApprovedOne: "1 twin approved by you",

    twinsApprovedOther: "{n} twins approved by you",

    twinsSentence:
      "The twins' answers are simulated: hypotheses to weigh, not opinions of real people.",

    proposePersonas: "Suggest archetypes",

    noPersonasTitle: "No archetype yet",

    noPersonas: "Add an archetype or ask for suggestions from the brief.",

    noTwins: "No twin in this version.",

    fromBrief: "From the brief",

    fromOwner: "Described by you",

    reused: "Reused from “{project}”",

    reusedElsewhere: "Reused from another project",

    hypothesesOne: "1 hypothesis to verify",

    hypothesesOther: "{n} hypotheses to verify",

    confirmedByYou: "Confirmed by you",

    rejectedChip: "Set aside",

    pending: "Pending confirmation",

    awaitingApproval: "To approve",

    goals: "Goals",

    context: "Context of use",

    holdsBack: "What holds them back",

    fullProfile: "See the full profile",

    confirm: "Confirm",

    reject: "Set aside",

    rejectConfirm: "Set the archetype aside",

    rejectionReason: "Why do you set it aside?",

    reasonPlaceholder: "Explain why this archetype does not describe who will use the product…",

    rejectedBecause: "Set aside: {reason}",

    cancel: "Cancel",

    talk: "Talk to the twin",

    pendingDiffsOne: "1 change to approve in the profile",

    pendingDiffsOther: "{n} changes to approve in the profile",

    startingProfiles: "Archetypes",

    profileTitle: "Profile of {name}",

    staleContext:
      "The brief or the perspectives changed: generate and approve a new User Twin version before continuing.",

    staleContextSections:
      "The brief or the perspectives changed: use «Update and confirm» above to keep these twins and re-anchor them, or create them again.",

    generateTwins: "Create the twins",

    regenerateTwins: "Create the twins again",

    decideProfiles:
      "Confirm or set aside every proposed archetype: the twins are born from the confirmed archetypes.",

    confirmOne: "Confirm at least one archetype to create the twins.",

    readyToGenerate:
      "Confirmed archetypes: {n}. Create their twins: you will be able to talk to them and correct them.",

    submitFailed:
      "The twins could not be brought to your approval. Refresh the page and try again.",

    requestPlaceholder:
      "Write what does not convince you in the profiles: the note stays in the history of the decisions.",

    decisionResume: "You paused this decision. Resume it when you are ready.",

    profileDetails: "View profile",

    evidenceDetails: "Why we think this",

    knowledgeSource: "Where does this information come from?",

    edit: "Correct",

    editField: "Correct {field}",

    observationUnavailable: "This information is read-only.",

    revisionValue: "New value",

    revisionItemsHint: "Use one item per line.",

    userProvided: "Owner / user provided",

    humanValidated: "Human validated",

    humanValidatedWarning:
      "Choose Human validated only if a person has checked this information. Approving a profile alone does not verify its assumptions.",

    proposeRevision: "Propose this change",

    diffs: "Suggested profile changes",

    proposedDiff: "Proposed",

    approvedDiff: "Approved",

    rejectedDiff: "Rejected",

    before: "Before",

    after: "After",

    approveDiff: "Approve change",

    rejectDiff: "Reject change",

    diffReason: "Decision reason",

    otherDecisions: "Other decisions",

    approveGate: "Confirm the twins and continue",

    rejectGate: "Reject",

    pause: "Pause",

    resume: "Resume",

    cancelGate: "Cancel approval",

    gateReason: "Reason for your decision",

    gateReasonHint: "Needed to reject the profiles.",

    gateMethodology:
      "Your approval allows the project to use these profiles. It does not mean their assumptions have been verified with real users.",

    currentSnapshotApproved: "You have approved these user profiles.",

    ready: "Ready for the Definition.",

    notReady: "Review and approve your user profiles to continue.",

    stale: "The profiles have changed since your last approval. Review them again.",

    revisionRequested:
      "You asked for changes. Correct the twins: the new version comes back for your approval.",

    revisionNote: "Your note: “{note}”",

    cancelled: "You cancelled this decision. Correct a twin to prepare a new version.",

    rejected: "You rejected these profiles. Correct a twin to prepare a new version.",

    pausedNeedsHuman: "The decision is stopped and needs your intervention.",

    technicalSummary: "Version {number} · {state}",

    technicalProfiles: "Proposed archetypes · twins not created yet",

    technicalEmpty: "No archetype yet",

    stateApproved: "approved",

    statePending: "waiting for your decision",

    stateDraft: "being prepared",

    contentHash: "Content hash",

    gateStatus: "Approval",

    workflow: "Workflow state",

    decisionCounter: "Decision no. {n}",

    technicalTwins: "Twins",

    technicalPersonas: "Archetypes",

    persistedLifecycle: "Persisted lifecycle",

    effectiveLifecycle: "Effective lifecycle",

    unknown: "Unknown",

    abstained: "Abstained",

    empty: "No value",

    requiredReason: "A reason is required for this decision.",

    requiredValue: "Enter a value before proposing the revision.",

    invalidField: "The selected observation is not mapped to a User Twin field.",

    projectMissing: "Project and access token are required.",

    profileInformation: "Profile information",
  },

  it: {
    region: "User Twin",

    loading: "Aggiornamento dei profili…",
    generating:
      "Preparazione dei profili in corso. Può richiedere alcuni minuti; mantieni aperta questa pagina.",

    error: "Operazione User Modeling non riuscita.",

    personasHeading: "Archetipi",

    twinsHeading: "I twin del progetto",

    profilesCount: "{confirmed} di {total} archetipi confermati",

    profilesSentence: "Conferma gli archetipi che descrivono chi userà il prodotto.",

    twinsCountOne: "1 twin da approvare",

    twinsCountOther: "{n} twin da approvare",

    twinsApprovedOne: "1 twin approvato da te",

    twinsApprovedOther: "{n} twin approvati da te",

    twinsSentence:
      "Le risposte dei twin sono simulate: ipotesi da pesare, non opinioni di persone reali.",

    proposePersonas: "Proponi archetipi",

    noPersonasTitle: "Ancora nessun archetipo",

    noPersonas: "Aggiungi un archetipo o chiedi proposte dal brief.",

    noTwins: "Nessun twin in questa versione.",

    fromBrief: "Dal brief",

    fromOwner: "Descritto da te",

    reused: "Riusato da «{project}»",

    reusedElsewhere: "Riusato da un altro progetto",

    hypothesesOne: "1 ipotesi da verificare",

    hypothesesOther: "{n} ipotesi da verificare",

    confirmedByYou: "Confermato da te",

    rejectedChip: "Scartato",

    pending: "In attesa di conferma",

    awaitingApproval: "Da approvare",

    goals: "Obiettivi",

    context: "Contesto d'uso",

    holdsBack: "Che cosa è di ostacolo",

    fullProfile: "Vedi il profilo completo",

    confirm: "Conferma",

    reject: "Scarta",

    rejectConfirm: "Scarta l'archetipo",

    rejectionReason: "Perché lo scarti?",

    reasonPlaceholder: "Spiega perché questo archetipo non descrive chi userà il prodotto…",

    rejectedBecause: "Scartato: {reason}",

    cancel: "Annulla",

    talk: "Parla con il twin",

    pendingDiffsOne: "1 modifica al profilo da approvare",

    pendingDiffsOther: "{n} modifiche al profilo da approvare",

    startingProfiles: "Archetipi",

    profileTitle: "Il profilo di {name}",

    staleContext:
      "Brief o prospettive sono cambiati: genera una nuova versione degli User Twin e approvala prima di proseguire.",

    staleContextSections:
      "Brief o prospettive sono cambiati: usa «Aggiorna e conferma» qui sopra per tenere questi twin e riagganciarli, oppure creali di nuovo.",

    generateTwins: "Crea i twin",

    regenerateTwins: "Crea di nuovo i twin",

    decideProfiles:
      "Conferma o scarta ogni archetipo proposto: i twin nascono dagli archetipi confermati.",

    confirmOne: "Conferma almeno un archetipo per creare i twin.",

    readyToGenerate: "Archetipi confermati: {n}. Crea i loro twin: potrai parlarci e correggerli.",

    submitFailed:
      "Non è stato possibile portare i twin alla tua approvazione. Ricarica la pagina e riprova.",

    requestPlaceholder:
      "Scrivi che cosa non ti convince nei profili: la nota resta nella cronologia delle decisioni.",

    decisionResume: "Hai messo in pausa questa decisione. Riprendila quando sei pronto.",

    profileDetails: "Vedi il profilo",

    evidenceDetails: "Da dove nasce questa informazione",

    knowledgeSource: "Da dove proviene questa informazione?",

    edit: "Correggi",

    editField: "Correggi {field}",

    observationUnavailable: "Questa informazione è di sola lettura.",

    revisionValue: "Nuovo valore",

    revisionItemsHint: "Inserisci un elemento per riga.",

    userProvided: "Fornito dal proprietario / utente",

    humanValidated: "Validato da una persona",

    humanValidatedWarning:
      "Scegli Validato da una persona solo se qualcuno ha verificato questa informazione. Approvare il profilo, da solo, non conferma le sue ipotesi.",

    proposeRevision: "Proponi questa modifica",

    diffs: "Modifiche proposte ai profili",

    proposedDiff: "Proposta",

    approvedDiff: "Approvata",

    rejectedDiff: "Rifiutata",

    before: "Prima",

    after: "Dopo",

    approveDiff: "Approva modifica",

    rejectDiff: "Rifiuta modifica",

    diffReason: "Motivazione della decisione",

    otherDecisions: "Altre decisioni",

    approveGate: "Conferma i twin e continua",

    rejectGate: "Rifiuta",

    pause: "Pausa",

    resume: "Riprendi",

    cancelGate: "Annulla approvazione",

    gateReason: "Motivazione della decisione",

    gateReasonHint: "Serve per rifiutare i profili.",

    gateMethodology:
      "La tua approvazione permette al progetto di usare questi profili. Non significa che le loro ipotesi siano state verificate con utenti reali.",

    currentSnapshotApproved: "Hai approvato questi profili degli utenti.",

    ready: "Pronto per la Definizione.",

    notReady: "Controlla e approva i profili degli utenti per proseguire.",

    stale: "I profili sono cambiati dalla tua ultima approvazione. Controllali di nuovo.",

    revisionRequested:
      "Hai chiesto modifiche. Correggi i twin: la nuova versione tornerà alla tua approvazione.",

    revisionNote: "La tua nota: «{note}»",

    cancelled:
      "Hai annullato questa decisione. Correggi un twin per prepararne una nuova versione.",

    rejected: "Hai rifiutato questi profili. Correggi un twin per prepararne una nuova versione.",

    pausedNeedsHuman: "La decisione è ferma e serve il tuo intervento.",

    technicalSummary: "Versione {number} · {state}",

    technicalProfiles: "Archetipi proposti · twin non ancora creati",

    technicalEmpty: "Ancora nessun archetipo",

    stateApproved: "approvata",

    statePending: "in attesa della tua decisione",

    stateDraft: "in preparazione",

    contentHash: "Hash del contenuto",

    gateStatus: "Approvazione",

    workflow: "Stato del flusso",

    decisionCounter: "Decisione n. {n}",

    technicalTwins: "Twin",

    technicalPersonas: "Archetipi",

    persistedLifecycle: "Lifecycle persistito",

    effectiveLifecycle: "Lifecycle effettivo",

    unknown: "Sconosciuto",

    abstained: "Astensione",

    empty: "Nessun valore",

    requiredReason: "Per questa decisione è richiesta una motivazione.",

    requiredValue: "Inserisci un valore prima di proporre la revisione.",

    invalidField: "L'osservazione selezionata non corrisponde a un campo User Twin.",

    projectMissing: "Sono richiesti progetto e access token.",

    profileInformation: "Informazione sul profilo",
  },
} as const;

const copy = computed(() => messages[props.locale]);
const archetypeCopy = computed(() =>
  props.locale === "it"
    ? {
        heading: "Archetipi",
        add: "Aggiungi archetipo",
        edit: "Modifica",
        remove: "Rimuovi",
        confirm: "Rimuovi archetipo",
        cancel: "Annulla",
        archive:
          "L'archetipo sarà archiviato e lo storico resterà disponibile. I twin dovranno essere aggiornati; requisiti e design che citano il twin rimosso possono richiedere una nuova preparazione.",
        stale:
          "Gli archetipi sono cambiati. Genera i twin aggiornati e approvali: i riferimenti precedenti restano nello storico.",
        contested: "Contestato",
        rationale: "Perché contesti questa informazione?",
      }
    : {
        heading: "Archetypes",
        add: "Add archetype",
        edit: "Edit",
        remove: "Remove",
        confirm: "Remove archetype",
        cancel: "Cancel",
        archive:
          "The archetype will be archived and its history preserved. The twins will need updating; requirements and design that cite the removed twin may need preparing again.",
        stale:
          "The archetypes changed. Generate the updated twins and approve them: earlier references remain in the history.",
        contested: "Contested",
        rationale: "Why do you contest this information?",
      },
);

function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/gu, (_match, key: string) => String(values[key] ?? ""));
}

const errorMessage = computed(() => {
  const code = localError.value ?? store.error?.code ?? store.error?.message;
  if (!code || isGenerationInterrupted(code)) return null;
  const errors: Record<string, [string, string]> = {
    ARCHETYPE_VERSION_CONFLICT: [
      "This archetype changed. Reload the latest version before saving.",
      "L'archetipo è cambiato. Ricarica la versione corrente prima di salvare.",
    ],
    ARCHETYPE_LIMIT_REACHED: [
      "You can keep up to eight active archetypes.",
      "Puoi mantenere fino a otto archetipi attivi.",
    ],
    ARCHETYPE_ALREADY_ARCHIVED: [
      "This archetype has already been removed.",
      "Questo archetipo è già stato rimosso.",
    ],
    ARCHETYPE_NOT_FOUND: [
      "This archetype is no longer available. Reload the list.",
      "Questo archetipo non è più disponibile. Ricarica l'elenco.",
    ],
    USER_TWIN_REVISION_PENDING: [
      "Decide the pending twin changes before changing the archetypes or generating new twins.",
      "Decidi le modifiche in attesa dei twin prima di cambiare gli archetipi o generare nuovi twin.",
    ],
    PERSISTENCE_REJECTED: [
      "The change could not be saved. Reload the current version.",
      "La modifica non è stata salvata. Ricarica la versione corrente.",
    ],
    INVALID_PROVIDER_OUTPUT: [
      "The model returned an incomplete or invalid proposal. No artifact was accepted. You can try again.",
      "Il modello ha restituito una proposta incompleta o non valida. Nessun artefatto è stato accettato. Puoi riprovare.",
    ],
    INCOMPLETE_OUTPUT: [
      "The model did not complete its response. Your project has been preserved. You can try again.",
      "Il modello non ha completato la risposta. Il progetto è stato conservato. Puoi riprovare.",
    ],
    PROVIDER_UNAVAILABLE: [
      "The local model is unavailable. Check model status above.",
      "Il modello locale non è disponibile. Controlla lo stato dei modelli qui sopra.",
    ],
    TIMEOUT: [
      "Model generation timed out. Check model availability before retrying.",
      "La generazione ha superato il tempo disponibile. Controlla il modello prima di riprovare.",
    ],
    CONTEXT_BUDGET_EXCEEDED: [
      "These profiles exceed the model context window. Use fewer target groups or configure a larger context.",
      "Questi profili superano il contesto del modello. Riduci i gruppi target oppure configura un contesto maggiore.",
    ],
  };
  return errors[code]?.[props.locale === "it" ? 1 : 0] ?? code;
});

const personas = computed(() => store.currentPersonas);
const archetypes = computed(
  () =>
    store.archetypes ??
    personas.value
      .filter(
        (persona) =>
          persona.profile.confirmation_status !== "REJECTED" && !persona.profile.archived,
      )
      .map(archetypeOf),
);

const twins = computed(() => store.currentTwins);

const peers = computed(() => twinPeers(personas.value.map((persona) => persona.persona_id)));

const pendingPersonas = computed(() =>
  personas.value.filter(
    (persona) => persona.profile.confirmation_status === "PENDING_CONFIRMATION",
  ),
);

const confirmedPersonas = computed(() =>
  personas.value.filter((persona) => persona.profile.confirmation_status === "CONFIRMED"),
);

const canGenerateTwins = computed(
  () =>
    (store.currentSnapshot === null ||
      store.readiness?.context_current === false ||
      store.readiness?.archetypes_current === false) &&
    personas.value.length > 0 &&
    pendingPersonas.value.length === 0 &&
    confirmedPersonas.value.length > 0,
);

const profileDiffs = computed(() =>
  Object.values(store.diffs).sort((left, right) => left.created_at.localeCompare(right.created_at)),
);

const gateTargetsCurrentSnapshot = computed(() => {
  const snapshot = store.currentSnapshot;

  const gate = store.currentGate;

  if (snapshot === null || gate === null) {
    return false;
  }

  return (
    gate.artifact.artifact_id === snapshot.id &&
    gate.artifact.version === snapshot.version_number &&
    gate.artifact.content_hash === snapshot.content_hash
  );
});

const canSubmitGate = computed(() => {
  if (store.currentSnapshot === null) {
    return false;
  }

  if (store.currentGate === null) {
    return true;
  }

  if (!gateTargetsCurrentSnapshot.value) {
    return true;
  }

  return store.currentGate.status === "DRAFT" || store.currentGate.status === "STALE";
});

const gatePendingApproval = computed(
  () => gateTargetsCurrentSnapshot.value && store.currentGate?.status === "PENDING_APPROVAL",
);

const gatePaused = computed(
  () => gateTargetsCurrentSnapshot.value && store.currentGate?.status === "PAUSED",
);

const decisionCounter = computed(() =>
  fill(messages[props.locale].decisionCounter, {
    n: store.currentGate?.iteration ?? 1,
  }),
);

const contextStale = computed(
  () =>
    store.currentSnapshot !== null &&
    (store.readiness?.context_current === false || store.readiness?.archetypes_current === false),
);

const staleContextText = computed(() =>
  store.readiness?.archetypes_current === false
    ? archetypeCopy.value.stale
    : props.sectionsMode
      ? copy.value.staleContextSections
      : copy.value.staleContext,
);

const phase = computed<Phase>(() => {
  if (store.currentSnapshot !== null) return "twins";
  return personas.value.length > 0 ? "profiles" : "empty";
});

const longOperation = computed(
  () => store.pending["propose-personas"] || store.pending["generate-snapshot"],
);

const snapshotApproved = computed(() => store.readiness?.approved_current_snapshot === true);

const showPersonaCards = computed(
  () =>
    phase.value === "profiles" ||
    (phase.value === "twins" && contextStale.value && pendingPersonas.value.length > 0),
);

const decision = computed<TwinsDecision | null>(() => {
  if (phase.value === "profiles") return "generate";
  if (phase.value !== "twins") return null;
  if (contextStale.value) return "generate";
  if (gatePendingApproval.value) return "approve";
  if (gatePaused.value) return "resume";
  return canSubmitGate.value ? "approve" : null;
});

const requestAvailable = computed(() => decision.value === "approve" && gatePendingApproval.value);

const otherDecisionsAvailable = computed(
  () =>
    (decision.value === "approve" || decision.value === "resume") &&
    (gatePendingApproval.value || gatePaused.value),
);

const barBusy = computed(() => store.isBusy || approving.value || modelingJob.value !== null);

const decisionCopy = computed(() => {
  const text = copy.value;
  switch (decision.value) {
    case "generate": {
      const description =
        pendingPersonas.value.length > 0
          ? text.decideProfiles
          : confirmedPersonas.value.length === 0
            ? text.confirmOne
            : fill(text.readyToGenerate, { n: confirmedPersonas.value.length });
      return {
        primary: contextStale.value ? text.regenerateTwins : text.generateTwins,
        description: contextStale.value ? `${staleContextText.value} ${description}` : description,
        disabled: !canGenerateTwins.value,
      };
    }
    case "resume":
      return { primary: text.resume, description: text.decisionResume, disabled: false };
    default:
      return {
        primary: text.approveGate,
        description:
          store.currentGate !== null && !gateTargetsCurrentSnapshot.value
            ? `${text.stale} ${text.gateMethodology}`
            : text.gateMethodology,
        disabled: false,
      };
  }
});

const gateNotice = computed(() => {
  const gate = store.currentGate;
  if (
    gate === null ||
    !gateTargetsCurrentSnapshot.value ||
    decision.value !== null ||
    phase.value !== "twins"
  ) {
    return null;
  }
  const text = copy.value;
  const notices: Record<string, string> = {
    REVISION_REQUESTED: text.revisionRequested,
    CANCELLED: text.cancelled,
    REJECTED: text.rejected,
    PAUSED_NEEDS_HUMAN: text.pausedNeedsHuman,
  };
  return notices[gate.status] ?? null;
});

const revisionNote = computed(() => {
  if (store.currentGate?.status !== "REVISION_REQUESTED") return null;
  const event = [...store.gateEvents]
    .reverse()
    .find((item: HumanGateEventPayload) => item.kind === "REQUEST_REVISION");
  return event?.reason ?? null;
});

const countLabel = computed(() => {
  const text = copy.value;
  if (phase.value === "profiles") {
    return fill(text.profilesCount, {
      confirmed: confirmedPersonas.value.length,
      total: personas.value.length,
    });
  }
  const n = twins.value.length;
  if (snapshotApproved.value) {
    return n === 1 ? text.twinsApprovedOne : fill(text.twinsApprovedOther, { n });
  }
  return n === 1 ? text.twinsCountOne : fill(text.twinsCountOther, { n });
});

const technicalSummary = computed(() => {
  const text = copy.value;
  const snapshot = store.currentSnapshot;
  if (snapshot === null) {
    return personas.value.length > 0 ? text.technicalProfiles : text.technicalEmpty;
  }
  const state = snapshotApproved.value
    ? text.stateApproved
    : decision.value === "approve" || decision.value === "resume"
      ? text.statePending
      : text.stateDraft;
  return fill(text.technicalSummary, { number: snapshot.version_number, state });
});

const technicalRows = computed(() => {
  const text = copy.value;
  const snapshot = store.currentSnapshot;
  const rows: { label: string; value: string }[] = [];
  if (snapshot !== null) {
    rows.push({ label: text.contentHash, value: snapshot.content_hash });
  }
  if (store.currentGate !== null) {
    rows.push({
      label: text.gateStatus,
      value: `${workflowStatusLabel(store.currentGate.status, props.locale)} · ${decisionCounter.value}`,
    });
  }
  rows.push({
    label: text.workflow,
    value: `${store.currentGate?.status ?? "—"} · ${store.readiness?.workflow_state ?? "—"}`,
  });
  return rows;
});

const profilePersona = computed(() => {
  const target = profileTarget.value;
  if (target === null || target.kind !== "persona") return null;
  return personas.value.find((persona) => persona.persona_id === target.id) ?? null;
});

const profileTwin = computed(() => {
  const target = profileTarget.value;
  if (target === null || target.kind !== "twin") return null;
  return twins.value.find((twin) => twin.twin_id === target.id) ?? null;
});

const profileTitle = computed(() => {
  const name = profileTwin.value?.profile.name ?? profilePersona.value?.profile.name ?? "";
  return fill(copy.value.profileTitle, { name });
});

const profileObservations = computed(() => {
  const observations =
    profileTwin.value?.profile.observations ?? profilePersona.value?.profile.observations ?? [];
  if (profileTwin.value === null) return observations;
  return [
    ...observations,
    ...(["description", "represents", "does_not_represent", "evidence_gaps"] as const)
      .filter(
        (field) =>
          !observations.some((observation) => observation.observation_key === `user_twin.${field}`),
      )
      .map((field): ProfileObservationPayload => ({
        observation_key: `user_twin.${field}`,
        value: { kind: "UNKNOWN", text: null, items: [], reason: null },
        epistemic_status: "UNSUPPORTED_ASSUMPTION",
        confidence: 0,
        provenance: [],
        human_validation: "REQUIRED",
        rationale: null,
      })),
  ];
});

const profileDiffsForTwin = computed(() => {
  const twin = profileTwin.value;
  return twin === null ? [] : profileDiffs.value.filter((diff) => diff.twin_id === twin.twin_id);
});

function fieldLabel(field: UserTwinField): string {
  return fieldLabels[props.locale][field];
}

function personaStatusLabel(persona: PersonaVersionPayload): string {
  switch (persona.profile.confirmation_status) {
    case "CONFIRMED":
      return copy.value.confirmedByYou;

    case "REJECTED":
      return copy.value.rejectedChip;

    case "PENDING_CONFIRMATION":
      return copy.value.pending;
  }
}

function observationField(observation: ProfileObservationPayload): UserTwinField | null {
  const parts = observation.observation_key.split(".");

  const candidate = parts.pop();

  if (candidate === undefined) {
    return null;
  }

  const typedCandidate = candidate as UserTwinField;

  return userTwinFields.has(typedCandidate) ? typedCandidate : null;
}

function formatObservation(observation: ProfileObservationPayload | null): string {
  if (observation === null) {
    return copy.value.empty;
  }

  switch (observation.value.kind) {
    case "TEXT":
      return observation.value.text ?? copy.value.empty;

    case "ITEMS":
      return observation.value.items.length > 0
        ? observation.value.items.join(", ")
        : copy.value.empty;

    case "UNKNOWN":
      return observation.value.reason ?? copy.value.unknown;

    case "ABSTAINED":
      return observation.value.reason ?? copy.value.abstained;
  }
}

function observationLabel(observation: ProfileObservationPayload): string {
  const field = observationField(observation);
  return field !== null ? fieldLabel(field) : copy.value.profileInformation;
}

function effectiveLifecycle(twin: UserTwinVersionPayload): string {
  const lifecycle = store.readiness?.twins.find(
    (item) => item.twin_id === twin.twin_id && item.version_number === twin.version_number,
  );

  return lifecycle?.effective_status ?? twin.profile.validation_status;
}

function knownValue(observation: ProfileObservationPayload | undefined): string | null {
  if (observation === undefined) return null;
  if (observation.value.kind === "TEXT") {
    const text = observation.value.text?.trim() ?? "";
    return text.length > 0 ? text : null;
  }
  if (observation.value.kind === "ITEMS") {
    return observation.value.items.length > 0 ? observation.value.items.join(", ") : null;
  }
  return null;
}

function observationBySuffix(
  observations: ProfileObservationPayload[],
  suffix: string,
): ProfileObservationPayload | undefined {
  return observations.find((item) => item.observation_key.split(".").pop() === suffix);
}

function summaryOf(
  observations: ProfileObservationPayload[],
  personaId: string,
  name: string,
): string | null {
  const persona = personas.value.find((item) => item.persona_id === personaId);
  const sources = [observations, persona?.profile.observations ?? []];
  for (const suffix of ["summary", "role"]) {
    for (const source of sources) {
      const value = knownValue(observationBySuffix(source, suffix));
      if (value !== null && value.trim().toLocaleLowerCase() !== name.trim().toLocaleLowerCase()) {
        return value;
      }
    }
  }
  return null;
}

function twinSummary(twin: UserTwinVersionPayload): string | null {
  const claim = twinRepresentation(twin, citedPersona(twin)).persona.description;
  return claim.value.kind === "UNKNOWN" || claim.value.kind === "ABSTAINED"
    ? null
    : claimText(claim, props.locale);
}
function citedPersona(twin: UserTwinVersionPayload): PersonaVersionPayload | undefined {
  return store.currentSnapshot?.snapshot.persona_versions.find(
    (persona) =>
      persona.persona_id === twin.profile.persona_reference.persona_id &&
      persona.version_number === twin.profile.persona_reference.version_number &&
      persona.content_hash === twin.profile.persona_reference.content_hash,
  );
}

function cardFacts(observations: ProfileObservationPayload[]): { label: string; value: string }[] {
  const text = copy.value;
  const facts = [
    { label: text.goals, value: knownValue(observationBySuffix(observations, "goals")) },
    { label: text.context, value: knownValue(observationBySuffix(observations, "context_of_use")) },
    {
      label: text.holdsBack,
      value:
        knownValue(observationBySuffix(observations, "frustrations")) ??
        knownValue(observationBySuffix(observations, "pain_points")),
    },
  ];
  return facts.flatMap((fact) => (fact.value === null ? [] : [{ ...fact, value: fact.value }]));
}

function hypothesisCount(observations: ProfileObservationPayload[]): number {
  return observations.filter((item) => item.human_validation === "REQUIRED").length;
}

function hypothesisLabel(observations: ProfileObservationPayload[]): string | null {
  const n = hypothesisCount(observations);
  if (n === 0) return null;
  return n === 1 ? copy.value.hypothesesOne : fill(copy.value.hypothesesOther, { n });
}

function isHypothesis(observation: ProfileObservationPayload): boolean {
  return (
    observation.human_validation === "REQUIRED" ||
    observation.epistemic_status === "MODEL_INFERRED" ||
    observation.epistemic_status === "UNSUPPORTED_ASSUMPTION"
  );
}

function sourceOrigin(source: PersonaVersionPayload["profile"]["source"]): string {
  return source === "OWNER_PROVIDED" ? copy.value.fromOwner : copy.value.fromBrief;
}

function twinOrigin(twin: UserTwinVersionPayload): string {
  for (const observation of twin.profile.observations) {
    for (const reference of observation.provenance) {
      if (reference.source_id.startsWith(IMPORTED_PREFIX)) {
        const summary = reference.summary ?? "";
        const project = summary.startsWith(IMPORTED_SUMMARY)
          ? summary.slice(IMPORTED_SUMMARY.length).replace(/…$/u, "").trim()
          : "";
        return project.length > 0
          ? fill(copy.value.reused, { project })
          : copy.value.reusedElsewhere;
      }
    }
  }
  return sourceOrigin(twin.profile.persona_reference.source);
}

function twinConfirmed(twin: UserTwinVersionPayload): boolean {
  return APPROVED_LIFECYCLES.has(effectiveLifecycle(twin));
}

function observationSummary(observation: ProfileObservationPayload): string {
  const labels = {
    INFERRED: ["Dedotto", "Inferred"],
    HYPOTHESIZED: ["Ipotizzato", "Hypothesized"],
    CONTESTED: ["Contestato", "Contested"],
    EVIDENCED: ["Evidenziato", "Evidenced"],
    UNKNOWN: ["Sconosciuto", "Unknown"],
  };
  const label = labels[observationDisplayStatus(observation)][props.locale === "it" ? 0 : 1];
  return observation.human_validation === "REQUIRED"
    ? `${label} · ${props.locale === "it" ? "da verificare" : "needs review"}`
    : (label ?? copy.value.unknown);
}

function lifecycleLabel(twin: UserTwinVersionPayload): string {
  const labels: Record<string, readonly [string, string]> = {
    PROTO_UT: ["Prima proposta", "Initial proposal"],
    PROJECT_GROUNDED_UT: ["Basato sul progetto", "Based on the project"],
    OWNER_APPROVED_UT: ["Profilo approvato", "Approved profile"],
    EMPIRICALLY_GROUNDED_UT: ["Basato su osservazioni reali", "Based on real observations"],
    EMPIRICALLY_VALIDATED_UT: [
      "Verificato con osservazioni reali",
      "Validated with real observations",
    ],
  };
  return labels[effectiveLifecycle(twin)]?.[props.locale === "it" ? 0 : 1] ?? copy.value.unknown;
}

function pendingDiffsLabel(twin: UserTwinVersionPayload): string | null {
  const n = profileDiffs.value.filter(
    (diff) => diff.twin_id === twin.twin_id && diff.status === "PROPOSED",
  ).length;
  if (n === 0) return null;
  return n === 1 ? copy.value.pendingDiffsOne : fill(copy.value.pendingDiffsOther, { n });
}

function diffStatusLabel(diff: UserTwinProfileDiffPayload): string {
  return diff.status === "PROPOSED"
    ? copy.value.proposedDiff
    : diff.status === "APPROVED"
      ? copy.value.approvedDiff
      : copy.value.rejectedDiff;
}

function personaReason(personaId: string): string {
  return personaReasons[personaId] ?? "";
}

function diffReason(diffId: string): string {
  return diffReasons[diffId] ?? "";
}

function gateActionRequiresReason(action: GateDecisionAction): boolean {
  return action === "REJECT" || action === "REQUEST_REVISION";
}

async function runAction(action: (token: string) => Promise<unknown>): Promise<boolean> {
  localError.value = null;

  try {
    await (props.authorize ? props.authorize(action) : action(props.accessToken));

    return true;
  } catch (error) {
    if (error instanceof Error) {
      localError.value = error.message;
    } else {
      localError.value = copy.value.error;
    }

    return false;
  }
}

async function loadProject(): Promise<void> {
  if (props.projectId.trim().length === 0 || props.accessToken.trim().length === 0) {
    localError.value = copy.value.projectMissing;

    return;
  }

  const projectId = props.projectId;

  if (await runAction((token) => store.load(projectId, token))) {
    loadedProjectId.value = projectId;
  }
}

function authorizedJobs<T>(operation: (token: string) => Promise<T>): Promise<T> {
  return props.authorize ? props.authorize(operation) : operation(props.accessToken);
}

function changed(): void {
  emit("sections-changed");
}

async function reloadAndTell(): Promise<void> {
  await loadProject();
  changed();
}

async function reloadArchetypes(): Promise<void> {
  await loadProject();
  if (store.error !== null || localError.value !== null) return;
  archetypeEditorOpen.value = false;
  editingArchetype.value = null;
  removingArchetype.value = null;
}

async function proposePersonas(): Promise<void> {
  if (modelingJob.value !== null) return;
  dismissModelingJob();
  if (await runAction((token) => store.proposePersonas(props.projectId, token))) {
    changed();
  }
}

const teamApproved = computed(
  () => team.projectId === props.projectId && team.readiness?.status === "READY_FOR_MAIN_WORKFLOW",
);

const shouldProposeAutomatically = computed(
  () =>
    props.autoLoad &&
    proposalFollowsApproval.value &&
    teamApproved.value &&
    loadedProjectId.value === props.projectId &&
    modelingChecked.value &&
    modelingJob.value === null &&
    !generationSeen.has(props.projectId) &&
    personas.value.length === 0 &&
    store.currentSnapshot === null &&
    !store.isBusy &&
    localError.value === null,
);

watch(
  shouldProposeAutomatically,

  (ready) => {
    if (!ready || autoProposalAttempted.value) {
      return;
    }

    autoProposalAttempted.value = true;

    void proposePersonas();
  },

  {
    immediate: true,
  },
);

async function startRejection(persona: PersonaVersionPayload): Promise<void> {
  localError.value = null;
  rejectingPersonaId.value = persona.persona_id;
  await nextTick();
  document.getElementById(`persona-reason-${persona.persona_id}`)?.focus();
}

async function cancelRejection(persona: PersonaVersionPayload): Promise<void> {
  rejectingPersonaId.value = null;
  await nextTick();
  document.getElementById(`persona-reject-${persona.persona_id}`)?.focus();
}

async function decidePersona(
  persona: PersonaVersionPayload,
  decision: PersonaOwnerDecision,
): Promise<void> {
  const reason = personaReason(persona.persona_id).trim();

  if (decision === "REJECT" && reason.length === 0) {
    localError.value = copy.value.requiredReason;

    return;
  }

  const applied = await runAction((token) =>
    store.decidePersona(
      props.projectId,
      persona.persona_id,
      decision,
      token,
      reason.length > 0 ? reason : null,
    ),
  );

  if (applied && rejectingPersonaId.value === persona.persona_id) {
    rejectingPersonaId.value = null;
  }

  if (applied) {
    changed();
  }
}

async function generateTwins(): Promise<void> {
  if (modelingJob.value !== null) return;
  dismissModelingJob();
  if (await runAction((token) => store.generateSnapshot(props.projectId, token))) {
    changed();
  }
}
function editArchetype(archetype: ArchetypePayload | null): void {
  editingArchetype.value = archetype;
  archetypeEditorOpen.value = true;
  removingArchetype.value = null;
}
async function saveArchetype(data: ArchetypeInput): Promise<void> {
  if (
    await runAction((token) =>
      store.saveArchetype(props.projectId, data, token, editingArchetype.value),
    )
  ) {
    archetypeEditorOpen.value = false;
    changed();
  }
}
async function archiveArchetype(): Promise<void> {
  const archetype = removingArchetype.value;
  if (archetype === null) return;
  if (await runAction((token) => store.archiveArchetype(props.projectId, archetype, token))) {
    removingArchetype.value = null;
    changed();
  }
}

function openProfile(kind: ProfileTarget["kind"], id: string): void {
  profileTarget.value = { kind, id };
}

function closeProfile(): void {
  profileTarget.value = null;
  cancelRevision();
}

function startRevision(twin: UserTwinVersionPayload, observation: ProfileObservationPayload): void {
  const field = observationField(observation);

  if (field === null) {
    localError.value = copy.value.invalidField;

    return;
  }

  editingTwinId.value = twin.twin_id;

  editingField.value = field;

  editingOriginalKind.value = observation.value.kind;

  revisionEpistemicStatus.value = "USER_PROVIDED";
  revisionRationale.value = "";

  if (observation.value.kind === "ITEMS") {
    editingValue.value = observation.value.items.join("\n");

    return;
  }

  if (observation.value.kind === "TEXT") {
    editingValue.value = observation.value.text ?? "";

    return;
  }

  editingValue.value = "";
}

function cancelRevision(): void {
  revisionRationale.value = "";
  editingTwinId.value = null;
  editingField.value = null;
  editingOriginalKind.value = "TEXT";
  editingValue.value = "";
  revisionEpistemicStatus.value = "USER_PROVIDED";
}

function isEditing(twin: UserTwinVersionPayload, observation: ProfileObservationPayload): boolean {
  return (
    editingTwinId.value === twin.twin_id &&
    editingField.value !== null &&
    editingField.value === observationField(observation)
  );
}

function replacementValue(field: UserTwinField) {
  const normalized = editingValue.value.trim();

  if (normalized.length === 0) {
    throw new Error(copy.value.requiredValue);
  }

  const useItems =
    editingOriginalKind.value === "ITEMS" ||
    (editingOriginalKind.value !== "TEXT" && multiValueFields.has(field));

  if (useItems) {
    const items = editingValue.value
      .split(/\r?\n/)
      .map((item) => item.trim())
      .filter((item) => item.length > 0);

    if (items.length === 0) {
      throw new Error(copy.value.requiredValue);
    }

    return {
      kind: "ITEMS" as const,
      text: null,
      items,
      reason: null,
    };
  }

  return {
    kind: "TEXT" as const,
    text: normalized,
    items: [],
    reason: null,
  };
}

async function submitRevision(): Promise<void> {
  const twinId = editingTwinId.value;

  const field = editingField.value;

  if (twinId === null || field === null) {
    localError.value = copy.value.invalidField;

    return;
  }

  let value;

  try {
    value = replacementValue(field);
  } catch (error) {
    localError.value = error instanceof Error ? error.message : copy.value.requiredValue;

    return;
  }

  const humanValidated = revisionEpistemicStatus.value === "HUMAN_VALIDATED";
  const contested = revisionEpistemicStatus.value === "CONTESTED";
  if (contested && revisionRationale.value.trim().length === 0) {
    localError.value = archetypeCopy.value.rationale;
    return;
  }

  const replacement: ProfileReplacementRequest = {
    field,

    value,

    epistemic_status: revisionEpistemicStatus.value,

    confidence: 1,

    provenance: [
      {
        source_kind: humanValidated ? "HUMAN_REVIEW" : "OWNER_INPUT",

        source_id: humanValidated ? "owner-human-review" : "owner-input",

        source_version: null,
        content_hash: null,

        locator: `user_twin.${field}`,

        summary: humanValidated
          ? props.locale === "it"
            ? "Revisione umana registrata dal proprietario."
            : "Human review recorded by the owner."
          : props.locale === "it"
            ? "Modifica fornita dal proprietario."
            : "Owner-provided profile revision.",
      },
    ],

    human_validation: contested ? "REQUIRED" : "NOT_REQUIRED",

    rationale: contested ? revisionRationale.value.trim() : null,
  };

  const applied = await runAction((token) =>
    store.proposeRevision(props.projectId, twinId, [replacement], token),
  );

  if (applied) {
    cancelRevision();
    changed();
  }
}

async function decideDiff(
  diff: UserTwinProfileDiffPayload,
  decision: ProfileRevisionDecision,
): Promise<void> {
  const reason = diffReason(diff.id).trim();

  if (decision === "REJECT" && reason.length === 0) {
    localError.value = copy.value.requiredReason;

    return;
  }

  const decided = await runAction((token) =>
    store.decideRevision(
      props.projectId,
      diff.id,
      decision,
      token,
      reason.length > 0 ? reason : null,
    ),
  );

  if (decided) {
    changed();
  }
}

async function submitGate(): Promise<boolean> {
  const submitted = await runAction((token) => store.submitGate(props.projectId, token));
  if (submitted && !gatePendingApproval.value) {
    localError.value = copy.value.submitFailed;
    return false;
  }
  return submitted;
}

async function decideGate(action: GateDecisionAction, note?: string): Promise<boolean> {
  const reason = (note ?? gateReason.value).trim();

  if (gateActionRequiresReason(action) && reason.length === 0) {
    localError.value = copy.value.requiredReason;

    return false;
  }

  const applied = await runAction((token) =>
    store.decideGate(props.projectId, action, token, reason.length > 0 ? reason : null),
  );

  if (applied && note === undefined) {
    gateReason.value = "";
  }

  if (applied) {
    changed();
  }

  return applied;
}

async function approveTwins(): Promise<void> {
  if (approving.value || store.isBusy) return;
  approving.value = true;
  try {
    if (!gatePendingApproval.value && !(await submitGate())) return;
    await decideGate("APPROVE");
  } finally {
    approving.value = false;
  }
}

async function onPrimary(): Promise<void> {
  switch (decision.value) {
    case "generate":
      await generateTwins();
      return;
    case "approve":
      await approveTwins();
      return;
    case "resume":
      await decideGate("RESUME");
      return;
  }
}

async function onRequest(text: string): Promise<void> {
  if (!requestAvailable.value) return;
  if (await decideGate("REQUEST_REVISION", text)) {
    await decisionBar.value?.completeRequest();
  }
}

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

watch(
  () => [props.projectId, props.accessToken, props.autoLoad] as const,

  ([projectId, accessToken, autoLoad]) => {
    loadedProjectId.value = null;

    autoProposalAttempted.value = false;

    proposalFollowsApproval.value = false;
    archetypeEditorOpen.value = false;
    editingArchetype.value = null;
    removingArchetype.value = null;

    if (!autoLoad || projectId.trim().length === 0 || accessToken.trim().length === 0) {
      return;
    }

    void loadProject();
  },

  {
    immediate: true,
  },
);

let teamApprovedBefore: boolean | null = null;

watchUpstream(
  () => props.upstream,
  (changed) => {
    const approvedNow = teamApproved.value;

    if (changed) {
      proposalFollowsApproval.value = teamApprovedBefore === false && approvedNow;

      if (props.autoLoad) {
        loadedProjectId.value = null;

        void loadProject();
      }
    }

    teamApprovedBefore = approvedNow;
  },
);
</script>

<template>
  <section
    ref="root"
    class="grid gap-6 text-on-night"
    data-surface="night"
    :aria-label="copy.region"
    data-testid="user-modeling-step"
  >
    <GenerationJobNotice
      v-if="modelingJob !== null || modelingJobFailure !== null"
      :job="modelingJob"
      :failure="modelingJobFailure"
      :locale="locale"
      @dismiss="dismissModelingJob"
    />
    <UiStateBlock
      v-else-if="longOperation"
      kind="loading"
      :title="copy.generating"
      data-testid="user-modeling-busy"
    />
    <p v-else class="sr-only" role="status">{{ store.isBusy ? copy.loading : "" }}</p>

    <UiStateBlock v-if="errorMessage !== null" kind="error" :text="errorMessage" />
    <UiButton
      v-if="
        store.error?.code === 'ARCHETYPE_VERSION_CONFLICT' ||
        store.error?.code === 'ARCHETYPE_NOT_FOUND'
      "
      variant="quiet"
      :disabled="store.isBusy"
      data-testid="archetype-reload"
      @click="reloadArchetypes"
      >{{ locale === "it" ? "Ricarica archetipi" : "Reload archetypes" }}</UiButton
    >

    <section
      class="grid gap-3"
      :aria-label="locale === 'it' ? 'Gestisci archetipi' : 'Manage archetypes'"
    >
      <div class="flex flex-wrap items-center justify-between gap-3">
        <h2 class="m-0 text-base font-semibold">{{ archetypeCopy.heading }}</h2>
        <UiButton
          variant="secondary"
          :disabled="store.isBusy || modelingJob !== null || archetypes.length >= 8"
          data-testid="archetype-add"
          @click="editArchetype(null)"
          >{{ archetypeCopy.add }}</UiButton
        >
      </div>
      <ArchetypeEditor
        v-if="archetypeEditorOpen"
        :archetype="editingArchetype"
        :busy="store.isBusy"
        :locale="locale"
        @save="saveArchetype"
        @cancel="archetypeEditorOpen = false"
      />
      <details
        v-if="archetypes.length > 0"
        class="rounded-panel border border-night-line bg-night-raised"
        :open="phase !== 'twins'"
        data-testid="archetype-list"
      >
        <summary class="flex min-h-11 cursor-pointer items-center px-4 text-sm font-semibold">
          {{ archetypeCopy.heading }} ({{ archetypes.length }})
        </summary>
        <ul class="m-0 grid list-none gap-3 border-t border-night-line p-4">
          <li v-for="archetype in archetypes" :key="archetype.persona_id" class="grid gap-1.5">
            <strong class="text-sm"
              >{{ archetype.name }}
              <span class="font-normal text-on-night-3"
                >· v{{ archetype.version_number }}</span
              ></strong
            >
            <p class="m-0 line-clamp-2 text-sm text-on-night-2">
              {{ archetype.description ?? copy.unknown }}
            </p>
            <div class="flex flex-wrap gap-2">
              <UiButton
                variant="quiet"
                :disabled="store.isBusy"
                :data-testid="`archetype-edit-${archetype.persona_id}`"
                :aria-label="`${archetypeCopy.edit}: ${archetype.name}`"
                @click="editArchetype(archetype)"
                >{{ archetypeCopy.edit }}</UiButton
              >
              <UiButton
                variant="quiet"
                :disabled="store.isBusy"
                :data-testid="`archetype-delete-${archetype.persona_id}`"
                :aria-label="`${archetypeCopy.remove}: ${archetype.name}`"
                @click="removingArchetype = archetype"
                >{{ archetypeCopy.remove }}</UiButton
              >
            </div>
          </li>
        </ul>
      </details>
      <section
        v-if="removingArchetype !== null"
        class="grid gap-3 rounded-panel border border-warn-on-night/40 p-4"
        :aria-label="`${archetypeCopy.remove}: ${removingArchetype.name}`"
      >
        <strong>{{ archetypeCopy.remove }}: {{ removingArchetype.name }}</strong>
        <p class="m-0 text-sm leading-normal text-on-night-2">{{ archetypeCopy.archive }}</p>
        <div class="flex flex-wrap gap-2">
          <UiButton
            variant="danger"
            :disabled="store.isBusy"
            data-testid="archetype-delete-confirm"
            @click="archiveArchetype"
            >{{ archetypeCopy.confirm }}</UiButton
          >
          <UiButton variant="quiet" :disabled="store.isBusy" @click="removingArchetype = null">{{
            archetypeCopy.cancel
          }}</UiButton>
        </div>
      </section>
    </section>

    <UiStateBlock
      v-if="phase === 'empty' && !longOperation"
      kind="empty"
      :title="copy.noPersonasTitle"
      :text="copy.noPersonas"
    >
      <UiButton
        variant="pill"
        :disabled="store.isBusy || modelingJob !== null"
        data-testid="propose-personas"
        @click="proposePersonas"
      >
        {{ copy.proposePersonas }}
      </UiButton>
    </UiStateBlock>

    <div v-if="phase !== 'empty'" class="flex flex-wrap items-start gap-x-6 gap-y-3">
      <div class="grid min-w-[min(100%,220px)] flex-1 gap-1.5">
        <p class="m-0 text-base leading-normal text-on-night-3" data-testid="user-modeling-count">
          <strong class="font-semibold text-on-night">{{ countLabel }}.</strong>
          {{ phase === "profiles" ? copy.profilesSentence : copy.twinsSentence }}
        </p>
        <template v-if="phase === 'twins'">
          <p
            v-if="snapshotApproved"
            class="m-0 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm font-medium text-petrol-on-night-2"
          >
            <span class="size-2 shrink-0 rounded-full bg-petrol-on-night" aria-hidden="true" />
            <span>{{ copy.currentSnapshotApproved }}</span>
            <span data-testid="requirements-readiness">
              {{ store.isReadyForRequirements ? copy.ready : copy.notReady }}
            </span>
          </p>
          <p v-else class="sr-only" data-testid="requirements-readiness">
            {{ store.isReadyForRequirements ? copy.ready : copy.notReady }}
          </p>
        </template>
      </div>
      <TwinImportPanel
        v-if="phase === 'twins' && twins.length > 0"
        :project-id="projectId"
        :locale="locale"
        :authorize="authorize"
        @imported="reloadAndTell"
      />
    </div>

    <div
      v-if="phase === 'twins' && contextStale"
      class="rounded-panel border border-warn-on-night/40 bg-warn-on-night/8 px-5 py-4 text-[15px] leading-normal font-semibold text-warn-on-night"
      role="status"
      data-testid="user-modeling-stale-context"
    >
      {{ staleContextText }}
    </div>

    <div
      v-if="gateNotice !== null"
      class="grid gap-1 rounded-panel border border-warn-on-night/40 bg-warn-on-night/8 px-5 py-4 text-[15px] leading-normal"
      role="status"
      data-testid="user-modeling-gate-notice"
    >
      <p class="m-0 font-semibold text-warn-on-night">{{ gateNotice }}</p>
      <p v-if="revisionNote" class="m-0 text-on-night-2">
        {{ fill(copy.revisionNote, { note: revisionNote }) }}
      </p>
    </div>

    <section
      v-if="showPersonaCards"
      aria-labelledby="personas-heading"
      data-testid="starting-personas"
    >
      <h2 id="personas-heading" class="sr-only">{{ copy.personasHeading }}</h2>
      <ul
        class="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(min(100%,260px),1fr))] gap-4 p-0"
      >
        <li v-for="persona in personas" :key="persona.id" class="flex">
          <component
            :is="persona.profile.confirmation_status === 'REJECTED' ? 'article' : UiClaimFrame"
            v-bind="
              persona.profile.confirmation_status === 'REJECTED'
                ? {}
                : {
                    status:
                      persona.profile.confirmation_status === 'CONFIRMED'
                        ? 'confirmed'
                        : 'hypothesis',
                    as: 'article',
                    radius: 'tile',
                    padded: false,
                  }
            "
            :class="[
              'flex w-full min-w-0 flex-col gap-3.5 p-[22px]',
              persona.profile.confirmation_status === 'REJECTED'
                ? 'rounded-tile border border-night-line bg-night-raised'
                : '',
            ]"
            data-testid="persona-card"
            :data-persona-id="persona.persona_id"
            :data-confirmation="persona.profile.confirmation_status"
          >
            <TwinIdentity
              size="lg"
              name-as="h3"
              :identity-key="persona.persona_id"
              :peers="peers"
              :name="persona.profile.name"
              :description="sourceOrigin(persona.profile.source)"
              :status="
                persona.profile.confirmation_status === 'CONFIRMED' ? 'confirmed' : 'hypothesis'
              "
              :locale="locale"
            />
            <div class="flex flex-wrap gap-2">
              <UiStatusChip
                v-if="persona.profile.confirmation_status === 'CONFIRMED'"
                status="approved"
                :label="copy.confirmedByYou"
              />
              <UiStatusChip
                v-else-if="persona.profile.confirmation_status === 'REJECTED'"
                status="rejected"
                :label="copy.rejectedChip"
              />
              <span
                v-else
                class="inline-flex min-h-[26px] items-center gap-1.5 rounded-pill border border-dashed border-violet-on-night bg-night-raised px-2.5 text-xs font-medium whitespace-nowrap text-violet-on-night-2"
                data-testid="hypothesis-chip"
              >
                <span
                  class="inline-block size-2 shrink-0 rounded-full border-[1.5px] border-violet-on-night"
                  aria-hidden="true"
                />
                {{ hypothesisLabel(persona.profile.observations) ?? personaStatusLabel(persona) }}
              </span>
            </div>
            <p
              v-if="
                summaryOf(persona.profile.observations, persona.persona_id, persona.profile.name)
              "
              class="m-0 text-[15px] leading-[1.55]"
            >
              {{
                summaryOf(persona.profile.observations, persona.persona_id, persona.profile.name)
              }}
            </p>
            <dl
              v-if="cardFacts(persona.profile.observations).length > 0"
              class="m-0 flex flex-col gap-2.5 text-sm leading-normal"
            >
              <div v-for="fact in cardFacts(persona.profile.observations)" :key="fact.label">
                <dt class="font-mono text-[11px] tracking-[0.06em] text-on-night-3 uppercase">
                  {{ fact.label }}
                </dt>
                <dd class="m-0 mt-0.5 line-clamp-3">{{ fact.value }}</dd>
              </div>
            </dl>
            <p
              v-if="
                persona.profile.confirmation_status === 'REJECTED' &&
                persona.profile.rejection_reason
              "
              class="m-0 text-sm leading-normal text-on-night-3"
            >
              {{ fill(copy.rejectedBecause, { reason: persona.profile.rejection_reason }) }}
            </p>
            <div class="mt-auto grid gap-2 pt-1">
              <button
                type="button"
                class="inline-flex min-h-11 items-center justify-self-start text-sm font-medium text-on-night-2 underline underline-offset-[3px] transition-colors duration-150 hover:text-on-night"
                data-testid="open-persona-profile"
                @click="openProfile('persona', persona.persona_id)"
              >
                {{ copy.fullProfile }}<span class="sr-only">: {{ persona.profile.name }}</span>
              </button>
              <template v-if="persona.profile.confirmation_status === 'PENDING_CONFIRMATION'">
                <div
                  v-if="rejectingPersonaId !== persona.persona_id"
                  class="grid grid-cols-2 gap-2"
                >
                  <UiButton
                    :disabled="store.isBusy"
                    full
                    data-testid="confirm-persona"
                    @click="decidePersona(persona, 'CONFIRM')"
                  >
                    {{ copy.confirm }}<span class="sr-only">: {{ persona.profile.name }}</span>
                  </UiButton>
                  <UiButton
                    :id="`persona-reject-${persona.persona_id}`"
                    variant="secondary"
                    :disabled="store.isBusy"
                    full
                    data-testid="reject-persona-start"
                    @click="startRejection(persona)"
                  >
                    {{ copy.reject }}<span class="sr-only">: {{ persona.profile.name }}</span>
                  </UiButton>
                </div>
                <div v-else class="grid gap-2">
                  <label
                    class="text-sm font-semibold text-on-night-2"
                    :for="`persona-reason-${persona.persona_id}`"
                  >
                    {{ copy.rejectionReason }}
                  </label>
                  <textarea
                    :id="`persona-reason-${persona.persona_id}`"
                    v-model="personaReasons[persona.persona_id]"
                    rows="2"
                    class="w-full rounded-field border border-night-line-strong bg-night-raised px-3 py-2 text-[15px] text-on-night placeholder:text-on-night-3"
                    :placeholder="copy.reasonPlaceholder"
                  />
                  <div class="grid grid-cols-[auto_minmax(0,1fr)] gap-2">
                    <UiButton variant="quiet" @click="cancelRejection(persona)">
                      {{ copy.cancel }}
                    </UiButton>
                    <UiButton
                      variant="danger"
                      full
                      :disabled="
                        store.isBusy || personaReason(persona.persona_id).trim().length === 0
                      "
                      data-testid="reject-persona"
                      @click="decidePersona(persona, 'REJECT')"
                    >
                      {{ copy.rejectConfirm }}
                    </UiButton>
                  </div>
                </div>
              </template>
            </div>
          </component>
        </li>
      </ul>
    </section>

    <section v-if="phase === 'twins'" aria-labelledby="twins-heading">
      <h2 id="twins-heading" class="sr-only">{{ copy.twinsHeading }}</h2>
      <p v-if="twins.length === 0" class="m-0 text-[15px] text-on-night-3">{{ copy.noTwins }}</p>
      <ul
        v-else
        class="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(min(100%,260px),1fr))] gap-4 p-0"
      >
        <li v-for="twin in twins" :key="twin.id" class="flex">
          <UiClaimFrame
            :status="twinConfirmed(twin) ? 'confirmed' : 'hypothesis'"
            as="article"
            radius="tile"
            :padded="false"
            class="flex w-full min-w-0 flex-col gap-3.5 p-[22px]"
            data-testid="twin-card"
            :data-twin-id="twin.twin_id"
          >
            <TwinIdentity
              size="lg"
              name-as="h3"
              :identity-key="twin.profile.persona_reference.persona_id"
              :peers="peers"
              :name="twin.profile.name"
              :description="twinOrigin(twin)"
              :status="twinConfirmed(twin) ? 'confirmed' : 'hypothesis'"
              :locale="locale"
            />
            <div class="flex flex-wrap gap-2">
              <UiStatusChip
                v-if="twinConfirmed(twin)"
                status="approved"
                :label="lifecycleLabel(twin)"
              />
              <span
                v-else
                class="inline-flex min-h-[26px] items-center gap-1.5 rounded-pill border border-dashed border-violet-on-night bg-night-raised px-2.5 text-xs font-medium whitespace-nowrap text-violet-on-night-2"
                data-testid="hypothesis-chip"
              >
                <span
                  class="inline-block size-2 shrink-0 rounded-full border-[1.5px] border-violet-on-night"
                  aria-hidden="true"
                />
                {{ hypothesisLabel(twin.profile.observations) ?? copy.awaitingApproval }}
              </span>
            </div>
            <p v-if="twinSummary(twin)" class="m-0 text-[15px] leading-[1.55]">
              {{ twinSummary(twin) }}
            </p>
            <TwinPersonaView
              :twin="twin"
              :persona="citedPersona(twin)"
              :locale="locale"
              :show-description="false"
            />
            <dl
              v-if="cardFacts(twin.profile.observations).length > 0"
              class="m-0 flex flex-col gap-2.5 text-sm leading-normal"
            >
              <div v-for="fact in cardFacts(twin.profile.observations)" :key="fact.label">
                <dt class="font-mono text-[11px] tracking-[0.06em] text-on-night-3 uppercase">
                  {{ fact.label }}
                </dt>
                <dd class="m-0 mt-0.5 line-clamp-3">{{ fact.value }}</dd>
              </div>
            </dl>
            <p
              v-if="pendingDiffsLabel(twin)"
              class="m-0 text-sm font-medium text-violet-on-night-2"
              data-testid="twin-pending-diffs"
            >
              {{ pendingDiffsLabel(twin) }}
            </p>
            <div class="mt-auto grid gap-2 pt-1">
              <button
                type="button"
                class="inline-flex min-h-11 items-center justify-self-start text-sm font-medium text-on-night-2 underline underline-offset-[3px] transition-colors duration-150 hover:text-on-night"
                data-testid="open-twin-profile"
                @click="openProfile('twin', twin.twin_id)"
              >
                {{ copy.fullProfile }}<span class="sr-only">: {{ twin.profile.name }}</span>
              </button>
              <UiButton
                variant="secondary"
                full
                data-testid="open-twin-chat"
                @click="emit('open-chat', twin)"
              >
                {{ copy.talk }}<span class="sr-only">: {{ twin.profile.name }}</span>
              </UiButton>
            </div>
          </UiClaimFrame>
        </li>
      </ul>
    </section>

    <div
      v-if="
        (phase === 'twins' && !showPersonaCards && personas.length > 0) || otherDecisionsAvailable
      "
      class="-mt-2 flex flex-wrap items-start gap-x-8"
    >
      <details
        v-if="phase === 'twins' && !showPersonaCards && personas.length > 0"
        class="group open:basis-full"
        data-testid="starting-personas"
      >
        <summary :class="disclosureSummary">
          <span aria-hidden="true" :class="disclosureChevron" />
          {{ copy.startingProfiles }} ({{ personas.length }})
        </summary>
        <ul
          class="m-0 mt-2 grid list-none gap-3 rounded-field border border-night-line bg-night-raised px-5 py-4"
        >
          <li
            v-for="persona in personas"
            :key="persona.id"
            class="flex flex-wrap items-center justify-between gap-3"
          >
            <TwinIdentity
              :identity-key="persona.persona_id"
              :peers="peers"
              :name="persona.profile.name"
              :description="sourceOrigin(persona.profile.source)"
              :status="
                persona.profile.confirmation_status === 'CONFIRMED' ? 'confirmed' : 'hypothesis'
              "
              :locale="locale"
            />
            <div class="flex flex-wrap items-center gap-2">
              <span class="text-xs text-on-night-3">
                {{ personaStatusLabel(persona) }} · v{{ persona.version_number }}
              </span>
              <button
                type="button"
                class="inline-flex min-h-11 items-center text-sm font-medium text-on-night-2 underline underline-offset-[3px] hover:text-on-night"
                @click="openProfile('persona', persona.persona_id)"
              >
                {{ copy.profileDetails }}<span class="sr-only">: {{ persona.profile.name }}</span>
              </button>
            </div>
          </li>
        </ul>
      </details>

      <details
        v-if="otherDecisionsAvailable"
        class="group open:basis-full"
        data-testid="twins-other-decisions"
      >
        <summary :class="disclosureSummary">
          <span aria-hidden="true" :class="disclosureChevron" />
          {{ copy.otherDecisions }}
        </summary>
        <div
          class="mt-2 grid gap-3 rounded-field border border-night-line bg-night-raised px-5 py-4"
        >
          <label for="gate-three-reason" class="text-sm font-semibold text-on-night-2">
            {{ copy.gateReason }}
          </label>
          <textarea
            id="gate-three-reason"
            v-model="gateReason"
            rows="2"
            class="min-h-20 w-full rounded-field border border-night-line-strong bg-night-raised px-3 py-2 text-[15px] text-on-night"
          />
          <p class="m-0 text-xs text-on-night-3">{{ copy.gateReasonHint }}</p>
          <div class="flex flex-wrap gap-3">
            <UiButton
              v-if="gatePendingApproval"
              variant="danger"
              :disabled="store.isBusy || gateReason.trim().length === 0"
              data-testid="twins-reject"
              @click="decideGate('REJECT')"
            >
              {{ copy.rejectGate }}
            </UiButton>
            <UiButton
              v-if="gatePendingApproval"
              variant="secondary"
              :disabled="store.isBusy"
              data-testid="twins-pause"
              @click="decideGate('PAUSE')"
            >
              {{ copy.pause }}
            </UiButton>
            <UiButton
              variant="secondary"
              :disabled="store.isBusy"
              data-testid="twins-cancel"
              @click="decideGate('CANCEL')"
            >
              {{ copy.cancelGate }}
            </UiButton>
          </div>
        </div>
      </details>
    </div>

    <Teleport :to="barTarget" :disabled="barTarget === null">
      <div
        v-if="decision !== null"
        class="contents"
        data-testid="twins-decision"
        :data-decision="decision"
        :data-gate-pending="gatePendingApproval ? 'true' : 'false'"
      >
        <UiDecisionBar
          ref="decisionBar"
          :primary-label="decisionCopy.primary"
          :description="decisionCopy.description"
          :secondary-label="requestAvailable ? undefined : null"
          :request-placeholder="copy.requestPlaceholder"
          :busy="barBusy"
          :disabled="decisionCopy.disabled"
          @primary="onPrimary"
          @request="onRequest"
        />
      </div>
    </Teleport>

    <Teleport :to="rowTarget" :disabled="rowTarget === null">
      <div v-if="phase !== 'empty'" data-testid="user-modeling-technical-details">
        <UiTechnicalDetails :summary="technicalSummary" :rows="technicalRows">
          <div class="grid gap-4 text-on-night-2">
            <section v-if="twins.length > 0" class="grid gap-1.5">
              <h3 class="m-0 font-mono text-[11px] tracking-label text-on-night-3 uppercase">
                {{ copy.technicalTwins }}
              </h3>
              <dl
                v-for="twin in twins"
                :key="twin.id"
                class="m-0 grid gap-0.5"
                data-testid="twin-technical-details"
              >
                <dt class="font-semibold text-on-night">{{ twin.profile.name }}</dt>
                <dd class="m-0 font-mono text-xs break-all text-on-night-3">
                  {{ twin.twin_id }} · v{{ twin.version_number }}
                </dd>
                <dd class="m-0">
                  {{ copy.persistedLifecycle }}: {{ twin.profile.validation_status }}
                </dd>
                <dd class="m-0">
                  {{ copy.effectiveLifecycle }}:
                  <span data-testid="effective-lifecycle">{{ effectiveLifecycle(twin) }}</span>
                </dd>
              </dl>
            </section>
            <section v-if="personas.length > 0" class="grid gap-1.5">
              <h3 class="m-0 font-mono text-[11px] tracking-label text-on-night-3 uppercase">
                {{ copy.technicalPersonas }}
              </h3>
              <p
                v-for="persona in personas"
                :key="persona.id"
                class="m-0"
                data-testid="persona-technical-details"
              >
                <span class="font-semibold text-on-night">{{ persona.profile.name }}</span>
                · {{ persona.profile.kind }} ·
                <span class="font-mono text-xs break-all">{{ persona.persona_id }}</span>
              </p>
            </section>
            <section v-if="profileDiffs.length > 0" class="grid gap-1.5">
              <h3 class="m-0 font-mono text-[11px] tracking-label text-on-night-3 uppercase">
                {{ copy.diffs }}
              </h3>
              <p v-for="diff in profileDiffs" :key="diff.id" class="m-0">
                {{ diffStatusLabel(diff) }} ·
                <span class="font-mono text-xs break-all">{{ diff.id }}</span>
              </p>
            </section>
          </div>
        </UiTechnicalDetails>
      </div>
    </Teleport>

    <UiSidePanel
      :open="profileTarget !== null"
      :title="profileTitle"
      surface="night"
      @close="closeProfile"
    >
      <div
        v-if="profileTwin !== null || profilePersona !== null"
        class="grid gap-5"
        data-testid="twin-profile-details"
        :data-profile-kind="profileTarget?.kind"
      >
        <div class="flex flex-wrap items-center gap-3">
          <TwinIdentity
            size="lg"
            :identity-key="
              profileTwin?.profile.persona_reference.persona_id ?? profilePersona?.persona_id ?? ''
            "
            :peers="peers"
            :name="profileTwin?.profile.name ?? profilePersona?.profile.name ?? ''"
            :description="
              profileTwin !== null
                ? twinOrigin(profileTwin)
                : profilePersona !== null
                  ? sourceOrigin(profilePersona.profile.source)
                  : ''
            "
            :status="
              (profileTwin !== null && twinConfirmed(profileTwin)) ||
              profilePersona?.profile.confirmation_status === 'CONFIRMED'
                ? 'confirmed'
                : 'hypothesis'
            "
            :locale="locale"
          />
          <span class="text-xs text-on-night-3">
            {{
              profileTwin !== null
                ? lifecycleLabel(profileTwin)
                : profilePersona !== null
                  ? personaStatusLabel(profilePersona)
                  : ""
            }}
          </span>
        </div>

        <section
          v-if="profileDiffsForTwin.length > 0"
          class="grid gap-3"
          aria-labelledby="profile-diffs-heading"
        >
          <h3 id="profile-diffs-heading" class="m-0 text-base font-semibold">
            {{ copy.diffs }}
          </h3>
          <article
            v-for="diff in profileDiffsForTwin"
            :key="diff.id"
            class="grid gap-3 rounded-field border-[1.5px] border-dashed border-violet-on-night/70 bg-violet-on-night/6 p-4"
            data-testid="profile-diff"
            :data-diff-status="diff.status"
          >
            <UiStatusChip
              :status="
                diff.status === 'APPROVED'
                  ? 'approved'
                  : diff.status === 'REJECTED'
                    ? 'rejected'
                    : 'pending'
              "
              :label="diffStatusLabel(diff)"
              class="justify-self-start"
            />
            <div
              v-for="operation in diff.operations"
              :key="operation.field"
              class="grid gap-3 sm:grid-cols-2"
            >
              <div class="min-w-0">
                <p class="m-0 font-mono text-[11px] tracking-[0.06em] text-on-night-3 uppercase">
                  {{ copy.before }} · {{ fieldLabel(operation.field) }}
                </p>
                <p class="m-0 mt-1 text-sm leading-normal text-on-night-2">
                  {{ formatObservation(operation.before) }}
                </p>
              </div>
              <div class="grid min-w-0 gap-2">
                <p class="m-0 font-mono text-[11px] tracking-[0.06em] text-on-night-3 uppercase">
                  {{ copy.after }} · {{ fieldLabel(operation.field) }}
                </p>
                <p class="m-0 text-sm leading-normal">{{ formatObservation(operation.after) }}</p>
                <UserModelingEpistemicBadge
                  :status="operation.after.epistemic_status"
                  :observation="operation.after"
                  :confidence="operation.after.confidence"
                  :human-validation="operation.after.human_validation"
                  :locale="locale"
                />
                <UserModelingProvenanceInspector :observation="operation.after" :locale="locale" />
              </div>
            </div>
            <div v-if="diff.status === 'PROPOSED'" class="grid gap-2">
              <label :for="`diff-reason-${diff.id}`" class="text-sm font-semibold text-on-night-2">
                {{ copy.diffReason }}
              </label>
              <textarea
                :id="`diff-reason-${diff.id}`"
                v-model="diffReasons[diff.id]"
                rows="2"
                class="w-full rounded-field border border-night-line-strong bg-night-raised px-3 py-2 text-[15px] text-on-night"
              />
              <div class="flex flex-wrap gap-2">
                <UiButton
                  :disabled="store.isBusy"
                  data-testid="approve-diff"
                  @click="decideDiff(diff, 'APPROVE')"
                >
                  {{ copy.approveDiff }}
                </UiButton>
                <UiButton
                  variant="secondary"
                  :disabled="store.isBusy || diffReason(diff.id).trim().length === 0"
                  data-testid="reject-diff"
                  @click="decideDiff(diff, 'REJECT')"
                >
                  {{ copy.rejectDiff }}
                </UiButton>
              </div>
            </div>
          </article>
        </section>

        <ul class="m-0 grid list-none gap-3 p-0">
          <li
            v-for="observation in profileObservations"
            :key="observation.observation_key"
            class="grid gap-2 rounded-field border px-4 py-3"
            :class="
              isHypothesis(observation)
                ? 'border-dashed border-violet-on-night/60 bg-violet-on-night/6'
                : 'border-petrol-on-night/70 bg-night-raised'
            "
            data-testid="profile-observation"
          >
            <div class="flex flex-wrap items-start justify-between gap-2">
              <div class="min-w-0 flex-1">
                <h3 class="m-0 font-mono text-[11px] tracking-[0.06em] text-on-night-3 uppercase">
                  {{ observationLabel(observation) }}
                </h3>
                <p class="m-0 mt-1 text-[15px] leading-normal whitespace-pre-line">
                  {{ formatObservation(observation) }}
                </p>
              </div>
              <UiButton
                v-if="profileTwin !== null && observationField(observation) !== null"
                variant="quiet"
                :disabled="store.isBusy"
                data-testid="edit-twin-observation"
                @click="startRevision(profileTwin, observation)"
              >
                {{ copy.edit }}<span class="sr-only">: {{ observationLabel(observation) }}</span>
              </UiButton>
              <span v-else-if="profileTwin !== null" class="text-xs leading-5 text-on-night-3">
                {{ copy.observationUnavailable }}
              </span>
            </div>
            <p
              class="m-0 text-xs"
              :class="
                isHypothesis(observation) ? 'text-violet-on-night-2' : 'text-petrol-on-night-2'
              "
            >
              {{ observationSummary(observation) }}
            </p>

            <form
              v-if="profileTwin !== null && isEditing(profileTwin, observation)"
              class="grid gap-3 rounded-field border border-night-line-strong bg-night-panel p-4"
              data-testid="twin-revision-form"
              @submit.prevent="submitRevision"
            >
              <label for="user-twin-revision-value" class="text-sm font-semibold text-on-night">
                {{ fill(copy.editField, { field: observationLabel(observation) }) }} ·
                {{ copy.revisionValue }}
              </label>
              <textarea
                id="user-twin-revision-value"
                v-model="editingValue"
                rows="4"
                class="w-full rounded-field border border-night-line-strong bg-night-raised px-3 py-2 text-[15px] text-on-night"
                data-testid="revision-value"
              />
              <p
                v-if="
                  editingOriginalKind === 'ITEMS' ||
                  (editingField !== null && multiValueFields.has(editingField))
                "
                class="m-0 text-xs text-on-night-3"
              >
                {{ copy.revisionItemsHint }}
              </p>
              <fieldset class="m-0 grid gap-1 border-0 p-0">
                <legend class="mb-1 p-0 text-sm font-semibold text-on-night-2">
                  {{ copy.knowledgeSource }}
                </legend>
                <label class="flex min-h-11 items-center gap-3 text-sm text-on-night-2">
                  <input
                    v-model="revisionEpistemicStatus"
                    type="radio"
                    value="USER_PROVIDED"
                    class="size-4 accent-petrol-on-night"
                  />
                  {{ copy.userProvided }}
                </label>
                <label class="flex min-h-11 items-center gap-3 text-sm text-on-night-2">
                  <input
                    v-model="revisionEpistemicStatus"
                    type="radio"
                    value="HUMAN_VALIDATED"
                    class="size-4 accent-petrol-on-night"
                  />
                  {{ copy.humanValidated }}
                </label>
                <label class="flex min-h-11 items-center gap-3 text-sm text-on-night-2">
                  <input
                    v-model="revisionEpistemicStatus"
                    type="radio"
                    value="CONTESTED"
                    class="size-4 accent-petrol-on-night"
                  />
                  {{ archetypeCopy.contested }}
                </label>
              </fieldset>
              <label
                v-if="revisionEpistemicStatus === 'CONTESTED'"
                class="grid gap-1.5 text-sm text-on-night-2"
              >
                {{ archetypeCopy.rationale }}
                <textarea
                  v-model="revisionRationale"
                  required
                  class="rounded-field border border-night-line bg-night-panel px-3 py-2 text-on-night"
                  data-testid="revision-rationale"
                />
              </label>
              <p
                class="m-0 rounded-field border border-warn-on-night/40 bg-warn-on-night/8 p-3 text-xs leading-5 text-warn-on-night"
              >
                {{ copy.humanValidatedWarning }}
              </p>
              <div class="flex flex-wrap gap-2">
                <UiButton type="submit" :disabled="store.isBusy" data-testid="submit-revision">
                  {{ copy.proposeRevision }}
                </UiButton>
                <UiButton variant="quiet" @click="cancelRevision">
                  {{ copy.cancel }}
                </UiButton>
              </div>
            </form>

            <details class="text-sm">
              <summary
                class="flex min-h-11 cursor-pointer items-center text-xs font-medium text-on-night-3 hover:text-on-night"
              >
                {{ copy.evidenceDetails }}
              </summary>
              <div class="grid gap-3 pt-1 pb-1">
                <UserModelingEpistemicBadge
                  :status="observation.epistemic_status"
                  :observation="observation"
                  :confidence="observation.confidence"
                  :human-validation="observation.human_validation"
                  :locale="locale"
                />
                <ArtifactWhy
                  v-if="profileTwin"
                  :code="
                    twinClaimCode(
                      profileTwin.twin_id,
                      profileTwin.version_number,
                      observation.observation_key,
                    )
                  "
                  kind="USER_TWIN_CLAIM"
                  :title="observationLabel(observation)"
                  :artifact-id="profileTwin.twin_id"
                  :version-number="profileTwin.version_number"
                  :content-hash="profileTwin.content_hash"
                  :locale="locale"
                  test-id="claim-why"
                />
                <UserModelingProvenanceInspector :observation="observation" :locale="locale" />
              </div>
            </details>
          </li>
        </ul>
      </div>
    </UiSidePanel>
  </section>
</template>
