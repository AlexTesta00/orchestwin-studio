<script lang="ts">
export type IterationJobStatus = "RUNNING" | "SUCCEEDED" | "REJECTED" | "FAILED";
export type IterationJobStage = "GENERATING" | "VALIDATING" | "RETRYING";
export type IterationStatus = "PROPOSED" | "APPLIED" | "REJECTED" | "FAILED";
export type IterationSide = "before" | "after";
export type GenerationLocale = "en" | "it";

export interface IterationReason {
  code: string;
  screen_code?: string | null | undefined;
  detail?: string | undefined;
}

export interface IterationFailure {
  code: string;
  reasons: readonly IterationReason[];
}

export interface IterationResult {
  status: string;
  generation_id: string;
  design_version_id: string;
  design_content_hash: string;
  package?: unknown;
  approach: string | null;
  changes: readonly string[];
  warnings: readonly IterationReason[];
  cost_microusd: number | null;
}

export interface IterationJob {
  job_id: string;
  kind: string;
  status: IterationJobStatus;
  stage: IterationJobStage | null;
  attempt: number;
  started_at: string;
  finished_at: string | null;
  alternative_id: string | null;
  result: IterationResult | null;
  failure: IterationFailure | null;
}

export interface IterationItem {
  generation_id: string;
  requested_at: string;
  request: string;
  assertions: readonly string[];
  changes: readonly string[];
  status: IterationStatus;
  base_design_version_number: number | null;
  applied_design_version_number: number | null;
  cost_microusd: number | null;
}

type Sentences = Record<string, readonly [string, string]>;

const FAILURES: Sentences = {
  MOCKUP_QUALITY_REJECTED: [
    "The Studio discarded the answer because it did not pass the quality checks.",
    "Lo Studio ha scartato la risposta perché non superava i controlli di qualità.",
  ],
  UNSAFE_MOCKUP_OUTPUT: [
    "The answer contained elements that the Studio does not accept.",
    "La risposta conteneva elementi che lo Studio non accetta.",
  ],
  MOCKUP_LANGUAGE_MISMATCH: [
    "The screens were written in a different language from the requirements.",
    "Le schermate erano scritte in una lingua diversa da quella dei requisiti.",
  ],
  MOCKUP_SCREEN_COUNT: [
    "The number of screens did not suit this alternative.",
    "Il numero di schermate non era adatto a questa alternativa.",
  ],
  MOCKUP_COVERAGE_TOO_LOW: [
    "The screens covered fewer than half of the requirements of the alternative.",
    "Le schermate coprivano meno della metà dei requisiti dell'alternativa.",
  ],
  GENERATED_MOCKUP_REQUIRES_VISUAL_LANGUAGE: [
    "This alternative has no visual style, so its mockup cannot be drawn.",
    "Questa alternativa non ha uno stile visivo, quindi il suo mockup non si può disegnare.",
  ],
  GENERATION_BUDGET_EXCEEDED: [
    "The spending limit that is set is not enough for this generation.",
    "Il tetto di spesa impostato non basta per questa generazione.",
  ],
  TOO_MANY_GENERATIONS: [
    "Too many drawings are already in progress. Wait for one to finish and try again.",
    "Ci sono già troppi disegni in corso. Aspetta che uno finisca e riprova.",
  ],
  REAL_MOCKUP_MODEL_NOT_CONFIGURED: [
    "The model that draws the mockups is not connected.",
    "Il modello che disegna i mockup non è collegato.",
  ],
  DESIGN_CONTEXT_CHANGED: [
    "The design changed in the meantime. Reload the page and try again.",
    "Il design è cambiato nel frattempo. Ricarica la pagina e riprova.",
  ],
  GENERATED_MOCKUP_REQUIRED: [
    "To ask for changes, apply a design with its drawn mockup first.",
    "Per chiedere modifiche serve prima un design applicato con il suo mockup disegnato.",
  ],
  ITERATION_REQUEST_INVALID: [
    "The request is not valid: write from 1 to 1000 characters and at most five rules.",
    "La richiesta non è valida: scrivi da 1 a 1000 caratteri e al massimo cinque regole.",
  ],
  GENERATION_JOB_NOT_FOUND: [
    "The Studio can no longer find this drawing: it may have been restarted. Try again.",
    "Lo Studio non trova più questo disegno: forse è stato riavviato. Riprova.",
  ],
  GENERATED_MOCKUP_NOT_FOUND: [
    "The mockup of this version was not found.",
    "Il mockup di questa versione non è stato trovato.",
  ],
  DESIGN_ALTERNATIVE_NOT_FOUND: [
    "This alternative is no longer part of the design.",
    "Questa alternativa non fa più parte del design.",
  ],
  PROVIDER_UNAVAILABLE: [
    "The model cannot be reached right now. Try again in a few minutes.",
    "Il modello non è raggiungibile in questo momento. Riprova tra qualche minuto.",
  ],
  TIMEOUT: [
    "The model took too long to answer. Try again.",
    "Il modello ha impiegato troppo tempo a rispondere. Riprova.",
  ],
  INCOMPLETE_OUTPUT: [
    "The model did not finish its answer. Try again.",
    "Il modello non ha finito la risposta. Riprova.",
  ],
  INVALID_PROVIDER_OUTPUT: [
    "The model returned an answer that cannot be read. Try again.",
    "Il modello ha restituito una risposta che non si può leggere. Riprova.",
  ],
  GENERATION_BUDGET_UNAVAILABLE: [
    "The Studio could not check the spending ceiling, so it did not start the drawing. Try again in a moment.",
    "Lo Studio non è riuscito a controllare il tetto di spesa, quindi non ha avviato il disegno. Riprova tra qualche istante.",
  ],
  GENERATION_POLL_TIMEOUT: [
    "The drawing has been running for more than twenty minutes. Try again to check whether it is ready.",
    "Il disegno dura da più di venti minuti. Riprova per controllare se è pronto.",
  ],
  GENERATION_STATUS_UNAVAILABLE: [
    "The Studio did not say how the drawing is going. Try again in a moment.",
    "Lo Studio non ha detto a che punto è il disegno. Riprova tra qualche istante.",
  ],
  GENERATION_START_FAILED: [
    "The drawing could not be started. Try again in a moment.",
    "Non è stato possibile avviare il disegno. Riprova tra qualche istante.",
  ],
  GENERATION_FAILED: [
    "The drawing did not succeed. You can try again.",
    "Il disegno non è riuscito. Puoi riprovare.",
  ],
  MOCKUP_STATUS_UNAVAILABLE: [
    "The Studio could not check whether a mockup already exists, so it did not draw a new one. Try again in a moment.",
    "Lo Studio non è riuscito a verificare se esiste già un mockup, quindi non ne ha disegnato uno nuovo. Riprova tra qualche istante.",
  ],
  MOCKUP_REJECTED: [
    "The Studio discarded the answer of the model.",
    "Lo Studio ha scartato la risposta del modello.",
  ],
  INVALID_MOCKUP_OUTPUT: [
    "The model returned a mockup that does not hold together. The design is unchanged: you can try again.",
    "Il modello ha restituito un mockup incoerente. Il design è invariato: puoi riprovare.",
  ],
  GENERATED_MOCKUP_PATH_ACTIVE: [
    "The mockups of this project are drawn by the hosted model: reload the page.",
    "I mockup di questo progetto li disegna il modello ospitato: ricarica la pagina.",
  ],
  DESIGN_ITERATIONS_UNAVAILABLE: [
    "The earlier requests could not be read. Try again in a moment.",
    "Non è stato possibile leggere le richieste precedenti. Riprova tra qualche istante.",
  ],
  INVALID_API_RESPONSE: [
    "The Studio gave an answer that this page cannot read.",
    "Lo Studio ha dato una risposta che questa pagina non riesce a leggere.",
  ],
  RATE_LIMITED: [
    "The model received too many requests. Try again in a few minutes.",
    "Il modello ha ricevuto troppe richieste. Riprova tra qualche minuto.",
  ],
  PROVIDER_REFUSED: [
    "The model declined to answer this request.",
    "Il modello ha rifiutato di rispondere a questa richiesta.",
  ],
  RESPONSE_SCHEMA_ERROR: [
    "The answer of the model did not have the expected shape. Try again.",
    "La risposta del modello non aveva la forma prevista. Riprova.",
  ],
  AUTHENTICATION_FAILED: [
    "The Studio is not authorised to use the model. Check its key.",
    "Lo Studio non è autorizzato a usare il modello. Controlla la chiave.",
  ],
  CONTEXT_BUDGET_EXCEEDED: [
    "The project is too large for the model.",
    "Il progetto è troppo grande per il modello.",
  ],
  IDENTITY_MISMATCH: [
    "A different model from the configured one answered, so the answer was not used.",
    "Ha risposto un modello diverso da quello configurato, quindi la risposta non è stata usata.",
  ],
  PROVIDER_ERROR: [
    "The model service returned an error. Try again in a few minutes.",
    "Il servizio del modello ha restituito un errore. Riprova tra qualche minuto.",
  ],
  INVALID_REQUEST: [
    "The model service did not accept the request.",
    "Il servizio del modello non ha accettato la richiesta.",
  ],
  ACCESS_TOKEN_REQUIRED: [
    "Your session has expired. Sign in again.",
    "La sessione è scaduta. Accedi di nuovo.",
  ],
  GENERATED_MOCKUP_PATH_INACTIVE: [
    "The model that draws the mockups is not in use for this project: Design & Evaluation shows the simple preview.",
    "Il modello che disegna i mockup non è in uso per questo progetto: Design e valutazione mostra l'anteprima semplice.",
  ],
  REQUIREMENTS_QUERY_UNAVAILABLE: [
    "The Studio could not read the requirements, so it did not start the drawing. Try again in a moment.",
    "Lo Studio non è riuscito a leggere i requisiti, quindi non ha avviato il disegno. Riprova tra qualche istante.",
  ],
  GENERATION_JOBS_UNAVAILABLE: [
    "The Studio cannot run drawings in the background right now. Try again in a moment.",
    "Lo Studio ora non riesce a disegnare in background. Riprova tra qualche istante.",
  ],
  MOCKUP_ENTRY_SCREEN_INVALID: [
    "This screen is not part of the mockup.",
    "Questa schermata non fa parte del mockup.",
  ],
  GENERATION_JOB_CANCELLED: [
    "The drawing stopped because the Studio was restarted. You can try again.",
    "Il disegno si è interrotto perché lo Studio è stato riavviato. Puoi riprovare.",
  ],
  GENERATION_JOB_FAILED: [
    "An unexpected error stopped the drawing. The project is unchanged: you can try again.",
    "Un errore imprevisto ha interrotto il disegno. Il progetto è invariato: puoi riprovare.",
  ],
};

const DEFAULT_FAILURE = [
  "The drawing did not succeed. The project is unchanged: you can try again.",
  "Il disegno non è riuscito. Il progetto è invariato: puoi riprovare.",
] as const;

const REASONS: Sentences = {
  UNREACHABLE_SCREEN: [
    "A screen could not be reached from any link",
    "Una schermata non si raggiungeva da nessun collegamento",
  ],
  NO_TRANSITION: [
    "The screens were not linked to each other",
    "Le schermate non erano collegate tra loro",
  ],
  SELF_LINK: [
    "A link led to its own screen without saying so",
    "Un collegamento portava alla sua stessa schermata senza dirlo",
  ],
  UNKNOWN_REQUIREMENT: [
    "A part referred to a requirement that does not exist",
    "Una parte citava un requisito che non esiste",
  ],
  UNTRACED_CONTROL: [
    "A button or a field was not linked to any requirement",
    "Un pulsante o un campo non era collegato a nessun requisito",
  ],
  UNTRACED_SCREEN: [
    "A screen was not linked to any requirement",
    "Una schermata non era collegata a nessun requisito",
  ],
  UNLABELLED_CONTROL: ["A field had no label", "Un campo non aveva un'etichetta"],
  UNNAMED_ACTION: [
    "A button or a link had no name",
    "Un pulsante o un collegamento non aveva un nome",
  ],
  TABLE_WITHOUT_HEADERS: [
    "A table had no column headers",
    "Una tabella non aveva le intestazioni delle colonne",
  ],
  HEADING_COUNT: [
    "A screen did not have exactly one main title",
    "Una schermata non aveva un solo titolo principale",
  ],
  SCREEN_TOO_EMPTY: [
    "A screen was too empty to look real",
    "Una schermata era troppo vuota per sembrare vera",
  ],
  TABLE_TOO_SHORT: [
    "A table had too few rows to look real",
    "Una tabella aveva troppo poche righe per sembrare vera",
  ],
  EMPTY_CELL: ["A table cell was empty", "Una cella di una tabella era vuota"],
  SELECT_TOO_SHORT: [
    "A drop-down list had fewer than two choices",
    "Un menu a tendina aveva meno di due scelte",
  ],
  PLACEHOLDER_TEXT: ["Some placeholder text was left", "Era rimasto un testo segnaposto"],
  LOW_CONTRAST: [
    "A text was hard to read on its background",
    "Un testo non si leggeva bene sul suo sfondo",
  ],
  UNREADABLE_TEXT_COLOUR: [
    "The colour of a text made it hard to read",
    "Il colore di un testo lo rendeva difficile da leggere",
  ],
  DATED_BACKGROUND: [
    "A background used a dated decorative pattern",
    "Uno sfondo usava un motivo decorativo datato",
  ],
  HEADING_LEVEL_SKIPPED: ["The titles skipped a level", "I titoli saltavano un livello"],
  LIST_TOO_SHORT: ["A list had a single item", "Un elenco aveva un solo elemento"],
  EMPTY_CONTAINER: ["A box was left empty", "Un riquadro era rimasto vuoto"],
  DECORATIVE_ICON_EXPOSED: [
    "A decorative icon was read out by screen readers",
    "Un'icona decorativa veniva letta dai lettori di schermo",
  ],
  BACKGROUND_WITHOUT_TEXT_COLOUR: [
    "A coloured background did not set the colour of its text",
    "Uno sfondo colorato non indicava il colore del suo testo",
  ],
  NO_RESPONSIVE_RULE: [
    "The screens did not adapt to phones",
    "Le schermate non si adattavano ai telefoni",
  ],
  SINGLE_STATE: [
    "The screens of errors, confirmations or empty lists were missing",
    "Mancavano le schermate di errore, di conferma o di elenco vuoto",
  ],
  WEAK_CONTROL_BORDER: [
    "The border of a field or a button could hardly be seen",
    "Il bordo di un campo o di un pulsante si vedeva appena",
  ],
  SELF_CLOSING: [
    "An element was written in a form that the Studio does not accept",
    "Un elemento era scritto in una forma che lo Studio non accetta",
  ],
  CLASS_INVALID: [
    "An element used a style name that the Studio does not accept",
    "Un elemento usava un nome di stile che lo Studio non accetta",
  ],
  DATA_REQ_INVALID: [
    "An element named the requirements in a wrong way",
    "Un elemento citava i requisiti in modo sbagliato",
  ],
  LINK_TARGET: [
    "A link led to a screen that does not exist",
    "Un collegamento portava a una schermata che non esiste",
  ],
  CONTENT_RULE: [
    "An element was placed where it cannot stay",
    "Un elemento era in un punto in cui non può stare",
  ],
  TOO_MANY_ELEMENTS: ["A screen had too many elements", "Una schermata aveva troppi elementi"],
  MARKUP_TOO_DEEP: [
    "The elements of a screen were nested too deeply",
    "Gli elementi di una schermata erano annidati troppo in profondità",
  ],
  UNEXPECTED_END_TAG: [
    "The code of a screen was not well formed",
    "Il codice di una schermata non era scritto correttamente",
  ],
  MISNESTED_ELEMENT: [
    "The code of a screen was not well formed",
    "Il codice di una schermata non era scritto correttamente",
  ],
  UNCLOSED_ELEMENT: [
    "The code of a screen was not well formed",
    "Il codice di una schermata non era scritto correttamente",
  ],
  TOKEN_NAMES: [
    "The colours of the visual style could not be read",
    "I colori dello stile visivo non si potevano leggere",
  ],
  TITLE_INVALID: [
    "A screen had no title or a title that was too long",
    "Una schermata non aveva un titolo o ne aveva uno troppo lungo",
  ],
  CONTRACT_VERSION: [
    "The answer followed rules of the Studio that are no longer in use",
    "La risposta seguiva regole dello Studio non più in uso",
  ],
  ALTERNATIVE_ID: [
    "The answer belonged to another alternative",
    "La risposta apparteneva a un'altra alternativa",
  ],
  MOCKUP_TOO_LONG: ["The mockup was too long", "Il mockup era troppo lungo"],
  MARKUP_TOO_LONG: ["A screen was too long", "Una schermata era troppo lunga"],
  STYLES_TOO_LONG: [
    "The styles of the mockup were too long",
    "Gli stili del mockup erano troppo lunghi",
  ],
  SCREEN_COUNT: [
    "The mockup had too many or too few screens",
    "Il mockup aveva troppe o troppo poche schermate",
  ],
  NOT_CANONICAL: [
    "The mockup was not saved in the form that the Studio expects",
    "Il mockup non era salvato nella forma che lo Studio si aspetta",
  ],
  SNAPSHOT_INVALID: [
    "The mockup was not saved in the form that the Studio expects",
    "Il mockup non era salvato nella forma che lo Studio si aspetta",
  ],
  SNAPSHOT_NOT_CANONICAL: [
    "The mockup was not saved in the form that the Studio expects",
    "Il mockup non era salvato nella forma che lo Studio si aspetta",
  ],
  SCREEN_LANGUAGE: [
    "A screen was written in another language than the requirements",
    "Una schermata era scritta in una lingua diversa da quella dei requisiti",
  ],
  REQUIREMENTS_NOT_COVERED: [
    "The mockup does not show some requirements yet",
    "Il mockup non mostra ancora alcuni requisiti",
  ],
  UNEXPECTED_ERROR: [
    "An unexpected error happened in the Studio",
    "Nello Studio è successo un errore imprevisto",
  ],
  STYLES_COLOUR: [
    "The styles wrote a colour by hand instead of using the palette of the alternative",
    "Gli stili scrivevano un colore a mano invece di usare la tavolozza dell'alternativa",
  ],
  STYLES_FONT: [
    "The styles chose a font outside those of the alternative",
    "Gli stili sceglievano un carattere fuori da quelli dell'alternativa",
  ],
  MOCKUP_INVALID: [
    "The answer was not a mockup that the Studio can read",
    "La risposta non era un mockup che lo Studio riesce a leggere",
  ],
  ELEMENT_REMOVED: [
    "The Studio removed an element that it does not accept, such as an image or a script: the mockup is still valid",
    "Lo Studio ha tolto un elemento che non accetta, come un'immagine o uno script: il mockup resta valido",
  ],
  ELEMENT_UNWRAPPED: [
    "The Studio removed a container that it does not accept and kept what was inside: the mockup is still valid",
    "Lo Studio ha tolto un contenitore che non accetta e ne ha tenuto il contenuto: il mockup resta valido",
  ],
  ATTRIBUTE_REMOVED: [
    "The Studio removed from an element a setting that would load or run something: the mockup is still valid",
    "Lo Studio ha tolto da un elemento un'impostazione che avrebbe caricato o avviato qualcosa: il mockup resta valido",
  ],
  LINK_REMOVED: [
    "The Studio removed a link that did not lead to a screen of the mockup: the mockup is still valid",
    "Lo Studio ha tolto un collegamento che non portava a una schermata del mockup: il mockup resta valido",
  ],
  REQUIREMENT_CODE_REMOVED: [
    "The Studio removed the mention of a requirement that the project does not have: the mockup is still valid",
    "Lo Studio ha tolto la citazione di un requisito che il progetto non ha: il mockup resta valido",
  ],
  REQUIREMENT_INHERITED: [
    "The Studio linked a button, a field or a link that named no requirement to the requirements of its screen: the mockup is still valid",
    "Lo Studio ha collegato ai requisiti della sua schermata un pulsante, un campo o un collegamento che non ne citava nessuno: il mockup resta valido",
  ],
  STYLE_DECLARATION_REMOVED: [
    "The Studio removed from the styles an instruction that it does not accept, such as a colour outside the palette: the mockup is still valid",
    "Lo Studio ha tolto dagli stili un'indicazione che non accetta, come un colore fuori dalla tavolozza: il mockup resta valido",
  ],
  STYLE_RULE_REMOVED: [
    "The Studio removed from the styles a rule that it does not accept: the mockup is still valid",
    "Lo Studio ha tolto dagli stili una regola che non accetta: il mockup resta valido",
  ],
  STYLE_REST_REMOVED: [
    "The Studio removed the last part of the styles because it could not be read: the mockup is still valid",
    "Lo Studio ha tolto l'ultima parte degli stili perché non si poteva leggere: il mockup resta valido",
  ],
};

const DEFAULT_REASON = [
  "One of the checks of the Studio did not pass",
  "Uno dei controlli dello Studio non è stato superato",
] as const;

const UNSAFE_REASON = [
  "The code of the screens contained something that the Studio does not accept",
  "Il codice delle schermate conteneva qualcosa che lo Studio non accetta",
] as const;

const UNSAFE_PREFIXES = [
  "STYLES_",
  "MARKUP_",
  "ELEMENT_",
  "ATTRIBUTE_",
  "SVG_",
  "ID_",
  "SCREEN_",
  "CSS_",
];

const REQUIREMENT_REASON = [
  "The mockup named the requirements in a way that the Studio does not recognise",
  "Il mockup citava i requisiti in un modo che lo Studio non riconosce",
] as const;

const NOT_RETRYABLE = new Set([
  "GENERATION_BUDGET_EXCEEDED",
  "REAL_MOCKUP_MODEL_NOT_CONFIGURED",
  "GENERATED_MOCKUP_REQUIRED",
  "GENERATED_MOCKUP_REQUIRES_VISUAL_LANGUAGE",
  "ITERATION_REQUEST_INVALID",
  "DESIGN_CONTEXT_CHANGED",
  "AUTHENTICATION_FAILED",
  "CONTEXT_BUDGET_EXCEEDED",
  "ACCESS_TOKEN_REQUIRED",
  "GENERATED_MOCKUP_PATH_ACTIVE",
  "GENERATED_MOCKUP_PATH_INACTIVE",
  "MOCKUP_ENTRY_SCREEN_INVALID",
]);

function pick(sentence: readonly [string, string], locale: GenerationLocale): string {
  return sentence[locale === "it" ? 1 : 0];
}

export function generationRetryable(code: string | null | undefined): boolean {
  return !NOT_RETRYABLE.has(code ?? "");
}

export function generationFailureText(
  code: string | null | undefined,
  locale: GenerationLocale,
): string {
  const known = code ? FAILURES[code] : undefined;
  return pick(known ?? DEFAULT_FAILURE, locale);
}

export function generationReasonText(code: string, locale: GenerationLocale): string {
  const known = REASONS[code];
  if (known !== undefined) {
    return pick(known, locale);
  }
  if (UNSAFE_PREFIXES.some((prefix) => code.startsWith(prefix))) {
    return pick(UNSAFE_REASON, locale);
  }
  if (code.startsWith("REQUIREMENT_")) {
    return pick(REQUIREMENT_REASON, locale);
  }
  return pick(DEFAULT_REASON, locale);
}
</script>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, provide, ref, useId, watch } from "vue";
import { useI18n } from "vue-i18n";

import GeneratedMockupFrame from "./GeneratedMockupFrame.vue";
import type { MockupDocument } from "./GeneratedMockupDialog.vue";
import UiAgentMessage from "./UiAgentMessage.vue";
import UiButton from "./UiButton.vue";
import UiClaimFrame from "./UiClaimFrame.vue";
import UiStateBlock from "./UiStateBlock.vue";
import UiStatusChip from "./UiStatusChip.vue";
import { surfaceKey, type SurfaceContext } from "./UiSurface.vue";
import {
  withScreenNames,
  type ScreenName,
  type ScreenNaming,
  type WorkflowName,
} from "./screenNames";

type Phase = "idle" | "drawing" | "ready" | "rejected" | "failed" | "error";

const QUOTE_CLASS = "border-l-2 border-on-night/40 pl-3 leading-normal whitespace-pre-line";

const props = withDefaults(
  defineProps<{
    job?: IterationJob | null | undefined;
    request?: string | null | undefined;
    items?: readonly IterationItem[] | undefined;
    before?: MockupDocument | null | undefined;
    after?: MockupDocument | null | undefined;
    assertions?: readonly string[] | undefined;
    error?: string | null | undefined;
    busy?: boolean | undefined;
    screens?: readonly ScreenName[] | undefined;
    workflows?: readonly WorkflowName[] | undefined;
    locale?: GenerationLocale | undefined;
  }>(),
  {
    job: null,
    request: null,
    items: () => [],
    before: null,
    after: null,
    assertions: () => [],
    error: null,
    busy: false,
    screens: () => [],
    workflows: () => [],
    locale: undefined,
  },
);

const emit = defineEmits<{
  apply: [generationId: string];
  discard: [generationId: string];
  "remove-assertion": [assertion: string];
  open: [side: IterationSide, screen: string];
  retry: [request: string];
  screen: [code: string];
}>();

const messages = {
  it: {
    title: "Modifiche su tua richiesta",
    designer: "Designer UX/UI",
    drawingMessage:
      "Sto disegnando la nuova versione con le tue indicazioni. Può richiedere qualche minuto: intanto puoi continuare a guardare il design.",
    readyMessage: "Ecco la nuova versione. Confrontala con quella attuale e decidi se applicarla.",
    request: "La tua richiesta",
    elapsed: "In corso da {time}",
    duration:
      "Di solito servono da 5 a 10 minuti. Puoi continuare a lavorare: il disegno prosegue anche se chiudi la pagina.",
    stages: {
      GENERATING: "Il designer sta disegnando le schermate.",
      VALIDATING: "Lo Studio controlla la nuova versione.",
      RETRYING: "Il primo tentativo non andava bene: il designer lo sta rifacendo.",
      none: "Il designer sta lavorando alla nuova versione.",
    },
    changes: "Cosa è cambiato",
    noChanges: "Il designer non ha elencato le modifiche.",
    screens: "Schermate da confrontare",
    opening: "Apro la schermata in tutte e due le versioni…",
    current: "Versione attuale",
    currentNote: "Applicata da te",
    proposed: "Nuova versione",
    proposedNote: "Proposta, non ancora applicata",
    frame: "{version}: {screen}",
    preparing: "Preparo l'anteprima…",
    open: "Apri in grande",
    openLabel: "Apri in grande: {version}",
    warnings: "Da controllare",
    warningsNote: "Lo Studio ha accettato la nuova versione, ma ha notato questi punti.",
    onScreen: "Nella schermata «{title}»: {text}",
    apply: "Applica la nuova versione",
    discard: "Scarta",
    rejectedTitle: "La nuova versione va rifatta",
    failedTitle: "La nuova versione non è stata disegnata",
    errorTitle: "La richiesta non è partita",
    why: "Perché",
    retry: "Riprova con la stessa richiesta",
    rules: "Regole valide per le prossime versioni",
    rulesNote: "Il designer le rispetta ogni volta che disegna una nuova versione del design.",
    remove: "Togli",
    removeLabel: "Togli la regola: {rule}",
    history: "Richieste precedenti ({n})",
    historyChanges: "Modifiche",
    historyRules: "Regole aggiunte",
    statuses: {
      PROPOSED: "Da decidere",
      APPLIED: "Applicata",
      REJECTED: "Scartata dallo Studio",
      FAILED: "Non riuscita",
    },
  },
  en: {
    title: "Changes you asked for",
    designer: "UX/UI designer",
    drawingMessage:
      "I am drawing the new version from your instructions. It can take a few minutes: meanwhile you can keep looking at the design.",
    readyMessage:
      "Here is the new version. Compare it with the current one and decide whether to apply it.",
    request: "Your request",
    elapsed: "Running for {time}",
    duration:
      "It usually takes 5 to 10 minutes. You can keep working: the drawing goes on even if you close the page.",
    stages: {
      GENERATING: "The designer is drawing the screens.",
      VALIDATING: "The Studio is checking the new version.",
      RETRYING: "The first attempt was not good enough: the designer is redoing it.",
      none: "The designer is working on the new version.",
    },
    changes: "What changed",
    noChanges: "The designer did not list the changes.",
    screens: "Screens to compare",
    opening: "Opening the screen in both versions…",
    current: "Current version",
    currentNote: "Applied by you",
    proposed: "New version",
    proposedNote: "Proposal, not applied yet",
    frame: "{version}: {screen}",
    preparing: "Preparing the preview…",
    open: "Open large",
    openLabel: "Open large: {version}",
    warnings: "To check",
    warningsNote: "The Studio accepted the new version, but it noticed these points.",
    onScreen: "On the screen “{title}”: {text}",
    apply: "Apply the new version",
    discard: "Discard",
    rejectedTitle: "The new version needs another try",
    failedTitle: "The new version was not drawn",
    errorTitle: "The request did not start",
    why: "Why",
    retry: "Try again with the same request",
    rules: "Rules that hold for the next versions",
    rulesNote: "The designer follows them every time it draws a new version of the design.",
    remove: "Remove",
    removeLabel: "Remove the rule: {rule}",
    history: "Earlier requests ({n})",
    historyChanges: "Changes",
    historyRules: "Rules added",
    statuses: {
      PROPOSED: "To decide",
      APPLIED: "Applied",
      REJECTED: "Discarded by the Studio",
      FAILED: "Did not succeed",
    },
  },
} as const;

const CHIPS = {
  PROPOSED: "pending",
  APPLIED: "approved",
  REJECTED: "rejected",
  FAILED: "failed",
} as const;

provide(
  surfaceKey,
  computed<SurfaceContext>(() => "night"),
);

const { locale: appLocale } = useI18n({ useScope: "global" });

const lang = computed<GenerationLocale>(
  () => props.locale ?? (appLocale.value === "it" ? "it" : "en"),
);
const copy = computed(() => messages[lang.value]);

const titleId = useId();
const historyId = useId();
const rulesId = useId();
const regionId = useId();
const tabPrefix = useId();

const now = ref(Date.now());
const historyOpen = ref(false);
const requested = ref<string | null>(null);
const focusIndex = ref(0);
const narrow = ref(false);
const tablist = ref<HTMLElement | null>(null);

let clock: ReturnType<typeof setInterval> | null = null;
let media: MediaQueryList | null = null;

const phase = computed<Phase>(() => {
  if (props.error !== null) {
    return "error";
  }
  const job = props.job;
  if (job === null) {
    return "idle";
  }
  if (job.status === "RUNNING") {
    return "drawing";
  }
  if (job.status === "SUCCEEDED") {
    return job.result === null ? "failed" : "ready";
  }
  return job.status === "REJECTED" ? "rejected" : "failed";
});

const visible = computed(
  () => phase.value !== "idle" || props.assertions.length > 0 || props.items.length > 0,
);

const requestText = computed(() => props.request?.trim() ?? "");

const elapsed = computed(() => {
  const started = props.job === null ? Number.NaN : Date.parse(props.job.started_at);
  if (Number.isNaN(started)) {
    return "";
  }
  const seconds = Math.max(0, Math.floor((now.value - started) / 1000));
  const minutes = Math.floor(seconds / 60);
  const time = minutes > 0 ? `${minutes} min ${seconds % 60} s` : `${seconds} s`;
  return fill(copy.value.elapsed, { time });
});

const stageText = computed(() => {
  const stage = props.job?.stage ?? null;
  return stage === null ? copy.value.stages.none : copy.value.stages[stage];
});

const result = computed(() => (phase.value === "ready" ? (props.job?.result ?? null) : null));

const naming = computed<ScreenNaming>(() => ({
  screens: [...props.screens, ...(props.after?.screens ?? []), ...(props.before?.screens ?? [])],
  workflows: props.workflows,
  locale: lang.value,
}));

const changes = computed(() =>
  (result.value?.changes ?? []).map((change) => withScreenNames(change, naming.value)),
);

const screens = computed(() => props.after?.screens ?? props.before?.screens ?? []);

const selectedScreen = computed(
  () =>
    requested.value ??
    props.after?.entry_screen ??
    props.before?.entry_screen ??
    screens.value[0]?.code ??
    null,
);

const selectedIndex = computed(() =>
  screens.value.findIndex((screen) => screen.code === selectedScreen.value),
);

const sides = computed(() =>
  (["before", "after"] as const).map((side) => {
    const document = side === "before" ? props.before : props.after;
    const version = side === "before" ? copy.value.current : copy.value.proposed;
    const screen = document?.screens.find((item) => item.code === document.entry_screen);
    return {
      side,
      document,
      version,
      note: side === "before" ? copy.value.currentNote : copy.value.proposedNote,
      status: side === "before" ? ("confirmed" as const) : ("hypothesis" as const),
      title: fill(copy.value.frame, { version, screen: screen?.title ?? document?.title ?? "" }),
      key: document === null ? side : `${side}|${document.content_hash}|${document.entry_screen}`,
    };
  }),
);

const warnings = computed(() => reasonLines(result.value?.warnings ?? []));

const failureText = computed(() => {
  if (phase.value === "error") {
    return generationFailureText(props.error, lang.value);
  }
  return generationFailureText(props.job?.failure?.code, lang.value);
});

const failureReasons = computed(() =>
  phase.value === "rejected" || phase.value === "failed"
    ? reasonLines(props.job?.failure?.reasons ?? [])
    : [],
);

const failureTitle = computed(() => {
  if (phase.value === "error") {
    return copy.value.errorTitle;
  }
  return phase.value === "rejected" ? copy.value.rejectedTitle : copy.value.failedTitle;
});

const canRetry = computed(() => {
  if (requestText.value.length === 0 || props.busy) {
    return false;
  }
  if (phase.value === "error") {
    return generationRetryable(props.error);
  }
  return generationRetryable(props.job?.failure?.code);
});

const history = computed(() =>
  props.items.map((item) => ({
    item,
    date: formatDate(item.requested_at),
    chip: CHIPS[item.status],
    label: copy.value.statuses[item.status],
    changes: item.changes.map((change) => withScreenNames(change, naming.value)),
  })),
);

function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_match, key: string) => String(values[key] ?? ""));
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return new Intl.DateTimeFormat(lang.value, { dateStyle: "medium", timeStyle: "short" }).format(
    date,
  );
}

function screenTitle(code: string | null | undefined): string | null {
  if (!code) {
    return null;
  }
  const known = [...(props.after?.screens ?? []), ...(props.before?.screens ?? [])];
  return known.find((screen) => screen.code === code)?.title ?? null;
}

function reasonLines(reasons: readonly IterationReason[]): string[] {
  const lines: string[] = [];
  for (const reason of reasons) {
    const text = generationReasonText(reason.code, lang.value);
    const title = screenTitle(reason.screen_code);
    const line = title === null ? text : fill(copy.value.onScreen, { title, text });
    if (!lines.includes(line)) {
      lines.push(line);
    }
  }
  return lines;
}

function tabId(index: number): string {
  return `${tabPrefix}-${index}`;
}

function chooseScreen(code: string): void {
  if (code === selectedScreen.value) {
    return;
  }
  requested.value = code;
  emit("screen", code);
}

function moveFocus(event: KeyboardEvent): void {
  const count = screens.value.length;
  const targets: Record<string, number> = {
    ArrowRight: focusIndex.value + 1,
    ArrowLeft: focusIndex.value - 1,
    Home: 0,
    End: count - 1,
  };
  const target = targets[event.key];
  if (target === undefined || count === 0) {
    return;
  }
  event.preventDefault();
  focusIndex.value = (target + count) % count;
  tablist.value?.querySelectorAll<HTMLElement>("[role='tab']")[focusIndex.value]?.focus();
}

function openLarge(side: IterationSide): void {
  const document = side === "before" ? props.before : props.after;
  if (document !== null) {
    emit("open", side, document.entry_screen);
  }
}

function apply(): void {
  const id = result.value?.generation_id;
  if (id !== undefined && !props.busy) {
    emit("apply", id);
  }
}

function discard(): void {
  const id = result.value?.generation_id;
  if (id !== undefined && !props.busy) {
    emit("discard", id);
  }
}

function retry(): void {
  if (canRetry.value) {
    emit("retry", requestText.value);
  }
}

function tick(): void {
  now.value = Date.now();
}

function updateNarrow(): void {
  narrow.value = media?.matches ?? false;
}

watch(
  phase,
  (current) => {
    if (current === "drawing" && clock === null) {
      tick();
      clock = setInterval(tick, 1000);
    }
    if (current !== "drawing" && clock !== null) {
      clearInterval(clock);
      clock = null;
    }
  },
  { immediate: true },
);

watch(
  () => [props.after?.entry_screen, props.before?.entry_screen],
  () => {
    requested.value = null;
  },
);

watch(
  selectedIndex,
  (index) => {
    focusIndex.value = Math.max(0, index);
  },
  { immediate: true },
);

onMounted(() => {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return;
  }
  media = window.matchMedia("(max-width: 767px)");
  updateNarrow();
  media.addEventListener?.("change", updateNarrow);
});

onBeforeUnmount(() => {
  if (clock !== null) {
    clearInterval(clock);
    clock = null;
  }
  media?.removeEventListener?.("change", updateNarrow);
  media = null;
});
</script>

<template>
  <section
    v-if="visible"
    class="grid gap-4 text-on-night"
    data-surface="night"
    :aria-labelledby="titleId"
    :data-phase="phase"
    data-testid="design-iteration-panel"
  >
    <h2 :id="titleId" class="text-xl font-semibold">{{ copy.title }}</h2>

    <template v-if="phase === 'drawing'">
      <UiAgentMessage :role-label="copy.designer" avatar="/team/ux.webp">
        {{ copy.drawingMessage }}
      </UiAgentMessage>
      <div
        class="grid gap-3 rounded-tile border border-night-line bg-night-raised p-5"
        aria-busy="true"
        data-testid="design-iteration-drawing"
      >
        <div v-if="requestText" class="grid gap-1">
          <p class="font-mono text-[11px] tracking-label text-on-night-3 uppercase">
            {{ copy.request }}
          </p>
          <blockquote :class="[QUOTE_CLASS, 'text-[15px]']" data-testid="design-iteration-request">
            {{ requestText }}
          </blockquote>
        </div>
        <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-on-night-2">
          <span
            class="inline-block h-[15px] w-[15px] shrink-0 animate-spin-arc rounded-full border-2 border-night-line-strong border-t-petrol-on-night"
            aria-hidden="true"
          />
          <span role="status" data-testid="design-iteration-stage">{{ stageText }}</span>
          <span class="text-on-night-3" data-testid="design-iteration-elapsed">{{ elapsed }}</span>
        </div>
        <p class="text-sm leading-normal text-on-night-3" data-testid="design-iteration-duration">
          {{ copy.duration }}
        </p>
      </div>
    </template>

    <template v-else-if="phase === 'ready' && result !== null">
      <UiAgentMessage :role-label="copy.designer" avatar="/team/ux.webp">
        {{ copy.readyMessage }}
      </UiAgentMessage>
      <div
        class="grid gap-5 rounded-tile border border-night-line bg-night-raised p-4 sm:p-6"
        data-testid="design-iteration-ready"
      >
        <div v-if="requestText" class="grid gap-1">
          <p class="font-mono text-[11px] tracking-label text-on-night-3 uppercase">
            {{ copy.request }}
          </p>
          <blockquote :class="[QUOTE_CLASS, 'text-[15px]']" data-testid="design-iteration-request">
            {{ requestText }}
          </blockquote>
        </div>
        <div class="grid gap-2">
          <h3 class="text-base font-semibold">{{ copy.changes }}</h3>
          <ul
            v-if="changes.length > 0"
            class="grid list-disc gap-1.5 pl-5 text-[15px] leading-normal text-on-night-2 marker:text-petrol-on-night"
            data-testid="design-iteration-changes"
          >
            <li v-for="change in changes" :key="change">{{ change }}</li>
          </ul>
          <p v-else class="text-sm text-on-night-3">{{ copy.noChanges }}</p>
        </div>
        <div class="grid gap-3">
          <div
            v-if="screens.length > 1"
            ref="tablist"
            role="tablist"
            :aria-label="copy.screens"
            class="-mx-1.5 flex min-w-0 gap-1 overflow-x-auto p-1.5"
            data-testid="design-iteration-screens"
            @keydown="moveFocus"
          >
            <button
              v-for="(screen, index) in screens"
              :id="tabId(index)"
              :key="screen.code"
              type="button"
              role="tab"
              :aria-selected="screen.code === selectedScreen ? 'true' : 'false'"
              :aria-controls="regionId"
              :tabindex="index === focusIndex ? 0 : -1"
              :class="[
                'inline-flex min-h-11 shrink-0 items-center rounded-pill px-3.5 text-[13px] font-medium whitespace-nowrap transition-colors duration-150',
                screen.code === selectedScreen
                  ? 'bg-on-night text-ink'
                  : 'text-on-night hover:bg-night-hover',
              ]"
              :data-screen="screen.code"
              data-testid="design-iteration-screen"
              @click="chooseScreen(screen.code)"
            >
              {{ screen.title }}
            </button>
          </div>
          <p
            v-if="requested !== null"
            class="inline-flex items-center gap-2 text-sm text-on-night-2"
            role="status"
            data-testid="design-iteration-opening"
          >
            <span
              class="inline-block h-[15px] w-[15px] shrink-0 animate-spin-arc rounded-full border-2 border-night-line-strong border-t-petrol-on-night"
              aria-hidden="true"
            />
            {{ copy.opening }}
          </p>
          <div
            :id="regionId"
            :role="screens.length > 1 ? 'tabpanel' : undefined"
            :aria-labelledby="
              screens.length > 1 && selectedIndex >= 0 ? tabId(selectedIndex) : undefined
            "
            :aria-busy="requested !== null ? 'true' : undefined"
            class="grid gap-4 md:grid-cols-2"
          >
            <UiClaimFrame
              v-for="item in sides"
              :key="item.side"
              as="section"
              :status="item.status"
              radius="tile"
              :padded="false"
              class="grid content-start gap-3 overflow-hidden p-3"
              :data-side="item.side"
              data-testid="design-iteration-side"
            >
              <div class="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 px-1">
                <h3 class="text-[15px] font-semibold">{{ item.version }}</h3>
                <span
                  :class="[
                    'text-xs',
                    item.status === 'confirmed'
                      ? 'text-petrol-on-night-2'
                      : 'text-violet-on-night-2',
                  ]"
                >
                  {{ item.note }}
                </span>
              </div>
              <div
                :class="[
                  'overflow-hidden rounded-field bg-night-deep',
                  narrow ? 'h-[520px]' : 'h-[420px]',
                ]"
              >
                <GeneratedMockupFrame
                  v-if="item.document"
                  :key="item.key"
                  :html="item.document.html"
                  :title="item.title"
                  :width="narrow ? 'phone' : 'desktop'"
                />
                <div v-else class="grid h-full place-items-center p-4">
                  <UiStateBlock kind="loading" :title="copy.preparing" />
                </div>
              </div>
              <UiButton
                variant="outline"
                class="justify-self-start"
                :disabled="!item.document"
                :data-side="item.side"
                data-testid="design-iteration-open"
                :aria-label="fill(copy.openLabel, { version: item.version })"
                @click="openLarge(item.side)"
              >
                {{ copy.open }}
              </UiButton>
            </UiClaimFrame>
          </div>
        </div>
        <div v-if="warnings.length > 0" class="grid gap-2" data-testid="design-iteration-warnings">
          <h3 class="text-base font-semibold text-warn-on-night">{{ copy.warnings }}</h3>
          <p class="text-sm text-on-night-3">{{ copy.warningsNote }}</p>
          <ul
            class="grid list-disc gap-1.5 pl-5 text-sm leading-normal text-on-night-2 marker:text-warn-on-night"
          >
            <li v-for="line in warnings" :key="line">{{ line }}</li>
          </ul>
        </div>
        <div class="flex flex-wrap items-center gap-3">
          <UiButton
            variant="outline"
            :disabled="busy"
            data-testid="design-iteration-discard"
            @click="discard"
          >
            {{ copy.discard }}
          </UiButton>
          <UiButton
            variant="pill"
            :disabled="busy"
            data-testid="design-iteration-apply"
            @click="apply"
          >
            {{ copy.apply }}
          </UiButton>
        </div>
      </div>
    </template>

    <UiStateBlock
      v-else-if="phase === 'rejected' || phase === 'failed' || phase === 'error'"
      kind="error"
      :title="failureTitle"
      :text="failureText"
      data-testid="design-iteration-failure"
    >
      <div class="grid gap-3">
        <div v-if="failureReasons.length > 0" class="grid gap-1">
          <p class="text-sm font-semibold">{{ copy.why }}</p>
          <ul class="grid list-disc gap-1 pl-5 text-sm leading-normal">
            <li v-for="line in failureReasons" :key="line">{{ line }}</li>
          </ul>
        </div>
        <div v-if="requestText" class="grid gap-1" data-testid="design-iteration-failure-request">
          <p class="text-sm font-semibold">{{ copy.request }}</p>
          <blockquote :class="[QUOTE_CLASS, 'text-sm text-on-night-2']">
            {{ requestText }}
          </blockquote>
        </div>
        <UiButton
          v-if="canRetry"
          variant="outline"
          class="justify-self-start"
          data-testid="design-iteration-retry"
          @click="retry"
        >
          {{ copy.retry }}
        </UiButton>
      </div>
    </UiStateBlock>

    <section
      v-if="assertions.length > 0"
      class="grid gap-2"
      :aria-labelledby="rulesId"
      data-testid="design-iteration-rules"
    >
      <h3 :id="rulesId" class="text-base font-semibold">{{ copy.rules }}</h3>
      <p class="text-sm text-on-night-3">{{ copy.rulesNote }}</p>
      <ul class="grid list-none gap-2">
        <li v-for="rule in assertions" :key="rule">
          <UiClaimFrame
            status="confirmed"
            :padded="false"
            class="flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5 pr-1.5 pl-3.5"
            data-testid="design-iteration-rule"
          >
            <span class="min-w-0 flex-1 text-sm leading-normal">{{ rule }}</span>
            <button
              type="button"
              class="inline-flex min-h-11 items-center rounded-pill px-3.5 text-[13px] font-medium text-on-night-2 transition-colors duration-150 hover:bg-night-hover hover:text-on-night disabled:cursor-not-allowed disabled:opacity-60"
              :aria-label="fill(copy.removeLabel, { rule })"
              :disabled="busy"
              data-testid="design-iteration-remove-rule"
              @click="emit('remove-assertion', rule)"
            >
              {{ copy.remove }}
            </button>
          </UiClaimFrame>
        </li>
      </ul>
    </section>

    <section v-if="items.length > 0" class="grid gap-2" data-testid="design-iteration-history">
      <button
        type="button"
        class="inline-flex min-h-11 items-center gap-2 justify-self-start text-left text-sm font-semibold text-on-night-2 transition-colors duration-150 hover:text-on-night"
        :aria-expanded="historyOpen ? 'true' : 'false'"
        :aria-controls="historyOpen ? historyId : undefined"
        data-testid="design-iteration-history-toggle"
        @click="historyOpen = !historyOpen"
      >
        <span
          aria-hidden="true"
          :class="[
            'inline-block transition-transform duration-150',
            historyOpen ? 'rotate-90' : '',
          ]"
          >›</span
        >
        {{ fill(copy.history, { n: items.length }) }}
      </button>
      <ol v-if="historyOpen" :id="historyId" class="grid list-none gap-2.5">
        <li
          v-for="entry in history"
          :key="entry.item.generation_id"
          class="grid gap-2 rounded-tile border border-night-line bg-night-raised p-4"
          :data-status="entry.item.status"
          data-testid="design-iteration-history-item"
        >
          <div class="flex flex-wrap items-center gap-2">
            <UiStatusChip :status="entry.chip" :label="entry.label" />
            <span v-if="entry.date" class="text-xs text-on-night-3">{{ entry.date }}</span>
          </div>
          <blockquote
            :class="[QUOTE_CLASS, 'text-[15px]']"
            data-testid="design-iteration-history-request"
          >
            {{ entry.item.request }}
          </blockquote>
          <div v-if="entry.changes.length > 0" class="grid gap-1">
            <p class="text-xs font-semibold text-on-night-3">{{ copy.historyChanges }}</p>
            <ul class="grid list-disc gap-1 pl-5 text-sm text-on-night-2">
              <li v-for="change in entry.changes" :key="change">{{ change }}</li>
            </ul>
          </div>
          <div v-if="entry.item.assertions.length > 0" class="grid gap-1">
            <p class="text-xs font-semibold text-on-night-3">{{ copy.historyRules }}</p>
            <ul class="grid list-disc gap-1 pl-5 text-sm text-on-night-2">
              <li v-for="rule in entry.item.assertions" :key="rule">{{ rule }}</li>
            </ul>
          </div>
        </li>
      </ol>
    </section>
  </section>
</template>
