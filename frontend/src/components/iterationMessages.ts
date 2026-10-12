import type { IterationCorrection } from "./iterationTypes";
import { fill } from "./textFormat";

export type GenerationLocale = "en" | "it";

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
    "The spending ceiling that is set is not enough for this generation.",
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
    "Your session has expired. Log in again.",
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
  ICON_UNKNOWN: [
    "The Studio replaced an icon whose name it does not know with a plain one: the mockup is still valid",
    "Lo Studio ha sostituito con un'icona semplice un'icona dal nome sconosciuto: il mockup resta valido",
  ],
  PLACEHOLDER_EMPTIED: [
    "The Studio emptied an icon or picture placeholder that held a drawing of its own: the mockup is still valid",
    "Lo Studio ha svuotato il segnaposto di un'icona o di una foto che conteneva un disegno: il mockup resta valido",
  ],
  TEXT_COLOUR_REPLACED: [
    "The Studio replaced the colour of a text that was hard to read with a palette colour that reads well: the mockup is still valid",
    "Lo Studio ha sostituito il colore di un testo poco leggibile con un colore della tavolozza che si legge bene: il mockup resta valido",
  ],
  CONTROL_BORDER_REPLACED: [
    "The Studio made the border of a field or of a button clearly visible: the mockup is still valid",
    "Lo Studio ha reso ben visibile il bordo di un campo o di un pulsante: il mockup resta valido",
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

const COLOURS: Sentences = {
  red: ["red", "rosso"],
  orange: ["orange", "arancione"],
  yellow: ["yellow", "giallo"],
  green: ["green", "verde"],
  teal: ["teal", "turchese"],
  blue: ["blue", "blu"],
  purple: ["purple", "viola"],
  pink: ["pink", "rosa"],
  brown: ["brown", "marrone"],
  grey: ["grey", "grigio"],
  black: ["black", "nero"],
  white: ["white", "bianco"],
};

const TEXT_CORRECTION = [
  "Text of the rule “{selector}”: {before} on {background}, {beforeRatio}:1, below the minimum of {threshold}:1; the Studio replaced it with {after}, {afterRatio}:1{rules}.",
  "Testo della regola «{selector}»: {before} su {background}, {beforeRatio}:1, sotto il minimo di {threshold}:1; lo Studio l'ha sostituito con {after}, {afterRatio}:1{rules}.",
] as const;

const BORDER_CORRECTION = [
  "Border of the controls of the rule “{selector}”: {before} on {background}, {beforeRatio}:1, below the minimum of {threshold}:1; replaced with {after}, {afterRatio}:1{rules}.",
  "Bordo dei controlli della regola «{selector}»: {before} su {background}, {beforeRatio}:1, sotto il minimo di {threshold}:1; sostituito con {after}, {afterRatio}:1{rules}.",
] as const;

const INHERITED_BACKGROUND = [
  "the inherited background {colour}",
  "sfondo ereditato {colour}",
] as const;

const CORRECTED_RULES = [" ({count} rules)", " ({count} regole)"] as const;

const RATIO_DIGITS = 1;
const RATIO_SCALE = 10 ** RATIO_DIGITS;

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

export function colourWord(key: string, locale: GenerationLocale): string {
  const known = COLOURS[key];
  return known === undefined ? "" : pick(known, locale);
}

export function correctionLines(
  corrections: readonly IterationCorrection[],
  locale: GenerationLocale,
): string[] {
  return corrections.map((correction) => correctionLine(correction, locale));
}

export function uncorrectedWarnings<T extends { code: string }>(
  warnings: readonly T[],
  corrections: readonly IterationCorrection[],
): T[] {
  const corrected = new Set<string>(corrections.map((correction) => correction.code));
  return warnings.filter((warning) => !corrected.has(warning.code));
}

function correctionLine(correction: IterationCorrection, locale: GenerationLocale): string {
  const sentence =
    correction.code === "CONTROL_BORDER_REPLACED" ? BORDER_CORRECTION : TEXT_CORRECTION;
  const background = colourText(correction.background, locale);
  return fill(pick(sentence, locale), {
    selector: correction.selector,
    before: colourText(correction.before, locale),
    background: correction.background.inherited
      ? fill(pick(INHERITED_BACKGROUND, locale), { colour: background })
      : background,
    beforeRatio: ratioText(correction.before.ratio, locale),
    threshold: thresholdText(correction.threshold, locale),
    after: colourText(correction.after, locale),
    afterRatio: ratioText(correction.after.ratio, locale),
    rules:
      correction.count > 1 ? fill(pick(CORRECTED_RULES, locale), { count: correction.count }) : "",
  });
}

function colourText(colour: { hex: string; name: string }, locale: GenerationLocale): string {
  const word = colourWord(colour.name, locale);
  const hex = colour.hex.toUpperCase();
  return word === "" ? hex : `${word} ${hex}`;
}

function ratioText(value: number, locale: GenerationLocale): string {
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: RATIO_DIGITS,
    maximumFractionDigits: RATIO_DIGITS,
  }).format(Math.floor(value * RATIO_SCALE) / RATIO_SCALE);
}

function thresholdText(value: number, locale: GenerationLocale): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: RATIO_DIGITS }).format(value);
}
