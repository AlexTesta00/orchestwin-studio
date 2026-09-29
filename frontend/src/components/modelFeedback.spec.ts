import { describe, expect, it } from "vitest";

import { modelFeedback } from "./modelFeedback";

const REFUSALS = [
  [
    "UX_DESIGNER_REQUIRED",
    "The team of this project has no UX/UI designer, so the design alternatives cannot be prepared. Go back to the Team step, add the designer and approve the team again.",
    "La squadra di questo progetto non ha un designer UX/UI, quindi le alternative di design non si possono preparare. Torna al passo Squadra, aggiungi il designer e approva di nuovo la squadra.",
  ],
  [
    "REQUIREMENTS_ANALYST_REQUIRED",
    "The team of this project has no needs analyst, so the requirements cannot be prepared. Go back to the Team step, add the analyst and approve the team again.",
    "La squadra di questo progetto non ha un analista delle esigenze, quindi i requisiti non si possono preparare. Torna al passo Squadra, aggiungi l’analista e approva di nuovo la squadra.",
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

  it("has no sentence for a code it does not know or for a missing code", () => {
    expect(modelFeedback("NOT_A_REASON", "en")).toBeUndefined();
    expect(modelFeedback("", "it")).toBeUndefined();
    expect(modelFeedback(null, "en")).toBeUndefined();
    expect(modelFeedback(undefined, "it")).toBeUndefined();
  });
});
