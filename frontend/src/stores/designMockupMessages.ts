import type { MockupIssuePayload } from "../types/designMockups";

export type MockupMessageLocale = "en" | "it";

interface LocalizedText {
  en: string;
  it: string;
}

const FAILURE_MESSAGES: Readonly<Record<string, LocalizedText>> = {
  MOCKUP_QUALITY_REJECTED: {
    en: "The mockup did not reach the quality the Studio requires, so it was discarded.",
    it: "Il mockup non raggiungeva la qualità che lo Studio richiede ed è stato scartato.",
  },
  UNSAFE_MOCKUP_OUTPUT: {
    en: "The answer contained elements that the Studio does not accept.",
    it: "La risposta conteneva elementi che lo Studio non accetta.",
  },
  MOCKUP_LANGUAGE_MISMATCH: {
    en: "The texts of the mockup were written in a different language from the requirements.",
    it: "I testi del mockup erano scritti in una lingua diversa da quella dei requisiti.",
  },
  MOCKUP_SCREEN_COUNT: {
    en: "The mockup had too many or too few screens for this alternative.",
    it: "Il mockup aveva troppe o troppo poche schermate per questa alternativa.",
  },
  MOCKUP_COVERAGE_TOO_LOW: {
    en: "The mockup showed less than half of the requirements of this alternative.",
    it: "Il mockup mostrava meno della metà dei requisiti di questa alternativa.",
  },
  MOCKUP_REJECTED: {
    en: "The Studio discarded the answer of the model.",
    it: "Lo Studio ha scartato la risposta del modello.",
  },
  GENERATED_MOCKUP_REQUIRES_VISUAL_LANGUAGE: {
    en: "This alternative has no visual style yet, so its mockup cannot be drawn.",
    it: "Questa alternativa non ha ancora uno stile visivo, quindi non si può disegnarne il mockup.",
  },
  GENERATION_BUDGET_EXCEEDED: {
    en: "The spending ceiling you set is not enough for this generation.",
    it: "Il tetto di spesa impostato non basta per questa generazione.",
  },
  GENERATION_BUDGET_UNAVAILABLE: {
    en: "The Studio could not check the spending ceiling, so it did not start the generation. Try again in a moment.",
    it: "Lo Studio non è riuscito a controllare il tetto di spesa, quindi non ha avviato la generazione. Riprova tra qualche istante.",
  },
  TOO_MANY_GENERATIONS: {
    en: "Too many generations are already running. Try again when one of them has finished.",
    it: "Ci sono già troppe generazioni in corso. Riprova quando una di queste sarà finita.",
  },
  REAL_MOCKUP_MODEL_NOT_CONFIGURED: {
    en: "The model that draws the mockups is not connected.",
    it: "Il modello che disegna i mockup non è collegato.",
  },
  DESIGN_CONTEXT_CHANGED: {
    en: "The design changed in the meantime. Open the step again and retry.",
    it: "Il design è cambiato nel frattempo. Riapri il passo e riprova.",
  },
  DESIGN_ALTERNATIVE_NOT_FOUND: {
    en: "This alternative is no longer part of the current design.",
    it: "Questa alternativa non fa più parte del design attuale.",
  },
  GENERATION_JOB_NOT_FOUND: {
    en: "The Studio no longer finds this generation, perhaps because it was restarted. You can try again.",
    it: "Lo Studio non trova più questa generazione, forse perché è stato riavviato. Puoi riprovare.",
  },
  GENERATION_POLL_TIMEOUT: {
    en: "The generation has been running for more than twenty minutes. Try again to check whether it is ready.",
    it: "La generazione dura da più di venti minuti. Riprova per controllare se è pronta.",
  },
  GENERATION_STATUS_UNAVAILABLE: {
    en: "The Studio did not say how the generation is going. Try again in a moment.",
    it: "Lo Studio non ha detto a che punto è la generazione. Riprova tra qualche istante.",
  },
  GENERATION_START_FAILED: {
    en: "The generation could not be started. Try again in a moment.",
    it: "Non è stato possibile avviare la generazione. Riprova tra qualche istante.",
  },
  GENERATION_FAILED: {
    en: "The generation did not succeed. You can try again.",
    it: "La generazione non è riuscita. Puoi riprovare.",
  },
  MOCKUP_STATUS_UNAVAILABLE: {
    en: "The Studio could not check whether a mockup already exists, so it did not start a new one. Try again in a moment.",
    it: "Lo Studio non è riuscito a verificare se esiste già un mockup, quindi non ne ha avviato uno nuovo. Riprova tra qualche istante.",
  },
  GENERATED_MOCKUP_NOT_FOUND: {
    en: "No mockup has been drawn for this alternative yet.",
    it: "Per questa alternativa non è ancora stato disegnato un mockup.",
  },
  GENERATED_MOCKUP_REQUIRED: {
    en: "To ask for changes, first apply a design whose mockup was drawn by the model.",
    it: "Per chiedere modifiche applica prima un design con un mockup disegnato dal modello.",
  },
  ITERATION_REQUEST_INVALID: {
    en: "Write the change in 1 to 1000 characters, with at most five rules of up to 300 characters each.",
    it: "Scrivi la modifica in 1-1000 caratteri, con al massimo cinque regole lunghe fino a 300 caratteri ciascuna.",
  },
  PROVIDER_UNAVAILABLE: {
    en: "The model cannot be reached right now. Try again in a few minutes.",
    it: "Il modello non è raggiungibile in questo momento. Riprova tra qualche minuto.",
  },
  TIMEOUT: {
    en: "The model did not answer in time.",
    it: "Il modello non ha risposto in tempo.",
  },
  RATE_LIMITED: {
    en: "The model received too many requests. Try again in a few minutes.",
    it: "Il modello ha ricevuto troppe richieste. Riprova tra qualche minuto.",
  },
  INCOMPLETE_OUTPUT: {
    en: "The model stopped before finishing its answer.",
    it: "Il modello si è fermato prima di finire la risposta.",
  },
  PROVIDER_REFUSED: {
    en: "The model declined to answer this request.",
    it: "Il modello ha rifiutato di rispondere a questa richiesta.",
  },
  RESPONSE_SCHEMA_ERROR: {
    en: "The answer of the model did not have the expected shape.",
    it: "La risposta del modello non aveva la forma prevista.",
  },
  AUTHENTICATION_FAILED: {
    en: "The Studio is not authorised to use the model. Check its key.",
    it: "Lo Studio non è autorizzato a usare il modello. Controlla la chiave.",
  },
  CONTEXT_BUDGET_EXCEEDED: {
    en: "The project is too large for the model.",
    it: "Il progetto è troppo grande per il modello.",
  },
  IDENTITY_MISMATCH: {
    en: "A different model from the configured one answered, so the answer was not used.",
    it: "Ha risposto un modello diverso da quello configurato, quindi la risposta non è stata usata.",
  },
  PROVIDER_ERROR: {
    en: "The model service returned an error.",
    it: "Il servizio del modello ha restituito un errore.",
  },
  INVALID_REQUEST: {
    en: "The model service did not accept the request.",
    it: "Il servizio del modello non ha accettato la richiesta.",
  },
  INVALID_API_RESPONSE: {
    en: "The Studio gave an answer that this page cannot read.",
    it: "Lo Studio ha dato una risposta che questa pagina non riesce a leggere.",
  },
  ACCESS_TOKEN_REQUIRED: {
    en: "Your session has expired. Log in again.",
    it: "La sessione è scaduta. Accedi di nuovo.",
  },
  invalid_authentication: {
    en: "Your session has expired. Log in again.",
    it: "La sessione è scaduta. Accedi di nuovo.",
  },
};

const REASON_MESSAGES: Readonly<Record<string, LocalizedText>> = {
  UNREACHABLE_SCREEN: {
    en: "A screen could not be reached from the first one.",
    it: "Una schermata non si poteva raggiungere dalla prima.",
  },
  NO_TRANSITION: {
    en: "The screens were not linked to each other.",
    it: "Le schermate non erano collegate tra loro.",
  },
  SELF_LINK: {
    en: "A link led back to its own screen without saying so.",
    it: "Un collegamento riportava alla stessa schermata senza dirlo.",
  },
  UNKNOWN_REQUIREMENT: {
    en: "A part of the mockup referred to a requirement that does not exist.",
    it: "Una parte del mockup citava un requisito che non esiste.",
  },
  UNTRACED_CONTROL: {
    en: "A control was not linked to any requirement.",
    it: "Un comando non era collegato a nessun requisito.",
  },
  UNTRACED_SCREEN: {
    en: "A screen was not linked to any requirement.",
    it: "Una schermata non era collegata a nessun requisito.",
  },
  UNLABELLED_CONTROL: {
    en: "A field had no label.",
    it: "Un campo non aveva un'etichetta.",
  },
  UNNAMED_ACTION: {
    en: "A button or a link had no name.",
    it: "Un pulsante o un collegamento non aveva un nome.",
  },
  TABLE_WITHOUT_HEADERS: {
    en: "A table had no column headers.",
    it: "Una tabella non aveva le intestazioni delle colonne.",
  },
  HEADING_COUNT: {
    en: "A screen did not have exactly one main title.",
    it: "Una schermata non aveva esattamente un titolo principale.",
  },
  SCREEN_TOO_EMPTY: {
    en: "A screen was too empty to look like a real product.",
    it: "Una schermata era troppo vuota per sembrare un prodotto vero.",
  },
  TABLE_TOO_SHORT: {
    en: "A table had too few rows to look real.",
    it: "Una tabella aveva troppo poche righe per sembrare vera.",
  },
  EMPTY_CELL: {
    en: "A table had empty cells.",
    it: "Una tabella aveva delle celle vuote.",
  },
  SELECT_TOO_SHORT: {
    en: "A drop-down list had fewer than two options.",
    it: "Un menu a tendina aveva meno di due opzioni.",
  },
  PLACEHOLDER_TEXT: {
    en: "Placeholder text stood in for real content.",
    it: "C'era testo segnaposto al posto di contenuti veri.",
  },
  LOW_CONTRAST: {
    en: "A text was hard to read on its background.",
    it: "Un testo non si leggeva bene sul suo sfondo.",
  },
  UNREADABLE_TEXT_COLOUR: {
    en: "A text colour was hard to read on the backgrounds of the page.",
    it: "Un colore del testo non si leggeva bene sugli sfondi della pagina.",
  },
  DATED_BACKGROUND: {
    en: "A background used a dated decorative pattern.",
    it: "Uno sfondo usava un motivo decorativo datato.",
  },
  HEADING_LEVEL_SKIPPED: {
    en: "The levels of the titles skipped a step.",
    it: "I livelli dei titoli saltavano un gradino.",
  },
  LIST_TOO_SHORT: {
    en: "A list had only one item.",
    it: "Un elenco aveva un solo elemento.",
  },
  EMPTY_CONTAINER: {
    en: "A box of the page was empty.",
    it: "Un riquadro della pagina era vuoto.",
  },
  DECORATIVE_ICON_EXPOSED: {
    en: "A decorative icon was read aloud by screen readers.",
    it: "Un'icona decorativa veniva letta dai lettori di schermo.",
  },
  BACKGROUND_WITHOUT_TEXT_COLOUR: {
    en: "A coloured background did not set the colour of its text.",
    it: "Uno sfondo colorato non indicava il colore del suo testo.",
  },
  NO_RESPONSIVE_RULE: {
    en: "The mockup did not adapt to small screens.",
    it: "Il mockup non si adattava agli schermi piccoli.",
  },
  SINGLE_STATE: {
    en: "Every screen showed the normal state: no error, confirmation or empty list.",
    it: "Tutte le schermate mostravano lo stato normale: nessun errore, conferma o elenco vuoto.",
  },
  WEAK_CONTROL_BORDER: {
    en: "The border of a field or of a button is too light to be seen.",
    it: "Il bordo di un campo o di un pulsante è troppo chiaro per essere visto.",
  },
  ICON_UNKNOWN: {
    en: "The Studio replaced an icon whose name it does not know with a plain one: the mockup is still valid.",
    it: "Lo Studio ha sostituito con un'icona semplice un'icona dal nome sconosciuto: il mockup resta valido.",
  },
  PLACEHOLDER_EMPTIED: {
    en: "The Studio emptied an icon or picture placeholder that held a drawing of its own: the mockup is still valid.",
    it: "Lo Studio ha svuotato il segnaposto di un'icona o di una foto che conteneva un disegno: il mockup resta valido.",
  },
  TEXT_COLOUR_REPLACED: {
    en: "The Studio replaced the colour of a text that was hard to read with a palette colour that reads well: the mockup is still valid.",
    it: "Lo Studio ha sostituito il colore di un testo poco leggibile con un colore della tavolozza che si legge bene: il mockup resta valido.",
  },
  CONTROL_BORDER_REPLACED: {
    en: "The Studio made the border of a field or of a button clearly visible: the mockup is still valid.",
    it: "Lo Studio ha reso ben visibile il bordo di un campo o di un pulsante: il mockup resta valido.",
  },
};

const GENERIC_FAILURE: LocalizedText = {
  en: "The request could not be completed. You can try again.",
  it: "Non è stato possibile completare la richiesta. Puoi riprovare.",
};

const GENERIC_REASON: LocalizedText = {
  en: "A part of the mockup did not follow the rules of the Studio.",
  it: "Una parte del mockup non rispettava le regole dello Studio.",
};

export function generationFailureMessage(
  code: string | null | undefined,
  locale: MockupMessageLocale,
): string {
  const text =
    code === null || code === undefined
      ? undefined
      : (FAILURE_MESSAGES[code] ?? REASON_MESSAGES[code]);

  return (text ?? GENERIC_FAILURE)[locale];
}

export function generationReasonMessages(
  reasons: readonly MockupIssuePayload[],
  locale: MockupMessageLocale,
): string[] {
  const messages: string[] = [];

  for (const reason of reasons) {
    const text = (REASON_MESSAGES[reason.code] ?? FAILURE_MESSAGES[reason.code] ?? GENERIC_REASON)[
      locale
    ];

    if (!messages.includes(text)) {
      messages.push(text);
    }
  }

  return messages;
}
