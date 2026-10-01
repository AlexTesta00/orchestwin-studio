import { describe, expect, it } from "vitest";

import { generationProgress, modelFeedback } from "./modelFeedback";

const REFUSALS = [
  [
    "UX_DESIGNER_REQUIRED",
    "The User experience (UX) perspective is missing: open Perspectives and prepare them again.",
    "Manca la prospettiva Esperienza d'uso (UX): apri Prospettive e preparale di nuovo.",
  ],
  [
    "REQUIREMENTS_ANALYST_REQUIRED",
    "The Product perspective is missing: open Perspectives and prepare them again.",
    "Manca la prospettiva Prodotto: apri Prospettive e preparale di nuovo.",
  ],
  [
    "GROUNDED_INPUT_REQUIRED",
    "The approved steps do not give the model enough facts for this proposal. Add details to the brief or to the earlier steps, then try again.",
    "I passi approvati non danno al modello abbastanza informazioni per questa proposta. Aggiungi dettagli al brief o ai passi precedenti, poi riprova.",
  ],
  [
    "PROPOSAL_REJECTED",
    "The model could not prepare this proposal from the approved steps. Your project is unchanged. You can try again.",
    "Il modello non è riuscito a preparare questa proposta a partire dai passi approvati. Il progetto è invariato. Puoi riprovare.",
  ],
  [
    "INVALID_PROVIDER_OUTPUT",
    "The model returned an invalid proposal. Your project is unchanged. You can try again.",
    "Il modello ha restituito una proposta non valida. Il progetto è invariato. Puoi riprovare.",
  ],
] as const;

const API_CODE = /\b[A-Z]{2,}(?:_[A-Z]+)+\b/;

const CODES = [
  "WEB_SOURCE_MOCKUP_STRUCTURE_MISMATCH",
  "SOURCE_DESIGN_STRUCTURE_MISMATCH",
  "INVALID_MOCKUP_OUTPUT",
  "DESIGN_CONTEXT_CHANGED",
  "REAL_MOCKUP_MODEL_NOT_CONFIGURED",
  "SOURCE_JAVASCRIPT_SYNTAX_INVALID",
  "SOURCE_JAVASCRIPT_PARSER_UNAVAILABLE",
  "INVALID_PROVIDER_OUTPUT",
  "PROPOSAL_REJECTED",
  "UX_DESIGNER_REQUIRED",
  "REQUIREMENTS_ANALYST_REQUIRED",
  "GROUNDED_INPUT_REQUIRED",
  "INCOMPLETE_OUTPUT",
  "CONTEXT_BUDGET_EXCEEDED",
  "PROVIDER_UNAVAILABLE",
  "TIMEOUT",
  "INVALID_API_RESPONSE",
  "SOURCE_CONTEXT_LIMIT_EXCEEDED",
] as const;

const OLD_STEP_NAMES =
  /passo Squadra|Team step|passo Requisiti|Requirements step|passo Pacchetto|Package step|\bPacchetto\b/;

const TEAM_WORDS =
  /\b(?:squadr[ae]|teams?|agent[ei]|agents?|assistent[ei]|assistants?|specialist[ai]|specialists?|ruol[oi]|roles?|membr[oi]|members?)\b/i;

describe("modelFeedback", () => {
  it.each(REFUSALS)(
    "puts %s into plain words in English and in Italian",
    (code, english, italian) => {
      expect(modelFeedback(code, "en")).toBe(english);
      expect(modelFeedback(code, "it")).toBe(italian);
    },
  );

  it("keeps the codes of the API out of the sentences and gives each reason its own", () => {
    for (const locale of ["en", "it"] as const) {
      const sentences = REFUSALS.map(([code]) => modelFeedback(code, locale) ?? "");

      expect(sentences.filter((sentence) => API_CODE.test(sentence))).toEqual([]);
      expect(new Set(sentences).size).toBe(REFUSALS.length);
    }
  });

  it("names no step by its old name and speaks of no team, in English and in Italian", () => {
    for (const locale of ["en", "it"] as const) {
      const sentences = [
        ...CODES.map((code) => modelFeedback(code, locale) ?? ""),
        generationProgress(locale),
      ];

      expect(sentences.filter((sentence) => sentence.length === 0)).toEqual([]);
      expect(sentences.filter((sentence) => OLD_STEP_NAMES.test(sentence))).toEqual([]);
      expect(sentences.filter((sentence) => TEAM_WORDS.test(sentence))).toEqual([]);
    }
  });

  it("speaks of the model, not of an assistant, while it prepares or cannot answer", () => {
    expect(generationProgress("en")).toBe(
      "The model is preparing the proposal. This may take a few minutes; keep this page open.",
    );
    expect(generationProgress("it")).toBe(
      "Il modello sta preparando la proposta. Può richiedere alcuni minuti: lascia aperta questa pagina.",
    );
    expect(modelFeedback("PROVIDER_UNAVAILABLE", "en")).toBe(
      "The model cannot be reached. Check its availability in Project details before retrying.",
    );
    expect(modelFeedback("PROVIDER_UNAVAILABLE", "it")).toBe(
      "Il modello non è raggiungibile. Controlla la sua disponibilità in Dettagli del progetto prima di riprovare.",
    );
    expect(modelFeedback("INCOMPLETE_OUTPUT", "en")).toBe(
      "The model did not complete its response. Your project has been preserved. You can try again.",
    );
    expect(modelFeedback("INCOMPLETE_OUTPUT", "it")).toBe(
      "Il modello non ha completato la risposta. Il progetto è stato conservato. Puoi riprovare.",
    );
  });

  it("has no sentence for a code it does not know or for a missing code", () => {
    expect(modelFeedback("NOT_A_REASON", "en")).toBeUndefined();
    expect(modelFeedback("", "it")).toBeUndefined();
    expect(modelFeedback(null, "en")).toBeUndefined();
    expect(modelFeedback(undefined, "it")).toBeUndefined();
  });
});
