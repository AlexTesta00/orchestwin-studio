const messages: Record<string, [string, string]> = {
  INVALID_PROVIDER_OUTPUT: [
    "The model returned an invalid proposal. No artifact was saved. You can try again.",
    "Il modello ha restituito una proposta non valida. Nessun artefatto è stato salvato. Puoi riprovare.",
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
    "The model is unavailable. Check model status above before retrying.",
    "Il modello non è disponibile. Controlla lo stato dei modelli qui sopra prima di riprovare.",
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
    ? "Generazione reale in corso. Sulla GPU locale può richiedere diversi minuti; mantieni aperta questa pagina."
    : "Real model generation is running. On a local GPU it may take several minutes; keep this page open.";
}
