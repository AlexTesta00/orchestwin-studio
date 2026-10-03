import type { WhyNode } from "../types/why";

export const whyMessages = {
  it: {
    why: "Perché?",
    upstream: "Da dove viene",
    downstream: "Che cosa ne dipende",
    validation: "Da verificare con persone vere",
    context: "Contesto dichiarato",
    interrupted: "Catena interrotta",
    model: "Motivazione generata dal modello",
    missing: "Mancano i dati per questo collegamento",
    retired: "Fonte ritirata",
    loading: "Leggo i collegamenti…",
    error: "Non è stato possibile leggere i collegamenti.",
    notFound: "I collegamenti per questo artefatto non sono disponibili.",
    choose: "Scegli la versione e il contesto dell'artefatto",
    details: "Tutti i dettagli",
    none: "Nessun collegamento registrato.",
    version: "Versione",
    hash: "Hash",
    base: "Versione su cui si basa",
    audit: "Provenienza del mockup",
    links: "Collegamenti registrati",
    historical: "Versione storica",
    current: "Versione corrente",
    source: "Fonte",
    claim: "Affermazione registrata",
    unknownValue: "Valore sconosciuto",
    abstainedValue: "Il modello si è astenuto",
    supports: "Sostiene questo claim",
    contradicts: "Contesta questo claim",
    adds: "Aggiunge questo claim",
    quote: "Citazione",
    lines: "Righe",
    offsets: "Caratteri",
    rationale: "Motivazione registrata",
    owner: "Motivazione del proprietario",
    unknown: "Origine della motivazione sconosciuta",
    system: "Motivazione di sistema",
    twin: "Arriva al twin",
    evidence: "Arriva a evidenza attiva",
    allPaths: "Tutti i percorsi arrivano all'evidenza",
    yes: "Sì",
    no: "No",
    noValidation: "Nessuna verifica con persone registrata in questa catena.",
    declared: "Le prospettive erano attive alla generazione. Sono contesto dichiarato.",
    sourceUnavailable:
      "Il testo originale non è disponibile. La citazione conservata resta leggibile.",
    gaps: {
      MISSING_NEED: "Manca il bisogno collegato",
      MISSING_SCENARIO: "Manca lo scenario collegato",
      MISSING_TWIN: "Manca il twin collegato",
      MISSING_CLAIM: "Manca il claim collegato",
      MISSING_SOURCE: "Manca la fonte collegata",
      MISSING_SOURCE_VERSION: "Manca la versione esatta della fonte",
      MISSING_RATIONALE: "La motivazione non è stata registrata",
      SOURCE_RETIRED: "Fonte ritirata",
      SOURCE_TEXT_UNAVAILABLE: "Testo originale della fonte non disponibile",
      OMITTED_SECTION: "Dati di questa sezione non disponibili",
      CONTEXT_OUTDATED: "La base appartiene a una versione precedente",
      VALIDATION_REFERENCE_UNAVAILABLE: "Il riferimento esatto dell'ipotesi non è disponibile",
    },
    perspectives: {
      UX: "Esperienza utente",
      ACCESSIBILITY: "Accessibilità",
      SOFTWARE_ENGINEERING: "Ingegneria del software",
      PRODUCT: "Prodotto",
      SECURITY: "Sicurezza",
    },
  },
  en: {
    why: "Why?",
    upstream: "Where it comes from",
    downstream: "What depends on it",
    validation: "To verify with real people",
    context: "Declared context",
    interrupted: "Interrupted chain",
    model: "Model-generated rationale",
    missing: "Data for this link is missing",
    retired: "Retired source",
    loading: "Reading the links…",
    error: "The links could not be read.",
    notFound: "Links for this artifact are not available.",
    choose: "Choose the artifact version and context",
    details: "All details",
    none: "No links recorded.",
    version: "Version",
    hash: "Hash",
    base: "Version it is based on",
    audit: "Mockup provenance",
    links: "Recorded links",
    historical: "Historical version",
    current: "Current version",
    source: "Source",
    claim: "Recorded claim",
    unknownValue: "Unknown value",
    abstainedValue: "The model abstained",
    supports: "Supports this claim",
    contradicts: "Contradicts this claim",
    adds: "Adds this claim",
    quote: "Quote",
    lines: "Lines",
    offsets: "Characters",
    rationale: "Recorded rationale",
    owner: "Owner rationale",
    unknown: "Unknown rationale origin",
    system: "System rationale",
    twin: "Reaches the twin",
    evidence: "Reaches active evidence",
    allPaths: "All paths reach evidence",
    yes: "Yes",
    no: "No",
    noValidation: "No verification with people recorded in this chain.",
    declared: "These perspectives were active at generation. They are declared context.",
    sourceUnavailable: "The original text is unavailable. The preserved quote can still be read.",
    gaps: {
      MISSING_NEED: "The linked need is missing",
      MISSING_SCENARIO: "The linked scenario is missing",
      MISSING_TWIN: "The linked twin is missing",
      MISSING_CLAIM: "The linked claim is missing",
      MISSING_SOURCE: "The linked source is missing",
      MISSING_SOURCE_VERSION: "The exact source version is missing",
      MISSING_RATIONALE: "The rationale was not recorded",
      SOURCE_RETIRED: "Retired source",
      SOURCE_TEXT_UNAVAILABLE: "Original source text unavailable",
      OMITTED_SECTION: "Data for this section is unavailable",
      CONTEXT_OUTDATED: "The basis belongs to a previous version",
      VALIDATION_REFERENCE_UNAVAILABLE: "The exact hypothesis reference is unavailable",
    },
    perspectives: {
      UX: "User experience",
      ACCESSIBILITY: "Accessibility",
      SOFTWARE_ENGINEERING: "Software engineering",
      PRODUCT: "Product",
      SECURITY: "Security",
    },
  },
} as const;

export function whyGapLabel(code: string, locale: "en" | "it"): string {
  const copy = whyMessages[locale];
  return copy.gaps[code as keyof typeof copy.gaps] ?? copy.missing;
}

const claimLabels = {
  role: ["Ruolo", "Role"],
  age_range: ["Fascia d'età", "Age range"],
  expertise: ["Esperienza", "Expertise"],
  goals: ["Obiettivi", "Goals"],
  recurring_tasks: ["Comportamenti", "Behaviours"],
  context_of_use: ["Contesti coperti", "Covered contexts"],
  information_needs: ["Bisogni", "Needs"],
  decision_criteria: ["Criteri di decisione", "Decision criteria"],
  preferred_vocabulary: ["Lessico preferito", "Preferred vocabulary"],
  frustrations: ["Frustrazioni", "Frustrations"],
  pain_points: ["Difficoltà", "Pain points"],
  trust_concerns: ["Dubbi sulla fiducia", "Trust concerns"],
  accessibility_needs: ["Bisogni di accessibilità", "Accessibility needs"],
  operational_constraints: ["Vincoli", "Constraints"],
  technical_literacy: ["Competenze tecniche", "Technical literacy"],
  risk_sensitivity: ["Sensibilità al rischio", "Risk sensitivity"],
  assumptions: ["Ipotesi", "Assumptions"],
  description: ["Descrizione", "Description"],
  represents: ["Rappresenta", "Represents"],
  does_not_represent: ["Non rappresenta", "Does not represent"],
  evidence_gaps: ["Limiti delle evidenze", "Evidence gaps"],
} as const;

const containerLabels = {
  AGENT_TEAM: ["Prospettive", "Perspectives"],
  PROJECT_BRIEF: ["Brief del progetto", "Project brief"],
  USER_MODELING: ["User twin", "User twins"],
  REQUIREMENTS_SPECIFICATION: ["Definizione", "Definition"],
  DESIGN_PACKAGE: ["Design e valutazione", "Design and evaluation"],
} as const;

export function whyNodeTitle(node: WhyNode, locale: "en" | "it"): string {
  if (node.kind === "VALIDATION_OUTCOME") {
    const labels = {
      CONFIRMED: ["Confermata", "Confirmed"],
      REFUTED: ["Smentita", "Refuted"],
      UNCERTAIN: ["Incerta", "Uncertain"],
    } as const;
    return labels[node.title as keyof typeof labels]?.[locale === "it" ? 0 : 1] ?? node.title;
  }
  if (node.title === node.kind) {
    const label = containerLabels[node.kind as keyof typeof containerLabels];
    if (label) return label[locale === "it" ? 0 : 1];
  }
  if (node.kind !== "USER_TWIN_CLAIM") return node.title;
  const field = node.code.split(":user_twin.").at(-1) ?? node.title;
  return claimLabels[field as keyof typeof claimLabels]?.[locale === "it" ? 0 : 1] ?? node.title;
}

const relationLabels = {
  GROUNDED_IN: ["Si basa su", "Is grounded in"],
  MOTIVATED_BY: ["Risponde al bisogno", "Addresses the need"],
  REVEALED_BY: ["È emerso nello scenario", "Emerged in the scenario"],
  TRACES_TO: ["È collegato a", "Is linked to"],
  SELECTS: ["Seleziona", "Selects"],
  EVALUATED_BY: ["È valutato dal twin", "Is evaluated by the twin"],
  EVALUATES: ["Riguarda", "Concerns"],
  CRITIQUES: ["Esamina", "Reviews"],
  SUPPORTS: ["Ha il sostegno della fonte", "Is supported by the source"],
  CONTRADICTS: ["È contestato dalla fonte", "Is contradicted by the source"],
  ADDS: ["Deriva dalla fonte", "Comes from the source"],
  CONTEXT: ["Ha come contesto", "Has context"],
  ACTOR: ["Ha come attore", "Has actor"],
  CLAIM_OF: ["È un claim del twin", "Is a claim of the twin"],
  HAS_CLAIM: ["Ha il claim", "Has claim"],
  CONTAINS: ["Contiene", "Contains"],
  ORIGINATES_FROM: ["Origina da", "Originates from"],
  VERIFIES_SCENARIO: ["Verifica lo scenario", "Verifies the scenario"],
  VERIFIES_DESIGN: ["Verifica il design", "Verifies the design"],
  TESTS_HYPOTHESIS: ["Verifica l'ipotesi", "Tests the hypothesis"],
  RECORDED_IN: ["È registrato nella fonte", "Is recorded in the source"],
} as const;

export function whyRelationLabel(kind: string, locale: "en" | "it"): string {
  return (
    relationLabels[kind as keyof typeof relationLabels]?.[locale === "it" ? 0 : 1] ??
    (locale === "it" ? "È collegato a" : "Is linked to")
  );
}
