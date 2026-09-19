const messages: Record<string, [string, string]> = {
  WEB_SOURCE_MOCKUP_STRUCTURE_MISMATCH: [
    "These changes no longer match the selected screen design. Keep its fields, actions and navigation before saving again. Your edits are still here.",
    "Queste modifiche non rispettano più le schermate scelte. Mantieni i campi, le azioni e i collegamenti prima di salvare di nuovo. Le modifiche sono ancora qui.",
  ],
  SOURCE_DESIGN_STRUCTURE_MISMATCH: [
    "The source changes the selected mockup's controls or screens. No revision was saved; preserve the selected design before trying again.",
    "Il sorgente modifica i controlli o le schermate del mockup scelto. Nessuna revisione è stata salvata: conserva il design selezionato prima di riprovare.",
  ],
  INVALID_MOCKUP_OUTPUT: [
    "The model returned an inconsistent mockup. The current design is unchanged; generate a new draft.",
    "Il modello ha restituito un mockup incoerente. Il design corrente è invariato; genera una nuova bozza.",
  ],
  DESIGN_CONTEXT_CHANGED: [
    "The design changed during generation. Refresh this step before generating another mockup.",
    "Il design è cambiato durante la generazione. Aggiorna il passaggio prima di generare un altro mockup.",
  ],
  REAL_MOCKUP_MODEL_NOT_CONFIGURED: [
    "The UX/UI model is not connected. Check model status before generating a mockup.",
    "Il modello UX/UI non è collegato. Controlla lo stato dei modelli prima di generare un mockup.",
  ],
  SOURCE_JAVASCRIPT_SYNTAX_INVALID: [
    "The JavaScript contains syntax errors and cannot be accepted. No source revision was saved.",
    "Il codice JavaScript contiene errori di sintassi e non può essere accettato. Nessuna revisione è stata salvata.",
  ],
  SOURCE_JAVASCRIPT_PARSER_UNAVAILABLE: [
    "The application checker is unavailable. Ask whoever manages this installation to restore it before trying again.",
    "Il controllo dell’applicazione non è disponibile. Chi gestisce questa installazione deve ripristinarlo prima di un nuovo tentativo.",
  ],
  INVALID_PROVIDER_OUTPUT: [
    "The model returned an invalid proposal. Your project is unchanged. You can try again.",
    "Il modello ha restituito una proposta non valida. Il progetto è invariato. Puoi riprovare.",
  ],
  INCOMPLETE_OUTPUT: [
    "The model stopped before completing the proposal within its time or token budget. Check model status before retrying.",
    "Il modello non ha completato la proposta entro il limite di tempo o token. Controlla lo stato dei modelli prima di riprovare.",
  ],
  CONTEXT_BUDGET_EXCEEDED: [
    "The project exceeds the model context window. Reduce the scope or configure a larger context.",
    "Il progetto supera il contesto del modello. Riduci l’ambito o configura un contesto maggiore.",
  ],
  PROVIDER_UNAVAILABLE: [
    "The AI assistant cannot be reached. Check assistant availability in Project tools and details before retrying.",
    "L’assistente AI non è raggiungibile. Controlla la disponibilità in Strumenti e dettagli del progetto prima di riprovare.",
  ],
  TIMEOUT: [
    "Generation timed out. Check model status before retrying.",
    "La generazione ha superato il tempo disponibile. Controlla lo stato dei modelli prima di riprovare.",
  ],
  INVALID_API_RESPONSE: [
    "The server could not complete this operation. Refresh the stage and retry.",
    "Il server non ha completato l’operazione. Aggiorna la fase e riprova.",
  ],
  SOURCE_CONTEXT_LIMIT_EXCEEDED: [
    "The approved project is too large for the configured generation context. Its content has been preserved.",
    "Il progetto approvato supera il contesto configurato per la generazione. Il suo contenuto è stato preservato.",
  ],
};

export function modelFeedback(code: string | null | undefined, locale: "en" | "it") {
  return code ? messages[code]?.[locale === "it" ? 1 : 0] : undefined;
}

export function generationProgress(locale: "en" | "it") {
  return locale === "it"
    ? "L’assistente sta preparando la proposta. Può richiedere alcuni minuti: lascia aperta questa pagina."
    : "The assistant is preparing the proposal. This may take a few minutes; keep this page open.";
}
