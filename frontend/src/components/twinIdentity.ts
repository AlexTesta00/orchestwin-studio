import type { AgentIdentifier } from "@/api/team-contracts";

type Locale = "it" | "en";
type RoleIdentity = {
  it: readonly [string, string];
  en: readonly [string, string];
  path: string;
  accent: string;
};

const roles: Record<AgentIdentifier, RoleIdentity> = {
  WORKFLOW_ORCHESTRATOR: {
    it: ["Coordinatore", "Organizza il lavoro e accompagna il progetto da un passo al successivo."],
    en: ["Coordinator", "Organizes the work and guides the project through each step."],
    path: "M12 3v5m-7 4h14M5 12v5m14-5v5M9 8h6v4H9zM2 17h6v4H2zM16 17h6v4h-6z",
    accent: "indigo",
  },
  INTAKE_CLARIFICATION_AGENT: {
    it: ["Guida del progetto", "Ti aiuta a chiarire l'idea, gli obiettivi e le priorità."],
    en: ["Project guide", "Helps you clarify the idea, goals and priorities."],
    path: "M4 4h16v12H9l-5 4V4Zm4 4h8m-8 4h5",
    accent: "sky",
  },
  TEAM_SELECTOR: {
    it: ["Organizzatore del team", "Propone gli specialisti adatti alla tua idea."],
    en: ["Team planner", "Suggests the specialists your idea needs."],
    path: "M8 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm-6 9v-2a6 6 0 0 1 12 0v2m3-10h5m-2.5-2.5v5M16 16l2 2 4-4",
    accent: "violet",
  },
  HUMAN_GATE_CONTROLLER: {
    it: ["Referente delle approvazioni", "Aspetta la tua conferma prima di proseguire."],
    en: ["Approval guide", "Waits for your confirmation before moving on."],
    path: "M12 3 3 7v6c0 5 9 8 9 8s9-3 9-8V7l-9-4Zm-4 9 3 3 5-6",
    accent: "emerald",
  },
  ARTIFACT_MANAGER: {
    it: [
      "Custode delle versioni",
      "Conserva proposte, risultati e decisioni per ritrovarli in ogni momento.",
    ],
    en: ["Version keeper", "Keeps proposals, results and decisions available for review."],
    path: "M3 7h18v14H3zM2 3h20v4H2zm7 9h6",
    accent: "amber",
  },
  SANDBOX_CONTROLLER: {
    it: ["Responsabile delle prove", "Esegue le prove in un ambiente separato dal tuo progetto."],
    en: ["Test environment keeper", "Runs checks in an environment separate from your project."],
    path: "m12 2 9 5v10l-9 5-9-5V7l9-5Zm-9 5 9 5 9-5m-9 5v10m-4-13 8-4",
    accent: "slate",
  },
  REQUIREMENTS_ANALYST: {
    it: ["Analista delle esigenze", "Trasforma la tua idea in funzioni e obiettivi chiari."],
    en: ["Needs analyst", "Turns your idea into clear features and goals."],
    path: "M8 3h12v18H4V7m4-4v4H4l4-4Zm1 8h7m-7 4h7m-7 4h4",
    accent: "sky",
  },
  UX_RESEARCHER_USER_MODELER: {
    it: ["Ricercatore degli utenti", "Esplora chi userà il prodotto e ciò di cui ha bisogno."],
    en: ["User researcher", "Explores who will use the product and what they need."],
    path: "M10 14a6 6 0 1 0 0-12 6 6 0 0 0 0 12Zm5-1 7 8M8 6h4m-2-2v4M3 21v-1a6 6 0 0 1 9-5",
    accent: "teal",
  },
  UX_UI_DESIGNER: {
    it: ["Designer UX/UI", "Disegna schermate semplici e percorsi facili da usare."],
    en: ["UX/UI designer", "Designs clear screens and easy-to-use journeys."],
    path: "M3 3h18v18H3zM3 8h18M8 8v13m4-5 6-6 2 2-6 6-3 1 1-3Z",
    accent: "violet",
  },
  SOFTWARE_ARCHITECT: {
    it: ["Architetto del prodotto", "Definisce come le parti del prodotto lavorano insieme."],
    en: ["Product architect", "Plans how the parts of the product work together."],
    path: "M9 2h6v6H9zm-7 14h6v6H2zm14 0h6v6h-6ZM12 8v4M5 16v-4h14v4",
    accent: "indigo",
  },
  FRONTEND_ENGINEER: {
    it: ["Sviluppatore dell'interfaccia", "Rende funzionanti le schermate che vedi e usi."],
    en: ["Interface developer", "Brings the screens you see and use to life."],
    path: "M2 3h20v16H2zM2 7h20m-14 4-3 2 3 2m8-4 3 2-3 2m-6 6h4",
    accent: "sky",
  },
  BACKEND_ENGINEER: {
    it: ["Sviluppatore dei servizi", "Gestisce dati e funzioni che lavorano dietro le schermate."],
    en: ["Service developer", "Builds the data and features behind the screens."],
    path: "M3 3h18v7H3zm0 11h18v7H3zM6 6.5h1m3 0h7m-11 11h1m3 0h7",
    accent: "slate",
  },
  MOBILE_ENGINEER: {
    it: ["Sviluppatore mobile", "Realizza l'esperienza per telefoni e tablet."],
    en: ["Mobile developer", "Builds the experience for phones and tablets."],
    path: "M6 2h12v20H6zM9 5h6m-4 14h2",
    accent: "teal",
  },
  QA_TEST_ENGINEER: {
    it: ["Specialista della qualità", "Controlla che le funzioni si comportino come previsto."],
    en: ["Quality specialist", "Checks that features work as expected."],
    path: "M6 3h12v3h3v16H3V6h3V3Zm0 3h12M7 14l3 3 7-8",
    accent: "emerald",
  },
  SECURITY_REVIEWER: {
    it: ["Specialista della sicurezza", "Controlla accessi, riservatezza e protezione dei dati."],
    en: ["Security specialist", "Reviews access, privacy and data protection."],
    path: "M5 10h14v12H5zm3 0V6a4 4 0 0 1 8 0v4m-4 5v3",
    accent: "amber",
  },
  ACCESSIBILITY_REVIEWER: {
    it: [
      "Specialista dell'accessibilità",
      "Aiuta a rendere il prodotto utilizzabile da più persone.",
    ],
    en: ["Accessibility specialist", "Helps more people use the product comfortably."],
    path: "M12 6a2 2 0 1 0 0-4 2 2 0 0 0 0 4ZM3 9l9 2 9-2m-9 2v5m0-5-5 11m5-11 5 11",
    accent: "rose",
  },
  INTEGRATION_ENGINEER: {
    it: [
      "Specialista dei collegamenti",
      "Collega il prodotto agli altri servizi di cui hai bisogno.",
    ],
    en: ["Integration specialist", "Connects your product to the other services it needs."],
    path: "M8 3v5m8-5v5M5 8h14v3a7 7 0 0 1-14 0V8Zm7 10v4M9 3v-1m6 1v-1",
    accent: "violet",
  },
};

const identityAccents = {
  indigo: "bg-indigo-50 text-indigo-700 ring-indigo-200",
  sky: "bg-sky-50 text-sky-700 ring-sky-200",
  violet: "bg-violet-50 text-violet-700 ring-violet-200",
  emerald: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  amber: "bg-amber-50 text-amber-800 ring-amber-200",
  slate: "bg-slate-100 text-slate-700 ring-slate-200",
  teal: "bg-teal-50 text-teal-700 ring-teal-200",
  rose: "bg-rose-50 text-rose-700 ring-rose-200",
} as const;

export function twinIdentity(role: string | undefined, identityKey: string, locale: Locale) {
  const known = role && Object.hasOwn(roles, role) ? roles[role as AgentIdentifier] : null;
  if (known) {
    return {
      name: known[locale][0],
      description: known[locale][1],
      path: known.path,
      accent: identityAccents[known.accent as keyof typeof identityAccents],
      isUser: false,
    };
  }
  let seed = 0;
  for (const character of identityKey) seed = (Math.imul(seed, 31) + character.charCodeAt(0)) >>> 0;
  const accents = Object.values(identityAccents);
  return {
    name: role ? (locale === "it" ? "Specialista" : "Specialist") : "User Twin",
    description: role
      ? locale === "it"
        ? "Contribuisce al lavoro del team."
        : "Contributes to the team's work."
      : locale === "it"
        ? "Rappresenta un punto di vista degli utenti del prodotto."
        : "Represents a perspective of your product's users.",
    path: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-8 9v-1a8 8 0 0 1 16 0v1",
    accent: accents[seed % accents.length],
    isUser: !role,
  };
}

export function identityInitials(name: string): string {
  return name
    .trim()
    .split(/\s+/u)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => [...part][0])
    .join("")
    .toLocaleUpperCase();
}
