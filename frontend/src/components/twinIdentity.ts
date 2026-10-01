import type { AgentIdentifier } from "@/api/team-contracts";

type Locale = "it" | "en";

export type StudioStep = 1 | 2 | 3 | 4 | 5 | 6;

type TeamImage = "a11y" | "an" | "ar" | "copy" | "fe" | "qa" | "ur" | "ux";

type RoleIdentity = {
  it: readonly [string, string];
  en: readonly [string, string];
  image: TeamImage;
  steps: readonly StudioStep[];
};

const EVERY_STEP: readonly StudioStep[] = [1, 2, 3, 4, 5, 6];

const roles: Record<AgentIdentifier, RoleIdentity> = {
  WORKFLOW_ORCHESTRATOR: {
    it: ["Coordinatore", "Organizza il lavoro e accompagna il progetto da un passo al successivo."],
    en: ["Coordinator", "Organizes the work and guides the project through each step."],
    image: "an",
    steps: EVERY_STEP,
  },
  INTAKE_CLARIFICATION_AGENT: {
    it: ["Guida del progetto", "Ti aiuta a chiarire l'idea, gli obiettivi e le priorità."],
    en: ["Project guide", "Helps you clarify the idea, goals and priorities."],
    image: "copy",
    steps: [1],
  },
  TEAM_SELECTOR: {
    it: ["Organizzatore delle prospettive", "Propone le prospettive adatte alla tua idea."],
    en: ["Perspectives planner", "Suggests the perspectives your idea needs."],
    image: "ur",
    steps: [2],
  },
  HUMAN_GATE_CONTROLLER: {
    it: ["Referente delle approvazioni", "Aspetta la tua conferma prima di proseguire."],
    en: ["Approval guide", "Waits for your confirmation before moving on."],
    image: "an",
    steps: EVERY_STEP,
  },
  ARTIFACT_MANAGER: {
    it: [
      "Custode delle versioni",
      "Conserva proposte, risultati e decisioni per ritrovarli in ogni momento.",
    ],
    en: ["Version keeper", "Keeps proposals, results and decisions available for review."],
    image: "copy",
    steps: EVERY_STEP,
  },
  SANDBOX_CONTROLLER: {
    it: ["Responsabile delle prove", "Esegue le prove in un ambiente separato dal tuo progetto."],
    en: ["Test environment keeper", "Runs checks in an environment separate from your project."],
    image: "qa",
    steps: [],
  },
  REQUIREMENTS_ANALYST: {
    it: [
      "Analista delle esigenze",
      "Trasforma il brief in requisiti chiari, con un modo per verificarli.",
    ],
    en: ["Needs analyst", "Turns the brief into clear requirements, each with a way to check it."],
    image: "an",
    steps: [4],
  },
  UX_RESEARCHER_USER_MODELER: {
    it: ["Ricercatore degli utenti", "Costruisce i twin e raccoglie le loro critiche."],
    en: ["User researcher", "Builds the twins and gathers their critiques."],
    image: "ur",
    steps: [3, 5],
  },
  UX_UI_DESIGNER: {
    it: ["Designer UX/UI", "Propone le alternative di design e i mockup navigabili."],
    en: ["UX/UI designer", "Proposes the design alternatives and the clickable mockups."],
    image: "ux",
    steps: [5],
  },
  SOFTWARE_ARCHITECT: {
    it: ["Architetto del prodotto", "Controlla che requisiti e design stiano in piedi insieme."],
    en: ["Product architect", "Checks that requirements and design hold together."],
    image: "ar",
    steps: [4, 6],
  },
  FRONTEND_ENGINEER: {
    it: ["Sviluppatore dell'interfaccia", "Prepara il pacchetto per chi costruirà le schermate."],
    en: ["Interface developer", "Prepares the package for whoever builds the screens."],
    image: "fe",
    steps: [5, 6],
  },
  BACKEND_ENGINEER: {
    it: ["Sviluppatore dei servizi", "Gestisce dati e funzioni che lavorano dietro le schermate."],
    en: ["Service developer", "Builds the data and features behind the screens."],
    image: "fe",
    steps: [5, 6],
  },
  MOBILE_ENGINEER: {
    it: ["Sviluppatore mobile", "Realizza l'esperienza per telefoni e tablet."],
    en: ["Mobile developer", "Builds the experience for phones and tablets."],
    image: "fe",
    steps: [5, 6],
  },
  QA_TEST_ENGINEER: {
    it: [
      "Specialista della qualità",
      "Scrive come controllare ogni requisito prima di dire «finito».",
    ],
    en: ["Quality specialist", "Writes how to check each requirement before calling it done."],
    image: "qa",
    steps: [4, 6],
  },
  SECURITY_REVIEWER: {
    it: ["Specialista della sicurezza", "Controlla accessi, riservatezza e protezione dei dati."],
    en: ["Security specialist", "Reviews access, privacy and data protection."],
    image: "qa",
    steps: [4, 5],
  },
  ACCESSIBILITY_REVIEWER: {
    it: [
      "Specialista dell'accessibilità",
      "Rivede contrasto, uso da tastiera e leggibilità dei mockup.",
    ],
    en: [
      "Accessibility specialist",
      "Reviews contrast, keyboard use and readability of the mockups.",
    ],
    image: "a11y",
    steps: [5],
  },
  INTEGRATION_ENGINEER: {
    it: [
      "Specialista dei collegamenti",
      "Collega il prodotto agli altri servizi di cui hai bisogno.",
    ],
    en: ["Integration specialist", "Connects your product to the other services it needs."],
    image: "ar",
    steps: [4, 6],
  },
};

export const TWIN_AVATARS = ["/twins/vb.webp", "/twins/lb.webp", "/twins/cp.webp"] as const;

export interface TwinRoster {
  readonly personaIds: readonly string[];
  readonly twins: readonly { readonly twinId: string; readonly personaId: string }[];
}

function knownRole(role: string | undefined): RoleIdentity | null {
  return role && Object.hasOwn(roles, role) ? roles[role as AgentIdentifier] : null;
}

function seedOf(value: string): number {
  let seed = 0;
  for (const character of value) seed = (Math.imul(seed, 31) + character.charCodeAt(0)) >>> 0;
  return seed;
}

export function roleAvatar(role: string | undefined): string {
  return `/team/${knownRole(role)?.image ?? "copy"}.webp`;
}

export function roleSteps(role: string | undefined): readonly StudioStep[] {
  return knownRole(role)?.steps ?? [];
}

export function twinPeers(personaIds: readonly string[]): string[] {
  return [...new Set(personaIds)].sort();
}

export function twinAvatar(identityKey: string, peers: readonly string[] = []): string {
  const position = peers.indexOf(identityKey);
  const index = position >= 0 ? position : seedOf(identityKey);
  return TWIN_AVATARS[index % TWIN_AVATARS.length] ?? TWIN_AVATARS[0];
}

export function rosterAvatar(identityKey: string, roster: TwinRoster): string {
  const personaKey =
    roster.twins.find((twin) => twin.twinId === identityKey)?.personaId ?? identityKey;
  return twinAvatar(personaKey, twinPeers(roster.personaIds));
}

export function twinIdentity(
  role: string | undefined,
  identityKey: string,
  locale: Locale,
  peers: readonly string[] = [],
) {
  const known = knownRole(role);
  if (known) {
    return {
      name: known[locale][0],
      description: known[locale][1],
      avatar: roleAvatar(role),
      isUser: false,
    };
  }
  return {
    name: role ? (locale === "it" ? "Specialista" : "Specialist") : "User Twin",
    description: role
      ? locale === "it"
        ? "Contribuisce al lavoro sul progetto."
        : "Contributes to the work on the project."
      : locale === "it"
        ? "Rappresenta un punto di vista degli utenti del prodotto."
        : "Represents a point of view of your product's users.",
    avatar: role ? roleAvatar(role) : twinAvatar(identityKey, peers),
    isUser: !role,
  };
}
