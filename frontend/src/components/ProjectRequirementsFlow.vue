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
  shallowRef,
  watch,
} from "vue";

import { apiClient } from "@/api/client";
import ArtifactViewSwitch, { type ArtifactView } from "./ArtifactViewSwitch.vue";
import GenerationJobNotice from "./GenerationJobNotice.vue";
import ProjectDiagramsView from "./ProjectDiagramsView.vue";
import RequirementsTableView from "./RequirementsTableView.vue";
import RequirementsDefinitionView from "./RequirementsDefinitionView.vue";
import RequirementsTraceabilityView from "./RequirementsTraceabilityView.vue";
import RequirementsTwinAlignment from "./RequirementsTwinAlignment.vue";
import RequirementsVersionComparison from "./RequirementsVersionComparison.vue";
import UiAgentMessage from "./UiAgentMessage.vue";
import UiButton from "./UiButton.vue";
import UiDecisionBar from "./UiDecisionBar.vue";
import UiStateBlock from "./UiStateBlock.vue";
import { surfaceKey, type SurfaceContext } from "./UiSurface.vue";
import UiTechnicalDetails from "./UiTechnicalDetails.vue";
import type { DiagramLink } from "./mermaidRenderer";
import { generationProgress, modelFeedback } from "./modelFeedback";
import { type UpstreamValue, watchUpstream } from "./upstreamChange";
import { workflowStatusLabel } from "./workflowLabels";
import {
  GENERATION_FAILED,
  isGenerationInterrupted,
  isGenerationLost,
} from "../api/generationJobs";
import { RequirementsApiError, requirementsApi, type RequirementsApi } from "../api/requirements";
import { useAuthStore } from "../stores/auth";
import { type GenerationResumeFailure, useGenerationResume } from "../stores/generationJobs";
import { type AuthorizedRequest, useRequirementsStore } from "../stores/requirements";
import type {
  HumanGateStatus,
  RequirementKind,
  RequirementPayload,
  RequirementPriority,
  RequirementSourcePayload,
  RequirementsArtifactEnvelope,
  RequirementsDiffOperationKind,
  RequirementsGateDecisionAction,
  RequirementsSpecificationDiffPayload,
  RequirementsSpecificationPayload,
  UserTwinVersionReferencePayload,
} from "../types/requirements";

type Locale = "en" | "it";
type DecisionState = "none" | "approve" | "paused" | "revision" | "closed" | "approved";

interface CheckCard {
  code: string;
  label: string;
  text: string;
  note: string | null;
}

const BAR_TARGET = "step-decision-bar";
const ROW_TARGET = "step-technical-row";
const HIGHLIGHT_DURATION = 4000;
const LINK_LABEL_LENGTH = 64;
const ANALYST_AVATAR = "/team/an.webp";
const QUOTE_CLASS =
  "m-0 border-l-2 border-on-night/40 pl-3 leading-normal whitespace-pre-line text-on-night-2";
const CHANGE_OPERATION = "REQUIREMENTS_CHANGE";
const REVISION_PENDING = "REQUIREMENTS_REVISION_PENDING";
const UNCHANGED = "REQUIREMENTS_UNCHANGED";
const CONTEXT_CHANGED = "REQUIREMENTS_CONTEXT_CHANGED";

const props = withDefaults(
  defineProps<{
    projectId: string;
    locale?: Locale;
    autoLoad?: boolean;
    prerequisiteReady?: boolean;
    authorize?: AuthorizedRequest;
    api?: RequirementsApi;
    upstream?: UpstreamValue;
    active?: boolean;
    sectionsMode?: boolean;
  }>(),
  {
    locale: "en",
    autoLoad: true,
    prerequisiteReady: true,
    upstream: null,
    active: true,
    sectionsMode: false,
  },
);

const emit = defineEmits<{ "sections-changed": [] }>();

provide(
  surfaceKey,
  computed<SurfaceContext>(() => "night"),
);

const auth = useAuthStore();
const store = useRequirementsStore();
const root = ref<HTMLElement | null>(null);
const viewSwitch = ref<InstanceType<typeof ArtifactViewSwitch> | null>(null);
const localError = ref<string | null>(null);
const view = ref<ArtifactView>("text");
const viewPanelId = "requirements-view-panel";
const editingRequirementId = ref<string | null>(null);
const gateReason = ref("");
const diffReasons = reactive<Record<string, string>>({});
const definitionView = ref<InstanceType<typeof RequirementsDefinitionView> | null>(null);
const checksOpen = ref(false);
const openRequirementIds = shallowRef<ReadonlySet<string>>(new Set());
const highlighted = ref<string | null>(null);
const decisionBar = ref<InstanceType<typeof UiDecisionBar> | null>(null);
const barTarget = ref<HTMLElement | null>(null);
const rowTarget = ref<HTMLElement | null>(null);
const deciding = ref(false);
const changeSection = ref<HTMLElement | null>(null);
const changeText = ref<string | null>(null);
const changeFailure = ref<GenerationResumeFailure | null>(null);
const changeUnavailable = ref(false);
const upstreamReloads = ref(0);
const edit = reactive({
  title: "",
  statement: "",
  kind: "FUNCTIONAL" as RequirementKind,
  priority: "MUST" as RequirementPriority,
});
let highlightTimer: ReturnType<typeof setTimeout> | undefined;
let visibility: ResizeObserver | null = null;

const messages = {
  en: {
    loading: "Loading the definition…",
    updating: "Updating the definition…",
    generating: "The needs analyst is writing the definition…",
    generate: "Prepare the definition",
    analyst: "Needs analyst",
    noSpecification:
      "I am ready to turn your brief and your twins into requirements: what the app must do, for whom, and how we will check it.",
    prerequisite:
      "Approve the profiles of your users first: then the requirements can be prepared.",
    preparedBy: "Prepared by the Needs analyst",
    requirementCount: ["requirement", "requirements"],
    storyCount: ["story", "stories"],
    criterionCount: ["acceptance criterion", "acceptance criteria"],
    scenarioCount: ["usage scenario", "usage scenarios"],
    needCount: ["need", "needs"],
    functionalGroup: "Functional requirements",
    nonFunctional: "Non-functional requirements",
    constraints: "Constraints",
    viewLabel: "Views of the definition",
    digestBoth: [
      "In short: {must} thing the application must do and {should} it should do.",
      "In short: {must} things the application must do and {should} it should do.",
    ],
    digestMust: [
      "In short: {must} thing the application must do.",
      "In short: {must} things the application must do.",
    ],
    digestShould: [
      "In short: {should} thing the application should do.",
      "In short: {should} things the application should do.",
    ],
    digestRows: [
      "The title is below: open the row to read the detail or propose a change.",
      "The titles are below: open a row to read the detail or propose a change.",
    ],
    openAll: "Open every detail",
    closeAll: "Close every detail",
    mustGroup: "Must do",
    shouldGroup: "Should do",
    askedBy: "Asked by",
    twinsHypothesis: "(simulated twins: a hypothesis)",
    verification: "Check",
    noVerification: "No acceptance criterion",
    edit: "Propose a change",
    editIntro: "Your change becomes a proposal: you review it before it is applied.",
    saveRevision: "Review changes",
    cancel: "Cancel",
    titleLabel: "Title",
    statementLabel: "Description",
    kindLabel: "Kind",
    priorityLabel: "Priority",
    functional: "Feature",
    quality: "Quality",
    constraint: "Constraint",
    must: "Essential",
    should: "Important",
    could: "Optional",
    later: "For later",
    invalidEdit: "Enter a title and a description before proposing the change.",
    criterionLabel: "How we check it",
    riskLabel: "Risk",
    doneLabel: "When it is finished",
    mitigation: "Remedy",
    onlyIf: "Only if {condition}.",
    checksTitle: "Acceptance criteria, risks and completion conditions ({count})",
    checksPurpose: "They serve whoever writes the code and the automatic checks of `ut test`.",
    storiesTitle: "Stories and usage scenarios",
    benefit: "Why",
    trigger: "Starts when",
    outcome: "Expected result",
    criteriaTitle: [
      "One requirement has no way to be checked yet",
      "{count} requirements have no way to be checked yet",
    ],
    storiesMissingTitle: [
      "One requirement is not linked to a story yet",
      "{count} requirements are not linked to a story yet",
    ],
    criteriaDetail: ["{codes} has no acceptance criterion", "{codes} have no acceptance criterion"],
    storiesDetail: ["{codes} is not linked to a story", "{codes} are not linked to a story"],
    numbers: [
      "Zero",
      "One",
      "Two",
      "Three",
      "Four",
      "Five",
      "Six",
      "Seven",
      "Eight",
      "Nine",
      "Ten",
    ],
    pendingTitle: ["A change is waiting for your decision", "Changes waiting for your decision"],
    before: "Before",
    after: "After",
    operations: { ADD: "Added", REPLACE: "Changed", REMOVE: "Removed" },
    diffReason: "Why you discard it (needed to discard it)",
    approveDiff: "Apply the change",
    rejectDiff: "Discard it",
    applyVersion: "Apply the new version",
    discardVersion: "Discard",
    yourRequest: "Your request",
    rewriting: "I am writing the requirements again with your request.",
    revisionPending:
      "A new version is already waiting for your decision: apply it or discard it before you ask for another change.",
    unchanged:
      "The analyst found nothing to change with this request. Try to describe the change in another way.",
    reasonRequired: "A reason is required to reject or to discard.",
    approveGate: "Approve the definition",
    barDefault:
      "When you approve, the designer prepares the design alternatives and the twins try them.",
    barDefaultSections:
      "When you approve, the sections that follow are updated with one gesture, without losing their content.",
    barApproved:
      "You approved this definition. You can still ask for a change in words: the new version comes back here for your approval.",
    barPending:
      "A proposed change is waiting above: if you approve now, it stays out of this version.",
    barGaps: [
      "One requirement has no way to be checked yet: if you approve now, it stays unchecked.",
      "{count} requirements have no way to be checked yet: if you approve now, they stay unchecked.",
    ],
    barRewriting:
      "The analyst is writing the requirements again: when the new version arrives, you decide whether to apply it.",
    barWaiting: "The new version is waiting above: apply it, then approve the definition here.",
    barRevision:
      "To approve, you need a new version: ask the analyst for one or propose the change on a requirement.",
    submitFailed:
      "The requirements could not be brought to your approval, so nothing was approved. Try again in a moment.",
    approveFailed:
      "The requirements are ready for your approval, but the approval did not go through. Press “Approve the definition” again.",
    requestFailed:
      "Your request for changes could not be recorded. Your note is still there: try again in a moment.",
    requestPlaceholder:
      "Write what is wrong: the request is recorded with your note. Then you can propose the change on the requirements.",
    changePlaceholder:
      "Write what to change: the analyst writes the requirements again and you decide whether to apply the new version.",
    moreActions: "Other choices on the approval",
    reason: "Reason (needed to reject)",
    rejectGate: "Reject the requirements",
    pause: "Pause the approval",
    cancelGate: "Cancel the approval",
    pausedText: "The approval of this definition is paused.",
    resume: "Resume the approval",
    revisionTitle: "You asked for changes",
    rejectedTitle: "You rejected these requirements",
    cancelledTitle: "You cancelled the approval",
    closedText:
      "To change them, propose the change on each requirement: the new version comes back here for your approval.",
    yourNote: "Your note",
    ready: "Definition approved by you. Next: Design & Evaluation.",
    version: "Version",
    statusPending: "waiting for your decision",
    statusApproved: "approved",
    statusPaused: "paused",
    statusRevision: "changes requested",
    statusRejected: "rejected",
    statusCancelled: "approval cancelled",
    contentHash: "Content hash",
    basedOn: "Based on version",
    created: "Created",
    approval: "Approval",
    decisionCounter: "Decision no. {n}",
    brief: "Brief",
    team: "Perspectives",
    twins: "User Twins",
    catalog: "Requirements catalogue",
    none: "None",
    methodology:
      "Gate 4 approves the exact specification ID, version, and content hash. A later version requires a new approval.",
    sources: "Sources of each requirement",
    sourcesLabel: "Sources",
    twinsLabel: "User Twins",
    history: "Changes already decided",
    applied: "Applied",
    discarded: "Discarded",
    openInText: "{code} · {title}: read it in the text",
    loadError: "The Definition could not be loaded.",
  },
  it: {
    loading: "Carico la definizione…",
    updating: "Aggiorno la definizione…",
    generating: "L'analista delle esigenze sta scrivendo la definizione…",
    generate: "Prepara la definizione",
    analyst: "Analista delle esigenze",
    noSpecification:
      "Sono pronto a trasformare il tuo brief e i tuoi twin in requisiti: cosa deve fare l'app, per chi e come lo verificheremo.",
    prerequisite: "Approva prima i profili dei tuoi utenti: poi si possono preparare i requisiti.",
    preparedBy: "Preparati dall'Analista delle esigenze",
    requirementCount: ["requisito", "requisiti"],
    storyCount: ["storia", "storie"],
    criterionCount: ["criterio di verifica", "criteri di verifica"],
    scenarioCount: ["scenario d'uso", "scenari d'uso"],
    needCount: ["bisogno", "bisogni"],
    functionalGroup: "Requisiti funzionali",
    nonFunctional: "Requisiti non funzionali",
    constraints: "Vincoli",
    viewLabel: "Vista della definizione",
    digestBoth: [
      "In breve: {must} cosa che l'applicazione deve fare e {should} che dovrebbe fare.",
      "In breve: {must} cose che l'applicazione deve fare e {should} che dovrebbe fare.",
    ],
    digestMust: [
      "In breve: {must} cosa che l'applicazione deve fare.",
      "In breve: {must} cose che l'applicazione deve fare.",
    ],
    digestShould: [
      "In breve: {should} cosa che l'applicazione dovrebbe fare.",
      "In breve: {should} cose che l'applicazione dovrebbe fare.",
    ],
    digestRows: [
      "Qui sotto trovi il titolo: apri la riga per leggere il dettaglio o proporre una modifica.",
      "Qui sotto trovi i titoli: apri una riga per leggere il dettaglio o proporre una modifica.",
    ],
    openAll: "Apri tutti i dettagli",
    closeAll: "Chiudi tutti i dettagli",
    mustGroup: "Deve fare",
    shouldGroup: "Dovrebbe fare",
    askedBy: "Chiesto da",
    twinsHypothesis: "(twin simulati: un'ipotesi)",
    verification: "Verifica",
    noVerification: "Senza criterio di verifica",
    edit: "Proponi modifica",
    editIntro: "La modifica diventa una proposta: la controlli prima che venga applicata.",
    saveRevision: "Controlla le modifiche",
    cancel: "Annulla",
    titleLabel: "Titolo",
    statementLabel: "Descrizione",
    kindLabel: "Tipo",
    priorityLabel: "Priorità",
    functional: "Funzionalità",
    quality: "Qualità",
    constraint: "Vincolo",
    must: "Essenziale",
    should: "Importante",
    could: "Facoltativo",
    later: "Per il futuro",
    invalidEdit: "Inserisci un titolo e una descrizione prima di proporre la modifica.",
    criterionLabel: "Come lo verifichiamo",
    riskLabel: "Rischio",
    doneLabel: "Quando è finito",
    mitigation: "Rimedio",
    onlyIf: "Solo se {condition}.",
    checksTitle: "Criteri di verifica, rischi e condizioni di fine lavoro ({count})",
    checksPurpose: "Servono a chi scrive il codice e ai controlli automatici di `ut test`.",
    storiesTitle: "Storie e scenari d'uso",
    benefit: "Perché",
    trigger: "Inizia quando",
    outcome: "Risultato atteso",
    criteriaTitle: [
      "Un requisito non ha ancora un modo per essere verificato",
      "{count} requisiti non hanno ancora un modo per essere verificati",
    ],
    storiesMissingTitle: [
      "Un requisito non è ancora legato a una storia",
      "{count} requisiti non sono ancora legati a una storia",
    ],
    criteriaDetail: [
      "{codes} è senza criterio di verifica",
      "{codes} sono senza criterio di verifica",
    ],
    storiesDetail: ["{codes} non è legato a una storia", "{codes} non sono legati a una storia"],
    numbers: [
      "Zero",
      "Un",
      "Due",
      "Tre",
      "Quattro",
      "Cinque",
      "Sei",
      "Sette",
      "Otto",
      "Nove",
      "Dieci",
    ],
    pendingTitle: [
      "Una modifica aspetta la tua decisione",
      "Modifiche che aspettano la tua decisione",
    ],
    before: "Prima",
    after: "Dopo",
    operations: { ADD: "Aggiunto", REPLACE: "Modificato", REMOVE: "Rimosso" },
    diffReason: "Perché la scarti (serve per scartarla)",
    approveDiff: "Applica la modifica",
    rejectDiff: "Scartala",
    applyVersion: "Applica la nuova versione",
    discardVersion: "Scarta",
    yourRequest: "La tua richiesta",
    rewriting: "Sto riscrivendo i requisiti con la tua richiesta.",
    revisionPending:
      "C'è già una nuova versione da decidere: applicala o scartala prima di chiedere un'altra modifica.",
    unchanged:
      "L'analista non ha trovato nulla da cambiare con questa richiesta. Prova a descrivere la modifica in un altro modo.",
    reasonRequired: "Per respingere o scartare serve una motivazione.",
    approveGate: "Approva la definizione",
    barDefault: "Approvando, il designer prepara le alternative di design e i twin le provano.",
    barDefaultSections:
      "Approvando, le sezioni che seguono si aggiornano con un gesto, senza perdere i contenuti.",
    barApproved:
      "Hai approvato questa definizione. Puoi ancora chiedere una modifica a parole: la nuova versione torna qui per la tua approvazione.",
    barPending:
      "Una modifica proposta aspetta qui sopra: se approvi ora, resta fuori da questa versione.",
    barGaps: [
      "Un requisito non ha ancora un modo per essere verificato: se approvi ora, resta senza verifica.",
      "{count} requisiti non hanno ancora un modo per essere verificati: se approvi ora, restano senza verifica.",
    ],
    barRewriting:
      "L'analista sta riscrivendo i requisiti: quando arriva la nuova versione, decidi tu se applicarla.",
    barWaiting: "La nuova versione aspetta qui sopra: applicala, poi approva qui la definizione.",
    barRevision:
      "Per approvare serve una nuova versione: chiedila all'analista o proponi la modifica su un requisito.",
    submitFailed:
      "Non è stato possibile portare i requisiti alla tua approvazione: non è stato approvato nulla. Riprova tra poco.",
    approveFailed:
      "I requisiti sono pronti per la tua approvazione, ma l'approvazione non è andata a buon fine. Premi di nuovo «Approva la definizione».",
    requestFailed:
      "Non è stato possibile registrare la tua richiesta di modifiche. La nota è ancora lì: riprova tra poco.",
    requestPlaceholder:
      "Scrivi che cosa non va: la richiesta viene registrata con la tua nota. Poi potrai proporre la modifica sui requisiti.",
    changePlaceholder:
      "Scrivi che cosa cambiare: l'analista riscrive i requisiti e decidi tu se applicare la nuova versione.",
    moreActions: "Altre scelte sull'approvazione",
    reason: "Motivazione (serve per respingere)",
    rejectGate: "Respingi i requisiti",
    pause: "Metti in pausa",
    cancelGate: "Annulla l'approvazione",
    pausedText: "L'approvazione di questa definizione è in pausa.",
    resume: "Riprendi l'approvazione",
    revisionTitle: "Hai chiesto modifiche",
    rejectedTitle: "Hai respinto questi requisiti",
    cancelledTitle: "Hai annullato l'approvazione",
    closedText:
      "Per cambiarli, proponi la modifica sul requisito: la nuova versione torna qui per la tua approvazione.",
    yourNote: "La tua nota",
    ready: "Definizione approvata da te. Ora Design e valutazione.",
    version: "Versione",
    statusPending: "in attesa della tua decisione",
    statusApproved: "approvata",
    statusPaused: "in pausa",
    statusRevision: "modifiche richieste",
    statusRejected: "respinta",
    statusCancelled: "approvazione annullata",
    contentHash: "Hash del contenuto",
    basedOn: "Basata sulla versione",
    created: "Creata il",
    approval: "Approvazione",
    decisionCounter: "Decisione n. {n}",
    brief: "Brief",
    team: "Prospettive",
    twins: "User Twin",
    catalog: "Catalogo dei requisiti",
    none: "Nessuno",
    methodology:
      "Gate 4 approva ID, versione e hash esatti della specifica. Una versione successiva richiede una nuova approvazione.",
    sources: "Fonti di ogni requisito",
    sourcesLabel: "Fonti",
    twinsLabel: "User Twin",
    history: "Modifiche già decise",
    applied: "Applicata",
    discarded: "Scartata",
    openInText: "{code} · {title}: leggilo nel testo",
    loadError: "Non è stato possibile caricare la Definizione.",
  },
} as const;

const copy = computed(() => messages[props.locale]);
const api = computed(() => props.api ?? requirementsApi);
const current = computed(() => store.current);
const specification = computed<RequirementsSpecificationPayload | null>(
  () => store.current?.specification ?? null,
);
const requirements = computed(() => specification.value?.requirements ?? []);
const stories = computed(() => specification.value?.user_stories ?? []);

const criteriaByRequirement = computed(() => {
  const codes = new Map<string, string[]>();

  for (const criterion of specification.value?.acceptance_criteria ?? []) {
    for (const requirementId of criterion.requirement_ids) {
      codes.set(requirementId, [...(codes.get(requirementId) ?? []), criterion.code]);
    }
  }

  return codes;
});
const storyRequirementIds = computed(
  () => new Set(stories.value.flatMap((story) => story.requirement_ids)),
);
const withoutCriteria = computed(() =>
  requirements.value
    .filter((requirement) => !criteriaByRequirement.value.has(requirement.id))
    .map((requirement) => requirement.code),
);
const withoutStories = computed(() =>
  requirements.value
    .filter((requirement) => !storyRequirementIds.value.has(requirement.id))
    .map((requirement) => requirement.code),
);
const requirementGroups = computed(() =>
  [
    {
      key: "functional",
      title: copy.value.functionalGroup,
      items: requirements.value.filter((item) => item.kind === "FUNCTIONAL"),
    },
    {
      key: "non-functional",
      title: copy.value.nonFunctional,
      items: requirements.value.filter((item) => item.kind === "NON_FUNCTIONAL"),
    },
    {
      key: "constraints",
      title: copy.value.constraints,
      items: requirements.value.filter((item) => item.kind === "CONSTRAINT"),
    },
  ].filter((group) => group.items.length > 0),
);

const summaryLine = computed(() => {
  const value = specification.value;

  if (value === null) {
    return "";
  }

  const text = copy.value;
  const counts = [
    counted(value.scenarios.length, text.scenarioCount),
    counted((value.needs ?? []).length, text.needCount),
    counted(value.user_stories.length, text.storyCount),
    counted(value.requirements.length, text.requirementCount),
    counted(value.acceptance_criteria.length, text.criterionCount),
  ];

  return `${text.preparedBy} · ${counts.join(", ")}`;
});

const digest = computed(() => {
  const total = requirements.value.length;

  if (total === 0) {
    return null;
  }

  const text = copy.value;
  const must = requirements.value.filter((item) => item.priority === "MUST").length;
  const should = total - must;
  const lead =
    should === 0
      ? formOf(must, text.digestMust)
      : must === 0
        ? formOf(should, text.digestShould)
        : formOf(must, text.digestBoth);

  return `${fill(lead, { must, should })} ${formOf(total, text.digestRows)}`;
});

const allRequirementsOpen = computed(
  () =>
    requirements.value.length > 0 &&
    requirements.value.every((requirement) => openRequirementIds.value.has(requirement.id)),
);

const coverageNotice = computed(() => {
  const missingCriteria = withoutCriteria.value;
  const missingStories = withoutStories.value;

  if (missingCriteria.length === 0 && missingStories.length === 0) {
    return null;
  }

  const text = copy.value;
  const title =
    missingCriteria.length > 0
      ? countSentence(missingCriteria.length, text.criteriaTitle)
      : countSentence(missingStories.length, text.storiesMissingTitle);
  const details = [
    missingCriteria.length > 0 ? codesSentence(missingCriteria, text.criteriaDetail) : null,
    missingStories.length > 0 ? codesSentence(missingStories, text.storiesDetail) : null,
  ].filter((sentence): sentence is string => sentence !== null);

  return { title, detail: `${details.join("; ")}.` };
});

const checkCards = computed<CheckCard[]>(() => {
  const value = specification.value;

  if (value === null) {
    return [];
  }

  const text = copy.value;

  return [
    ...value.acceptance_criteria.map((item) => ({
      code: item.code,
      label: text.criterionLabel,
      text: item.statement,
      note: null,
    })),
    ...value.risks.map((item) => ({
      code: item.code,
      label: text.riskLabel,
      text: item.summary,
      note: `${text.mitigation}: ${item.mitigation}`,
    })),
    ...value.definition_of_done.map((item) => ({
      code: item.code,
      label: text.doneLabel,
      text: item.statement,
      note:
        item.applicability === "CONDITIONAL" && (item.condition?.trim() ?? "").length > 0
          ? text.onlyIf.replace("{condition}", () => item.condition?.trim() ?? "")
          : null,
    })),
  ];
});
const checkCodes = computed(() => new Set(checkCards.value.map((card) => card.code)));
const checksTitle = computed(() =>
  fill(copy.value.checksTitle, { count: checkCards.value.length }),
);

const diagramLinks = computed<DiagramLink[]>(() => {
  const value = specification.value;

  if (value === null) {
    return [];
  }

  const link = (code: string, title: string): DiagramLink => ({
    code,
    label: copy.value.openInText
      .replace("{code}", () => code)
      .replace("{title}", () => shortened(title)),
  });

  return [
    ...(value.needs ?? []).map((item) => link(item.code, item.title)),
    ...value.requirements.map((item) => link(item.code, item.title)),
    ...value.user_stories.map((item) => link(item.code, item.goal)),
    ...value.acceptance_criteria.map((item) => link(item.code, item.statement)),
    ...value.scenarios.map((item) => link(item.code, item.title)),
    ...value.risks.map((item) => link(item.code, item.summary)),
    ...value.definition_of_done.map((item) => link(item.code, item.statement)),
  ];
});

const diffs = computed(() => store.diffHistory);
const pendingDiffs = computed(() => diffs.value.filter((diff) => diff.status === "PROPOSED"));
const decidedDiffs = computed(() => diffs.value.filter((diff) => diff.status !== "PROPOSED"));
const gateTargetsCurrent = computed(() => {
  if (store.gate === null || store.current === null) {
    return false;
  }

  return (
    store.gate.artifact.artifact_id === store.current.id &&
    store.gate.artifact.version === store.current.version_number &&
    store.gate.artifact.content_hash === store.current.content_hash
  );
});
const canSubmitGate = computed(() => {
  if (store.current === null) {
    return false;
  }

  if (store.gate === null || !gateTargetsCurrent.value) {
    return true;
  }

  return store.gate.status === "DRAFT" || store.gate.status === "STALE";
});
const gatePending = computed(
  () => gateTargetsCurrent.value && store.gate?.status === "PENDING_APPROVAL",
);
const gatePaused = computed(() => gateTargetsCurrent.value && store.gate?.status === "PAUSED");
const gateStatus = computed<HumanGateStatus | null>(() =>
  gateTargetsCurrent.value ? (store.gate?.status ?? null) : null,
);
const decisionState = computed<DecisionState>(() => {
  if (store.current === null) {
    return "none";
  }

  if (store.isReadyForDesign) {
    return "approved";
  }

  if (canSubmitGate.value || gatePending.value) {
    return "approve";
  }

  if (gatePaused.value) {
    return "paused";
  }

  const status = gateStatus.value;

  if (status === "REVISION_REQUESTED" || status === "PAUSED_NEEDS_HUMAN") {
    return "revision";
  }

  return status === "REJECTED" || status === "CANCELLED" ? "closed" : "none";
});
const closedTitle = computed(() => {
  if (decisionState.value === "revision") {
    return copy.value.revisionTitle;
  }

  return gateStatus.value === "REJECTED" ? copy.value.rejectedTitle : copy.value.cancelledTitle;
});
const closedNote = computed(() => {
  const kind = decisionState.value === "revision" ? "REQUEST_REVISION" : "REJECT";
  const gateId = store.gate?.id;

  return (
    store.gateEvents
      .filter((event) => event.gate_id === gateId && event.kind === kind)
      .at(-1)
      ?.reason?.trim() ?? ""
  );
});
const lastRequest = computed(() => {
  if (decisionState.value !== "revision") {
    return null;
  }

  const gateId = store.gate?.id;

  return (
    store.gateEvents
      .filter((event) => event.gate_id === gateId && event.kind === "REQUEST_REVISION")
      .at(-1) ?? null
  );
});
const changeRequestText = computed(() => {
  if (changeText.value !== null) {
    return changeText.value;
  }

  const note = lastRequest.value?.reason?.trim() ?? "";
  return note.length === 0 ? null : note;
});
const pendingItems = computed(() =>
  pendingDiffs.value.map((diff) => ({ diff, request: requestOf(diff) })),
);
const approvedChanges = computed(() => props.sectionsMode && decisionState.value === "approved");
const barVisible = computed(
  () =>
    decisionState.value === "approve" ||
    ((decisionState.value === "revision" || approvedChanges.value) && !changeUnavailable.value),
);
const closedVisible = computed(
  () =>
    decisionState.value === "closed" ||
    (decisionState.value === "revision" && !changeRunning.value && pendingDiffs.value.length === 0),
);
const barDescription = computed(() => {
  const text = copy.value;

  if (changeRunning.value) {
    return text.barRewriting;
  }

  if (decisionState.value === "revision") {
    return pendingDiffs.value.length > 0 ? text.barWaiting : text.barRevision;
  }

  if (decisionState.value === "approved") {
    return pendingDiffs.value.length > 0 ? text.barWaiting : text.barApproved;
  }

  if (pendingDiffs.value.length > 0) {
    return text.barPending;
  }

  const missing = withoutCriteria.value.length;

  if (missing > 0) {
    return countSentence(missing, text.barGaps);
  }

  return props.sectionsMode ? text.barDefaultSections : text.barDefault;
});
const decisionCounter = computed(() =>
  copy.value.decisionCounter.replace("{n}", String(store.gate?.iteration ?? 1)),
);
const statusSummary = computed(() => {
  const text = copy.value;

  switch (decisionState.value) {
    case "approved":
      return text.statusApproved;
    case "paused":
      return text.statusPaused;
    case "revision":
      return text.statusRevision;
    case "closed":
      return gateStatus.value === "REJECTED" ? text.statusRejected : text.statusCancelled;
    default:
      return text.statusPending;
  }
});
const technicalSummary = computed(
  () => `${copy.value.version} ${current.value?.version_number ?? ""} · ${statusSummary.value}`,
);
const technicalRows = computed(() => {
  const version = current.value;
  const value = specification.value;

  if (version === null || value === null) {
    return [];
  }

  const text = copy.value;
  const gate = store.gate;

  return [
    { label: text.contentHash, value: version.content_hash },
    {
      label: text.basedOn,
      value:
        version.based_on_version_number === null
          ? text.none
          : String(version.based_on_version_number),
    },
    { label: text.created, value: formatDate(version.created_at) },
    {
      label: text.approval,
      value:
        gate === null
          ? workflowStatusLabel(null, props.locale)
          : `${workflowStatusLabel(gate.status, props.locale)} · ${decisionCounter.value}`,
    },
    { label: text.brief, value: `v${value.project_brief_reference.version_number}` },
    { label: text.team, value: `v${value.agent_team_reference.version_number}` },
    { label: text.twins, value: `v${value.user_modeling_reference.version_number}` },
    { label: text.catalog, value: `v${value.catalog_version}` },
  ];
});
const errorMessage = computed(() => {
  if (localError.value !== null) {
    return localError.value;
  }

  const error = store.error;

  if (error === null || isGenerationInterrupted(error.code)) {
    return null;
  }

  return modelFeedback(error.code, props.locale) ?? error.message ?? copy.value.loadError;
});

function counted(count: number, [singular, plural]: readonly [string, string]): string {
  return `${count} ${count === 1 ? singular : plural}`;
}

function formOf(count: number, [one, many]: readonly [string, string]): string {
  return count === 1 ? one : many;
}

function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_match, key: string) => String(values[key] ?? ""));
}

function commandParts(text: string): { key: number; text: string; command: boolean }[] {
  return text
    .split("`")
    .map((part, index) => ({ key: index, text: part, command: index % 2 === 1 }))
    .filter((part) => part.text.length > 0);
}

function countSentence(count: number, [one, many]: readonly [string, string]): string {
  return count === 1
    ? one
    : many.replace("{count}", () => copy.value.numbers[count] ?? String(count));
}

function codesSentence(codes: readonly string[], [one, many]: readonly [string, string]): string {
  const list = new Intl.ListFormat(props.locale, { type: "conjunction" }).format(codes);
  return (codes.length === 1 ? one : many).replace("{codes}", () => list);
}

function shortened(text: string): string {
  const value = text.trim().replace(/\s+/g, " ");
  return value.length <= LINK_LABEL_LENGTH
    ? value
    : `${value.slice(0, LINK_LABEL_LENGTH - 1).trimEnd()}…`;
}

function formatDate(value: string): string {
  const date = new Date(value);

  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat(props.locale, { dateStyle: "medium", timeStyle: "short" }).format(
        date,
      );
}

function twinNames(requirement: RequirementPayload): string[] {
  return [...new Set(requirement.user_twin_references.map((twin) => twin.name))];
}

function criteriaOf(requirement: RequirementPayload): readonly string[] {
  return criteriaByRequirement.value.get(requirement.id) ?? [];
}

function tabIdOf(target: ArtifactView): string | undefined {
  return viewSwitch.value?.tabId(target);
}

function itemClass(code: string): string {
  return highlighted.value === code ? "bg-petrol-on-night/12 ring-1 ring-petrol-on-night/60" : "";
}

function detailIdOf(requirement: RequirementPayload): string {
  return `requirement-detail-${requirement.id}`;
}

function isRequirementOpen(requirement: RequirementPayload): boolean {
  return openRequirementIds.value.has(requirement.id);
}

function openRequirements(ids: readonly string[]): void {
  const closed = ids.filter((id) => !openRequirementIds.value.has(id));

  if (closed.length > 0) {
    openRequirementIds.value = new Set([...openRequirementIds.value, ...closed]);
  }
}

function toggleRequirement(requirement: RequirementPayload): void {
  const next = new Set(openRequirementIds.value);

  if (!next.delete(requirement.id)) {
    next.add(requirement.id);
  }

  openRequirementIds.value = next;
}

function toggleAllRequirements(): void {
  openRequirementIds.value = allRequirementsOpen.value
    ? new Set()
    : new Set(requirements.value.map((requirement) => requirement.id));
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
    localError.value =
      modelFeedback(store.error?.code, props.locale) ??
      (error instanceof Error
        ? (modelFeedback(error.message, props.locale) ?? error.message)
        : copy.value.loadError);
    return false;
  }
}

async function load(): Promise<void> {
  if (props.projectId.trim().length === 0) {
    return;
  }

  await run(() => store.load(props.projectId, authorizedRequest, api.value));
}

function changed(): void {
  emit("sections-changed");
}

async function reloadAndTell(): Promise<void> {
  await load();
  changed();
}

async function generate(): Promise<void> {
  if (!props.prerequisiteReady || store.isBusy || requirementsJob.value !== null) return;
  dismissRequirementsJob();
  const generated = await run(() => store.generate(props.projectId, authorizedRequest, api.value));
  if (generated) {
    changed();
  } else if (isGenerationInterrupted(store.error?.code)) {
    localError.value = null;
  }
}

const {
  job: requirementsJob,
  failure: requirementsJobFailure,
  dismiss: dismissRequirementsJob,
} = useGenerationResume({
  projectId: () => props.projectId,
  operations: ["REQUIREMENTS_PROPOSAL", CHANGE_OPERATION],
  authorize: authorizedRequest,
  onSettled: reloadAndTell,
});

const proposalJob = computed(() =>
  requirementsJob.value?.operation === CHANGE_OPERATION ? null : requirementsJob.value,
);
const proposalFailure = computed(() =>
  requirementsJobFailure.value?.operation === CHANGE_OPERATION
    ? null
    : requirementsJobFailure.value,
);
const changeJob = computed(() =>
  requirementsJob.value?.operation === CHANGE_OPERATION ? requirementsJob.value : null,
);
const changeRunning = computed(() => store.pending["request-change"] || changeJob.value !== null);
const shownChangeFailure = computed(
  () =>
    changeFailure.value ??
    (requirementsJobFailure.value?.operation === CHANGE_OPERATION
      ? requirementsJobFailure.value
      : null),
);
const changeSentence = computed(() => {
  const code = shownChangeFailure.value?.code;

  if (code === REVISION_PENDING) {
    return copy.value.revisionPending;
  }

  return code === UNCHANGED ? copy.value.unchanged : null;
});
const analystVoice = computed(() => ({
  role: copy.value.analyst,
  avatar: ANALYST_AVATAR,
  message: copy.value.rewriting,
}));

function requestOf(diff: RequirementsSpecificationDiffPayload): string | null {
  const known = store.changeRequests[diff.id];

  if (known !== undefined) {
    return known;
  }

  const event = lastRequest.value;
  const note = event?.reason?.trim() ?? "";

  if (
    event === null ||
    note.length === 0 ||
    diff.base_version_id !== store.current?.id ||
    Date.parse(diff.created_at) < Date.parse(event.occurred_at)
  ) {
    return null;
  }

  return note;
}

function dismissChangeFailure(): void {
  changeFailure.value = null;

  if (requirementsJobFailure.value?.operation === CHANGE_OPERATION) {
    dismissRequirementsJob();
  }
}

async function revealChange(): Promise<void> {
  await nextTick();
  changeSection.value?.scrollIntoView?.({
    block: "start",
    behavior: prefersReducedMotion() ? "auto" : "smooth",
  });
}

function startEdit(requirement: RequirementPayload): void {
  editingRequirementId.value = requirement.id;
  edit.title = requirement.title;
  edit.statement = requirement.statement;
  edit.kind = requirement.kind;
  edit.priority = requirement.priority;
}

function cancelEdit(): void {
  editingRequirementId.value = null;
  edit.title = "";
  edit.statement = "";
  edit.kind = "FUNCTIONAL";
  edit.priority = "MUST";
}

function proposedSpecification(): RequirementsSpecificationPayload | null {
  const value = specification.value;
  const requirementId = editingRequirementId.value;

  if (
    value === null ||
    requirementId === null ||
    edit.title.trim().length === 0 ||
    edit.statement.trim().length === 0
  ) {
    return null;
  }

  return {
    ...value,
    requirements: value.requirements.map((requirement: RequirementPayload): RequirementPayload =>
      requirement.id === requirementId
        ? {
            ...requirement,
            title: edit.title.trim().replace(/\s+/g, " "),
            statement: edit.statement.trim().replace(/\s+/g, " "),
            kind: edit.kind,
            priority: edit.priority,
          }
        : requirement,
    ),
  };
}

async function submitRevision(): Promise<void> {
  const proposed = proposedSpecification();

  if (proposed === null) {
    localError.value = copy.value.invalidEdit;
    return;
  }

  const applied = await run(() =>
    store.proposeRevision(props.projectId, proposed, authorizedRequest, api.value),
  );

  if (applied) {
    cancelEdit();
    changed();
  }
}

function formatRequirementSources(requirement: RequirementPayload): string {
  const sources = requirement.sources
    .map((source: RequirementSourcePayload) => source.locator ?? source.source_id)
    .join(", ");

  return sources.length === 0 ? copy.value.none : sources;
}

function needLinks(requirement: RequirementPayload) {
  return (specification.value?.needs ?? []).filter((need) =>
    requirement.need_ids?.includes(need.id),
  );
}

function formatRequirementTwins(requirement: RequirementPayload): string {
  if (requirement.user_twin_references.length === 0) {
    return copy.value.none;
  }

  return requirement.user_twin_references
    .map((twin: UserTwinVersionReferencePayload) => `${twin.name} v${twin.version_number}`)
    .join(", ");
}

function diffReason(diffId: string): string {
  return diffReasons[diffId] ?? "";
}

async function decideDiff(
  diff: RequirementsSpecificationDiffPayload,
  decision: "APPROVE" | "REJECT",
): Promise<void> {
  const reason = diffReason(diff.id).trim();

  if (decision === "REJECT" && reason.length === 0) {
    localError.value = copy.value.reasonRequired;
    return;
  }

  const decided = await run(() =>
    store.decideRevision(
      props.projectId,
      diff.id,
      decision,
      authorizedRequest,
      reason.length === 0 ? null : reason,
      api.value,
    ),
  );

  if (decided) {
    changeFailure.value = null;
    changed();
  }
}

async function submitGate(): Promise<boolean> {
  const submitted = await run(() =>
    store.submitGate(props.projectId, authorizedRequest, api.value),
  );

  if (!submitted || (!gatePending.value && !store.isReadyForDesign)) {
    localError.value = copy.value.submitFailed;
    return false;
  }

  return true;
}

async function decideGate(action: RequirementsGateDecisionAction): Promise<boolean> {
  const reason = gateReason.value.trim();

  if ((action === "REJECT" || action === "REQUEST_REVISION") && reason.length === 0) {
    localError.value = copy.value.reasonRequired;
    return false;
  }

  const decided = await run(() =>
    store.decideGate(
      props.projectId,
      action,
      authorizedRequest,
      reason.length === 0 ? null : reason,
      api.value,
    ),
  );

  if (decided) {
    changed();
  }

  return decided;
}

async function approve(): Promise<void> {
  if (deciding.value || store.isBusy || changeRunning.value) {
    return;
  }

  deciding.value = true;

  try {
    if (canSubmitGate.value && !(await submitGate())) {
      return;
    }

    if (gatePending.value) {
      const approved = await decideGate("APPROVE");

      if (!approved || !store.isReadyForDesign) {
        localError.value = copy.value.approveFailed;
      }
    }
  } finally {
    deciding.value = false;
  }
}

async function recordRequest(reason: string): Promise<boolean> {
  if (canSubmitGate.value && !(await submitGate())) {
    return false;
  }

  if (!gatePending.value) {
    return false;
  }

  const requested = await run(() =>
    store.decideGate(props.projectId, "REQUEST_REVISION", authorizedRequest, reason, api.value),
  );

  if (requested) {
    changed();
  } else {
    localError.value = copy.value.requestFailed;
  }

  return requested;
}

async function askForChange(request: string): Promise<void> {
  const projectId = props.projectId;
  changeText.value = request;
  const asked = store.requestChange(projectId, request, authorizedRequest, api.value);
  void revealChange();

  try {
    await asked;
    await decisionBar.value?.completeRequest();
    changed();
  } catch (error) {
    if (props.projectId !== projectId) {
      return;
    }

    store.clearError();
    const code = error instanceof RequirementsApiError ? error.code : null;

    if (error instanceof RequirementsApiError && error.status === 404 && code === null) {
      changeUnavailable.value = true;
      await decisionBar.value?.completeRequest();
      return;
    }

    changeFailure.value = {
      operation: CHANGE_OPERATION,
      code: code ?? GENERATION_FAILED,
      lost: isGenerationLost(code),
    };

    if (code === REVISION_PENDING || code === CONTEXT_CHANGED) {
      void load();
    }

    void revealChange();
  } finally {
    changeText.value = null;
  }
}

async function requestChanges(note: string): Promise<void> {
  const request = note.trim();

  if (request.length === 0 || deciding.value || store.isBusy || changeRunning.value) {
    return;
  }

  localError.value = null;
  dismissChangeFailure();

  if (pendingDiffs.value.length > 0) {
    changeFailure.value = { operation: CHANGE_OPERATION, code: REVISION_PENDING, lost: false };
    void revealChange();
    return;
  }

  deciding.value = true;

  try {
    if (decisionState.value === "approve") {
      if (!(await recordRequest(request))) {
        return;
      }
    } else if (decisionState.value !== "revision" && !approvedChanges.value) {
      return;
    }

    if (changeUnavailable.value) {
      await decisionBar.value?.completeRequest();
      return;
    }

    await askForChange(request);
  } finally {
    deciding.value = false;
  }
}

function envelopeSummary(envelope: RequirementsArtifactEnvelope | null): string {
  if (envelope === null) {
    return copy.value.none;
  }

  switch (envelope.kind) {
    case "NEED":
      return envelope.need?.statement ?? copy.value.none;
    case "REQUIREMENT":
      return envelope.requirement?.statement ?? copy.value.none;
    case "USER_STORY":
      return envelope.user_story?.goal ?? copy.value.none;
    case "ACCEPTANCE_CRITERION":
      return envelope.acceptance_criterion?.statement ?? copy.value.none;
    case "SCENARIO":
      return envelope.scenario?.expected_outcome ?? copy.value.none;
    case "RISK":
      return envelope.risk?.summary ?? copy.value.none;
    case "DEFINITION_OF_DONE":
      return envelope.definition_of_done?.statement ?? copy.value.none;
  }
}

function operationLabel(operation: RequirementsDiffOperationKind): string {
  return copy.value.operations[operation];
}

function diffStatusLabel(status: RequirementsSpecificationDiffPayload["status"]): string {
  return status === "APPROVED" ? copy.value.applied : copy.value.discarded;
}

function onChecksToggle(event: Event): void {
  if (event.target instanceof HTMLDetailsElement) {
    checksOpen.value = event.target.open;
  }
}

function prefersReducedMotion(): boolean {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

async function openItem(code: string): Promise<void> {
  view.value = "text";

  definitionView.value?.openItem(code);

  if (checkCodes.value.has(code)) {
    checksOpen.value = true;
  }

  const requirement = requirements.value.find((item) => item.code === code);

  if (requirement !== undefined) {
    openRequirements([requirement.id]);
  }

  await nextTick();
  definitionView.value?.openItem(code);
  await nextTick();
  const target = [
    ...(root.value?.querySelectorAll<HTMLElement>("[data-requirements-item]") ?? []),
  ].find((element) => element.dataset.requirementsItem === code);

  if (target === undefined) {
    return;
  }

  highlighted.value = code;
  clearTimeout(highlightTimer);
  highlightTimer = setTimeout(() => {
    if (highlighted.value === code) {
      highlighted.value = null;
    }
  }, HIGHLIGHT_DURATION);
  target.scrollIntoView?.({
    block: "center",
    behavior: prefersReducedMotion() ? "auto" : "smooth",
  });
  target.focus({ preventScroll: true });
}

function rendered(element: Element): boolean {
  return typeof element.checkVisibility !== "function" || element.checkVisibility();
}

function refreshBarTarget(): void {
  const element = root.value;
  const visible = element !== null && element.isConnected && rendered(element);
  const target = document.getElementById(BAR_TARGET);
  const row = document.getElementById(ROW_TARGET);
  const next = visible && target !== null && rendered(target) ? target : null;
  const nextRow = visible && row !== null && rendered(row) ? row : null;

  if (barTarget.value !== next) {
    barTarget.value = next;
  }
  if (rowTarget.value !== nextRow) {
    rowTarget.value = nextRow;
  }
}

async function refreshAfterRender(): Promise<void> {
  await nextTick();
  refreshBarTarget();
}

watch(
  () => [props.projectId, props.autoLoad] as const,
  ([projectId, autoLoad]) => {
    if (autoLoad && projectId.trim().length > 0) {
      void load();
    }
  },
  {
    immediate: true,
  },
);

watchUpstream(
  () => props.upstream,
  (changed) => {
    if (!changed) return;
    upstreamReloads.value += 1;
    if (props.autoLoad) void load();
  },
);

watch(
  pendingDiffs,
  (pending, previous) => {
    const known = new Set((previous ?? []).map((diff) => diff.id));

    openRequirements(
      pending
        .filter((diff) => !known.has(diff.id))
        .flatMap((diff) => diff.operations)
        .filter((operation) => operation.artifact_kind === "REQUIREMENT")
        .map((operation) => operation.artifact_id),
    );
  },
  { immediate: true },
);

onMounted(() => {
  refreshBarTarget();
  void refreshAfterRender();

  if (typeof ResizeObserver === "undefined" || root.value === null) {
    return;
  }

  visibility = new ResizeObserver(refreshBarTarget);
  visibility.observe(root.value);
});

onUpdated(refreshBarTarget);

watch(() => props.active, refreshAfterRender);

onBeforeUnmount(() => {
  visibility?.disconnect();
  clearTimeout(highlightTimer);
});
</script>

<template>
  <section
    ref="root"
    class="grid gap-6 text-on-night"
    data-testid="requirements-flow"
    :aria-busy="store.isBusy ? 'true' : undefined"
  >
    <UiStateBlock
      v-if="errorMessage !== null"
      kind="error"
      :title="errorMessage"
      data-testid="requirements-error"
    />

    <RequirementsTwinAlignment
      v-if="current !== null"
      :project-id="projectId"
      :locale="locale"
      :refresh-key="`${current.content_hash}:${store.pendingDiffs.length}:${upstreamReloads}`"
      :authorize="authorize"
      @realigned="reloadAndTell"
    />

    <UiStateBlock
      v-if="current === null && store.pending.load"
      kind="loading"
      :title="copy.loading"
    />

    <section
      v-else-if="current === null"
      class="grid gap-5 rounded-tile border border-night-line bg-night-raised p-5 sm:p-7"
      data-testid="requirements-empty"
    >
      <UiAgentMessage :role-label="copy.analyst" :avatar="ANALYST_AVATAR">
        {{ copy.noSpecification }}
      </UiAgentMessage>
      <p v-if="!prerequisiteReady" class="m-0 text-sm text-on-night-3" role="status">
        {{ copy.prerequisite }}
      </p>
      <GenerationJobNotice
        v-if="proposalJob !== null || proposalFailure !== null"
        :job="proposalJob"
        :failure="proposalFailure"
        :locale="locale"
        @dismiss="dismissRequirementsJob"
      />
      <UiStateBlock
        v-else-if="store.pending.generate"
        kind="loading"
        :title="copy.generating"
        :text="generationProgress(locale)"
      />
      <UiButton
        variant="pill"
        size="lg"
        class="justify-self-start"
        :disabled="store.isBusy || !prerequisiteReady || requirementsJob !== null"
        data-testid="generate-requirements"
        @click="generate"
      >
        {{ copy.generate }}
      </UiButton>
    </section>

    <template v-else-if="specification !== null">
      <div class="flex flex-wrap items-center gap-x-4 gap-y-3" data-testid="requirements-toolbar">
        <ArtifactViewSwitch
          ref="viewSwitch"
          v-model="view"
          :locale="locale"
          :label="copy.viewLabel"
          :panel-id="viewPanelId"
        />
        <p class="m-0 text-sm leading-normal text-on-night-3" data-testid="requirements-summary">
          {{ summaryLine }}
        </p>
      </div>

      <div
        v-if="coverageNotice !== null"
        class="rounded-panel border border-warn-on-night/40 bg-warn-on-night/10 py-4 pr-4 pl-5"
        data-testid="requirements-coverage-notice"
      >
        <p class="m-0 text-[15px] font-semibold text-warn-on-night">{{ coverageNotice.title }}</p>
        <p class="m-0 mt-0.5 text-sm leading-normal text-warn-on-night">
          {{ coverageNotice.detail }}
        </p>
      </div>

      <section
        v-if="changeRunning || shownChangeFailure !== null"
        ref="changeSection"
        class="grid scroll-mt-6 gap-3"
        data-testid="requirements-change"
      >
        <template v-if="changeRunning">
          <GenerationJobNotice
            v-if="changeJob !== null"
            :job="changeJob"
            :locale="locale"
            :agent="analystVoice"
          >
            <template v-if="changeRequestText !== null" #default>
              <div class="grid gap-1" data-testid="requirements-change-request">
                <p class="m-0 text-xs font-semibold text-on-night-3">{{ copy.yourRequest }}</p>
                <blockquote :class="['text-[15px]', QUOTE_CLASS]">
                  {{ changeRequestText }}
                </blockquote>
              </div>
            </template>
          </GenerationJobNotice>
          <div v-else data-testid="requirements-change-waiting">
            <UiAgentMessage :role-label="copy.analyst" :avatar="ANALYST_AVATAR">
              <p role="status" class="m-0 font-semibold text-on-night">{{ copy.rewriting }}</p>
              <div
                v-if="changeRequestText !== null"
                class="mt-3 grid gap-1"
                data-testid="requirements-change-request"
              >
                <p class="m-0 text-xs font-semibold text-on-night-3">{{ copy.yourRequest }}</p>
                <blockquote :class="['text-[15px]', QUOTE_CLASS]">
                  {{ changeRequestText }}
                </blockquote>
              </div>
            </UiAgentMessage>
          </div>
        </template>
        <UiStateBlock
          v-else-if="changeSentence !== null"
          kind="error"
          :title="changeSentence"
          data-testid="requirements-change-failure"
          :data-code="shownChangeFailure?.code"
        />
        <GenerationJobNotice
          v-else
          :job="null"
          :failure="shownChangeFailure"
          :locale="locale"
          @dismiss="dismissChangeFailure"
        />
      </section>

      <section
        v-if="pendingDiffs.length > 0"
        class="grid gap-3"
        aria-labelledby="requirements-pending-title"
        data-testid="requirements-pending-changes"
      >
        <h2 id="requirements-pending-title" class="m-0 text-lg font-semibold">
          {{ pendingDiffs.length === 1 ? copy.pendingTitle[0] : copy.pendingTitle[1] }}
        </h2>
        <article
          v-for="{ diff, request } in pendingItems"
          :key="diff.id"
          class="grid gap-4 rounded-tile border border-night-line-strong bg-night-raised p-5"
          data-testid="requirements-pending-change"
          :data-origin="request === null ? 'edit' : 'request'"
        >
          <div v-if="request !== null" class="grid gap-1" data-testid="requirements-change-request">
            <p class="m-0 text-xs font-semibold text-on-night-3">{{ copy.yourRequest }}</p>
            <blockquote :class="['text-[15px]', QUOTE_CLASS]">{{ request }}</blockquote>
          </div>
          <div
            v-for="operation in diff.operations"
            :key="`${operation.artifact_kind}:${operation.artifact_id}`"
            class="grid gap-4 sm:grid-cols-2"
          >
            <div class="min-w-0">
              <p class="m-0 font-mono text-[11px] tracking-[0.06em] text-on-night-3 uppercase">
                {{ copy.before }} · {{ operation.display_code }}
              </p>
              <p class="m-0 mt-1.5 text-sm leading-normal text-on-night-2">
                {{ envelopeSummary(operation.before) }}
              </p>
            </div>
            <div class="min-w-0">
              <p
                class="m-0 font-mono text-[11px] tracking-[0.06em] text-petrol-on-night-2 uppercase"
              >
                {{ copy.after }} · {{ operationLabel(operation.operation) }}
              </p>
              <p class="m-0 mt-1.5 text-sm leading-normal">
                {{ envelopeSummary(operation.after) }}
              </p>
            </div>
          </div>
          <label class="grid gap-1.5 text-sm font-medium text-on-night-2">
            {{ copy.diffReason }}
            <textarea
              v-model="diffReasons[diff.id]"
              rows="2"
              class="min-h-11 rounded-field border border-night-line-strong bg-night-panel px-3 py-2.5 text-[15px] font-normal text-on-night [color-scheme:dark]"
            />
          </label>
          <div class="flex flex-wrap gap-3">
            <UiButton
              :variant="request === null ? 'outline' : 'pill'"
              data-testid="approve-requirements-diff"
              :disabled="store.isBusy"
              @click="decideDiff(diff, 'APPROVE')"
            >
              {{ request === null ? copy.approveDiff : copy.applyVersion }}
            </UiButton>
            <UiButton
              variant="quiet"
              :disabled="store.isBusy || diffReason(diff.id).trim().length === 0"
              data-testid="reject-requirements-diff"
              @click="decideDiff(diff, 'REJECT')"
            >
              {{ request === null ? copy.rejectDiff : copy.discardVersion }}
            </UiButton>
          </div>
        </article>
      </section>

      <RequirementsTableView
        v-if="view === 'table'"
        :id="viewPanelId"
        role="tabpanel"
        :aria-labelledby="tabIdOf('table')"
        :specification="specification"
        :locale="locale"
        data-testid="requirements-table-view"
      />
      <ProjectDiagramsView
        v-else-if="view === 'diagram'"
        :id="viewPanelId"
        role="tabpanel"
        :aria-labelledby="tabIdOf('diagram')"
        :project-id="projectId"
        stage="requirements"
        :locale="locale"
        :refresh-key="current.content_hash"
        :authorize="authorize"
        :links="diagramLinks"
        data-testid="requirements-diagram-view"
        @select-node="openItem"
      />

      <div
        v-show="view === 'text'"
        :id="view === 'text' ? viewPanelId : undefined"
        :role="view === 'text' ? 'tabpanel' : undefined"
        :aria-labelledby="view === 'text' ? tabIdOf('text') : undefined"
        class="grid gap-4"
        data-testid="requirements-text-view"
      >
        <div
          v-if="digest !== null"
          class="flex flex-wrap items-center justify-between gap-x-6 gap-y-3"
        >
          <p
            class="m-0 min-w-0 flex-[1_1_320px] text-[15px] leading-normal text-on-night-2"
            data-testid="requirements-digest"
          >
            {{ digest }}
          </p>
          <UiButton
            v-if="requirements.length > 1"
            variant="outline"
            class="shrink-0"
            :aria-expanded="allRequirementsOpen ? 'true' : 'false'"
            data-testid="requirements-toggle-all"
            @click="toggleAllRequirements"
          >
            {{ allRequirementsOpen ? copy.closeAll : copy.openAll }}
          </UiButton>
        </div>

        <RequirementsDefinitionView
          ref="definitionView"
          :highlighted="highlighted"
          :specification="specification"
          :locale="locale"
          @select-item="openItem"
        />

        <section
          class="rounded-tile border border-night-line bg-night-raised px-5 pt-2 pb-2 sm:px-6"
          data-testid="requirements-groups"
        >
          <template v-for="(group, index) in requirementGroups" :key="group.key">
            <h2 :class="['m-0 mb-1 text-lg font-semibold', index === 0 ? 'mt-4' : 'mt-5']">
              {{ group.title }}
            </h2>
            <ul class="m-0 list-none p-0">
              <li
                v-for="requirement in group.items"
                :key="requirement.id"
                :class="[
                  '-mx-3 rounded-field border-b border-on-night/8 transition-colors duration-500 last:border-b-0',
                  itemClass(requirement.code),
                ]"
                :data-requirements-item="requirement.code"
                tabindex="-1"
                data-testid="requirement-row"
              >
                <button
                  type="button"
                  class="flex min-h-12 w-full cursor-pointer items-start gap-3 rounded-field px-3 py-3 text-left transition-colors duration-150 hover:bg-night-hover"
                  :aria-expanded="isRequirementOpen(requirement) ? 'true' : 'false'"
                  :aria-controls="detailIdOf(requirement)"
                  data-testid="requirement-toggle"
                  @click="toggleRequirement(requirement)"
                >
                  <span
                    :class="[
                      'inline-block w-3 shrink-0 text-xs leading-6 text-on-night-3 transition-transform duration-150',
                      isRequirementOpen(requirement) ? 'rotate-90' : '',
                    ]"
                    aria-hidden="true"
                    >▸</span
                  >
                  <span class="min-w-0 flex-1 text-base font-semibold">{{
                    requirement.title
                  }}</span>
                </button>
                <div
                  v-show="isRequirementOpen(requirement)"
                  :id="detailIdOf(requirement)"
                  class="grid gap-4 pr-3 pb-4 pl-9 sm:pl-32"
                  data-testid="requirement-detail"
                >
                  <div class="min-w-0">
                    <p class="m-0 text-[15px] leading-normal">{{ requirement.statement }}</p>
                    <p
                      v-if="needLinks(requirement).length > 0"
                      class="m-0 mt-2 text-sm leading-normal"
                    >
                      <strong>{{ locale === "it" ? "Bisogni" : "Needs" }}:</strong>{{ " " }}
                      <template v-for="(need, index) in needLinks(requirement)" :key="need.id">
                        <span v-if="index > 0"> · </span>
                        <button
                          type="button"
                          class="cursor-pointer underline"
                          @click="openItem(need.code)"
                        >
                          {{ need.title }}
                        </button>
                      </template>
                    </p>
                    <p
                      v-if="requirement.sources.length > 0"
                      class="m-0 mt-2 text-sm leading-normal"
                    >
                      {{ copy.sourcesLabel }}: {{ formatRequirementSources(requirement) }}
                    </p>
                    <div
                      class="mt-2.5 flex flex-wrap items-center gap-2 text-[13px] text-on-night-3"
                      data-testid="requirement-meta"
                    >
                      <template v-if="twinNames(requirement).length > 0">
                        <span>{{ copy.askedBy }}</span>
                        <span
                          v-for="name in twinNames(requirement)"
                          :key="name"
                          :title="name"
                          class="inline-flex min-h-6 items-center rounded-pill border border-dashed border-violet-on-night px-2 text-xs font-medium whitespace-nowrap text-violet-on-night-2"
                          data-testid="requirement-twin"
                          >{{ name }}</span
                        >
                        <span class="sr-only">{{ copy.twinsHypothesis }}</span>
                        <span aria-hidden="true">·</span>
                      </template>
                      <span v-if="criteriaOf(requirement).length > 0">
                        {{ copy.verification }}: {{ criteriaOf(requirement).join(", ") }}
                      </span>
                      <span v-else class="font-medium text-warn-on-night">
                        {{ copy.noVerification }}
                      </span>
                    </div>
                  </div>
                  <form
                    v-if="editingRequirementId === requirement.id"
                    class="grid gap-4 rounded-field border border-night-line-strong bg-night-panel p-4"
                    data-testid="requirement-edit-form"
                    @submit.prevent="submitRevision"
                  >
                    <p class="m-0 text-sm leading-normal text-on-night-2">{{ copy.editIntro }}</p>
                    <label class="grid gap-1.5 text-sm font-medium text-on-night-2">
                      {{ copy.titleLabel }}
                      <input
                        v-model="edit.title"
                        class="min-h-11 rounded-field border border-night-line-strong bg-night-raised px-3 py-2 text-[15px] font-normal text-on-night"
                      />
                    </label>
                    <label class="grid gap-1.5 text-sm font-medium text-on-night-2">
                      {{ copy.statementLabel }}
                      <textarea
                        v-model="edit.statement"
                        rows="3"
                        class="min-h-11 rounded-field border border-night-line-strong bg-night-raised px-3 py-2.5 text-[15px] font-normal text-on-night"
                        data-testid="requirement-statement"
                      />
                    </label>
                    <div class="grid gap-3 sm:grid-cols-2">
                      <label class="grid gap-1.5 text-sm font-medium text-on-night-2">
                        {{ copy.kindLabel }}
                        <select
                          v-model="edit.kind"
                          class="min-h-11 rounded-field border border-night-line-strong bg-night-raised px-3 text-[15px] font-normal text-on-night [color-scheme:dark]"
                        >
                          <option value="FUNCTIONAL">{{ copy.functional }}</option>
                          <option value="NON_FUNCTIONAL">{{ copy.quality }}</option>
                          <option value="CONSTRAINT">{{ copy.constraint }}</option>
                        </select>
                      </label>
                      <label class="grid gap-1.5 text-sm font-medium text-on-night-2">
                        {{ copy.priorityLabel }}
                        <select
                          v-model="edit.priority"
                          class="min-h-11 rounded-field border border-night-line-strong bg-night-raised px-3 text-[15px] font-normal text-on-night [color-scheme:dark]"
                        >
                          <option value="MUST">{{ copy.must }}</option>
                          <option value="SHOULD">{{ copy.should }}</option>
                          <option value="COULD">{{ copy.could }}</option>
                          <option value="WONT_FOR_NOW">{{ copy.later }}</option>
                        </select>
                      </label>
                    </div>
                    <div class="flex flex-wrap gap-3">
                      <UiButton
                        type="submit"
                        :disabled="store.isBusy"
                        data-testid="submit-requirements-revision"
                      >
                        {{ copy.saveRevision }}
                      </UiButton>
                      <UiButton variant="quiet" @click="cancelEdit">{{ copy.cancel }}</UiButton>
                    </div>
                  </form>
                  <UiButton
                    v-else
                    variant="outline"
                    class="justify-self-start"
                    data-testid="edit-requirement"
                    @click="startEdit(requirement)"
                  >
                    {{ copy.edit }}
                  </UiButton>
                </div>
              </li>
            </ul>
          </template>
        </section>

        <details
          v-if="checkCards.length > 0"
          class="group rounded-tile border border-night-line bg-night-raised"
          :open="checksOpen"
          data-testid="requirements-checks"
          @toggle="onChecksToggle"
        >
          <summary
            class="flex min-h-12 cursor-pointer list-none flex-wrap items-center gap-x-3 gap-y-0.5 px-5 py-3 [&::-webkit-details-marker]:hidden"
          >
            <span
              class="inline-block text-xs text-on-night-3 group-open:rotate-90"
              aria-hidden="true"
              >▸</span
            >
            <span class="text-[15px] font-semibold">{{ checksTitle }}</span>
          </summary>
          <div class="grid gap-3 border-t border-night-line px-5 py-4">
            <p
              class="m-0 text-sm leading-normal text-on-night-2"
              data-testid="requirements-checks-purpose"
            >
              <template v-for="part in commandParts(copy.checksPurpose)" :key="part.key">
                <code
                  v-if="part.command"
                  class="rounded-[4px] bg-on-night/8 px-1 font-mono text-[13px] text-on-night"
                  >{{ part.text }}</code
                >
                <template v-else>{{ part.text }}</template>
              </template>
            </p>
            <div class="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-3">
              <div
                v-for="card in checkCards"
                :key="card.code"
                :class="[
                  'rounded-panel border border-night-line bg-night-raised p-[18px] transition-colors duration-500',
                  itemClass(card.code),
                ]"
                :data-requirements-item="card.code"
                tabindex="-1"
                data-testid="requirements-check"
              >
                <p class="m-0 font-mono text-[11px] tracking-[0.06em] text-on-night-3 uppercase">
                  {{ card.label }} · {{ card.code }}
                </p>
                <p class="m-0 mt-2 text-sm leading-normal">{{ card.text }}</p>
                <p
                  v-if="card.note !== null"
                  class="m-0 mt-1.5 text-sm leading-normal text-on-night-2"
                >
                  {{ card.note }}
                </p>
              </div>
            </div>
          </div>
        </details>
      </div>

      <p
        v-if="decisionState === 'approved'"
        class="m-0 flex items-center gap-2.5 text-[15px] font-semibold text-petrol-on-night-2"
        data-testid="requirements-readiness"
      >
        <span
          class="inline-block h-2 w-2 shrink-0 rounded-full bg-petrol-on-night"
          aria-hidden="true"
        />
        {{ copy.ready }}
      </p>

      <div
        v-if="decisionState === 'paused'"
        class="flex flex-wrap items-center gap-3 rounded-panel border border-night-line-strong bg-night-raised px-5 py-4"
        data-testid="requirements-gate-paused"
      >
        <p class="m-0 min-w-0 flex-[1_1_260px] text-[15px]">{{ copy.pausedText }}</p>
        <UiButton variant="outline" :disabled="store.isBusy" @click="decideGate('CANCEL')">
          {{ copy.cancelGate }}
        </UiButton>
        <UiButton
          variant="pill"
          :disabled="store.isBusy"
          data-testid="resume-requirements-gate"
          @click="decideGate('RESUME')"
        >
          {{ copy.resume }}
        </UiButton>
      </div>

      <div
        v-if="closedVisible"
        class="grid gap-2 rounded-panel border border-night-line-strong bg-night-raised px-5 py-4"
        data-testid="requirements-gate-closed"
      >
        <p class="m-0 text-[15px] font-semibold">{{ closedTitle }}</p>
        <div v-if="closedNote.length > 0" class="grid gap-1" data-testid="requirements-gate-note">
          <p class="m-0 text-xs font-semibold text-on-night-3">{{ copy.yourNote }}</p>
          <blockquote :class="['text-sm', QUOTE_CLASS]">{{ closedNote }}</blockquote>
        </div>
        <p class="m-0 text-sm leading-normal text-on-night-3">{{ copy.closedText }}</p>
      </div>

      <details
        v-if="gatePending"
        class="rounded-panel border border-night-line"
        data-testid="requirements-more-actions"
      >
        <summary
          class="flex min-h-11 cursor-pointer items-center px-5 text-sm font-semibold text-on-night-2"
        >
          {{ copy.moreActions }}
        </summary>
        <div class="grid gap-3 border-t border-night-line px-5 py-4">
          <label class="grid gap-1.5 text-sm font-medium text-on-night-2">
            {{ copy.reason }}
            <textarea
              v-model="gateReason"
              rows="2"
              class="min-h-11 rounded-field border border-night-line-strong bg-night-panel px-3 py-2.5 text-[15px] font-normal text-on-night"
            />
          </label>
          <div class="flex flex-wrap gap-3">
            <UiButton
              variant="danger"
              :disabled="store.isBusy || gateReason.trim().length === 0"
              @click="decideGate('REJECT')"
            >
              {{ copy.rejectGate }}
            </UiButton>
            <UiButton variant="quiet" :disabled="store.isBusy" @click="decideGate('PAUSE')">
              {{ copy.pause }}
            </UiButton>
            <UiButton variant="quiet" :disabled="store.isBusy" @click="decideGate('CANCEL')">
              {{ copy.cancelGate }}
            </UiButton>
          </div>
        </div>
      </details>

      <Teleport :to="barTarget" :disabled="barTarget === null">
        <UiDecisionBar
          v-if="barVisible"
          ref="decisionBar"
          :primary-label="copy.approveGate"
          :description="barDescription"
          :request-placeholder="
            changeUnavailable ? copy.requestPlaceholder : copy.changePlaceholder
          "
          :busy="store.isBusy || deciding || changeRunning"
          :disabled="decisionState !== 'approve'"
          @primary="approve"
          @request="requestChanges"
        />
      </Teleport>

      <Teleport :to="rowTarget" :disabled="rowTarget === null">
        <UiTechnicalDetails :summary="technicalSummary" :rows="technicalRows">
          <p class="m-0 text-[13px] leading-normal text-on-night-3">{{ copy.methodology }}</p>
          <section class="grid gap-2">
            <h2 class="m-0 text-sm font-semibold">
              {{ copy.sources }}
            </h2>
            <dl class="m-0 grid gap-2 text-[13px]">
              <div
                v-for="requirement in requirements"
                :key="requirement.id"
                class="grid gap-x-4 gap-y-0.5 sm:grid-cols-[76px_minmax(0,1fr)]"
              >
                <dt class="font-mono text-xs text-on-night">{{ requirement.code }}</dt>
                <dd class="m-0 leading-normal break-words text-on-night-2">
                  {{ copy.sourcesLabel }}: {{ formatRequirementSources(requirement) }} ·
                  {{ copy.twinsLabel }}: {{ formatRequirementTwins(requirement) }}
                </dd>
              </div>
            </dl>
          </section>
          <section v-if="decidedDiffs.length > 0" class="grid gap-2">
            <h2 class="m-0 text-sm font-semibold">
              {{ copy.history }}
            </h2>
            <ul class="m-0 grid list-none gap-2 p-0 text-[13px] text-on-night-2">
              <li
                v-for="diff in decidedDiffs"
                :key="diff.id"
                class="grid gap-0.5"
                data-testid="requirements-decided-change"
              >
                <span>
                  <strong class="font-semibold text-on-night">{{
                    diffStatusLabel(diff.status)
                  }}</strong>
                  · {{ diff.operations.map((operation) => operation.display_code).join(", ") }}
                </span>
                <template v-if="diff.decision_reason">
                  <span class="text-xs font-semibold text-on-night-3">{{ copy.yourNote }}</span>
                  <blockquote
                    :class="['text-[13px]', QUOTE_CLASS]"
                    data-testid="requirements-decided-note"
                  >
                    {{ diff.decision_reason }}
                  </blockquote>
                </template>
                <span class="font-mono text-xs break-all text-on-night-3">{{ diff.id }}</span>
              </li>
            </ul>
          </section>
          <RequirementsVersionComparison :versions="store.history" :locale="locale" />
          <RequirementsTraceabilityView
            v-if="store.traceability !== null && store.coverage !== null"
            :traceability="store.traceability"
            :coverage="store.coverage"
            :locale="locale"
          />
        </UiTechnicalDetails>
      </Teleport>
    </template>

    <p class="sr-only" role="status">
      {{
        store.isBusy && !store.pending.generate && !changeRunning && current !== null
          ? copy.updating
          : ""
      }}
    </p>
  </section>
</template>
