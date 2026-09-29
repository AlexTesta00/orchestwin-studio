import { describe, expect, it } from "vitest";

import { observationLabel } from "./observationLabels";

const TWIN_WORDS: Record<string, [string, string]> = {
  role: ["Role", "Ruolo"],
  expertise: ["Expertise", "Competenze"],
  goals: ["Goals", "Obiettivi"],
  recurring_tasks: ["Recurring tasks", "Attività ricorrenti"],
  context_of_use: ["Context of use", "Contesto d'uso"],
  information_needs: ["Information needs", "Bisogni informativi"],
  decision_criteria: ["Decision criteria", "Criteri decisionali"],
  preferred_vocabulary: ["Preferred vocabulary", "Vocabolario preferito"],
  frustrations: ["Frustrations", "Frustrazioni"],
  pain_points: ["Pain points", "Pain point"],
  trust_concerns: ["Trust concerns", "Preoccupazioni sulla fiducia"],
  accessibility_needs: ["Accessibility needs", "Esigenze di accessibilità"],
  operational_constraints: ["Operational constraints", "Vincoli operativi"],
  technical_literacy: ["Technical literacy", "Competenza tecnica"],
  risk_sensitivity: ["Risk sensitivity", "Sensibilità al rischio"],
  assumptions: ["Assumptions", "Assunzioni"],
};

describe("observationLabel", () => {
  it("names every field of a twin with the words of the step of the User Twins", () => {
    for (const [field, [english, italian]] of Object.entries(TWIN_WORDS)) {
      expect(observationLabel(`user_twin.${field}`, "en")).toBe(english);
      expect(observationLabel(`user_twin.${field}`, "it")).toBe(italian);
      expect(observationLabel(field, "it")).toBe(italian);
    }
  });

  it("names the fields of a persona with or without the prefix", () => {
    expect(observationLabel("persona.summary", "it")).toBe("Sintesi del profilo");
    expect(observationLabel("persona.summary", "en")).toBe("Profile summary");
    expect(observationLabel("summary", "en")).toBe("Profile summary");
    expect(observationLabel("persona.goals", "it")).toBe("Obiettivi");
    expect(observationLabel("persona.context_of_use", "en")).toBe("Context of use");
    expect(observationLabel("persona.age_range", "it")).toBe("Fascia di età");
  });

  it("turns an unknown key into readable words and never fails", () => {
    expect(observationLabel("user_twin.favourite_colour", "it")).toBe("Favourite colour");
    expect(observationLabel("working__hours", "en")).toBe("Working hours");
    expect(observationLabel("constructor", "en")).toBe("Constructor");
    expect(observationLabel("user_twin.", "en")).toBe("User twin");
    expect(observationLabel("", "it")).toBe("");
  });
});
