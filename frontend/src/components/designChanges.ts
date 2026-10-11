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
