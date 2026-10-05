export type ObservationLabelLocale = "en" | "it";

const LABELS: ReadonlyMap<string, readonly [string, string]> = new Map([
  ["role", ["Role", "Ruolo"]],
  ["age_range", ["Age range", "Fascia di età"]],
  ["summary", ["Profile summary", "Sintesi del profilo"]],
  ["expertise", ["Expertise", "Competenze"]],
  ["goals", ["Goals", "Obiettivi"]],
  ["recurring_tasks", ["Recurring tasks", "Attività ricorrenti"]],
  ["context_of_use", ["Context of use", "Contesto d'uso"]],
  ["information_needs", ["Information needs", "Bisogni informativi"]],
  ["decision_criteria", ["Decision criteria", "Criteri decisionali"]],
  ["preferred_vocabulary", ["Preferred vocabulary", "Vocabolario preferito"]],
  ["frustrations", ["Frustrations", "Frustrazioni"]],
  ["pain_points", ["Pain points", "Difficoltà"]],
  ["trust_concerns", ["Trust concerns", "Preoccupazioni sulla fiducia"]],
  ["accessibility_needs", ["Accessibility needs", "Esigenze di accessibilità"]],
  ["operational_constraints", ["Operational constraints", "Vincoli operativi"]],
  ["technical_literacy", ["Technical literacy", "Competenza tecnica"]],
  ["risk_sensitivity", ["Risk sensitivity", "Sensibilità al rischio"]],
  ["assumptions", ["Assumptions", "Assunzioni"]],
]);

function fieldOf(key: string): string {
  const segments = key
    .split(".")
    .map((segment) => segment.trim())
    .filter((segment) => segment.length > 0);
  return segments.at(-1) ?? "";
}

function readable(field: string): string {
  const words = field.replace(/[_-]+/gu, " ").replace(/\s+/gu, " ").trim();
  return words.length === 0 ? words : `${words.charAt(0).toLocaleUpperCase()}${words.slice(1)}`;
}

export function observationLabel(key: string, locale: ObservationLabelLocale): string {
  const field = fieldOf(key);
  const label = LABELS.get(field);
  return label === undefined ? readable(field) : label[locale === "it" ? 1 : 0];
}
