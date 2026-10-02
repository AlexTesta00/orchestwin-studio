<script lang="ts">
import type { DesignChangePayload, DesignPackagePayload } from "../types/design";

export type ChangeLocale = "en" | "it";

type Sentence = readonly [string, string];

const CHANGE_SENTENCES: Readonly<Record<string, Sentence>> = {
  "ALTERNATIVE:ADD": ["A new alternative: {alternative}", "Una nuova alternativa: {alternative}"],
  "ALTERNATIVE:REPLACE": [
    "The alternative {alternative} changes",
    "Cambia l'alternativa {alternative}",
  ],
  "ALTERNATIVE:REMOVE": [
    "The alternative {alternative} is removed",
    "Viene tolta l'alternativa {alternative}",
  ],
  "CRITIQUE:ADD": [
    "A new opinion of {twin} on {alternative}",
    "Un nuovo parere di {twin} su {alternative}",
  ],
  "CRITIQUE:REPLACE": [
    "The opinion of {twin} on {alternative} changes",
    "Cambia il parere di {twin} su {alternative}",
  ],
  "CRITIQUE:REMOVE": [
    "The opinion of {twin} on {alternative} is removed",
    "Viene tolto il parere di {twin} su {alternative}",
  ],
  "CRITIQUE_VERDICT:ADD": [
    "{twin} gives a verdict on {alternative}",
    "{twin} dà un giudizio su {alternative}",
  ],
  "CRITIQUE_VERDICT:REPLACE": [
    "The verdict of {twin} on {alternative} changes",
    "Cambia il giudizio di {twin} su {alternative}",
  ],
  "CRITIQUE_VERDICT:REMOVE": [
    "The verdict of {twin} on {alternative} is removed",
    "Viene tolto il giudizio di {twin} su {alternative}",
  ],
  "CONCERN:ADD": ["A new point of attention: {concern}", "Un nuovo punto di attenzione: {concern}"],
  "CONCERN:REPLACE": [
    "The point of attention “{concern}” changes",
    "Cambia il punto di attenzione «{concern}»",
  ],
  "CONCERN:REMOVE": [
    "The point of attention “{concern}” is removed",
    "Viene tolto il punto di attenzione «{concern}»",
  ],
  "PROTOTYPE:ADD": [
    "The mockup of the chosen design is added",
    "Si aggiunge il mockup del design scelto",
  ],
  "PROTOTYPE:REPLACE": [
    "The mockup of the chosen design changes",
    "Cambia il mockup del design scelto",
  ],
  "PROTOTYPE:REMOVE": [
    "The mockup of the chosen design is removed",
    "Si toglie il mockup del design scelto",
  ],
  "SELECTION:ADD": ["You choose {alternative}", "Scegli {alternative}"],
  "SELECTION:REPLACE": ["You choose {alternative}", "Scegli {alternative}"],
  "SELECTION:REMOVE": ["No alternative stays chosen", "Nessuna alternativa resta scelta"],
  "SELECTION:RECOMMENDATION": [
    "The designer now recommends {alternative}",
    "Il designer ora consiglia {alternative}",
  ],
  "OPEN_QUESTIONS:*": ["The open questions change", "Cambiano le domande aperte"],
  "GENERATED_MOCKUP:ADD": [
    "The mockup drawn by the model for {alternative} enters the design",
    "Entra nel design il mockup disegnato dal modello per {alternative}",
  ],
  "GENERATED_MOCKUP:REPLACE": [
    "The mockup drawn for {alternative} changes",
    "Cambia il mockup disegnato per {alternative}",
  ],
  "GENERATED_MOCKUP:REMOVE": [
    "The mockup drawn for {alternative} leaves the design",
    "Esce dal design il mockup disegnato per {alternative}",
  ],
  "GENERATED_SCREEN:ADD": ["A new screen: “{screen}”", "Una nuova schermata: «{screen}»"],
  "GENERATED_SCREEN:REPLACE": ["The screen “{screen}” changes", "Cambia la schermata «{screen}»"],
  "GENERATED_SCREEN:REMOVE": [
    "The screen “{screen}” is removed",
    "Viene tolta la schermata «{screen}»",
  ],
  "GENERATED_STYLES:*": [
    "The colours and styles of the mockup change",
    "Cambiano colori e stili del mockup",
  ],
  "OWNER_ASSERTION:ADD": ["A new rule", "Una nuova regola"],
  "OWNER_ASSERTION:REPLACE": ["A rule changes", "Cambia una regola"],
  "OWNER_ASSERTION:REMOVE": ["A rule is removed", "Viene tolta una regola"],
  "OWNER_ASSERTION_ORDER:*": ["The order of the rules changes", "Cambia l'ordine delle regole"],
};

const UNKNOWN_CHANGE: Sentence = ["Another change to the design", "Un'altra modifica al design"];

const FALLBACKS = {
  alternative: ["an alternative", "un'alternativa"],
  twin: ["a twin", "un twin"],
  concern: ["a point of attention", "un punto di attenzione"],
  screen: ["a screen", "una schermata"],
} as const;

function textOf(record: Record<string, unknown> | null, key: string): string | null {
  const value = record?.[key];
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : null;
}

function selectionKey(change: DesignChangePayload): string {
  const owner = "owner_selected_alternative_id";
  if (change.kind === "REMOVE" || (change.after !== null && textOf(change.after, owner) === null)) {
    return "SELECTION:REMOVE";
  }
  if (
    change.before !== null &&
    change.after !== null &&
    textOf(change.before, owner) === textOf(change.after, owner)
  ) {
    return "SELECTION:RECOMMENDATION";
  }
  return `SELECTION:${change.kind}`;
}

function selectedAlternativeOf(change: DesignChangePayload): string | null {
  if (change.artifact_kind !== "SELECTION") {
    return null;
  }
  return selectionKey(change) === "SELECTION:RECOMMENDATION"
    ? textOf(change.after, "recommended_alternative_id")
    : textOf(change.after, "owner_selected_alternative_id");
}

export function designChangeSentence(
  change: DesignChangePayload,
  packages: readonly (DesignPackagePayload | null | undefined)[],
  locale: ChangeLocale,
): string {
  const index = locale === "it" ? 1 : 0;
  const known = packages.filter(
    (item): item is DesignPackagePayload => item !== null && item !== undefined,
  );
  const key =
    change.artifact_kind === "SELECTION"
      ? selectionKey(change)
      : `${change.artifact_kind}:${change.kind}`;
  const template =
    CHANGE_SENTENCES[key] ?? CHANGE_SENTENCES[`${change.artifact_kind}:*`] ?? UNKNOWN_CHANGE;
  const critique =
    change.artifact_kind === "CRITIQUE" || change.artifact_kind === "CRITIQUE_VERDICT"
      ? (known.flatMap((item) => item.critiques).find((item) => item.id === change.artifact_id) ??
        null)
      : null;
  const alternativeId =
    critique?.design_alternative_id ?? selectedAlternativeOf(change) ?? change.artifact_id;
  const alternative =
    known.flatMap((item) => item.alternatives).find((item) => item.id === alternativeId) ?? null;
  const concern =
    known.flatMap((item) => item.concerns).find((item) => item.id === change.artifact_id) ?? null;
  const values: Record<string, string> = {
    alternative:
      alternative === null
        ? FALLBACKS.alternative[index]
        : `${alternative.code} · ${alternative.title}`,
    twin: critique?.user_twin_reference.name ?? FALLBACKS.twin[index],
    concern:
      concern?.summary ??
      textOf(change.after, "summary") ??
      textOf(change.before, "summary") ??
      FALLBACKS.concern[index],
    screen:
      textOf(change.after, "title") ??
      textOf(change.before, "title") ??
      textOf(change.after, "code") ??
      textOf(change.before, "code") ??
      FALLBACKS.screen[index],
  };
  return template[index].replace(/\{(\w+)\}/g, (_match, key: string) => values[key] ?? "");
}

export function designChangeQuote(change: DesignChangePayload): string | null {
  return change.artifact_kind === "OWNER_ASSERTION"
    ? (textOf(change.after, "text") ?? textOf(change.before, "text"))
    : null;
}

const PLACE_CODE = /^(?:SCR|ELM)-\d+\b[\s:·-]*/;

export function readablePlace(location: string): string {
  return location
    .split("·")
    .map((part) => part.trim().replace(PLACE_CODE, "").trim())
    .filter((part) => part.length > 0)
    .join(" · ");
}
</script>

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
  useId,
  watch,
} from "vue";

import { apiClient } from "@/api/client";
import ArtifactViewSwitch, { type ArtifactView } from "./ArtifactViewSwitch.vue";
import DeclarativePrototypePreview from "./DeclarativePrototypePreview.vue";
import DesignAlternativeComparison, {
  type AlternativePreview,
  MOCKUP_READ_FAILURE,
} from "./DesignAlternativeComparison.vue";
import DesignIterationPanel, {
  generationFailureText,
  generationReasonText,
  generationRetryable,
  type IterationJob,
  type IterationSide,
} from "./DesignIterationPanel.vue";
import DesignLoopNextStep from "./DesignLoopNextStep.vue";
import DesignObservationList, {
  type ObservationCritique,
  type ObservationFinding,
  type ObservationInsightRequest,
  type ObservationTarget,
} from "./DesignObservationList.vue";
import DesignTableView from "./DesignTableView.vue";
import DesignTwinMatrix, {
  type TwinMatrixCell,
  type TwinMatrixSelection,
  type TwinMatrixSeverity,
} from "./DesignTwinMatrix.vue";
import GeneratedMockupDialog, { type MockupObservation } from "./GeneratedMockupDialog.vue";
import GenerationJobNotice from "./GenerationJobNotice.vue";
import ProjectDesignDiscussionPanel from "./ProjectDesignDiscussionPanel.vue";
import ProjectDesignEvaluationPanel from "./ProjectDesignEvaluationPanel.vue";
import ProjectDiagramsView from "./ProjectDiagramsView.vue";
import UiAgentMessage from "./UiAgentMessage.vue";
import UiButton from "./UiButton.vue";
import UiDecisionBar from "./UiDecisionBar.vue";
import UiStateBlock from "./UiStateBlock.vue";
import { surfaceKey, type SurfaceContext } from "./UiSurface.vue";
import UiTechnicalDetails from "./UiTechnicalDetails.vue";
import { generationProgress, modelFeedback } from "./modelFeedback";
import { elementNames, type ScreenName, type WorkflowName } from "./screenNames";
import { rosterAvatar, type TwinRoster } from "./twinIdentity";
import { type UpstreamValue, watchUpstream } from "./upstreamChange";
import { workflowStatusLabel } from "./workflowLabels";
import { designApi, type DesignApi } from "../api/design";
import type { DesignAlignmentApi } from "../api/designAlignment";
import { designIterationsApi, type DesignIterationsApi } from "../api/designIterations";
import { designLoopApi, DesignLoopApiError, type DesignLoopApi } from "../api/designLoop";
import { designMockupsApi, type DesignMockupsApi } from "../api/designMockups";
import { designReviewPinsApi, type DesignReviewPinsApi } from "../api/designReviewPins";
import { isGenerationInterrupted } from "../api/generationJobs";
import { modelUsageApi, type ModelUsageApi } from "../api/modelUsage";
import type { RequirementsApi } from "../api/requirements";
import { useAuthStore } from "../stores/auth";
import { type AuthorizedRequest, useDesignStore } from "../stores/design";
import { ITERATION_ASSERTION_LIMIT, useDesignIterationsStore } from "../stores/designIterations";
import { findingKey, runMode, useDesignLoopStore } from "../stores/designLoop";
import { errorStatusOf, useDesignMockupsStore } from "../stores/designMockups";
import { useGenerationResume } from "../stores/generationJobs";
import { useInsightTrayStore } from "../stores/insightTray";
import { useRequirementsStore } from "../stores/requirements";
import { useUserModelingStore } from "../stores/userModeling";
import type {
  DesignAlternativePayload,
  DesignGateDecisionAction,
  DesignGenerationPayload,
  DesignMockupPayload,
  DesignPackageDiffPayload,
  DesignPackageVersionPayload,
  DesignRevisionPayload,
  HumanGateStatus,
  PrototypeElementPayload,
  SyntheticDesignCritiquePayload,
  VersionedArtifactReferencePayload,
} from "../types/design";
import type {
  DesignEvaluationRunPayload,
  InsightApplicationPayload,
  InsightBriefField,
  SyntheticFindingPayload,
  SyntheticFindingSeverity,
} from "../types/designLoop";
import type {
  MockupDocumentPayload,
  MockupDocumentSource,
  MockupResultPayload,
  ModelUsagePayload,
} from "../types/designMockups";

type Locale = "en" | "it";
type DecisionState = "none" | "choose" | "approve" | "paused" | "revision" | "closed" | "approved";
type DialogSource = "latest" | "applied" | "review";

interface DialogState {
  alternativeId: string;
  source: DialogSource;
  revision: string | null;
  entryScreen: string | null;
  title: string;
}

interface DeclarativeEntry {
  status: "loading" | "ready" | "none" | "error";
  mockup: DesignMockupPayload | null;
}

interface ThumbnailWant {
  alternativeId: string;
  source: MockupDocumentSource;
  key: string;
}

const BAR_TARGET = "step-decision-bar";
const ROW_TARGET = "step-technical-row";
const DESIGNER_AVATAR = "/team/ux.webp";
const QUOTE_CLASS =
  "m-0 border-l-2 border-on-night/40 pl-3 leading-normal whitespace-pre-line text-on-night-2";
const ELEMENT_LABEL_LIMIT = 80;
const SEVERITY_RANK: Record<SyntheticFindingSeverity, number> = {
  critical: 4,
  major: 3,
  moderate: 2,
  minor: 1,
  observation: 0,
};
const CRITIQUE_LISTS = [
  "strengths",
  "concerns",
  "unmet_needs",
  "accessibility_observations",
  "trust_concerns",
  "questions",
  "suggested_changes",
] as const;
const NON_FUNCTIONAL_CRITERIA = new Set(["accessibility", "trust", "cognitive_load"]);
const REQUIREMENT_CODE = /\b[A-Z][A-Z0-9]*-\d+\b/g;
const REVIEWED_KINDS = new Set([
  "PROTOTYPE",
  "SELECTION",
  "GENERATED_MOCKUP",
  "GENERATED_SCREEN",
  "GENERATED_STYLES",
]);

const props = withDefaults(
  defineProps<{
    projectId: string;
    locale?: Locale;
    autoLoad?: boolean;
    prerequisiteReady?: boolean;
    authorize?: AuthorizedRequest;
    api?: DesignApi;
    loopApi?: DesignLoopApi;
    requirementsApi?: Pick<RequirementsApi, "readiness" | "submitGate" | "decideGate">;
    alignmentApi?: Pick<DesignAlignmentApi, "status">;
    mockupsApi?: DesignMockupsApi;
    iterationsApi?: DesignIterationsApi;
    pinsApi?: DesignReviewPinsApi;
    usageApi?: ModelUsageApi;
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

const messages = {
  en: {
    designer: "UX/UI designer",
    noPackage:
      "I am ready to propose a look for your app: I prepare the alternatives and have the twins try them.",
    prerequisite: "Approve the requirements first: then I can prepare the alternatives.",
    generate: "Prepare the design alternatives",
    generating: "The designer is preparing the alternatives…",
    loading: "Loading the design…",
    updating: "Updating the design…",
    introOne: "I prepared one alternative and had the twins try it. Their opinion is below.",
    introMany: "I prepared {n} alternatives and had the twins try them. Their opinion is below.",
    introChosen:
      "You chose {alternative}. Read what the twins think and approve the design when you are ready.",
    introIterate:
      "You chose {alternative}. If something should change, ask for changes: I draw a new version and you compare it with the current one.",
    numbers: ["no", "one", "two", "three", "four", "five", "six", "seven", "eight"],
    viewLabel: "Views of the design",
    loadError: "Design & Evaluation could not be loaded.",
    mockupRequired: "The mockup of this alternative is not ready yet: wait for it before choosing.",
    mockupRequiredDeclarative: "Try the mockup of this alternative first: then you can choose it.",
    pendingOther:
      "Another change is waiting for your decision above: apply it or discard it first.",
    proposeFailed: "Your choice could not be recorded, so nothing changed. Try again in a moment.",
    applyFailed:
      "Your choice is recorded but it was not applied yet. Press “Choose this one” again.",
    noChanges: "This design is already the current one.",
    iterationApplyFailed:
      "The new version is recorded but it was not applied yet. Press “Apply the new version” again.",
    iterationStale: "The design changed in the meantime: this version can no longer be applied.",
    iterationPending:
      "A new version is already waiting for your decision: apply it or discard it before asking for other changes.",
    ruleTooLong:
      "A rule can have at most 300 characters: shorten the request or do not keep it as a rule.",
    ruleFailed: "The rule could not be removed. Try again in a moment.",
    hintTry: "Try the mockup first: then you can choose it.",
    hintPendingOther: "Decide first on the change waiting above.",
    notCovered: "The mockup does not show these requirements yet: {list}.",
    previewTitle: "Mockup of {alternative}",
    previewDraft: "Model-generated draft · not applied",
    previewCurrent: "The mockup of the chosen design",
    previewHelp:
      "Explore the screens and controls. Example results illustrate the design; the application is built from the knowledge folder with your own tools.",
    previewMissing: "This alternative has no preview yet. Creating it takes a moment.",
    previewError: "The preview could not be loaded.",
    createMockup: "Create the preview",
    reloadPreview: "Try again",
    closePreview: "Close the preview",
    pendingTitle: ["A change is waiting for your decision", "Changes waiting for your decision"],
    applyDiff: "Apply the change",
    rejectDiff: "Discard it",
    diffReason: "Why you discard it (needed to discard it)",
    reasonRequired: "A reason is required to reject or to discard.",
    regenerateText:
      "Did you bring insights into the project? Regenerate the alternatives: the twins will review them again.",
    regenerate: "Regenerate the alternatives",
    regenerating: "The designer is regenerating the alternatives…",
    regenerationRejected: "The design could not be regenerated.",
    regenerationRequirements:
      "The requirements have changed and are waiting for your approval. Approve them again, then regenerate the design alternatives.",
    regenerationNoPackage:
      "There is no design to regenerate yet. Generate the design alternatives first.",
    concernsTitle: "Points of attention and open questions ({n})",
    concerns: "Points of attention",
    remedy: "Remedy",
    openQuestions: "Open questions",
    approveGate: "Approve the chosen design",
    askChanges: "Ask for changes",
    barChoose:
      "Choose one of the alternatives with “Choose this one”: then you approve the design here.",
    barApprove:
      "You approve {alternative}. The knowledge folder will contain this design and the opinion of the twins.",
    barApproved:
      "You approved this design. You can still ask for changes in words: the new version comes back here for your approval.",
    barApprovedDrawing:
      "The designer is drawing the new version you asked for: the approved design stays as it is until you apply it.",
    barApprovedWaiting: "The new version is waiting above: apply it, then approve it here.",
    barPending:
      "A proposed change is waiting above: if you approve now, it stays out of this version.",
    barIteration:
      "A new version is waiting above: if you approve now, you approve the current one.",
    barDrawing:
      "The designer is drawing the new version you asked for: you can wait for it or approve the current one.",
    barRevision:
      "You asked for changes: ask the designer for a new version, choose the other alternative or regenerate the alternatives.",
    barRequestIteration: "Until you apply the new version, the current design stays as it is.",
    barRequestRevision:
      "The current design does not change: your note stays in the history of the design.",
    iterationPlaceholder:
      "Write what to change: the designer draws a new version and you decide whether to apply it.",
    revisionPlaceholder:
      "Write what is wrong: the request is recorded with your note. For a different design, choose the other alternative or regenerate the alternatives.",
    keepRule: "Keep it as a rule for the next versions",
    keepRuleHint: "The designer will follow it every time it draws a new version.",
    submitFailed:
      "The design could not be brought to your approval, so nothing was approved. Try again in a moment.",
    approveFailed:
      "The design is ready for your approval, but the approval did not go through. Press “Approve the chosen design” again.",
    requestFailed:
      "Your request for changes could not be recorded. Your note is still there: try again in a moment.",
    moreActions: "Other choices on the approval",
    reason: "Reason (needed to reject or to ask for a revision)",
    rejectGate: "Reject the design",
    requestRevision: "Ask for a revision",
    pause: "Pause the approval",
    cancelGate: "Cancel the approval",
    pausedText: "The approval of this design is paused.",
    resume: "Resume the approval",
    revisionTitle: "You asked for changes",
    rejectedTitle: "You rejected this design",
    cancelledTitle: "You cancelled the approval",
    closedText:
      "To change it, choose the other alternative, ask for changes or regenerate the alternatives: the new version comes back here for your approval.",
    yourNote: "Your note",
    ready: "Design approved by you. Next: the Dossier.",
    reanchoredReview:
      "The design was re-anchored to the new Definition: you can ask the twins for a new evaluation.",
    matrixEmpty: "The twins have not given an opinion on these alternatives yet.",
    readObservations: "Read every observation of {twin} on {alternative} ({count})",
    closeObservations: "Close the observations",
    version: "Version",
    statusChoose: "waiting for your choice",
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
    requirements: "Requirements",
    catalog: "Style catalogue",
    model: "Model that draws the mockups",
    localModel: "local model, declarative preview",
    mockupGeneration: "Mockup of {code}",
    generations: "Generations of the project",
    cost: "Cost of the generations",
    tokens: "Tokens",
    tokensValue: "{input} in · {output} out · {reasoning} reasoning",
    none: "None",
    methodology:
      "Gate 5 approves the exact Design Package ID, version, and content hash. Owner approval is governance, not empirical validation. Synthetic User Twin feedback remains a design hypothesis.",
    history: "Versions of the design",
    historyItem: "Version {n} · {date}",
    decided: "Changes already decided",
    applied: "Applied",
    discarded: "Discarded",
    provenance: "Provenance of the critiques",
    confidence: "self-assessed confidence {value}",
    usage: "Generations with the hosted model",
    usageItem: "{date} · {purpose} · {model} · {status}",
    subscription: "subscription",
    mockupNotes: "Notes of the Studio on the mockups",
    mockupNotesIntro: "The Studio accepted these mockups and noted these points.",
    mockupNotesOf: "{code} · {title}",
    onScreen: "On the screen “{title}”: {text}",
  },
  it: {
    designer: "Designer UX/UI",
    noPackage:
      "Sono pronto a proporti un aspetto per la tua app: preparo le alternative e le faccio provare ai twin.",
    prerequisite: "Approva prima i requisiti: poi posso preparare le alternative.",
    generate: "Prepara le alternative di design",
    generating: "Il designer sta preparando le alternative…",
    loading: "Carico il design…",
    updating: "Aggiorno il design…",
    introOne:
      "Ho preparato un'alternativa e l'ho fatta provare ai twin. Il loro parere è qui sotto.",
    introMany:
      "Ho preparato {n} alternative e le ho fatte provare ai twin. Il loro parere è qui sotto.",
    introChosen:
      "Hai scelto {alternative}. Leggi il parere dei twin e approva il design quando sei pronto.",
    introIterate:
      "Hai scelto {alternative}. Se qualcosa va cambiato, chiedi modifiche: disegno una nuova versione e la confronti con quella attuale.",
    numbers: ["nessuna", "una", "due", "tre", "quattro", "cinque", "sei", "sette", "otto"],
    viewLabel: "Viste del design",
    loadError: "Non è stato possibile caricare Design e valutazione.",
    mockupRequired:
      "Il mockup di questa alternativa non è ancora pronto: aspettalo prima di sceglierla.",
    mockupRequiredDeclarative:
      "Prova prima il mockup di questa alternativa: poi potrai sceglierla.",
    pendingOther:
      "Un'altra modifica aspetta la tua decisione qui sopra: applicala o scartala prima.",
    proposeFailed:
      "Non è stato possibile registrare la tua scelta: non è cambiato nulla. Riprova tra poco.",
    applyFailed:
      "La tua scelta è registrata ma non è ancora stata applicata. Premi di nuovo «Scegli questa».",
    noChanges: "Questo design è già quello attuale.",
    iterationApplyFailed:
      "La nuova versione è registrata ma non è ancora stata applicata. Premi di nuovo «Applica la nuova versione».",
    iterationStale: "Il design è cambiato nel frattempo: questa versione non si può più applicare.",
    iterationPending:
      "Una nuova versione aspetta già la tua decisione: applicala o scartala prima di chiedere altre modifiche.",
    ruleTooLong:
      "Una regola può avere al massimo 300 caratteri: accorcia la richiesta o non tenerla come regola.",
    ruleFailed: "Non è stato possibile togliere la regola. Riprova tra poco.",
    hintTry: "Prova prima il mockup: poi potrai sceglierla.",
    hintPendingOther: "Decidi prima la modifica che aspetta qui sopra.",
    notCovered: "Il mockup non mostra ancora questi requisiti: {list}.",
    previewTitle: "Mockup di {alternative}",
    previewDraft: "Bozza generata dal modello · non applicata",
    previewCurrent: "Il mockup del design scelto",
    previewHelp:
      "Esplora schermate e controlli. I risultati di esempio illustrano il design; l'applicazione si realizza dalla cartella di conoscenza con i tuoi strumenti.",
    previewMissing:
      "Questa alternativa non ha ancora un'anteprima. Crearla richiede qualche istante.",
    previewError: "Non è stato possibile caricare l'anteprima.",
    createMockup: "Crea l'anteprima",
    reloadPreview: "Riprova",
    closePreview: "Chiudi l'anteprima",
    pendingTitle: [
      "Una modifica aspetta la tua decisione",
      "Modifiche che aspettano la tua decisione",
    ],
    applyDiff: "Applica la modifica",
    rejectDiff: "Scartala",
    diffReason: "Perché la scarti (serve per scartarla)",
    reasonRequired: "Per respingere o scartare serve una motivazione.",
    regenerateText:
      "Hai portato degli spunti nel progetto? Rigenera le alternative: i twin le valuteranno di nuovo.",
    regenerate: "Rigenera le alternative",
    regenerating: "Il designer sta rigenerando le alternative…",
    regenerationRejected: "Non è stato possibile rigenerare il design.",
    regenerationRequirements:
      "I requisiti sono cambiati e aspettano la tua approvazione. Riapprovali, poi rigenera le alternative di design.",
    regenerationNoPackage:
      "Non c'è ancora un design da rigenerare. Genera prima le alternative di design.",
    concernsTitle: "Punti di attenzione e domande aperte ({n})",
    concerns: "Punti di attenzione",
    remedy: "Rimedio",
    openQuestions: "Domande aperte",
    approveGate: "Approva il design scelto",
    askChanges: "Chiedi modifiche",
    barChoose: "Scegli una delle alternative con «Scegli questa»: poi approvi il design qui.",
    barApprove:
      "Approvi {alternative}. La cartella di conoscenza conterrà questo design e il parere dei twin.",
    barApproved:
      "Hai approvato questo design. Puoi ancora chiedere modifiche a parole: la nuova versione torna qui per la tua approvazione.",
    barApprovedDrawing:
      "Il designer sta disegnando la nuova versione che hai chiesto: il design approvato resta com'è finché non la applichi.",
    barApprovedWaiting: "La nuova versione aspetta qui sopra: applicala, poi approvala qui.",
    barPending:
      "Una modifica proposta aspetta qui sopra: se approvi ora, resta fuori da questa versione.",
    barIteration: "Una nuova versione aspetta qui sopra: se approvi ora, approvi quella attuale.",
    barDrawing:
      "Il designer sta disegnando la nuova versione che hai chiesto: puoi aspettarla o approvare quella attuale.",
    barRevision:
      "Hai chiesto modifiche: chiedi al designer una nuova versione, scegli l'altra alternativa o rigenera le alternative.",
    barRequestIteration: "Finché non applichi la nuova versione, il design attuale resta com'è.",
    barRequestRevision: "Il design attuale non cambia: la tua nota resta nella storia del design.",
    iterationPlaceholder:
      "Scrivi che cosa cambiare: il designer disegna una nuova versione e decidi tu se applicarla.",
    revisionPlaceholder:
      "Scrivi che cosa non va: la richiesta viene registrata con la tua nota. Per un design diverso scegli l'altra alternativa o rigenera le alternative.",
    keepRule: "Tienila come regola per le prossime versioni",
    keepRuleHint: "Il designer la rispetterà ogni volta che disegna una nuova versione.",
    submitFailed:
      "Non è stato possibile portare il design alla tua approvazione: non è stato approvato nulla. Riprova tra poco.",
    approveFailed:
      "Il design è pronto per la tua approvazione, ma l'approvazione non è andata a buon fine. Premi di nuovo «Approva il design scelto».",
    requestFailed:
      "Non è stato possibile registrare la tua richiesta di modifiche. La nota è ancora lì: riprova tra poco.",
    moreActions: "Altre scelte sull'approvazione",
    reason: "Motivazione (serve per respingere o per chiedere una revisione)",
    rejectGate: "Respingi il design",
    requestRevision: "Chiedi una revisione",
    pause: "Metti in pausa",
    cancelGate: "Annulla l'approvazione",
    pausedText: "L'approvazione di questo design è in pausa.",
    resume: "Riprendi l'approvazione",
    revisionTitle: "Hai chiesto modifiche",
    rejectedTitle: "Hai respinto questo design",
    cancelledTitle: "Hai annullato l'approvazione",
    closedText:
      "Per cambiarlo scegli l'altra alternativa, chiedi modifiche o rigenera le alternative: la nuova versione torna qui per la tua approvazione.",
    yourNote: "La tua nota",
    ready: "Design approvato da te. Ora il Dossier.",
    reanchoredReview:
      "Il design è stato riagganciato alla Definizione nuova: puoi chiedere ai twin una nuova valutazione.",
    matrixEmpty: "I twin non hanno ancora espresso un parere su queste alternative.",
    readObservations: "Leggi tutte le osservazioni di {twin} su {alternative} ({count})",
    closeObservations: "Chiudi le osservazioni",
    version: "Versione",
    statusChoose: "in attesa della tua scelta",
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
    requirements: "Requisiti",
    catalog: "Catalogo degli stili",
    model: "Modello che disegna i mockup",
    localModel: "modello locale, anteprima dichiarativa",
    mockupGeneration: "Mockup di {code}",
    generations: "Generazioni del progetto",
    cost: "Costo delle generazioni",
    tokens: "Token",
    tokensValue: "{input} in ingresso · {output} in uscita · {reasoning} di ragionamento",
    none: "Nessuno",
    methodology:
      "Il Gate 5 approva ID, versione e hash esatti del Design Package. L'approvazione del proprietario è governance, non validazione empirica. Il feedback sintetico dei User Twin resta un'ipotesi progettuale.",
    history: "Versioni del design",
    historyItem: "Versione {n} · {date}",
    decided: "Modifiche già decise",
    applied: "Applicata",
    discarded: "Scartata",
    provenance: "Provenienza delle critiche",
    confidence: "confidenza auto-valutata {value}",
    usage: "Generazioni con il modello ospitato",
    usageItem: "{date} · {purpose} · {model} · {status}",
    subscription: "abbonamento",
    mockupNotes: "Note dello Studio sui mockup",
    mockupNotesIntro: "Lo Studio ha accettato questi mockup e ha annotato questi punti.",
    mockupNotesOf: "{code} · {title}",
    onScreen: "Nella schermata «{title}»: {text}",
  },
} as const;

const auth = useAuthStore();
const store = useDesignStore();
const loopStore = useDesignLoopStore();
const mockups = useDesignMockupsStore();
const iterations = useDesignIterationsStore();
const tray = useInsightTrayStore();
const modeling = useUserModelingStore();
const requirementsStore = useRequirementsStore();

const copy = computed(() => messages[props.locale]);
const api = computed(() => props.api ?? designApi);
const loop = computed(() => props.loopApi ?? designLoopApi);
const mockupsApi = computed(() => props.mockupsApi ?? designMockupsApi);
const iterationsApi = computed(() => props.iterationsApi ?? designIterationsApi);
const pinsApi = computed(() => props.pinsApi ?? designReviewPinsApi);
const usageApi = computed(() => props.usageApi ?? modelUsageApi);

const uid = useId();
const root = ref<HTMLElement | null>(null);
const previewSection = ref<HTMLElement | null>(null);
const iterationSection = ref<HTMLElement | null>(null);
const viewSwitch = ref<InstanceType<typeof ArtifactViewSwitch> | null>(null);
const decisionBar = ref<InstanceType<typeof UiDecisionBar> | null>(null);
const barTarget = ref<HTMLElement | null>(null);
const rowTarget = ref<HTMLElement | null>(null);
const view = ref<ArtifactView>("text");
const viewPanelId = "design-view-panel";
const localError = ref<string | null>(null);
const deciding = ref(false);
const choosing = ref<string | null>(null);
const gateReason = ref("");
const diffReasons = reactive<Record<string, string>>({});
const reviewRequestedFor = ref<string | null>(null);
const nextStepRefresh = ref(0);
const selectedCell = ref<TwinMatrixSelection | null>(null);
const observationsOpen = ref(false);
const dialog = ref<DialogState | null>(null);
const dialogBusy = ref(false);
const previewAlternativeId = ref<string | null>(null);
const declarative = reactive<Record<string, DeclarativeEntry>>({});
const declarativeBusy = ref<string | null>(null);
const thumbnails = reactive<Record<string, "loading" | "missing" | "failed">>({});
const ensuring = reactive<Record<string, number>>({});
const iterationScreen = ref<string | null>(null);
const requestOpen = ref(false);
const keepAsRule = ref(false);
const usage = ref<ModelUsagePayload | null>(null);
const validationFailure = ref<{ key: string; code: string } | null>(null);
const applyingSource = ref<string | null>(null);
const applyFailure = ref<{ id: string; code: string } | null>(null);
const prepared = new Set<string>();
const stepShown = ref(false);
const lifetime = new AbortController();
let preparation: { from: string } | null = null;
let handledApplicationId: string | null = null;
let declarativeEpoch = 0;
let dialogSequence = 0;
let usageSequence = 0;
let visibility: ResizeObserver | null = null;

const current = computed(() => (store.projectId === props.projectId ? store.current : null));
const packageValue = computed(() => current.value?.package ?? null);
const alternatives = computed(() => packageValue.value?.alternatives ?? []);
const chosenAlternativeId = computed(
  () => packageValue.value?.owner_selected_alternative_id ?? null,
);
const chosenAlternative = computed(
  () => alternatives.value.find((item) => item.id === chosenAlternativeId.value) ?? null,
);
const appliedGenerated = computed(
  () => (packageValue.value?.generated_mockup ?? null) !== null && chosenAlternative.value !== null,
);
const generatedPath = computed(
  () => mockups.projectId === props.projectId && mockups.generatedMockupsEnabled,
);
const iterationMode = computed(
  () => generatedPath.value && mockups.iterationsEnabled && appliedGenerated.value,
);
const requirementsSpecification = computed(() =>
  requirementsStore.projectId === props.projectId
    ? (requirementsStore.current?.specification ?? null)
    : null,
);
const pendingDiff = computed(() => store.pendingDiffs[0] ?? null);
const decidedDiffs = computed(() => store.diffHistory.filter((diff) => diff.status !== "PROPOSED"));
const twinReferences = computed(() => packageValue.value?.grounding.user_twin_references ?? []);
const twinNames = computed(() =>
  Object.fromEntries(twinReferences.value.map((reference) => [reference.twin_id, reference.name])),
);
const appliedPrototype = computed(() => {
  const prototype = packageValue.value?.prototype ?? null;
  return prototype !== null && prototype.design_alternative_id === chosenAlternativeId.value
    ? prototype
    : null;
});
const appliedScreens = computed<ScreenName[]>(() => {
  const generated = appliedGenerated.value
    ? (packageValue.value?.generated_mockup?.mockup.screens ?? [])
    : [];
  return screenNamesOf(generated.length > 0 ? generated : (appliedPrototype.value?.screens ?? []));
});
const appliedElements = computed(() => {
  const names: Record<string, string> = {};
  for (const screen of appliedPrototype.value?.screens ?? []) {
    for (const element of screen.elements) {
      const label = elementLabel(element);
      if (label.length > 0) {
        names[element.code] = label;
      }
    }
  }
  return names;
});
const workflowsByAlternative = computed<Record<string, WorkflowName[]>>(() =>
  Object.fromEntries(
    alternatives.value.map((alternative) => [alternative.id, workflowNamesOf(alternative)]),
  ),
);
const chosenWorkflows = computed(
  () => workflowsByAlternative.value[chosenAlternativeId.value ?? ""] ?? [],
);
const iterationScreens = computed<ScreenName[]>(() => [
  ...screenNamesOf(iterations.result?.package.generated_mockup?.mockup.screens ?? []),
  ...appliedScreens.value,
]);
const staticCheckAvailable = computed(
  () => !(mockups.projectId === props.projectId && mockups.capabilities?.static_check === false),
);
const mockupsPaid = computed(
  () => !(mockups.projectId === props.projectId && mockups.capabilities?.paid === false),
);

const gateTargetsCurrent = computed(() => {
  const gate = store.gate;
  const version = current.value;
  if (gate === null || version === null) {
    return false;
  }
  return (
    gate.artifact.artifact_id === version.id &&
    gate.artifact.version === version.version_number &&
    gate.artifact.content_hash === version.content_hash
  );
});
const canSubmitGate = computed(() => {
  const version = current.value;
  if (version === null || !version.ready_for_gate) {
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
  const version = current.value;
  if (version === null) {
    return "none";
  }
  if (store.isReadyForArchitecture) {
    return "approved";
  }
  if (!version.ready_for_gate) {
    return "choose";
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
const approvedChanges = computed(
  () => props.sectionsMode && decisionState.value === "approved" && iterationMode.value,
);
const barVisible = computed(
  () =>
    decisionState.value === "choose" ||
    decisionState.value === "approve" ||
    (decisionState.value === "revision" && iterationMode.value) ||
    approvedChanges.value,
);
const iterationWaiting = computed(
  () => iterations.state === "drawing" || iterations.state === "ready",
);
const secondaryLabel = computed(() =>
  (iterationMode.value || decisionState.value === "approve") && !iterationWaiting.value
    ? copy.value.askChanges
    : null,
);
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
const decisionCounter = computed(() =>
  fill(copy.value.decisionCounter, {
    n: store.gate?.iteration ?? 1,
  }),
);

const reviewRun = computed<DesignEvaluationRunPayload | null>(() => {
  const version = current.value;
  if (version === null || loopStore.projectId !== props.projectId) {
    return null;
  }
  return (
    loopStore.runs.find(
      (run) =>
        runMode(run) === "TWIN_REVIEW" &&
        run.design_version_id === version.id &&
        run.design_content_hash === version.content_hash,
    ) ?? null
  );
});
const reanchoredWithoutReview = computed(() => {
  const version = current.value;
  if (version === null || reviewRun.value !== null || loopStore.projectId !== props.projectId) {
    return false;
  }
  const base = store.history.find(
    (item) => item.version_number === version.based_on_version_number,
  );
  return (
    base !== undefined &&
    sameAlternatives(base.package, version.package) &&
    !sameReference(
      base.package.grounding.requirements_reference,
      version.package.grounding.requirements_reference,
    ) &&
    loopStore.runs.some(
      (run) => runMode(run) === "TWIN_REVIEW" && run.design_version_id !== version.id,
    )
  );
});
const reviewPins = computed(() =>
  reviewRun.value === null ? null : mockups.pinsFor(reviewRun.value.id),
);
const reviewElements = computed(() => ({
  ...appliedElements.value,
  ...elementNames(
    reviewRun.value?.responses.flatMap((response) =>
      response.findings.map((finding) => finding.location),
    ) ?? [],
  ),
}));
const pinNumbers = computed(() => {
  const numbers = new Map<string, number>();
  const pins = reviewPins.value;
  if (pins !== null) {
    for (const pin of [...pins.pins, ...pins.unanchored]) {
      numbers.set(`${pin.twin_id}:${pin.finding_id}`, pin.number);
    }
  }
  return numbers;
});
const dismissedSignature = computed(() => {
  const run = reviewRun.value;
  if (run === null) {
    return "";
  }
  return run.responses
    .flatMap((response) => response.findings)
    .filter(
      (finding) =>
        loopStore.validationByKey[findingKey(run.id, finding.twin_id, finding.finding_id)]
          ?.decision === "OWNER_DISMISSED",
    )
    .map((finding) => `${finding.twin_id}:${finding.finding_id}`)
    .sort()
    .join("|");
});

const roster = computed<TwinRoster>(() => ({
  personaIds: modeling.currentPersonas.map((persona) => persona.persona_id),
  twins: modeling.currentTwins.map((twin) => ({
    twinId: twin.twin_id,
    personaId: twin.profile.persona_reference.persona_id,
  })),
}));

const matrixAlternatives = computed(() =>
  alternatives.value.map((item) => ({ id: item.id, code: item.code, title: item.title })),
);
const matrixTwins = computed(() =>
  twinReferences.value.map((reference) => ({
    id: reference.twin_id,
    name: reference.name,
    avatar: twinAvatarOf(reference.twin_id),
  })),
);
const matrixCells = computed<TwinMatrixCell[]>(() => {
  const cells: TwinMatrixCell[] = [];
  for (const twin of twinReferences.value) {
    for (const alternative of alternatives.value) {
      const critique = critiqueOf(twin.twin_id, alternative.id);
      const findings = reviewFindingsOf(twin.twin_id, alternative.id);
      if (critique === null && findings === null) {
        continue;
      }
      const open = findings?.filter((finding) => !isDismissed(finding)) ?? null;
      cells.push({
        twin: twin.twin_id,
        alternative: alternative.id,
        verdict: critique?.verdict ?? null,
        quote: critique?.quote ?? null,
        count: open === null ? critiqueItemCount(critique) : open.length,
        strengths: critique?.strengths ?? [],
        concerns: critique?.concerns ?? [],
        severity: open === null ? null : worstSeverity(open),
      });
    }
  }
  return cells;
});
const activeCell = computed<TwinMatrixSelection | null>(() => {
  const chosen = selectedCell.value;
  if (
    chosen !== null &&
    twinReferences.value.some((twin) => twin.twin_id === chosen.twin) &&
    alternatives.value.some((item) => item.id === chosen.alternative)
  ) {
    return chosen;
  }
  const twin = twinReferences.value[0];
  const alternative =
    chosenAlternative.value ??
    alternatives.value.find((item) => item.id === packageValue.value?.recommended_alternative_id) ??
    alternatives.value[0];
  return twin === undefined || alternative === undefined
    ? null
    : { twin: twin.twin_id, alternative: alternative.id };
});
const observation = computed(() => {
  const cell = activeCell.value;
  if (cell === null) {
    return null;
  }
  const twin = twinReferences.value.find((item) => item.twin_id === cell.twin);
  const alternative = alternatives.value.find((item) => item.id === cell.alternative);
  if (twin === undefined || alternative === undefined) {
    return null;
  }
  const findings = reviewFindingsOf(twin.twin_id, alternative.id);
  const critique = critiqueOf(twin.twin_id, alternative.id);
  return {
    twin: { id: twin.twin_id, name: twin.name, avatar: twinAvatarOf(twin.twin_id) },
    alternative: { id: alternative.id, code: alternative.code, title: alternative.title },
    runId: findings === null ? null : (reviewRun.value?.id ?? null),
    findings:
      findings === null
        ? null
        : findings.map<ObservationFinding>((finding) => ({
            finding_id: finding.finding_id,
            twin_id: finding.twin_id,
            summary: finding.summary,
            location: finding.location,
            criterion: finding.criterion,
            severity: finding.severity,
            recommended_action: finding.recommended_action,
            number: pinNumbers.value.get(`${finding.twin_id}:${finding.finding_id}`) ?? null,
          })),
    critique: critique === null ? null : critiqueView(critique),
    count: findings === null ? critiqueItemCount(critique) : findings.length,
    screens: screensOf(alternative.id),
    elements: alternative.id === chosenAlternativeId.value ? reviewElements.value : {},
    workflows: workflowNamesOf(alternative),
  };
});
const observationsLabel = computed(() => {
  const value = observation.value;
  if (value === null) {
    return "";
  }
  if (observationsOpen.value) {
    return copy.value.closeObservations;
  }
  return fill(copy.value.readObservations, {
    twin: value.twin.name,
    alternative: `${value.alternative.code} · ${value.alternative.title}`,
    count: value.count,
  });
});
const observationValidations = computed(() => {
  const decisions: Record<string, { decision: "OWNER_CONFIRMED" | "OWNER_DISMISSED" }> = {};
  for (const [key, validation] of Object.entries(loopStore.validationByKey)) {
    decisions[key] = { decision: validation.decision };
  }
  return decisions;
});
const appliedInsights = computed(() => {
  const applied: Record<string, ObservationTarget> = {};
  if (loopStore.projectId === props.projectId) {
    for (const application of loopStore.applications) {
      applied[application.source_id] = application.target;
    }
  }
  for (const item of tray.itemsOf(props.projectId)) {
    applied[item.sourceId] = "BRIEF";
  }
  return applied;
});

const previews = computed<Record<string, AlternativePreview>>(() => {
  const result: Record<string, AlternativePreview> = {};
  if (!generatedPath.value) {
    return result;
  }
  for (const alternative of alternatives.value) {
    result[alternative.id] = previewOf(alternative);
  }
  return result;
});
const thumbnailWants = computed<ThumbnailWant[]>(() => {
  if (!generatedPath.value || current.value === null) {
    return [];
  }
  const wants: ThumbnailWant[] = [];
  for (const alternative of alternatives.value) {
    const entry = mockups.entry(alternative.id);
    if (
      entry.state === "drawing" ||
      entry.state === "rejected" ||
      entry.state === "failed" ||
      mockups.isChecking(alternative.id) ||
      (ensuring[alternative.id] ?? 0) > 0
    ) {
      continue;
    }
    wants.push(thumbnailWant(alternative));
  }
  return wants;
});
const choosable = computed<Record<string, boolean>>(() => {
  const result: Record<string, boolean> = {};
  const pending = pendingDiff.value;
  for (const alternative of alternatives.value) {
    result[alternative.id] =
      pending === null
        ? choicePackage(alternative.id) !== null
        : pending.proposed_package.owner_selected_alternative_id === alternative.id;
  }
  return result;
});
const hints = computed<Record<string, string>>(() => {
  const result: Record<string, string> = {};
  const pending = pendingDiff.value;
  for (const alternative of alternatives.value) {
    if (alternative.id === chosenAlternativeId.value) {
      continue;
    }
    if (pending !== null) {
      if (pending.proposed_package.owner_selected_alternative_id !== alternative.id) {
        result[alternative.id] = copy.value.hintPendingOther;
      }
      continue;
    }
    if (!generatedPath.value && choicePackage(alternative.id) === null) {
      result[alternative.id] = copy.value.hintTry;
    }
  }
  return result;
});

const cardNotes = computed<Record<string, string>>(() => {
  const result: Record<string, string> = {};
  if (!generatedPath.value) {
    return result;
  }
  const titles = new Map(
    (requirementsSpecification.value?.requirements ?? []).map((item) => [item.code, item.title]),
  );
  for (const alternative of alternatives.value) {
    const entry = mockups.entry(alternative.id);
    if (entry.state !== "ready") {
      continue;
    }
    const codes = [
      ...new Set(
        entry.result.warnings
          .filter((warning) => warning.code === "REQUIREMENTS_NOT_COVERED")
          .flatMap((warning) => warning.detail.match(REQUIREMENT_CODE) ?? []),
      ),
    ];
    if (codes.length > 0) {
      const list = new Intl.ListFormat(props.locale, { type: "conjunction" }).format(
        codes.map((code) => (titles.has(code) ? `${code} · ${titles.get(code)}` : code)),
      );
      result[alternative.id] = fill(copy.value.notCovered, { list });
    }
  }
  return result;
});

const previewAlternative = computed(
  () => alternatives.value.find((item) => item.id === previewAlternativeId.value) ?? null,
);
const previewContent = computed(() => {
  const alternative = previewAlternative.value;
  if (alternative === null) {
    return null;
  }
  const saved = declarative[alternative.id];
  const draft = saved?.mockup?.package.prototype ?? null;
  if (draft !== null && draft.design_alternative_id === alternative.id) {
    return { prototype: draft, draft: true, generationId: saved?.mockup?.generation_id ?? null };
  }
  const applied = packageValue.value?.prototype ?? null;
  if (applied !== null && applied.design_alternative_id === alternative.id) {
    return { prototype: applied, draft: false, generationId: null };
  }
  return null;
});

const dialogDocument = computed<MockupDocumentPayload | null>(() => {
  const state = dialog.value;
  if (state === null) {
    return null;
  }
  const entryScreen = state.entryScreen ?? "";
  if (state.source === "review") {
    const run = reviewRun.value;
    return run === null ? null : mockups.reviewDocumentFor(run.id, entryScreen);
  }
  return mockups.documentFor(state.alternativeId, {
    source: state.source,
    entryScreen,
    ...(state.revision === null ? {} : { revision: state.revision }),
  });
});
const dialogPins = computed(() =>
  dialog.value?.source === "review" ? (reviewPins.value?.pins ?? []) : [],
);
const dialogUnanchored = computed(() =>
  dialog.value?.source === "review" ? (reviewPins.value?.unanchored ?? []) : [],
);
const dialogObservations = computed<MockupObservation[]>(() => {
  const run = reviewRun.value;
  const pins = reviewPins.value;
  if (dialog.value?.source !== "review" || run === null || pins === null) {
    return [];
  }
  const findings = new Map(
    run.responses
      .flatMap((response) => response.findings)
      .map((finding) => [`${finding.twin_id}:${finding.finding_id}`, finding]),
  );
  return [...pins.pins, ...pins.unanchored].flatMap((pin) => {
    const finding = findings.get(`${pin.twin_id}:${pin.finding_id}`);
    return finding === undefined
      ? []
      : [
          {
            number: pin.number,
            twin_name: twinNames.value[pin.twin_id] ?? "",
            severity: finding.severity,
            text: finding.summary,
            place: finding.location,
          },
        ];
  });
});

const iterationJob = computed<IterationJob | null>(() => {
  const state = iterations.state;
  const job = iterations.job;
  if (state === "idle") {
    return null;
  }
  if (state === "drawing") {
    return job;
  }
  if (state === "ready") {
    const result = iterations.result;
    if (result === null) {
      return null;
    }
    if (job !== null && job.result?.generation_id === result.generation_id) {
      return job;
    }
    return {
      job_id: result.generation_id,
      kind: "ITERATION",
      status: "SUCCEEDED",
      stage: null,
      attempt: 1,
      started_at: current.value?.created_at ?? new Date(0).toISOString(),
      finished_at: null,
      alternative_id: chosenAlternativeId.value,
      result,
      failure: null,
    };
  }
  if (job === null) {
    return null;
  }
  return {
    ...job,
    status: state === "rejected" ? "REJECTED" : "FAILED",
    stage: null,
    result: null,
    failure: iterations.failure ?? job.failure,
  };
});
const iterationError = computed(() =>
  (iterations.state === "rejected" || iterations.state === "failed") && iterationJob.value === null
    ? (iterations.failure?.code ?? "GENERATION_FAILED")
    : null,
);
const iterationBefore = computed(() => {
  const alternativeId = chosenAlternativeId.value;
  if (alternativeId === null || iterations.state !== "ready") {
    return null;
  }
  return mockups.documentFor(alternativeId, {
    source: "applied",
    entryScreen: iterationScreen.value ?? "",
  });
});
const iterationAfter = computed(() => {
  const alternativeId = chosenAlternativeId.value;
  const result = iterations.result;
  if (alternativeId === null || iterations.state !== "ready" || result === null) {
    return null;
  }
  return mockups.documentFor(alternativeId, {
    source: "latest",
    entryScreen: iterationScreen.value ?? "",
    revision: result.generation_id,
  });
});
const iterationVisible = computed(
  () =>
    iterationMode.value &&
    (iterations.state !== "idle" ||
      (packageValue.value?.owner_assertions ?? []).length > 0 ||
      iterations.items.length > 0),
);

const agentText = computed(() => {
  const chosen = chosenAlternative.value;
  if (chosen !== null) {
    return fill(iterationMode.value ? copy.value.introIterate : copy.value.introChosen, {
      alternative: `${chosen.code} · ${chosen.title}`,
    });
  }
  const total = alternatives.value.length;
  if (total === 1) {
    return copy.value.introOne;
  }
  return fill(copy.value.introMany, { n: copy.value.numbers[total] ?? String(total) });
});
const barDescription = computed(() => {
  const text = copy.value;
  if (decisionState.value === "choose") {
    return text.barChoose;
  }
  if (requestOpen.value && secondaryLabel.value !== null) {
    return iterationMode.value ? text.barRequestIteration : text.barRequestRevision;
  }
  if (decisionState.value === "approved") {
    if (pendingDiff.value !== null || iterations.state === "ready") {
      return text.barApprovedWaiting;
    }
    return iterations.state === "drawing" ? text.barApprovedDrawing : text.barApproved;
  }
  if (decisionState.value === "revision") {
    return text.barRevision;
  }
  if (pendingDiff.value !== null) {
    return text.barPending;
  }
  if (iterations.state === "ready") {
    return text.barIteration;
  }
  if (iterations.state === "drawing") {
    return text.barDrawing;
  }
  const chosen = chosenAlternative.value;
  return fill(text.barApprove, {
    alternative: chosen === null ? "" : `${chosen.code} · ${chosen.title}`,
  });
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
const concernCount = computed(
  () =>
    (packageValue.value?.concerns.length ?? 0) + (packageValue.value?.open_questions.length ?? 0),
);
const statusSummary = computed(() => {
  const text = copy.value;
  switch (decisionState.value) {
    case "approved":
      return text.statusApproved;
    case "choose":
      return text.statusChoose;
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
  if (version === null) {
    return [];
  }
  const text = copy.value;
  const gate = store.gate;
  const grounding = version.package.grounding;
  const rows: { label: string; value: string }[] = [
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
    { label: text.requirements, value: `v${grounding.requirements_reference.version_number}` },
    { label: text.catalog, value: `v${grounding.catalog.version}` },
    {
      label: text.model,
      value: generatedPath.value ? (mockups.capabilities?.model ?? text.none) : text.localModel,
    },
  ];
  for (const alternative of alternatives.value) {
    const entry = mockups.entry(alternative.id);
    if (entry.state === "ready") {
      rows.push({
        label: fill(text.mockupGeneration, { code: alternative.code }),
        value: entry.result.generation_id,
      });
    }
  }
  const totals = usage.value?.totals ?? null;
  if (totals !== null) {
    rows.push({ label: text.generations, value: String(totals.generations) });
    rows.push({ label: text.cost, value: money(totals.cost_microusd) });
    rows.push({
      label: text.tokens,
      value: fill(text.tokensValue, {
        input: count(totals.input_tokens),
        output: count(totals.output_tokens),
        reasoning: count(totals.reasoning_tokens ?? 0),
      }),
    });
  }
  return rows;
});

const mockupNotes = computed(() => {
  const text = copy.value;
  const notes: { id: string; label: string; lines: string[] }[] = [];
  for (const alternative of alternatives.value) {
    const entry = mockups.entry(alternative.id);
    if (entry.state !== "ready" || entry.result.warnings.length === 0) {
      continue;
    }
    const screens = new Map(
      (entry.result.package.generated_mockup?.mockup.screens ?? []).map((screen) => [
        screen.code,
        screen.title,
      ]),
    );
    const lines: string[] = [];
    for (const warning of entry.result.warnings) {
      const sentence = generationReasonText(warning.code, props.locale);
      const title = warning.screen_code === null ? undefined : screens.get(warning.screen_code);
      const line = title === undefined ? sentence : fill(text.onScreen, { title, text: sentence });
      if (!lines.includes(line)) {
        lines.push(line);
      }
    }
    notes.push({
      id: alternative.id,
      label: fill(text.mockupNotesOf, { code: alternative.code, title: alternative.title }),
      lines,
    });
  }
  return notes;
});

function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_match, key: string) => String(values[key] ?? ""));
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat(props.locale, { dateStyle: "medium", timeStyle: "short" }).format(
        date,
      );
}

function money(microusd: number | null): string {
  return new Intl.NumberFormat(props.locale === "it" ? "it-IT" : "en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 3,
  }).format((microusd ?? 0) / 1_000_000);
}

function count(value: number): string {
  return new Intl.NumberFormat(props.locale === "it" ? "it-IT" : "en-US").format(value);
}

function percent(value: number): string {
  return new Intl.NumberFormat(props.locale, { style: "percent", maximumFractionDigits: 0 }).format(
    value,
  );
}

function twinAvatarOf(twinId: string): string {
  return rosterAvatar(twinId, roster.value);
}

function screenNamesOf(screens: readonly ScreenName[]): ScreenName[] {
  return screens.map((screen) => ({ code: screen.code, title: screen.title }));
}

function workflowNamesOf(alternative: DesignAlternativePayload): WorkflowName[] {
  return alternative.workflows.map((workflow) => ({ code: workflow.code, title: workflow.title }));
}

function elementLabel(element: PrototypeElementPayload): string {
  const name = element.accessible_name?.trim() ?? "";
  const label = (name.length > 0 ? name : element.content).replace(/\s+/g, " ").trim();
  return label.length <= ELEMENT_LABEL_LIMIT
    ? label
    : `${label.slice(0, ELEMENT_LABEL_LIMIT - 1)}…`;
}

function screensOf(alternativeId: string): ScreenName[] {
  if (alternativeId === chosenAlternativeId.value && appliedScreens.value.length > 0) {
    return appliedScreens.value;
  }
  const entry = mockups.entry(alternativeId);
  const drawn =
    entry.state === "ready" ? (entry.result.package.generated_mockup?.mockup.screens ?? []) : [];
  return screenNamesOf(
    drawn.length > 0
      ? drawn
      : (mockups.documentFor(alternativeId, { source: "latest" })?.screens ?? []),
  );
}

function versionKey(version: DesignPackageVersionPayload | null): string {
  return version === null ? "" : `${version.id}|${version.content_hash}`;
}

async function preparing<T>(operation: () => Promise<T>): Promise<T> {
  const token = { from: versionKey(current.value) };
  preparation = token;
  try {
    return await operation();
  } finally {
    if (preparation === token) {
      preparation = null;
    }
  }
}

function critiqueOf(twinId: string, alternativeId: string): SyntheticDesignCritiquePayload | null {
  return (
    packageValue.value?.critiques.find(
      (critique) =>
        critique.design_alternative_id === alternativeId &&
        critique.user_twin_reference.twin_id === twinId,
    ) ?? null
  );
}

function reviewFindingsOf(twinId: string, alternativeId: string): SyntheticFindingPayload[] | null {
  const run = reviewRun.value;
  if (run === null || run.alternative_id !== alternativeId) {
    return null;
  }
  const response = run.responses.find((item) => item.twin_id === twinId);
  return response === undefined ? null : response.findings;
}

function isDismissed(finding: SyntheticFindingPayload): boolean {
  const run = reviewRun.value;
  return (
    run !== null &&
    loopStore.validationByKey[findingKey(run.id, finding.twin_id, finding.finding_id)]?.decision ===
      "OWNER_DISMISSED"
  );
}

function worstSeverity(findings: readonly SyntheticFindingPayload[]): TwinMatrixSeverity | null {
  let worst: SyntheticFindingSeverity | null = null;
  for (const finding of findings) {
    if (worst === null || SEVERITY_RANK[finding.severity] > SEVERITY_RANK[worst]) {
      worst = finding.severity;
    }
  }
  return worst;
}

function critiqueItemCount(critique: SyntheticDesignCritiquePayload | null): number {
  if (critique === null) {
    return 0;
  }
  return CRITIQUE_LISTS.reduce(
    (total, key) => total + critique[key].filter((item) => item.trim().length > 0).length,
    0,
  );
}

function critiqueView(critique: SyntheticDesignCritiquePayload): ObservationCritique {
  return {
    code: critique.code,
    user_twin_reference: {
      twin_id: critique.user_twin_reference.twin_id,
      name: critique.user_twin_reference.name,
    },
    strengths: critique.strengths,
    concerns: critique.concerns,
    unmet_needs: critique.unmet_needs,
    accessibility_observations: critique.accessibility_observations,
    trust_concerns: critique.trust_concerns,
    questions: critique.questions,
    suggested_changes: critique.suggested_changes,
  };
}

function thumbnailWant(alternative: DesignAlternativePayload): ThumbnailWant {
  const source: MockupDocumentSource =
    appliedGenerated.value && alternative.id === chosenAlternativeId.value ? "applied" : "latest";
  const entry = mockups.entry(alternative.id);
  const revision =
    source === "applied"
      ? (current.value?.content_hash ?? "none")
      : entry.state === "ready"
        ? entry.result.generation_id
        : "none";
  return { alternativeId: alternative.id, source, key: `${alternative.id}|${source}|${revision}` };
}

function previewOf(alternative: DesignAlternativePayload): AlternativePreview {
  const entry = mockups.entry(alternative.id);
  if (entry.state === "drawing") {
    return { kind: "drawing", startedAt: entry.startedAt, stage: entry.job.stage };
  }
  if (entry.state === "rejected" || entry.state === "failed") {
    return {
      kind: entry.state,
      code: entry.code,
      reasons: entry.reasons,
      retryable: generationRetryable(entry.code),
    };
  }
  const want = thumbnailWant(alternative);
  const document = mockups.documentFor(alternative.id, { source: want.source });
  if (document !== null) {
    return { kind: "document", html: document.html };
  }
  if (mockups.isChecking(alternative.id)) {
    return { kind: "loading" };
  }
  const state = thumbnails[want.key];
  if (state === "missing") {
    return { kind: "missing" };
  }
  if (state === "failed") {
    return { kind: "failed", code: MOCKUP_READ_FAILURE, reasons: [], retryable: true };
  }
  return { kind: "loading" };
}

function resultOf(alternativeId: string): MockupResultPayload | DesignMockupPayload | null {
  if (generatedPath.value) {
    const entry = mockups.entry(alternativeId);
    return entry.state === "ready" && (entry.result.package.generated_mockup ?? null) !== null
      ? entry.result
      : null;
  }
  return declarative[alternativeId]?.mockup ?? null;
}

function choicePackage(alternativeId: string): DesignPackagePayload | null {
  const version = current.value;
  const result = resultOf(alternativeId);
  if (version === null || result === null || alternativeId === chosenAlternativeId.value) {
    return null;
  }
  const proposed = result.package;
  if (
    proposed.owner_selected_alternative_id !== alternativeId ||
    proposed.prototype === null ||
    proposed.prototype.design_alternative_id !== alternativeId
  ) {
    return null;
  }
  if (
    result.design_version_id === version.id &&
    result.design_content_hash === version.content_hash
  ) {
    return proposed;
  }
  return {
    ...version.package,
    owner_selected_alternative_id: alternativeId,
    prototype: proposed.prototype,
    generated_mockup: proposed.generated_mockup ?? null,
  };
}

function samePackage(left: DesignPackagePayload, right: DesignPackagePayload): boolean {
  return (
    left.owner_selected_alternative_id === right.owner_selected_alternative_id &&
    JSON.stringify(left.generated_mockup ?? null) ===
      JSON.stringify(right.generated_mockup ?? null) &&
    JSON.stringify(left.prototype) === JSON.stringify(right.prototype) &&
    JSON.stringify(left.owner_assertions ?? []) === JSON.stringify(right.owner_assertions ?? [])
  );
}

function sameAlternatives(left: DesignPackagePayload, right: DesignPackagePayload): boolean {
  return (
    left.owner_selected_alternative_id === right.owner_selected_alternative_id &&
    left.alternatives.map((item) => item.id).join("|") ===
      right.alternatives.map((item) => item.id).join("|")
  );
}

function sameReference(
  left: VersionedArtifactReferencePayload,
  right: VersionedArtifactReferencePayload,
): boolean {
  return (
    left.artifact_id === right.artifact_id &&
    left.version_number === right.version_number &&
    left.content_hash === right.content_hash
  );
}

function reviewAffected(diff: DesignPackageDiffPayload): boolean {
  return diff.changes.some((change) => REVIEWED_KINDS.has(change.artifact_kind));
}

function changed(): void {
  emit("sections-changed");
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

async function generate(): Promise<void> {
  if (!props.prerequisiteReady || store.isBusy || designJob.value !== null) {
    return;
  }
  dismissDesignJob();
  const generated = await preparing(() =>
    run(() => store.generate(props.projectId, authorizedRequest, api.value)),
  );
  if (generated) {
    changed();
  } else if (isGenerationInterrupted(store.error?.code)) {
    localError.value = null;
  }
}

function regenerationFailure(code: string | null, proposalIssue: string | null): string {
  if (code === "REQUIREMENTS_APPROVAL_REQUIRED") {
    return copy.value.regenerationRequirements;
  }
  if (code === "DESIGN_PACKAGE_NOT_FOUND") {
    return copy.value.regenerationNoPackage;
  }
  return (
    modelFeedback(proposalIssue, props.locale) ??
    modelFeedback(code, props.locale) ??
    copy.value.regenerationRejected
  );
}

async function regenerate(): Promise<void> {
  if (store.isBusy || deciding.value || loopStore.isBusy || designJob.value !== null) {
    return;
  }
  localError.value = null;
  dismissDesignJob();
  await preparing(regenerateDesign);
}

async function regenerateDesign(): Promise<void> {
  let result: DesignGenerationPayload;
  try {
    result = await loopStore.regenerate(props.projectId, authorizedRequest, loop.value);
  } catch (error) {
    const code = error instanceof DesignLoopApiError ? error.code : null;
    if (!isGenerationInterrupted(code)) {
      localError.value = regenerationFailure(code, null);
    }
    nextStepRefresh.value++;
    return;
  }
  if (result.status !== "CREATED") {
    localError.value = regenerationFailure(result.issue, result.proposal_issue);
    nextStepRefresh.value++;
    return;
  }
  const loaded = await run(() => store.load(props.projectId, authorizedRequest, api.value));
  nextStepRefresh.value++;
  changed();
  if (loaded) {
    declarativeEpoch++;
    previewAlternativeId.value = null;
    selectedCell.value = null;
  }
}

async function reloadAfterGeneration(): Promise<void> {
  const loaded = await preparing(() =>
    run(() => store.load(props.projectId, authorizedRequest, api.value)),
  );
  nextStepRefresh.value++;
  changed();
  if (loaded) {
    declarativeEpoch++;
    previewAlternativeId.value = null;
    selectedCell.value = null;
  }
}

const {
  job: designJob,
  failure: designJobFailure,
  dismiss: dismissDesignJob,
} = useGenerationResume({
  projectId: () => props.projectId,
  operations: ["DESIGN_PROPOSAL", "DESIGN_REGENERATION"],
  authorize: authorizedRequest,
  onSettled: reloadAfterGeneration,
});

function onReapproved(): void {
  localError.value = null;
  changed();
}

async function onInsightApplied(application: InsightApplicationPayload): Promise<void> {
  if (application.id === handledApplicationId) {
    return;
  }
  handledApplicationId = application.id;
  nextStepRefresh.value++;
  changed();
  if (application.target === "DESIGN" && application.project_id === props.projectId) {
    await load();
  }
}

async function decideRevision(diffId: string): Promise<DesignPackageVersionPayload | null> {
  const previous = current.value?.id ?? null;
  const decided = await run(() =>
    store.decideRevision(props.projectId, diffId, "APPROVE", authorizedRequest, null, api.value),
  );
  const version = current.value;
  if (!decided || version === null || version.id === previous) {
    return null;
  }
  return version;
}

async function propose(proposed: DesignPackagePayload): Promise<DesignRevisionPayload | null> {
  let outcome: DesignRevisionPayload | null = null;
  const proposedOk = await run(async () => {
    outcome = await store.proposeRevision(props.projectId, proposed, authorizedRequest, api.value);
  });
  return proposedOk ? outcome : null;
}

async function applyPackage(
  proposed: DesignPackagePayload,
  failedApproval: string,
  requestReview: boolean,
): Promise<boolean> {
  const pending = pendingDiff.value;
  let diff: DesignPackageDiffPayload;
  if (pending !== null) {
    if (!samePackage(pending.proposed_package, proposed)) {
      localError.value = copy.value.pendingOther;
      return false;
    }
    diff = pending;
  } else {
    const created = await propose(proposed);
    if (created === null) {
      localError.value = copy.value.proposeFailed;
      return false;
    }
    if (created.diff === null || created.diff.status !== "PROPOSED") {
      localError.value =
        created.domain_issue === "NO_CHANGES" ? copy.value.noChanges : copy.value.proposeFailed;
      return false;
    }
    diff = created.diff;
  }
  const version = await decideRevision(diff.id);
  if (version === null) {
    localError.value = failedApproval;
    return false;
  }
  if (requestReview && version.package.prototype !== null && reviewAffected(diff)) {
    reviewRequestedFor.value = version.id;
  }
  changed();
  return true;
}

async function choose(alternativeId: string): Promise<void> {
  if (deciding.value || store.isBusy) {
    return;
  }
  const pending = pendingDiff.value;
  if (
    pending !== null &&
    pending.proposed_package.owner_selected_alternative_id !== alternativeId
  ) {
    localError.value = copy.value.pendingOther;
    return;
  }
  const proposed = pending !== null ? pending.proposed_package : choicePackage(alternativeId);
  if (proposed === null) {
    localError.value = generatedPath.value
      ? copy.value.mockupRequired
      : copy.value.mockupRequiredDeclarative;
    return;
  }
  deciding.value = true;
  choosing.value = alternativeId;
  try {
    if (await applyPackage(proposed, copy.value.applyFailed, true)) {
      selectedCell.value = null;
    }
  } finally {
    deciding.value = false;
    choosing.value = null;
  }
}

async function decideDiff(diff: DesignPackageDiffPayload, approve: boolean): Promise<void> {
  if (deciding.value || store.isBusy) {
    return;
  }
  if (approve) {
    deciding.value = true;
    try {
      const version = await decideRevision(diff.id);
      if (version !== null) {
        if (version.package.prototype !== null && reviewAffected(diff)) {
          reviewRequestedFor.value = version.id;
        }
        changed();
      }
    } finally {
      deciding.value = false;
    }
    return;
  }
  const reason = (diffReasons[diff.id] ?? "").trim().replace(/\s+/g, " ");
  if (reason.length === 0) {
    localError.value = copy.value.reasonRequired;
    return;
  }
  const discarded = await run(() =>
    store.decideRevision(props.projectId, diff.id, "REJECT", authorizedRequest, reason, api.value),
  );
  if (discarded) {
    changed();
  }
}

async function submitGate(): Promise<boolean> {
  const submitted = await run(() =>
    store.submitGate(props.projectId, authorizedRequest, api.value),
  );
  if (!submitted || (!gatePending.value && !store.isReadyForArchitecture)) {
    localError.value = copy.value.submitFailed;
    return false;
  }
  return true;
}

async function decideGate(action: DesignGateDecisionAction): Promise<boolean> {
  const reason = gateReason.value.trim().replace(/\s+/g, " ");
  if ((action === "REJECT" || action === "REQUEST_REVISION") && reason.length === 0) {
    localError.value = copy.value.reasonRequired;
    return false;
  }
  const applied = await run(() =>
    store.decideGate(
      props.projectId,
      action,
      authorizedRequest,
      reason.length === 0 ? null : reason,
      api.value,
    ),
  );
  if (applied) {
    gateReason.value = "";
    changed();
  }
  return applied;
}

async function approve(): Promise<void> {
  if (deciding.value || store.isBusy || decisionState.value !== "approve") {
    return;
  }
  deciding.value = true;
  try {
    if (canSubmitGate.value && !(await submitGate())) {
      return;
    }
    if (gatePending.value) {
      const approved = await decideGate("APPROVE");
      if (!approved || !store.isReadyForArchitecture) {
        localError.value = copy.value.approveFailed;
      }
    }
  } finally {
    deciding.value = false;
  }
}

function closeRequest(): void {
  requestOpen.value = false;
  keepAsRule.value = false;
}

async function completeRequest(): Promise<void> {
  closeRequest();
  await decisionBar.value?.completeRequest();
}

async function requestRevision(note: string): Promise<void> {
  if (canSubmitGate.value && !(await submitGate())) {
    return;
  }
  if (!gatePending.value) {
    return;
  }
  const requested = await run(() =>
    store.decideGate(props.projectId, "REQUEST_REVISION", authorizedRequest, note, api.value),
  );
  if (requested) {
    await completeRequest();
    changed();
  } else {
    localError.value = copy.value.requestFailed;
  }
}

async function startIteration(note: string): Promise<void> {
  if (keepAsRule.value && [...note].length > ITERATION_ASSERTION_LIMIT) {
    localError.value = copy.value.ruleTooLong;
    return;
  }
  localError.value = null;
  const outcome = await iterations.start(
    { request: note, assertions: keepAsRule.value ? [note] : [] },
    authorizedRequest,
    { api: iterationsApi.value, mockupsApi: mockupsApi.value, signal: lifetime.signal },
  );
  if (outcome === "started" || outcome === "running") {
    iterationScreen.value = null;
    await completeRequest();
    await revealIteration();
    return;
  }
  if (outcome === "pending") {
    localError.value = copy.value.iterationPending;
  } else if (outcome === "invalid") {
    localError.value = generationFailureText("ITERATION_REQUEST_INVALID", props.locale);
  } else if (outcome === "unavailable") {
    localError.value = generationFailureText("GENERATED_MOCKUP_REQUIRED", props.locale);
  } else if (outcome === "refused") {
    await revealIteration();
  }
}

async function requestChanges(note: string): Promise<void> {
  const text = note.trim();
  if (text.length === 0 || deciding.value || store.isBusy) {
    return;
  }
  deciding.value = true;
  try {
    if (iterationMode.value) {
      await startIteration(text);
    } else {
      await requestRevision(text);
    }
  } finally {
    deciding.value = false;
  }
}

function onBarClick(event: MouseEvent): void {
  if (event.target instanceof Element && event.target.closest("[data-testid='decision-cancel']")) {
    closeRequest();
  }
}

function onBarKeydown(event: KeyboardEvent): void {
  if (
    event.key === "Escape" &&
    event.target instanceof Element &&
    event.target.closest("[data-testid='decision-note']")
  ) {
    closeRequest();
  }
}

async function applyIteration(generationId: string): Promise<void> {
  const result = iterations.result;
  if (deciding.value || store.isBusy || result === null || result.generation_id !== generationId) {
    return;
  }
  if (!iterations.isApplicable) {
    localError.value = copy.value.iterationStale;
    return;
  }
  deciding.value = true;
  try {
    if (await applyPackage(result.package, copy.value.iterationApplyFailed, true)) {
      iterations.settleApplied();
      iterationScreen.value = null;
    }
  } finally {
    deciding.value = false;
  }
}

function discardIteration(): void {
  iterations.discard();
  iterationScreen.value = null;
}

async function retryIteration(): Promise<void> {
  if (deciding.value) {
    return;
  }
  await iterations.retry(authorizedRequest, {
    api: iterationsApi.value,
    mockupsApi: mockupsApi.value,
    signal: lifetime.signal,
  });
}

async function removeAssertion(rule: string): Promise<void> {
  const version = current.value;
  if (version === null || deciding.value || store.isBusy) {
    return;
  }
  deciding.value = true;
  try {
    await applyPackage(
      {
        ...version.package,
        owner_assertions: (version.package.owner_assertions ?? []).filter((item) => item !== rule),
      },
      copy.value.ruleFailed,
      false,
    );
  } finally {
    deciding.value = false;
  }
}

function prefersReducedMotion(): boolean {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

async function revealIteration(): Promise<void> {
  await nextTick();
  iterationSection.value?.scrollIntoView?.({
    block: "start",
    behavior: prefersReducedMotion() ? "auto" : "smooth",
  });
}

async function openMockup(alternativeId: string): Promise<void> {
  const alternative = alternatives.value.find((item) => item.id === alternativeId);
  if (alternative === undefined) {
    return;
  }
  if (!generatedPath.value) {
    await openDeclarative(alternativeId);
    return;
  }
  const chosen = alternativeId === chosenAlternativeId.value && appliedGenerated.value;
  const source: DialogSource =
    chosen && reviewRun.value !== null && reviewPins.value !== null
      ? "review"
      : chosen
        ? "applied"
        : "latest";
  dialog.value = {
    alternativeId,
    source,
    revision: null,
    entryScreen: null,
    title: `${alternative.code} · ${alternative.title}`,
  };
  await loadDialogDocument();
}

async function openIterationSide(side: IterationSide, screen: string): Promise<void> {
  const alternative = chosenAlternative.value;
  const result = iterations.result;
  if (alternative === null || (side === "after" && result === null)) {
    return;
  }
  dialog.value = {
    alternativeId: alternative.id,
    source: side === "before" ? "applied" : "latest",
    revision: side === "after" && result !== null ? result.generation_id : null,
    entryScreen: screen,
    title: `${alternative.code} · ${alternative.title}`,
  };
  await loadDialogDocument();
}

async function loadDialogDocument(): Promise<void> {
  const state = dialog.value;
  if (state === null) {
    return;
  }
  const sequence = ++dialogSequence;
  dialogBusy.value = true;
  const entry = state.entryScreen === null ? {} : { entryScreen: state.entryScreen };
  try {
    const reviewing = state.source === "review" ? reviewRun.value : null;
    if (reviewing !== null) {
      await mockups.loadReviewDocument(reviewing.id, authorizedRequest, {
        api: pinsApi.value,
        ...entry,
      });
    } else {
      await mockups.loadDocument(state.alternativeId, authorizedRequest, {
        api: mockupsApi.value,
        source: state.source === "applied" ? "applied" : "latest",
        ...entry,
        ...(state.revision === null ? {} : { revision: state.revision }),
      });
    }
  } catch {
    return;
  } finally {
    if (sequence === dialogSequence) {
      dialogBusy.value = false;
    }
  }
}

function onDialogScreen(code: string): void {
  if (dialog.value === null) {
    return;
  }
  dialog.value = { ...dialog.value, entryScreen: code };
  void loadDialogDocument();
}

function closeDialog(): void {
  dialogSequence++;
  dialog.value = null;
  dialogBusy.value = false;
}

async function openDeclarative(alternativeId: string): Promise<void> {
  previewAlternativeId.value = alternativeId;
  const entry = declarative[alternativeId];
  if (entry === undefined || entry.status === "error") {
    await loadDeclarative(alternativeId);
  }
  await nextTick();
  previewSection.value?.scrollIntoView?.({
    block: "start",
    behavior: prefersReducedMotion() ? "auto" : "smooth",
  });
}

async function loadDeclarative(alternativeId: string): Promise<void> {
  const version = current.value;
  if (version === null) {
    return;
  }
  const epoch = declarativeEpoch;
  const projectId = props.projectId;
  declarative[alternativeId] = {
    status: "loading",
    mockup: declarative[alternativeId]?.mockup ?? null,
  };
  try {
    const saved = await authorizedRequest((token) =>
      api.value.currentMockup(projectId, alternativeId, token),
    );
    if (epoch === declarativeEpoch) {
      declarative[alternativeId] = { status: saved === null ? "none" : "ready", mockup: saved };
    }
  } catch {
    if (epoch === declarativeEpoch) {
      declarative[alternativeId] = { status: "error", mockup: null };
    }
  }
}

async function createDeclarative(alternativeId: string): Promise<void> {
  const version = current.value;
  if (version === null || declarativeBusy.value !== null || store.isBusy) {
    return;
  }
  const epoch = ++declarativeEpoch;
  const projectId = props.projectId;
  declarativeBusy.value = alternativeId;
  localError.value = null;
  try {
    const result = await authorizedRequest((token) =>
      api.value.generateMockup(
        projectId,
        {
          design_version_id: version.id,
          design_content_hash: version.content_hash,
          alternative_id: alternativeId,
        },
        token,
      ),
    );
    if (epoch === declarativeEpoch) {
      declarative[alternativeId] = { status: "ready", mockup: result };
    }
  } catch (error) {
    if (epoch === declarativeEpoch) {
      localError.value =
        error instanceof Error
          ? (modelFeedback(error.message, props.locale) ?? error.message)
          : copy.value.loadError;
    }
  } finally {
    if (epoch === declarativeEpoch) {
      declarativeBusy.value = null;
    }
  }
}

async function retryMockup(alternativeId: string): Promise<void> {
  const alternative = alternatives.value.find((item) => item.id === alternativeId);
  if (alternative === undefined) {
    return;
  }
  const want = thumbnailWant(alternative);
  const entry = mockups.entry(alternativeId);
  const unreadable = thumbnails[want.key] === "failed";
  delete thumbnails[want.key];
  if (unreadable && entry.state !== "rejected" && entry.state !== "failed") {
    return;
  }
  await mockups.retry(alternativeId, authorizedRequest, {
    api: mockupsApi.value,
    signal: lifetime.signal,
  });
}

function loadThumbnail(want: ThumbnailWant): void {
  if (thumbnails[want.key] !== undefined) {
    return;
  }
  if (mockups.documentFor(want.alternativeId, { source: want.source }) !== null) {
    return;
  }
  thumbnails[want.key] = "loading";
  mockups
    .loadDocument(want.alternativeId, authorizedRequest, {
      api: mockupsApi.value,
      source: want.source,
    })
    .then(
      () => {
        delete thumbnails[want.key];
      },
      (error: unknown) => {
        thumbnails[want.key] = errorStatusOf(error) === 404 ? "missing" : "failed";
      },
    );
}

async function loadPins(force = false): Promise<void> {
  const run = reviewRun.value;
  if (run === null || !generatedPath.value || !appliedGenerated.value) {
    return;
  }
  try {
    await mockups.loadReviewPins(run.id, authorizedRequest, { api: pinsApi.value, force });
  } catch {
    return;
  }
}

async function loadUsage(): Promise<void> {
  const sequence = ++usageSequence;
  const projectId = props.projectId;
  try {
    const payload = await authorizedRequest((token) => usageApi.value.usage(projectId, token));
    if (sequence === usageSequence) {
      usage.value = payload;
    }
  } catch {
    if (sequence === usageSequence) {
      usage.value = null;
    }
  }
}

function holdThumbnail(alternativeId: string): void {
  ensuring[alternativeId] = (ensuring[alternativeId] ?? 0) + 1;
}

function releaseThumbnail(alternativeId: string): void {
  const remaining = (ensuring[alternativeId] ?? 1) - 1;
  if (remaining > 0) {
    ensuring[alternativeId] = remaining;
  } else {
    delete ensuring[alternativeId];
  }
}

async function prepareMockups(): Promise<void> {
  const version = current.value;
  if (version === null || !stepShown.value || !props.active) {
    return;
  }
  const key = `${version.id}|${version.content_hash}`;
  if (prepared.has(key)) {
    return;
  }
  prepared.add(key);
  const alternativeIds = version.package.alternatives.map((alternative) => alternative.id);
  alternativeIds.forEach(holdThumbnail);
  const loaded = await mockups.loadCapabilities(authorizedRequest, { api: mockupsApi.value });
  if (current.value?.id !== version.id || current.value.content_hash !== version.content_hash) {
    alternativeIds.forEach(releaseThumbnail);
    return;
  }
  if (loaded?.generated_mockups === true) {
    const draw = mockups.wasPrepared(props.projectId, version.id, version.content_hash);
    for (const alternative of version.package.alternatives) {
      void mockups
        .ensure(alternative.id, authorizedRequest, {
          api: mockupsApi.value,
          signal: lifetime.signal,
          draw,
        })
        .then(
          (outcome) => {
            if (outcome === "missing" || outcome === "chosen") {
              thumbnails[thumbnailWant(alternative).key] = "missing";
            }
          },
          () => undefined,
        )
        .finally(() => {
          releaseThumbnail(alternative.id);
        });
    }
    if (loaded.iterations) {
      void iterations.recover(authorizedRequest, {
        api: iterationsApi.value,
        mockupsApi: mockupsApi.value,
        signal: lifetime.signal,
      });
      void iterations
        .loadList(authorizedRequest, { api: iterationsApi.value })
        .catch(() => undefined);
    }
  } else {
    alternativeIds.forEach(releaseThumbnail);
    for (const alternative of version.package.alternatives) {
      void loadDeclarative(alternative.id);
    }
    const chosen = version.package.owner_selected_alternative_id;
    if (previewAlternativeId.value === null && chosen !== null) {
      previewAlternativeId.value = chosen;
    }
  }
  void loadUsage();
}

function selectCell(selection: TwinMatrixSelection): void {
  selectedCell.value = selection;
  observationsOpen.value = true;
}

async function validate(finding: ObservationFinding, confirmed: boolean): Promise<void> {
  const runId = observation.value?.runId ?? null;
  if (runId === null || loopStore.validating !== null) {
    return;
  }
  const key = findingKey(runId, finding.twin_id, finding.finding_id);
  validationFailure.value = null;
  try {
    await loopStore.validate(
      props.projectId,
      runId,
      {
        twin_id: finding.twin_id,
        finding_id: finding.finding_id,
        decision: confirmed ? "OWNER_CONFIRMED" : "OWNER_DISMISSED",
        note: null,
      },
      authorizedRequest,
      loop.value,
    );
  } catch {
    validationFailure.value = {
      key,
      code: loopStore.validationError ?? "DESIGN_LOOP_REQUEST_FAILED",
    };
    observationsOpen.value = true;
  }
}

function briefFieldOf(request: ObservationInsightRequest): InsightBriefField {
  const runId = observation.value?.runId ?? "";
  const finding = observation.value?.findings?.find(
    (item) => `run:${runId}:${item.twin_id}:${item.finding_id}` === request.source.id,
  );
  return finding !== undefined && NON_FUNCTIONAL_CRITERIA.has(finding.criterion)
    ? "non_functional_requirements"
    : "functional_requirements";
}

async function applyInsight(request: ObservationInsightRequest): Promise<void> {
  if (applyingSource.value !== null) {
    return;
  }
  applyFailure.value = null;
  const source = request.source;
  if (request.target === "BRIEF") {
    tray.add(props.projectId, {
      sourceKind: source.kind,
      sourceId: source.id,
      sourceTwinId: source.twinId,
      text: source.text,
      briefField: briefFieldOf(request),
    });
    return;
  }
  applyingSource.value = source.id;
  try {
    const application = await loopStore.apply(
      props.projectId,
      {
        source_kind: source.kind,
        source_id: source.id,
        source_twin_id: source.twinId,
        text: source.text,
        target: request.target,
        brief_field: null,
        mitigation: source.mitigation,
      },
      authorizedRequest,
      loop.value,
    );
    await onInsightApplied(application);
  } catch {
    applyFailure.value = { id: source.id, code: loopStore.error ?? "DESIGN_LOOP_REQUEST_FAILED" };
    observationsOpen.value = true;
  } finally {
    applyingSource.value = null;
  }
}

function rendered(element: Element): boolean {
  return typeof element.checkVisibility !== "function" || element.checkVisibility();
}

function refreshTargets(): void {
  const element = root.value;
  const visible = props.active && element !== null && element.isConnected && rendered(element);
  const bar = document.getElementById(BAR_TARGET);
  const row = document.getElementById(ROW_TARGET);
  const nextBar = visible && bar !== null && rendered(bar) ? bar : null;
  const nextRow = visible && row !== null && rendered(row) ? row : null;
  if (barTarget.value !== nextBar) {
    barTarget.value = nextBar;
  }
  if (rowTarget.value !== nextRow) {
    rowTarget.value = nextRow;
  }
  const shown = props.active && element !== null && (!element.isConnected || rendered(element));
  if (stepShown.value !== shown) {
    stepShown.value = shown;
  }
}

async function refreshWhenDrawn(): Promise<void> {
  await nextTick();
  refreshTargets();
}

watch(
  () => props.projectId,
  async () => {
    reviewRequestedFor.value = null;
    observationsOpen.value = false;
    if (props.autoLoad) {
      await load();
    }
  },
  { immediate: true },
);

watchUpstream(
  () => props.upstream,
  (changed) => {
    if (!changed) {
      return;
    }
    nextStepRefresh.value++;
    if (props.autoLoad) {
      void load();
    }
  },
);

watch(
  () => [props.projectId, current.value?.id, current.value?.content_hash] as const,
  () => {
    const version = current.value;
    if (version !== null && preparation !== null && versionKey(version) !== preparation.from) {
      mockups.markPrepared(props.projectId, version.id, version.content_hash);
      preparation = null;
    }
    mockups.activate(props.projectId, version);
    iterations.activate(props.projectId, version);
    selectedCell.value = null;
    void prepareMockups();
  },
  { immediate: true },
);

watch(
  () => [thumbnailWants.value, stepShown.value] as const,
  ([wants, shown]) => {
    if (!shown || !props.active) {
      return;
    }
    for (const want of wants) {
      loadThumbnail(want);
    }
  },
  { immediate: true },
);

watch(stepShown, (shown) => {
  if (shown) {
    void prepareMockups();
  }
});

watch(() => props.active, refreshWhenDrawn);

watch(
  () => [iterations.state, iterations.result?.generation_id, iterationScreen.value] as const,
  ([state, generationId, screen]) => {
    const alternativeId = chosenAlternativeId.value;
    if (state !== "ready" || generationId === undefined || alternativeId === null) {
      return;
    }
    const entry = screen === null ? {} : { entryScreen: screen };
    void mockups
      .loadDocument(alternativeId, authorizedRequest, {
        api: mockupsApi.value,
        source: "applied",
        ...entry,
      })
      .catch(() => undefined);
    void mockups
      .loadDocument(alternativeId, authorizedRequest, {
        api: mockupsApi.value,
        source: "latest",
        revision: generationId,
        ...entry,
      })
      .catch(() => undefined);
  },
  { immediate: true },
);

watch(
  () => [reviewRun.value?.id ?? null, generatedPath.value, appliedGenerated.value] as const,
  () => {
    void loadPins();
  },
  { immediate: true },
);

watch(dismissedSignature, (signature, previous) => {
  const run = reviewRun.value;
  if (run === null || previous === undefined || signature === previous) {
    return;
  }
  mockups.forgetReview(run.id);
  void loadPins(true);
});

watch(
  () =>
    alternatives.value
      .map((alternative) => mockups.entry(alternative.id).state)
      .concat(iterations.state)
      .join("|"),
  (signature, previous) => {
    if (previous !== undefined && signature !== previous && generatedPath.value) {
      void loadUsage();
    }
  },
);

watch(
  () => loopStore.lastApplication,
  (application) => {
    if (application !== null && loopStore.projectId === props.projectId) {
      void onInsightApplied(application);
    }
  },
);

watch(secondaryLabel, (label) => {
  if (label === null) {
    closeRequest();
  }
});

onMounted(() => {
  refreshTargets();
  void refreshWhenDrawn();
  if (typeof ResizeObserver === "undefined" || root.value === null) {
    return;
  }
  visibility = new ResizeObserver(refreshTargets);
  visibility.observe(root.value);
});

onUpdated(refreshTargets);

onBeforeUnmount(() => {
  lifetime.abort();
  visibility?.disconnect();
  declarativeEpoch++;
  dialogSequence++;
});
</script>

<template>
  <section
    ref="root"
    class="grid gap-6 text-on-night"
    data-testid="design-flow"
    :aria-busy="store.isBusy ? 'true' : undefined"
  >
    <UiStateBlock
      v-if="errorMessage !== null"
      kind="error"
      :title="errorMessage"
      data-testid="design-error"
    />

    <UiStateBlock
      v-if="current === null && store.pending.load"
      kind="loading"
      :title="copy.loading"
    />

    <section
      v-else-if="current === null"
      class="grid gap-5 rounded-tile border border-night-line bg-night-raised p-5 sm:p-7"
      data-testid="design-empty"
    >
      <UiAgentMessage :role-label="copy.designer" :avatar="DESIGNER_AVATAR">
        {{ copy.noPackage }}
      </UiAgentMessage>
      <p v-if="!prerequisiteReady" class="m-0 text-sm text-on-night-3" role="status">
        {{ copy.prerequisite }}
      </p>
      <GenerationJobNotice
        v-if="designJob !== null || designJobFailure !== null"
        :job="designJob"
        :failure="designJobFailure"
        :locale="locale"
        @dismiss="dismissDesignJob"
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
        :disabled="store.isBusy || !prerequisiteReady || designJob !== null"
        data-testid="generate-design"
        @click="generate"
      >
        {{ copy.generate }}
      </UiButton>
    </section>

    <template v-else>
      <UiAgentMessage :role-label="copy.designer" :avatar="DESIGNER_AVATAR">
        {{ agentText }}
      </UiAgentMessage>

      <div class="flex flex-wrap items-center gap-x-4 gap-y-3" data-testid="design-toolbar">
        <ArtifactViewSwitch
          ref="viewSwitch"
          v-model="view"
          :locale="locale"
          :label="copy.viewLabel"
          :panel-id="viewPanelId"
        />
      </div>

      <DesignTableView
        v-if="view === 'table'"
        :id="viewPanelId"
        role="tabpanel"
        :aria-labelledby="viewSwitch?.tabId('table')"
        :design="current.package"
        :requirements="requirementsSpecification"
        :locale="locale"
        data-testid="design-table-view"
      />
      <ProjectDiagramsView
        v-else-if="view === 'diagram'"
        :id="viewPanelId"
        role="tabpanel"
        :aria-labelledby="viewSwitch?.tabId('diagram')"
        :project-id="projectId"
        stage="design"
        :locale="locale"
        :refresh-key="current.content_hash"
        :authorize="authorize"
        data-testid="design-diagram-view"
      />

      <div
        v-show="view === 'text'"
        :id="view === 'text' ? viewPanelId : undefined"
        :role="view === 'text' ? 'tabpanel' : undefined"
        :aria-labelledby="view === 'text' ? viewSwitch?.tabId('text') : undefined"
        class="grid gap-6"
        data-testid="design-text-view"
      >
        <section
          v-if="store.pendingDiffs.length > 0"
          class="grid gap-3"
          :aria-labelledby="`${uid}-pending`"
          data-testid="design-pending-changes"
        >
          <h2 :id="`${uid}-pending`" class="m-0 text-lg font-semibold">
            {{ store.pendingDiffs.length === 1 ? copy.pendingTitle[0] : copy.pendingTitle[1] }}
          </h2>
          <article
            v-for="diff in store.pendingDiffs"
            :key="diff.id"
            class="grid gap-4 rounded-tile border border-night-line-strong bg-night-raised p-5"
            data-testid="design-pending-change"
          >
            <ul class="m-0 grid list-disc gap-1.5 pl-5 text-[15px] leading-normal">
              <li
                v-for="change in diff.changes"
                :key="`${change.artifact_kind}:${change.artifact_id}:${change.kind}`"
                data-testid="design-change"
              >
                {{ designChangeSentence(change, [diff.proposed_package, current.package], locale) }}
                <blockquote
                  v-if="designChangeQuote(change) !== null"
                  :class="['mt-1 text-sm', QUOTE_CLASS]"
                  data-testid="design-change-quote"
                >
                  {{ designChangeQuote(change) }}
                </blockquote>
              </li>
            </ul>
            <label class="grid gap-1.5 text-sm font-medium text-on-night-2">
              {{ copy.diffReason }}
              <textarea
                v-model="diffReasons[diff.id]"
                rows="2"
                class="min-h-11 rounded-field border border-night-line-strong bg-night-panel px-3 py-2.5 text-[15px] font-normal text-on-night"
              />
            </label>
            <div class="flex flex-wrap gap-3">
              <UiButton
                variant="pill"
                :disabled="store.isBusy || deciding"
                data-testid="approve-design-diff"
                @click="decideDiff(diff, true)"
              >
                {{ copy.applyDiff }}
              </UiButton>
              <UiButton
                variant="quiet"
                :disabled="
                  store.isBusy || deciding || (diffReasons[diff.id] ?? '').trim().length === 0
                "
                data-testid="reject-design-diff"
                @click="decideDiff(diff, false)"
              >
                {{ copy.rejectDiff }}
              </UiButton>
            </div>
          </article>
        </section>

        <div v-if="iterationVisible" ref="iterationSection" class="scroll-mt-24">
          <DesignIterationPanel
            :job="iterationJob"
            :request="iterations.request?.request ?? null"
            :items="iterations.items"
            :before="iterationBefore"
            :after="iterationAfter"
            :assertions="current.package.owner_assertions ?? []"
            :error="iterationError"
            :busy="deciding || store.isBusy"
            :screens="iterationScreens"
            :workflows="chosenWorkflows"
            :locale="locale"
            @apply="applyIteration"
            @discard="discardIteration"
            @remove-assertion="removeAssertion"
            @open="openIterationSide"
            @retry="retryIteration"
            @screen="iterationScreen = $event"
          />
        </div>

        <DesignAlternativeComparison
          :alternatives="current.package.alternatives"
          :version-number="current.version_number"
          :content-hash="current.content_hash"
          :twins="current.package.grounding.user_twin_references"
          :recommended-alternative-id="current.package.recommended_alternative_id"
          :selected-alternative-id="chosenAlternativeId"
          :previews="previews"
          :choosable="choosable"
          :hints="hints"
          :notes="cardNotes"
          :choosing="choosing"
          :disabled="store.isBusy || deciding"
          :paid="mockupsPaid"
          :locale="locale"
          @select="choose"
          @open="openMockup"
          @retry="retryMockup"
        />

        <section
          v-if="!generatedPath && previewAlternative !== null"
          ref="previewSection"
          class="grid scroll-mt-24 gap-3 rounded-tile border border-night-line bg-night-raised p-4 sm:p-6"
          :aria-labelledby="`${uid}-preview`"
          data-design-mockup
          data-testid="design-preview"
        >
          <div class="flex flex-wrap items-center gap-3">
            <h2 :id="`${uid}-preview`" class="m-0 min-w-0 flex-1 text-lg font-semibold">
              {{
                fill(copy.previewTitle, {
                  alternative: `${previewAlternative.code} · ${previewAlternative.title}`,
                })
              }}
            </h2>
            <UiButton
              variant="quiet"
              data-testid="design-preview-close"
              @click="previewAlternativeId = null"
            >
              {{ copy.closePreview }}
            </UiButton>
          </div>
          <template v-if="previewContent !== null">
            <p
              :class="[
                'm-0 text-xs font-semibold',
                previewContent.draft ? 'text-violet-on-night-2' : 'text-petrol-on-night-2',
              ]"
            >
              {{ previewContent.draft ? copy.previewDraft : copy.previewCurrent }}
            </p>
            <p class="m-0 text-sm leading-normal text-on-night-3">{{ copy.previewHelp }}</p>
            <DeclarativePrototypePreview
              :key="previewContent.generationId ?? previewContent.prototype.id"
              :prototype="previewContent.prototype"
              :visual="previewAlternative.visual_language"
              :locale="locale"
            />
          </template>
          <UiStateBlock
            v-else-if="declarative[previewAlternative.id]?.status === 'loading'"
            kind="loading"
          />
          <div v-else class="grid gap-3" data-testid="design-preview-missing">
            <p class="m-0 text-[15px] text-on-night-2">
              {{
                declarative[previewAlternative.id]?.status === "error"
                  ? copy.previewError
                  : copy.previewMissing
              }}
            </p>
            <UiButton
              v-if="declarative[previewAlternative.id]?.status === 'error'"
              variant="outline"
              class="justify-self-start"
              @click="loadDeclarative(previewAlternative.id)"
            >
              {{ copy.reloadPreview }}
            </UiButton>
            <UiButton
              v-else
              variant="outline"
              class="justify-self-start"
              :disabled="declarativeBusy !== null || store.isBusy"
              data-testid="design-create-preview"
              @click="createDeclarative(previewAlternative.id)"
            >
              {{ copy.createMockup }}
            </UiButton>
            <UiStateBlock
              v-if="declarativeBusy === previewAlternative.id"
              kind="loading"
              :text="generationProgress(locale)"
            />
          </div>
        </section>

        <DesignTwinMatrix
          v-if="twinReferences.length > 0 && alternatives.length > 0"
          :alternatives="matrixAlternatives"
          :twins="matrixTwins"
          :cells="matrixCells"
          :selected="activeCell"
          :locale="locale"
          @select="selectCell"
        >
          <div class="grid gap-7">
            <div v-if="observation !== null" data-testid="design-observations">
              <button
                type="button"
                class="flex min-h-12 w-full items-start gap-3 rounded-field border border-night-line-strong bg-on-night/3 px-4 py-3 text-left text-[15px] leading-6 font-semibold text-on-night transition-colors duration-150 hover:bg-night-hover"
                :aria-expanded="observationsOpen ? 'true' : 'false'"
                :aria-controls="`${uid}-observations`"
                data-testid="design-observations-toggle"
                @click="observationsOpen = !observationsOpen"
              >
                <span
                  :class="[
                    'inline-block w-3 shrink-0 text-xs leading-6 text-on-night-3 transition-transform duration-150',
                    observationsOpen ? 'rotate-90' : '',
                  ]"
                  aria-hidden="true"
                  >▸</span
                >
                <span class="min-w-0 flex-1 break-words" data-testid="design-observations-label">{{
                  observationsLabel
                }}</span>
              </button>
              <div :id="`${uid}-observations`" data-testid="design-observations-region">
                <DesignObservationList
                  v-if="observationsOpen"
                  class="mt-4"
                  :twin="observation.twin"
                  :alternative="observation.alternative"
                  :run-id="observation.runId"
                  :findings="observation.findings"
                  :critique="observation.critique"
                  :validations="observationValidations"
                  :validating="loopStore.validating"
                  :failure="validationFailure"
                  :applied="appliedInsights"
                  :applying="applyingSource"
                  :apply-failure="applyFailure"
                  :screens="observation.screens"
                  :elements="observation.elements"
                  :workflows="observation.workflows"
                  :locale="locale"
                  @confirm="validate($event, true)"
                  @dismiss="validate($event, false)"
                  @apply-insight="applyInsight"
                />
              </div>
            </div>
            <div v-if="current.package.prototype" class="grid gap-3">
              <p
                v-if="reanchoredWithoutReview"
                class="m-0 rounded-field border border-petrol-on-night/35 bg-petrol-on-night/8 px-4 py-3 text-sm leading-normal text-on-night-2"
                data-testid="design-reanchored-review"
              >
                {{ copy.reanchoredReview }}
              </p>
              <ProjectDesignEvaluationPanel
                :project-id="projectId"
                :design-version-id="current.id"
                :design-content-hash="current.content_hash"
                :twin-names="twinNames"
                :locale="locale"
                :authorize="authorizedRequest"
                :api="props.loopApi"
                :auto-evaluate-version-id="reviewRequestedFor"
                :static-check-available="staticCheckAvailable"
                :screens="appliedScreens"
                :elements="reviewElements"
                :workflows="workflowsByAlternative"
                @applied="onInsightApplied"
              />
            </div>
          </div>
        </DesignTwinMatrix>
        <p
          v-else-if="alternatives.length > 0"
          class="m-0 text-sm text-on-night-3"
          data-testid="design-matrix-empty"
        >
          {{ copy.matrixEmpty }}
        </p>

        <ProjectDesignDiscussionPanel
          v-if="current.package.prototype"
          :project-id="projectId"
          :design-version-id="current.id"
          :design-content-hash="current.content_hash"
          :twin-names="twinNames"
          :screens="appliedScreens"
          :elements="reviewElements"
          :workflows="workflowsByAlternative"
          :locale="locale"
          :authorize="authorizedRequest"
          :api="props.loopApi"
          @applied="onInsightApplied"
        />

        <details
          v-if="concernCount > 0"
          class="group rounded-tile border border-night-line bg-night-raised"
          data-testid="design-concerns"
        >
          <summary
            class="flex min-h-12 cursor-pointer list-none items-center gap-3 px-5 py-3 [&::-webkit-details-marker]:hidden"
          >
            <span
              class="inline-block text-xs text-on-night-3 group-open:rotate-90"
              aria-hidden="true"
              >▸</span
            >
            <span class="text-[15px] font-semibold">
              {{ fill(copy.concernsTitle, { n: concernCount }) }}
            </span>
          </summary>
          <div class="grid gap-5 border-t border-night-line px-5 py-4 lg:grid-cols-2">
            <section v-if="current.package.concerns.length > 0" class="grid content-start gap-2">
              <h3 class="m-0 text-sm font-semibold">{{ copy.concerns }}</h3>
              <ul class="m-0 grid list-none gap-2 p-0">
                <li
                  v-for="concern in current.package.concerns"
                  :key="concern.id"
                  class="rounded-field border border-warn-on-night/30 bg-warn-on-night/6 px-4 py-3 text-sm leading-normal"
                >
                  <p class="m-0 font-semibold text-warn-on-night">{{ concern.summary }}</p>
                  <p class="m-0 mt-1 text-on-night-2">
                    {{ copy.remedy }}: {{ concern.mitigation }}
                  </p>
                </li>
              </ul>
            </section>
            <section
              v-if="current.package.open_questions.length > 0"
              class="grid content-start gap-2"
            >
              <h3 class="m-0 text-sm font-semibold">{{ copy.openQuestions }}</h3>
              <ul class="m-0 list-disc space-y-1.5 pl-5 text-sm leading-normal text-on-night-2">
                <li v-for="question in current.package.open_questions" :key="question">
                  {{ question }}
                </li>
              </ul>
            </section>
          </div>
        </details>

        <section
          v-if="current.package.prototype && pendingDiff === null"
          class="grid gap-3"
          data-design-regenerate
        >
          <DesignLoopNextStep
            :project-id="projectId"
            :design-requirements-version-id="
              current.package.grounding.requirements_reference.artifact_id
            "
            :design-version-id="current.id"
            :design-approved="decisionState === 'approved'"
            :refresh-key="nextStepRefresh"
            :busy="store.isBusy || deciding || loopStore.isBusy || designJob !== null"
            :locale="locale"
            :authorize="authorizedRequest"
            :api="props.requirementsApi"
            :alignment-api="props.alignmentApi"
            @regenerate="regenerate"
            @reapproved="onReapproved"
          >
            <div class="flex flex-wrap items-center gap-4 text-sm text-on-night-3">
              <span class="min-w-[min(100%,16rem)] flex-1 leading-normal">
                {{ copy.regenerateText }}
              </span>
              <UiButton
                variant="outline"
                :disabled="store.isBusy || deciding || loopStore.isBusy || designJob !== null"
                data-testid="design-regenerate"
                @click="regenerate"
              >
                {{ copy.regenerate }}
              </UiButton>
            </div>
          </DesignLoopNextStep>
          <GenerationJobNotice
            v-if="designJob !== null || designJobFailure !== null"
            :job="designJob"
            :failure="designJobFailure"
            :locale="locale"
            @dismiss="dismissDesignJob"
          />
          <UiStateBlock
            v-else-if="loopStore.busy === 'regenerate'"
            kind="loading"
            :title="copy.regenerating"
            :text="generationProgress(locale)"
            data-testid="design-regenerating"
          />
        </section>
      </div>

      <p
        v-if="decisionState === 'approved'"
        class="m-0 flex items-center gap-2.5 text-[15px] font-semibold text-petrol-on-night-2"
        data-testid="design-readiness"
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
        data-testid="design-gate-paused"
      >
        <p class="m-0 min-w-0 flex-[1_1_260px] text-[15px]">{{ copy.pausedText }}</p>
        <UiButton variant="outline" :disabled="store.isBusy" @click="decideGate('CANCEL')">
          {{ copy.cancelGate }}
        </UiButton>
        <UiButton
          variant="pill"
          :disabled="store.isBusy"
          data-testid="resume-design-gate"
          @click="decideGate('RESUME')"
        >
          {{ copy.resume }}
        </UiButton>
      </div>

      <div
        v-if="decisionState === 'revision' || decisionState === 'closed'"
        class="grid gap-2 rounded-panel border border-night-line-strong bg-night-raised px-5 py-4"
        data-testid="design-gate-closed"
      >
        <p class="m-0 text-[15px] font-semibold">{{ closedTitle }}</p>
        <div v-if="closedNote.length > 0" class="grid gap-1" data-testid="design-gate-note">
          <p class="m-0 text-xs font-semibold text-on-night-3">{{ copy.yourNote }}</p>
          <blockquote :class="['text-sm', QUOTE_CLASS]">{{ closedNote }}</blockquote>
        </div>
        <p class="m-0 text-sm leading-normal text-on-night-3">{{ copy.closedText }}</p>
      </div>

      <details
        v-if="gatePending"
        class="rounded-panel border border-night-line"
        data-testid="design-more-actions"
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
              data-testid="design-gate-reason"
            />
          </label>
          <div class="flex flex-wrap gap-3">
            <UiButton
              variant="danger"
              :disabled="store.isBusy || gateReason.trim().length === 0"
              data-testid="reject-design-gate"
              @click="decideGate('REJECT')"
            >
              {{ copy.rejectGate }}
            </UiButton>
            <UiButton
              v-if="iterationMode"
              variant="outline"
              :disabled="store.isBusy || gateReason.trim().length === 0"
              data-testid="request-design-revision"
              @click="decideGate('REQUEST_REVISION')"
            >
              {{ copy.requestRevision }}
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
          :secondary-label="secondaryLabel"
          :request-placeholder="
            iterationMode ? copy.iterationPlaceholder : copy.revisionPlaceholder
          "
          :busy="store.isBusy || deciding"
          :disabled="decisionState !== 'approve'"
          @primary="approve"
          @secondary="requestOpen = true"
          @request="requestChanges"
          @click="onBarClick"
          @keydown="onBarKeydown"
        >
          <label
            v-if="requestOpen && iterationMode"
            class="mt-2 flex min-h-11 cursor-pointer items-center gap-2.5 text-sm text-on-night-2"
            data-testid="design-request-rule"
          >
            <input
              v-model="keepAsRule"
              type="checkbox"
              class="h-5 w-5 shrink-0 accent-petrol-on-night"
              :aria-describedby="`${uid}-rule-hint`"
              data-testid="design-request-rule-input"
            />
            <span>
              {{ copy.keepRule }}
              <span :id="`${uid}-rule-hint`" class="block text-xs text-on-night-3">
                {{ copy.keepRuleHint }}
              </span>
            </span>
          </label>
        </UiDecisionBar>
      </Teleport>

      <Teleport :to="rowTarget" :disabled="rowTarget === null">
        <UiTechnicalDetails :summary="technicalSummary" :rows="technicalRows">
          <p class="m-0 text-[13px] leading-normal text-on-night-3">{{ copy.methodology }}</p>
          <section v-if="store.history.length > 0" class="grid gap-2">
            <h2 class="m-0 text-sm font-semibold">{{ copy.history }}</h2>
            <ol class="m-0 grid list-none gap-1.5 p-0">
              <li
                v-for="version in store.history"
                :key="version.id"
                class="grid gap-0.5 sm:grid-cols-[200px_minmax(0,1fr)] sm:gap-x-5"
              >
                <span class="text-on-night-2">
                  {{
                    fill(copy.historyItem, {
                      n: version.version_number,
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
          <section v-if="decidedDiffs.length > 0" class="grid gap-2">
            <h2 class="m-0 text-sm font-semibold">{{ copy.decided }}</h2>
            <ul class="m-0 grid list-none gap-2 p-0 text-[13px] text-on-night-2">
              <li
                v-for="diff in decidedDiffs"
                :key="diff.id"
                class="grid gap-0.5"
                data-testid="design-decided-change"
              >
                <span>
                  <strong class="font-semibold text-on-night">
                    {{ diff.status === "APPROVED" ? copy.applied : copy.discarded }}
                  </strong>
                  ·
                  {{
                    diff.changes
                      .map((change) =>
                        designChangeSentence(
                          change,
                          [diff.proposed_package, current?.package],
                          locale,
                        ),
                      )
                      .join("; ")
                  }}
                </span>
                <template v-for="(change, index) in diff.changes" :key="index">
                  <blockquote
                    v-if="designChangeQuote(change) !== null"
                    :class="['text-[13px]', QUOTE_CLASS]"
                    data-testid="design-decided-quote"
                  >
                    {{ designChangeQuote(change) }}
                  </blockquote>
                </template>
                <template v-if="diff.decision_reason">
                  <span class="text-xs font-semibold text-on-night-3">{{ copy.yourNote }}</span>
                  <blockquote
                    :class="['text-[13px]', QUOTE_CLASS]"
                    data-testid="design-decided-note"
                  >
                    {{ diff.decision_reason }}
                  </blockquote>
                </template>
                <span class="font-mono text-xs break-all text-on-night-3">{{ diff.id }}</span>
              </li>
            </ul>
          </section>
          <section v-if="current.package.critiques.length > 0" class="grid gap-2">
            <h2 class="m-0 text-sm font-semibold">{{ copy.provenance }}</h2>
            <ul class="m-0 grid list-none gap-1.5 p-0 text-[13px] text-on-night-2">
              <li
                v-for="critique in current.package.critiques"
                :key="critique.id"
                data-testid="critique-provenance"
              >
                <strong class="font-semibold text-on-night">
                  {{ critique.code }} · {{ critique.user_twin_reference.name }}
                </strong>
                · {{ critique.epistemic_status }} · {{ critique.human_validation }} ·
                {{ fill(copy.confidence, { value: percent(critique.confidence) }) }}
                <span class="block">{{ critique.rationale }}</span>
                <span
                  v-for="reference in critique.provenance"
                  :key="`${reference.source_kind}:${reference.source_id}:${reference.locator}`"
                  class="block font-mono text-xs break-all text-on-night-3"
                >
                  {{ reference.source_kind }} · {{ reference.source_id }}
                  <template v-if="reference.locator !== null"> · {{ reference.locator }}</template>
                </span>
              </li>
            </ul>
          </section>
          <section v-if="usage !== null && usage.items.length > 0" class="grid gap-2">
            <h2 class="m-0 text-sm font-semibold">{{ copy.usage }}</h2>
            <ul class="m-0 grid list-none gap-1 p-0 font-mono text-xs text-on-night-2">
              <li v-for="item in usage.items" :key="item.generation_id" class="break-all">
                {{
                  fill(copy.usageItem, {
                    date: formatDate(item.recorded_at),
                    purpose: item.purpose ?? item.task,
                    model: item.model,
                    status: item.status,
                  })
                }}
                ·
                {{
                  item.provider_kind === "CLAUDE_CODE_CLI"
                    ? copy.subscription
                    : money(item.cost_microusd)
                }}
                · {{ item.generation_id }}
              </li>
            </ul>
          </section>
          <section
            v-if="mockupNotes.length > 0"
            class="grid gap-2"
            data-testid="design-mockup-notes"
          >
            <h2 class="m-0 text-sm font-semibold">{{ copy.mockupNotes }}</h2>
            <p class="m-0 text-[13px] leading-normal text-on-night-3">
              {{ copy.mockupNotesIntro }}
            </p>
            <div v-for="note in mockupNotes" :key="note.id" class="grid gap-1">
              <h3 class="m-0 text-[13px] font-semibold text-on-night">{{ note.label }}</h3>
              <ul class="m-0 grid list-none gap-1 p-0 text-[13px] text-on-night-2">
                <li v-for="line in note.lines" :key="line">{{ line }}</li>
              </ul>
            </div>
          </section>
        </UiTechnicalDetails>
      </Teleport>

      <GeneratedMockupDialog
        v-if="dialog !== null"
        :title="dialog.title"
        :document="dialogDocument"
        :pins="dialogPins"
        :unanchored="dialogUnanchored"
        :observations="dialogObservations"
        :elements="reviewElements"
        :workflows="workflowsByAlternative[dialog.alternativeId] ?? []"
        :busy="dialogBusy"
        :locale="locale"
        @close="closeDialog"
        @screen="onDialogScreen"
      />
    </template>

    <p class="sr-only" role="status">
      {{ store.isBusy && !store.pending.generate && current !== null ? copy.updating : "" }}
    </p>
  </section>
</template>
