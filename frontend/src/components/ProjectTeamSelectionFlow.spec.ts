import { createPinia, setActivePinia } from "pinia";
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils";
import { defineComponent, h, vShow, withDirectives } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  AGENT_IDENTIFIERS,
  type AgentCatalogEntryResponse,
  type AgentCatalogResponse,
  type AgentIdentifier,
  type AgentTeamApi,
  type PerspectiveAspectKey,
  type PerspectiveKey,
  type PerspectiveStanding,
  type PerspectiveView,
  type ProjectWorkflowReadiness,
  type RuleEvidenceResponse,
  type TeamProposalEditInput,
  type TeamProposalRevisionKind,
  type TeamProposalVersionResponse,
  type TeamSelectionIssueResponse,
} from "@/api/team-contracts";
import type {
  HumanGateEventKind,
  HumanGateEventResponse,
  HumanGateResponse,
  HumanGateStatus,
} from "@/api/workflow-contracts";
import { ApiError } from "@/api/client";
import { createAppI18n } from "@/i18n";
import { type TeamAuthorizedRequest } from "@/stores/team";

import ProjectTeamSelectionFlow from "./ProjectTeamSelectionFlow.vue";
import { expectAccessible } from "@/test/axe";

enableAutoUnmount(afterEach);

const PROJECT_ID = "project-id";

const PLATFORM: readonly AgentIdentifier[] = AGENT_IDENTIFIERS.slice(0, 6);
const CORE: readonly AgentIdentifier[] = [
  "REQUIREMENTS_ANALYST",
  "UX_RESEARCHER_USER_MODELER",
  "UX_UI_DESIGNER",
  "SOFTWARE_ARCHITECT",
  "QA_TEST_ENGINEER",
  "ACCESSIBILITY_REVIEWER",
];
const BASE: readonly AgentIdentifier[] = [...PLATFORM, ...CORE];

const CATALOG: AgentCatalogResponse = {
  catalog_version: 1,
  content_hash: "a".repeat(64),
  agents: AGENT_IDENTIFIERS.map((agentId): AgentCatalogEntryResponse => {
    const platform = PLATFORM.includes(agentId);
    return {
      agent_id: agentId,
      catalog_version: 1,
      kind: platform ? "PLATFORM_COMPONENT" : "SPECIALIST",
      selection_policy: platform ? "ALWAYS_PRESENT" : "OWNER_SELECTABLE",
      capabilities: platform ? ["WORKFLOW_ORCHESTRATION"] : ["REQUIREMENTS_ANALYSIS"],
      supported_project_modes: ["GREENFIELD_GENERATION"],
      name_key: `agentCatalog.roles.${agentId.toLowerCase()}.name`,
      description_key: `agentCatalog.roles.${agentId.toLowerCase()}.description`,
      is_always_present: platform,
    };
  }),
};

type UnitKey = "SECURITY" | PerspectiveAspectKey;

interface UnitSignal {
  readonly standing: Exclude<PerspectiveStanding, "ALWAYS">;
  readonly requested?: RuleEvidenceResponse;
  readonly excluded?: RuleEvidenceResponse;
}

interface BriefSignals {
  readonly units?: Partial<Record<UnitKey, UnitSignal>>;
  readonly accessibilityWords?: RuleEvidenceResponse;
}

const UNIT_AGENTS: Readonly<Record<UnitKey, AgentIdentifier>> = {
  SECURITY: "SECURITY_REVIEWER",
  WEB: "FRONTEND_ENGINEER",
  SERVICES: "BACKEND_ENGINEER",
  MOBILE: "MOBILE_ENGINEER",
  INTEGRATIONS: "INTEGRATION_ENGINEER",
};
const ASPECT_KEYS: readonly PerspectiveAspectKey[] = ["WEB", "SERVICES", "MOBILE", "INTEGRATIONS"];
const NO_WORDS: RuleEvidenceResponse = { fields: [], terms: [] };

function perspectivesFor(
  selected: readonly AgentIdentifier[],
  signals: BriefSignals = {},
): PerspectiveView[] {
  const has = (agentId: AgentIdentifier) => selected.includes(agentId);
  const unit = (key: UnitKey) => {
    const signal: UnitSignal = signals.units?.[key] ?? { standing: "OPTIONAL" };
    return {
      agent_id: UNIT_AGENTS[key],
      standing: signal.standing,
      applied: has(UNIT_AGENTS[key]),
      editable: signal.standing === "OPTIONAL" || signal.standing === "CONTESTED",
      requested: signal.requested ?? NO_WORDS,
      excluded: signal.excluded ?? NO_WORDS,
    };
  };
  const always = (
    key: PerspectiveKey,
    agents: readonly AgentIdentifier[],
    requested: RuleEvidenceResponse = NO_WORDS,
  ): PerspectiveView => ({
    key,
    standing: "ALWAYS",
    applied: agents.every(has),
    editable: false,
    agent_id: null,
    requested,
    excluded: NO_WORDS,
    aspects: [],
  });
  return [
    always("UX", ["UX_RESEARCHER_USER_MODELER", "UX_UI_DESIGNER"]),
    always("ACCESSIBILITY", ["ACCESSIBILITY_REVIEWER"], signals.accessibilityWords),
    {
      ...always("SOFTWARE_ENGINEERING", ["SOFTWARE_ARCHITECT", "QA_TEST_ENGINEER"]),
      aspects: ASPECT_KEYS.map((key) => ({ key, ...unit(key) })),
    },
    always("PRODUCT", ["REQUIREMENTS_ANALYST"]),
    { key: "SECURITY", aspects: [], ...unit("SECURITY") },
  ];
}

interface VersionOptions {
  readonly signals?: BriefSignals | undefined;
  readonly issues?: readonly TeamSelectionIssueResponse[] | undefined;
  readonly briefVersion?: number | undefined;
  readonly revision?: TeamProposalRevisionKind | undefined;
  readonly withoutPerspectives?: boolean | undefined;
}

function proposalVersion(
  selected: readonly AgentIdentifier[],
  versionNumber = 1,
  options: VersionOptions = {},
): TeamProposalVersionResponse {
  return {
    id: `proposal-id-${versionNumber}`,
    project_id: PROJECT_ID,
    version_number: versionNumber,
    revision_kind:
      options.revision ?? (versionNumber === 1 ? "PROPOSER_GENERATED" : "OWNER_EDITED"),
    based_on_version_number: versionNumber === 1 ? null : versionNumber - 1,

    schema_version: 1,
    provider_kind: "FAKE_DETERMINISTIC",
    provider_id: "fake-deterministic-team-proposal",
    provider_version: 1,

    project_mode: "GREENFIELD_GENERATION",
    brief_version_id: `brief-version-id-${options.briefVersion ?? 1}`,
    brief_version_number: options.briefVersion ?? 1,
    brief_content_hash: "b".repeat(64),

    catalog_version: 1,
    catalog_content_hash: "a".repeat(64),
    constraints_content_hash: "c".repeat(64),
    content_hash: String(versionNumber).repeat(64),

    selected_agent_ids: selected,
    role_constraints: [],
    constraint_issues: options.issues ?? [],
    members: [],
    ...(options.withoutPerspectives === true
      ? {}
      : { perspectives: perspectivesFor(selected, options.signals) }),

    created_by_user_id: "owner-id",
    created_at: "2026-08-12T12:00:00Z",
  };
}

function gateFor(version: TeamProposalVersionResponse, status: HumanGateStatus): HumanGateResponse {
  return {
    id: "team-gate",
    project_id: PROJECT_ID,
    owner_user_id: "owner-id",
    gate_type: "AGENT_TEAM",
    artifact: {
      project_id: PROJECT_ID,
      gate_type: "AGENT_TEAM",
      artifact_id: version.id,
      version: version.version_number,
      content_hash: version.content_hash,
    },
    iteration: 1,
    max_iterations: 3,
    status,
    created_at: "2026-09-19T00:00:00Z",
    updated_at: "2026-09-19T00:00:00Z",
    event_sequence: 2,
    resume_status: null,
  };
}

const CONTRADICTION: TeamSelectionIssueResponse = {
  code: "CONTRADICTORY_ROLE_SIGNALS",
  agent_id: "BACKEND_ENGINEER",
  mandatory_reasons: [
    {
      code: "BACKEND_DELIVERY_SIGNAL",
      evidence: { fields: ["technical_constraints"], terms: ["api"] },
    },
  ],
  impossible_reasons: [
    {
      code: "EXPLICIT_SCOPE_EXCLUSION",
      evidence: { fields: ["description"], terms: ["senza server"] },
    },
  ],
};

const MIXED: BriefSignals = {
  accessibilityWords: { fields: ["non_functional_requirements"], terms: ["wcag"] },
  units: {
    WEB: {
      standing: "REQUIRED",
      requested: { fields: ["description", "technical_constraints"], terms: ["browser", "web"] },
    },
    SERVICES: {
      standing: "CONTESTED",
      requested: { fields: ["technical_constraints"], terms: ["api"] },
      excluded: { fields: ["description"], terms: ["senza server"] },
    },
    MOBILE: { standing: "OPTIONAL" },
    INTEGRATIONS: {
      standing: "EXCLUDED",
      excluded: { fields: ["description"], terms: ["no integrations"] },
    },
  },
};
const MIXED_SELECTED: readonly AgentIdentifier[] = [
  ...BASE,
  "FRONTEND_ENGINEER",
  "MOBILE_ENGINEER",
];

interface FakeState {
  current: TeamProposalVersionResponse | null;
  history: TeamProposalVersionResponse[];
  gate: HumanGateResponse | null;
  events?: HumanGateEventResponse[];
  signals?: BriefSignals;
  issues?: readonly TeamSelectionIssueResponse[];
  selection?: readonly AgentIdentifier[];
  readiness?: ProjectWorkflowReadiness | undefined;
  briefVersion?: number;
  failSubmit?: boolean;
  failApprovals?: number;
}

function record(
  state: FakeState,
  kind: HumanGateEventKind,
  previous: HumanGateStatus,
  resulting: HumanGateStatus,
  reason: string | null,
): void {
  if (state.current === null) return;
  const events = state.events ?? [];
  events.push({
    id: `event-${events.length + 1}`,
    gate_id: "team-gate",
    sequence_number: events.length + 1,
    kind,
    previous_status: previous,
    resulting_status: resulting,
    artifact: gateFor(state.current, resulting).artifact,
    occurred_at: "2026-09-19T00:00:00Z",
    actor_user_id: "owner-id",
    reason,
  });
  state.events = events;
}

function fakeApi(state: FakeState) {
  const api = {
    getAgentCatalog: vi.fn(async () => CATALOG),
    generateProjectTeamProposal: vi.fn(async () => {
      state.current = proposalVersion(state.selection ?? BASE, state.history.length + 1, {
        signals: state.signals,
        issues: state.issues,
        briefVersion: state.briefVersion,
        revision: "PROPOSER_GENERATED",
      });
      state.history.push(state.current);
      state.readiness = undefined;
      return { status: "CREATED" as const, version: state.current, issues: state.issues ?? [] };
    }),
    listProjectTeamProposals: vi.fn(async () => state.history),
    getCurrentProjectTeamProposal: vi.fn(async () => {
      if (state.current === null) throw new ApiError(404, "team_proposal_not_found");
      return state.current;
    }),
    editCurrentProjectTeamProposal: vi.fn(
      async (_accessToken: string, _projectId: string, input: TeamProposalEditInput) => {
        state.current = proposalVersion(input.selected_agent_ids, state.history.length + 1, {
          signals: state.signals,
          briefVersion: state.briefVersion,
          revision: "OWNER_EDITED",
        });
        state.history.push(state.current);
        return { status: "UPDATED" as const, version: state.current, issues: [], events: [] };
      },
    ),
    submitAgentTeamGate: vi.fn(async () => {
      if (state.failSubmit === true) throw new ApiError(503, "agent_team_service_unavailable");
      if (state.current === null) {
        return { status: "PROPOSAL_NOT_FOUND" as const, gate: null, events: [], issue: null };
      }
      state.gate = gateFor(state.current, "PENDING_APPROVAL");
      record(state, "SUBMIT", "DRAFT", "PENDING_APPROVAL", null);
      return { status: "SUBMITTED" as const, gate: state.gate, events: [], issue: null };
    }),
    getCurrentAgentTeamGate: vi.fn(async () => {
      if (state.gate === null) throw new ApiError(404, "agent_team_gate_not_found");
      return state.gate;
    }),
    listAgentTeamGateEvents: vi.fn(async () => state.events ?? []),
    decideAgentTeamGate: vi.fn(
      async (_accessToken: string, _projectId: string, action: string, reason?: string | null) => {
        if (state.gate === null || state.current === null) {
          return { status: "GATE_NOT_FOUND" as const, gate: null, event: null, issue: null };
        }
        if (action === "APPROVE" && (state.failApprovals ?? 0) > 0) {
          state.failApprovals = (state.failApprovals ?? 0) - 1;
          throw new ApiError(409, "gate_state_conflict");
        }
        const next: Record<string, HumanGateStatus> = {
          APPROVE: "APPROVED",
          REQUEST_REVISION: "REVISION_REQUESTED",
          REJECT: "REJECTED",
          PAUSE: "PAUSED",
          RESUME: "PENDING_APPROVAL",
          CANCEL: "CANCELLED",
        };
        const previous = state.gate.status;
        state.gate = gateFor(state.current, next[action] ?? state.gate.status);
        record(state, action as HumanGateEventKind, previous, state.gate.status, reason ?? null);
        return { status: "APPLIED" as const, gate: state.gate, event: null, issue: null };
      },
    ),
    getProjectWorkflowReadiness: vi.fn(async () => ({
      status:
        state.readiness ??
        (state.gate?.status === "APPROVED" && state.gate.artifact.artifact_id === state.current?.id
          ? ("READY_FOR_MAIN_WORKFLOW" as const)
          : ("TEAM_APPROVAL_REQUIRED" as const)),
    })),
  } satisfies AgentTeamApi;
  return api;
}

const executeAuthorized: TeamAuthorizedRequest = <T>(
  operation: (accessToken: string) => Promise<T>,
): Promise<T> => operation("access-token");

interface MountOptions {
  readonly attachTo?: HTMLElement;
  readonly locale?: "en" | "it";
  readonly sectionsMode?: boolean;
}

function mountFlow(api: AgentTeamApi, options: MountOptions = {}) {
  return mount(ProjectTeamSelectionFlow, {
    ...(options.attachTo === undefined ? {} : { attachTo: options.attachTo }),
    props: {
      projectId: PROJECT_ID,
      api,
      authorize: executeAuthorized,
      ...(options.sectionsMode === undefined ? {} : { sectionsMode: options.sectionsMode }),
    },
    global: {
      plugins: [createPinia(), createAppI18n(options.locale ?? "en")],
    },
  });
}

function emulateVisibility(): () => void {
  const original = Object.getOwnPropertyDescriptor(Element.prototype, "checkVisibility");
  Object.defineProperty(Element.prototype, "checkVisibility", {
    configurable: true,
    value(this: Element) {
      return this.closest('[style*="display: none"]') === null;
    },
  });
  return () => {
    if (original === undefined) {
      Reflect.deleteProperty(Element.prototype, "checkVisibility");
    } else {
      Object.defineProperty(Element.prototype, "checkVisibility", original);
    }
  };
}

type FlowWrapper = ReturnType<typeof mountFlow>;

function decisionBar(wrapper: FlowWrapper, decision: string) {
  return wrapper.get(`[data-testid="team-decision"][data-decision="${decision}"]`);
}

function perspectiveRow(wrapper: FlowWrapper, key: PerspectiveKey) {
  return wrapper.get(`[data-testid="perspective-row"][data-perspective="${key}"]`);
}

function aspectRow(wrapper: FlowWrapper, key: PerspectiveAspectKey) {
  return wrapper.get(`[data-testid="aspect-row"][data-aspect="${key}"]`);
}

function switchOf(wrapper: FlowWrapper, key: UnitKey) {
  return wrapper.get(`[data-testid="perspective-switch-${key}"]`);
}

function isOn(wrapper: FlowWrapper, key: UnitKey): boolean {
  return (switchOf(wrapper, key).element as HTMLInputElement).checked;
}

function referencedText(wrapper: FlowWrapper, ids: string | undefined): string {
  return (ids ?? "")
    .split(" ")
    .filter((id) => id.length > 0)
    .map((id) => wrapper.get(`[id="${id}"]`).text())
    .join(" ");
}

async function openTechnicalDetails(wrapper: FlowWrapper): Promise<void> {
  const toggle = wrapper.get(
    '[data-testid="team-technical-details"] [data-testid="step-technical-details-toggle"]',
  );
  if (toggle.attributes("aria-expanded") !== "true") {
    await toggle.trigger("click");
  }
}

async function refresh(wrapper: FlowWrapper): Promise<void> {
  await openTechnicalDetails(wrapper);
  await wrapper.get('[data-testid="team-refresh"]').trigger("click");
  await flushPromises();
}

async function save(wrapper: FlowWrapper): Promise<void> {
  await wrapper.get('[data-testid="team-selection-form"]').trigger("submit");
  await flushPromises();
}

const NAMES = {
  en: ["User experience (UX)", "Accessibility", "Software engineering", "Product", "Security"],
  it: [
    "Esperienza d'uso (UX)",
    "Accessibilità",
    "Ingegneria del software",
    "Prodotto",
    "Sicurezza",
  ],
} as const;

const LINES = {
  en: [
    "Looks at the project through the eyes of the people who will use it: goals, context, places where they may get stuck.",
    "Checks that everyone can use it: keyboard, contrast, readable text, clear messages.",
    "Keeps the project feasible within its technical constraints, time and budget, and verifiable.",
    "Keeps the priorities: what the first version needs and what can wait.",
    "Protects data and access: who may see and do what.",
  ],
  it: [
    "Guarda il progetto con gli occhi di chi lo userà: obiettivi, contesto, punti in cui ci si può bloccare.",
    "Controlla che tutti possano usarlo: tastiera, contrasto, testi leggibili, messaggi chiari.",
    "Tiene il progetto realizzabile entro vincoli tecnici, tempi e budget, e verificabile.",
    "Tiene le priorità: che cosa serve nella prima versione e che cosa può aspettare.",
    "Protegge dati e accessi: chi può vedere e fare che cosa.",
  ],
} as const;

const ASPECT_NAMES = {
  en: ["Web interface", "Services and data", "Mobile", "Connections to other systems"],
  it: ["Interfaccia web", "Servizi e dati", "Mobile", "Collegamenti con altri sistemi"],
} as const;

const ASPECT_LINES = {
  en: [
    "Works in the browser, from phone to desktop.",
    "Data and logic that live on a server.",
    "Use on phones and tablets.",
    "Data exchanged with outside services.",
  ],
  it: [
    "Funziona nel browser, dal telefono al computer.",
    "Dati e funzioni che stanno su un server.",
    "Uso su telefono e tablet.",
    "Scambio di dati con servizi esterni.",
  ],
} as const;

const BRINGS_LABELS = {
  en: ["In Definition", "In Design & Evaluation"],
  it: ["In Definizione", "In Design e valutazione"],
} as const;

const BRINGS = {
  en: [
    [
      "Stories and scenarios written from each twin's point of view; each requirement says what the person sees.",
      "Each alternative takes every twin to their goal in few steps and lets them correct a mistake.",
    ],
    [
      "Requirements and criteria on keyboard, contrast, names of controls and error messages.",
      "Every action reachable from the keyboard, readable contrast, no information by colour alone.",
    ],
    [
      "Requirements feasible within the constraints of the brief and criteria that can be checked by using the application.",
      "Alternatives that can be built, with the empty, loading and error states of each screen.",
    ],
    [
      "The priority of each requirement and what stays out.",
      "For each alternative, which goal it serves best and what it gives up.",
    ],
    [
      "Data and actions to protect, access, session, what happens with wrong credentials.",
      "How one sees being signed in and how to sign out, confirmations before deleting, sensitive data not in full.",
    ],
  ],
  it: [
    [
      "Storie e scenari scritti dal punto di vista di ogni twin; ogni requisito dice che cosa vede la persona.",
      "Ogni alternativa porta ogni twin al suo obiettivo in pochi passi e lascia correggere un errore.",
    ],
    [
      "Requisiti e criteri su tastiera, contrasto, nomi dei controlli e messaggi di errore.",
      "Ogni azione raggiungibile da tastiera, contrasto leggibile, nessuna informazione affidata al solo colore.",
    ],
    [
      "Requisiti realizzabili entro i vincoli del brief e criteri che si possono controllare usando l'applicazione.",
      "Alternative che si possono costruire, con gli stati vuoto, in caricamento e di errore di ogni schermata.",
    ],
    [
      "Priorità di ogni requisito e ciò che resta fuori.",
      "Per ogni alternativa, quale obiettivo serve meglio e a che cosa rinuncia.",
    ],
    [
      "Dati e azioni da proteggere, accesso, sessione, che cosa succede con credenziali sbagliate.",
      "Come si vede di essere entrati e come si esce, conferme prima di cancellare, dati sensibili non in chiaro.",
    ],
  ],
} as const;

const ALWAYS_MISSING = {
  en: "This version was prepared before this perspective became always applied: prepare the perspectives again.",
  it: "Questa versione è stata preparata prima che questa prospettiva diventasse sempre applicata: prepara di nuovo le prospettive.",
} as const;

const PREPARE_AGAIN = {
  en: "Prepare the perspectives again",
  it: "Prepara di nuovo le prospettive",
} as const;

const FORBIDDEN_WORDS = [
  "squadra",
  "team",
  "agente",
  "agenti",
  "agent",
  "agents",
  "assistente",
  "assistenti",
  "assistant",
  "assistants",
  "specialista",
  "specialisti",
  "specialist",
  "specialists",
  "ruolo",
  "ruoli",
  "role",
  "roles",
  "membro",
  "membri",
  "member",
  "members",
];

const FORBIDDEN = new RegExp(
  `(?<![\\p{L}\\p{N}_])(?:${FORBIDDEN_WORDS.join("|")})(?![\\p{L}\\p{N}_])`,
  "giu",
);

function readableText(root: Element): string {
  const attributes = [...root.querySelectorAll("*")].flatMap((element) =>
    ["aria-label", "placeholder", "title", "alt"].map((name) => element.getAttribute(name) ?? ""),
  );
  return [root.textContent ?? "", ...attributes].join("\n");
}

describe("ProjectTeamSelectionFlow", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    document.body.innerHTML = "";
  });

  it.each(["en", "it"] as const)(
    "shows in %s the five perspectives of a brief without signals, in order, with the aspects of software engineering",
    async (locale) => {
      const version = proposalVersion(BASE);
      const wrapper = mountFlow(fakeApi({ current: version, history: [version], gate: null }), {
        locale,
      });
      await flushPromises();

      expect(wrapper.find('[data-testid="perspectives-header"]').exists()).toBe(false);
      expect(wrapper.get('[data-testid="team-step"]').attributes("aria-label")).toBe(
        locale === "en" ? "Perspectives" : "Prospettive",
      );
      expect(wrapper.text()).not.toContain(
        locale === "en" ? "The competences through which" : "Le competenze con cui guardare",
      );
      const headings = wrapper.findAll("h1, h2, h3, h4, h5, h6");
      expect(headings[0]?.element.tagName).toBe("H2");
      expect(headings[0]?.text()).toBe(NAMES[locale][0]);
      expect(wrapper.find("h1").exists()).toBe(false);

      const rows = wrapper.findAll('[data-testid="perspective-row"]');
      expect(rows.map((row) => row.attributes("data-perspective"))).toEqual([
        "UX",
        "ACCESSIBILITY",
        "SOFTWARE_ENGINEERING",
        "PRODUCT",
        "SECURITY",
      ]);
      expect(rows.map((row) => row.get("h2").text())).toEqual(NAMES[locale]);
      expect(rows.map((row) => row.get('[data-testid="unit-line"]').text())).toEqual(LINES[locale]);
      expect(rows.map((row) => row.attributes("data-applied"))).toEqual([
        "true",
        "true",
        "true",
        "true",
        "false",
      ]);

      const aspects = perspectiveRow(wrapper, "SOFTWARE_ENGINEERING").findAll(
        '[data-testid="aspect-row"]',
      );
      expect(aspects.map((aspect) => aspect.attributes("data-aspect"))).toEqual(ASPECT_KEYS);
      expect(aspects.map((aspect) => aspect.get("h3").text())).toEqual(ASPECT_NAMES[locale]);
      expect(aspects.map((aspect) => aspect.get('[data-testid="unit-line"]').text())).toEqual(
        ASPECT_LINES[locale],
      );
      expect(wrapper.findAll('[data-testid="aspect-row"]')).toHaveLength(4);

      const always = locale === "en" ? "Always applied" : "Sempre applicata";
      const open = locale === "en" ? "Your choice" : "A scelta";
      expect(wrapper.findAll('[data-testid="unit-standing"]').map((node) => node.text())).toEqual([
        always,
        always,
        always,
        open,
        open,
        open,
        open,
        always,
        open,
      ]);
      expect(wrapper.find('[data-testid="unit-brief-words"]').exists()).toBe(false);
      expect(wrapper.get('[data-testid="perspectives-digest"]').text()).toBe(
        locale === "en"
          ? "In short: 4 of 5 perspectives applied."
          : "In breve: 4 prospettive applicate su 5.",
      );

      const switches = wrapper.findAll('input[role="switch"]');
      expect(switches.map((control) => control.attributes("data-testid"))).toEqual([
        "perspective-switch-WEB",
        "perspective-switch-SERVICES",
        "perspective-switch-MOBILE",
        "perspective-switch-INTEGRATIONS",
        "perspective-switch-SECURITY",
      ]);
      expect(
        switches.map((control) => referencedText(wrapper, control.attributes("aria-labelledby"))),
      ).toEqual([...ASPECT_NAMES[locale], NAMES[locale][4]]);
      expect(
        referencedText(wrapper, switchOf(wrapper, "SECURITY").attributes("aria-describedby")),
      ).toBe(`${open} ${LINES[locale][4]}`);
      expect(switches.every((control) => !(control.element as HTMLInputElement).checked)).toBe(
        true,
      );
      expect(wrapper.find("img").exists()).toBe(false);
      await expectAccessible(wrapper.element);
    },
  );

  it.each([
    [
      "en",
      [
        "Always applied",
        "Always applied",
        "Always applied",
        "The brief asks for it",
        "The brief says two different things: you decide",
        "Applied, your choice",
        "The brief rules it out",
        "Always applied",
        "Your choice",
      ],
      [
        ["requested", "“browser”, “web” in The idea, Technical constraints"],
        ["requested", "In favour: “api” in Technical constraints"],
        ["excluded", "Against: “senza server” in The idea"],
        ["excluded", "“no integrations” in The idea"],
      ],
      "In short: 4 of 5 perspectives applied. For you to decide: Services and data.",
    ],
    [
      "it",
      [
        "Sempre applicata",
        "Sempre applicata",
        "Sempre applicata",
        "La chiede il brief",
        "Il brief dice due cose diverse: decidi tu",
        "Applicata, a tua scelta",
        "Il brief la esclude",
        "Sempre applicata",
        "A scelta",
      ],
      [
        ["requested", "«browser», «web» in L'idea, Vincoli tecnici"],
        ["requested", "A favore: «api» in Vincoli tecnici"],
        ["excluded", "Contro: «senza server» in L'idea"],
        ["excluded", "«no integrations» in L'idea"],
      ],
      "In breve: 4 prospettive applicate su 5. Da decidere: Servizi e dati.",
    ],
  ] as const)(
    "says in %s the standing of every perspective and aspect with the words of the brief and their field",
    async (locale, standings, words, digest) => {
      const version = proposalVersion(MIXED_SELECTED, 1, {
        signals: MIXED,
        issues: [CONTRADICTION],
      });
      const wrapper = mountFlow(fakeApi({ current: version, history: [version], gate: null }), {
        locale,
      });
      await flushPromises();

      expect(wrapper.findAll('[data-testid="unit-standing"]').map((node) => node.text())).toEqual(
        standings,
      );
      expect(
        wrapper
          .findAll('[data-testid="unit-brief-words"]')
          .map((node) => [node.attributes("data-words"), node.text()]),
      ).toEqual(words);
      expect(
        perspectiveRow(wrapper, "ACCESSIBILITY").find('[data-testid="unit-brief-words"]').exists(),
      ).toBe(false);
      expect(wrapper.get('[data-testid="perspectives-digest"]').text()).toBe(digest);
      expect(
        wrapper.findAll('input[role="switch"]').map((control) => control.attributes("data-testid")),
      ).toEqual([
        "perspective-switch-SERVICES",
        "perspective-switch-MOBILE",
        "perspective-switch-SECURITY",
      ]);
      expect(aspectRow(wrapper, "WEB").find("input").exists()).toBe(false);
      expect(aspectRow(wrapper, "INTEGRATIONS").find("input").exists()).toBe(false);
      expect(isOn(wrapper, "SERVICES")).toBe(false);
      expect(isOn(wrapper, "MOBILE")).toBe(true);
      expect(wrapper.find('[role="alert"]').exists()).toBe(false);
      expect(wrapper.find('[class*="fail"]').exists()).toBe(false);
      await expectAccessible(wrapper.element);
    },
  );

  it.each([
    [
      "REQUIRED",
      {
        standing: "REQUIRED",
        requested: { fields: ["functional_requirements"], terms: ["password"] },
      },
      [...BASE, "SECURITY_REVIEWER"],
      "The brief asks for it",
      ["“password” in What it must do"],
      "In short: 5 of 5 perspectives applied.",
    ],
    [
      "EXCLUDED",
      { standing: "EXCLUDED", excluded: { fields: ["description"], terms: ["no login"] } },
      BASE,
      "The brief rules it out",
      ["“no login” in The idea"],
      "In short: 4 of 5 perspectives applied.",
    ],
    [
      "CONTESTED",
      {
        standing: "CONTESTED",
        requested: { fields: ["functional_requirements"], terms: ["password"] },
        excluded: { fields: ["description"], terms: ["no login"] },
      },
      BASE,
      "The brief says two different things: you decide",
      ["In favour: “password” in What it must do", "Against: “no login” in The idea"],
      "In short: 4 of 5 perspectives applied. For you to decide: Security.",
    ],
  ] as const)(
    "shows security %s on its own row with the words of the brief",
    async (standing, signal, selected, words, briefWords, digest) => {
      const version = proposalVersion(selected, 1, { signals: { units: { SECURITY: signal } } });
      const wrapper = mountFlow(fakeApi({ current: version, history: [version], gate: null }));
      await flushPromises();

      const security = perspectiveRow(wrapper, "SECURITY");
      expect(security.attributes("data-standing")).toBe(standing);
      expect(security.get('[data-testid="unit-standing"]').text()).toBe(words);
      expect(
        security.findAll('[data-testid="unit-brief-words"]').map((node) => node.text()),
      ).toEqual(briefWords);
      expect(security.find("input").exists()).toBe(standing === "CONTESTED");
      expect(wrapper.get('[data-testid="perspectives-digest"]').text()).toBe(digest);
      expect(wrapper.find('[role="alert"]').exists()).toBe(false);
    },
  );

  it("keeps a contested aspect off, not as an error, and saves it switched on with the complete selection and no rationale", async () => {
    const version = proposalVersion(MIXED_SELECTED, 1, {
      signals: MIXED,
      issues: [CONTRADICTION],
    });
    const state: FakeState = { current: version, history: [version], gate: null, signals: MIXED };
    const api = fakeApi(state);
    const wrapper = mountFlow(api);
    await flushPromises();

    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
    expect(wrapper.find('[data-state="error"]').exists()).toBe(false);
    expect(wrapper.find('[class*="fail"]').exists()).toBe(false);
    expect(isOn(wrapper, "SERVICES")).toBe(false);
    expect(aspectRow(wrapper, "SERVICES").attributes("data-applied")).toBe("false");
    expect(wrapper.find('[data-testid="team-changes"]').exists()).toBe(false);

    await switchOf(wrapper, "SERVICES").setValue(true);

    expect(aspectRow(wrapper, "SERVICES").get('[data-testid="unit-pending"]').text()).toBe(
      "To be saved",
    );
    expect(aspectRow(wrapper, "SERVICES").get('[data-testid="unit-standing"]').text()).toBe(
      "The brief says two different things: you decide",
    );
    expect(wrapper.find("textarea").exists()).toBe(false);
    expect(wrapper.get('[data-testid="team-changes"]').text()).toContain(
      "You changed the perspectives: save to create their new version.",
    );
    const bar = decisionBar(wrapper, "approve");
    expect(bar.get('[data-testid="decision-primary"]').attributes("disabled")).toBeDefined();
    expect(bar.text()).toContain("Save the changes to the perspectives before deciding.");

    await save(wrapper);

    expect(api.editCurrentProjectTeamProposal).toHaveBeenCalledTimes(1);
    expect(api.editCurrentProjectTeamProposal.mock.calls[0]?.slice(0, 2)).toEqual([
      "access-token",
      PROJECT_ID,
    ]);
    expect(api.editCurrentProjectTeamProposal.mock.calls[0]?.[2]).toStrictEqual({
      selected_agent_ids: [...MIXED_SELECTED, "BACKEND_ENGINEER"],
    });
    expect(wrapper.emitted("sections-changed")).toHaveLength(1);
    expect(isOn(wrapper, "SERVICES")).toBe(true);
    expect(aspectRow(wrapper, "SERVICES").attributes("data-applied")).toBe("true");
    expect(aspectRow(wrapper, "SERVICES").find('[data-testid="unit-pending"]').exists()).toBe(
      false,
    );
    expect(wrapper.find('[data-testid="team-changes"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="team-operation-status"]').text()).toBe(
      "The perspectives have been updated.",
    );
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
    expect(
      decisionBar(wrapper, "approve")
        .get('[data-testid="decision-primary"]')
        .attributes("disabled"),
    ).toBeUndefined();
  });

  it("switches security on and off after the approval, each change making a new version to approve", async () => {
    const first = proposalVersion(BASE);
    const state: FakeState = { current: first, history: [first], gate: gateFor(first, "APPROVED") };
    const api = fakeApi(state);
    const wrapper = mountFlow(api, { sectionsMode: true });
    await flushPromises();

    expect(wrapper.find('[data-testid="team-decision"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="perspectives-approved"]').exists()).toBe(true);
    expect(switchOf(wrapper, "SECURITY").attributes("disabled")).toBeUndefined();

    await switchOf(wrapper, "SECURITY").setValue(true);

    const security = () => perspectiveRow(wrapper, "SECURITY");
    expect(security().get('[data-testid="unit-standing"]').text()).toBe("Applied, your choice");
    expect(security().get('[data-testid="unit-pending"]').text()).toBe("To be saved");
    expect(wrapper.get('[data-testid="perspectives-digest"]').text()).toBe(
      "In short: 5 of 5 perspectives applied.",
    );

    await save(wrapper);

    expect(api.editCurrentProjectTeamProposal.mock.calls[0]?.[2]).toStrictEqual({
      selected_agent_ids: [...BASE, "SECURITY_REVIEWER"],
    });
    expect(security().attributes("data-applied")).toBe("true");
    expect(security().get('[data-testid="unit-standing"]').text()).toBe("Applied, your choice");
    expect(security().find('[data-testid="unit-pending"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="perspectives-approved"]').exists()).toBe(false);
    expect(decisionBar(wrapper, "approve").text()).toContain(
      "5 of 5 perspectives will guide the requirements and the design. You can change them later.",
    );

    await switchOf(wrapper, "SECURITY").setValue(false);

    expect(security().get('[data-testid="unit-standing"]').text()).toBe("Your choice");
    expect(security().get('[data-testid="unit-pending"]').text()).toBe("To be saved");
    expect(wrapper.get('[data-testid="perspectives-digest"]').text()).toBe(
      "In short: 4 of 5 perspectives applied.",
    );

    await save(wrapper);

    expect(api.editCurrentProjectTeamProposal).toHaveBeenCalledTimes(2);
    expect(api.editCurrentProjectTeamProposal.mock.calls[1]?.[2]).toStrictEqual({
      selected_agent_ids: [...BASE],
    });
    expect(security().attributes("data-applied")).toBe("false");
    expect(wrapper.emitted("sections-changed")).toHaveLength(2);
    expect(
      wrapper
        .get('[data-testid="team-technical-details"] [data-testid="step-technical-details-toggle"]')
        .text(),
    ).toContain("Version 3 · waiting for your decision");
  });

  it("undoes a pending change and keeps the decision disabled meanwhile", async () => {
    const state: FakeState = { current: proposalVersion(BASE), history: [], gate: null };
    const api = fakeApi(state);
    const wrapper = mountFlow(api);
    await flushPromises();

    await switchOf(wrapper, "SECURITY").setValue(true);

    const bar = decisionBar(wrapper, "approve");
    expect(bar.get('[data-testid="decision-primary"]').attributes("disabled")).toBeDefined();
    expect(bar.text()).toContain("Save the changes to the perspectives before deciding.");

    await wrapper.get('[data-testid="discard-team-changes"]').trigger("click");

    expect(wrapper.find('[data-testid="team-changes"]').exists()).toBe(false);
    expect(isOn(wrapper, "SECURITY")).toBe(false);
    expect(perspectiveRow(wrapper, "SECURITY").find('[data-testid="unit-pending"]').exists()).toBe(
      false,
    );
    expect(
      decisionBar(wrapper, "approve")
        .get('[data-testid="decision-primary"]')
        .attributes("disabled"),
    ).toBeUndefined();
    expect(api.editCurrentProjectTeamProposal).not.toHaveBeenCalled();
  });

  it("approves the perspectives with one press that sends them for approval and then approves them", async () => {
    const state: FakeState = { current: proposalVersion(BASE), history: [], gate: null };
    const api = fakeApi(state);
    const wrapper = mountFlow(api, { sectionsMode: true });
    await flushPromises();

    const bar = decisionBar(wrapper, "approve");
    expect(bar.attributes("data-gate-pending")).toBe("false");
    expect(bar.find('[data-testid="decision-secondary"]').exists()).toBe(false);
    expect(bar.get('[data-testid="decision-primary"]').text()).toBe("Approve the perspectives");
    expect(bar.text()).toContain(
      "4 of 5 perspectives will guide the requirements and the design. You can change them later.",
    );
    expect(wrapper.find('[data-testid="perspectives-approved"]').exists()).toBe(false);

    await bar.get('[data-testid="decision-primary"]').trigger("click");
    await flushPromises();

    expect(api.submitAgentTeamGate).toHaveBeenCalledTimes(1);
    expect(api.submitAgentTeamGate).toHaveBeenCalledWith("access-token", PROJECT_ID);
    expect(api.decideAgentTeamGate).toHaveBeenCalledTimes(1);
    expect(api.decideAgentTeamGate).toHaveBeenCalledWith(
      "access-token",
      PROJECT_ID,
      "APPROVE",
      null,
    );
    expect(api.submitAgentTeamGate.mock.invocationCallOrder[0]!).toBeLessThan(
      api.decideAgentTeamGate.mock.invocationCallOrder[0]!,
    );
    expect(wrapper.emitted("sections-changed")).toHaveLength(1);
    expect(wrapper.find('[data-testid="team-decision"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="team-other-decisions"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="perspectives-approved"]').text()).toBe(
      "You already approved the perspectives. You can still change them: each change creates a new version to approve, and the sections that follow are updated with one gesture without losing their content.",
    );
    expect(
      wrapper
        .get('[data-testid="team-technical-details"] [data-testid="step-technical-details-toggle"]')
        .text(),
    ).toContain("Version 1 · approved");
    await expectAccessible(wrapper.element);
  });

  it.each([
    [
      "en",
      "You already approved the perspectives. You can still change them: each change creates a new version to approve, and the sections that follow are updated with one gesture without losing their content.",
    ],
    [
      "it",
      "Hai già approvato le prospettive. Puoi ancora cambiarle: ogni cambio crea una versione nuova da approvare, e le sezioni che seguono si aggiornano con un gesto senza perdere i contenuti.",
    ],
  ] as const)(
    "says in %s after the approval that the perspectives can still change, once the six steps are sections",
    async (locale, sentence) => {
      const version = proposalVersion(BASE);
      const api = fakeApi({
        current: version,
        history: [version],
        gate: gateFor(version, "APPROVED"),
      });
      const sections = mountFlow(api, { locale, sectionsMode: true });
      await flushPromises();

      expect(sections.get('[data-testid="perspectives-approved"]').text()).toBe(sentence);
      expect(sections.find('[data-testid="team-decision"]').exists()).toBe(false);
      expect(sections.find('[data-testid="team-proposal-needed"]').exists()).toBe(false);
      expect(switchOf(sections, "SECURITY").attributes("disabled")).toBeUndefined();

      const firstPass = mountFlow(api, { locale });
      await flushPromises();

      expect(firstPass.find('[data-testid="perspectives-approved"]').exists()).toBe(false);
      expect(firstPass.text()).not.toContain(locale === "en" ? "sections" : "sezioni");
      expect(switchOf(firstPass, "SECURITY").attributes("disabled")).toBeUndefined();
    },
  );

  it.each([
    [
      "en",
      "In short: 3 of 5 perspectives applied.",
      BASE.filter((agentId) => agentId !== "ACCESSIBILITY_REVIEWER"),
      ["ACCESSIBILITY"],
    ],
    [
      "it",
      "In breve: 3 prospettive applicate su 5.",
      BASE.filter((agentId) => agentId !== "ACCESSIBILITY_REVIEWER"),
      ["ACCESSIBILITY"],
    ],
    [
      "it",
      "In breve: 1 prospettiva applicata su 5.",
      [...PLATFORM, "REQUIREMENTS_ANALYST"],
      ["UX", "ACCESSIBILITY", "SOFTWARE_ENGINEERING"],
    ],
  ] as const)(
    "says in %s «%s» for a proposal prepared before a perspective became always applied, and prepares it again",
    async (locale, digest, selected, missing) => {
      const version = proposalVersion(selected);
      const api = fakeApi({ current: version, history: [version], gate: null });
      const wrapper = mountFlow(api, { locale });
      await flushPromises();

      expect(wrapper.get('[data-testid="perspectives-digest"]').text()).toBe(digest);
      const flagged = wrapper
        .findAll('[data-testid="perspective-row"]')
        .filter((row) => row.find('[data-testid="unit-always-missing"]').exists());
      expect(flagged.map((row) => row.attributes("data-perspective"))).toEqual(missing);
      for (const row of flagged) {
        const own = row
          .findAll('[data-testid="unit-standing"], input')
          .filter((node) => node.element.closest('[data-testid="aspect-row"]') === null);
        expect(row.attributes("data-applied")).toBe("false");
        expect(own).toHaveLength(0);
        expect(row.get('[data-testid="unit-always-missing"] p').text()).toBe(
          ALWAYS_MISSING[locale],
        );
        expect(row.get('[data-testid="perspective-prepare-again"]').text()).toBe(
          PREPARE_AGAIN[locale],
        );
      }
      expect(perspectiveRow(wrapper, "PRODUCT").get('[data-testid="unit-standing"]').text()).toBe(
        locale === "en" ? "Always applied" : "Sempre applicata",
      );
      expect(
        [...readableText(wrapper.element).matchAll(FORBIDDEN)].map((match) => match[0]),
      ).toEqual([]);
      await expectAccessible(wrapper.element);

      await flagged[0]!.get('[data-testid="perspective-prepare-again"]').trigger("click");
      await flushPromises();

      expect(api.generateProjectTeamProposal).toHaveBeenCalledWith("access-token", PROJECT_ID);
      expect(wrapper.emitted("sections-changed")).toHaveLength(1);
      expect(wrapper.find('[data-testid="unit-always-missing"]').exists()).toBe(false);
      expect(wrapper.get('[data-testid="perspectives-digest"]').text()).toBe(
        locale === "en"
          ? "In short: 4 of 5 perspectives applied."
          : "In breve: 4 prospettive applicate su 5.",
      );
    },
  );

  it("shows only the standing of a unit that the project requires without words of the brief", async () => {
    const version = proposalVersion([...BASE, "INTEGRATION_ENGINEER"], 1, {
      signals: { units: { INTEGRATIONS: { standing: "REQUIRED" } } },
    });
    const wrapper = mountFlow(fakeApi({ current: version, history: [version], gate: null }));
    await flushPromises();

    const integrations = aspectRow(wrapper, "INTEGRATIONS");
    expect(integrations.attributes("data-applied")).toBe("true");
    expect(integrations.get('[data-testid="unit-standing"]').text()).toBe("The brief asks for it");
    expect(integrations.find('[data-testid="unit-brief-words"]').exists()).toBe(false);
    expect(integrations.find("input").exists()).toBe(false);
  });

  it.each([
    ["en", "The brief changed: prepare the perspectives again.", "Prepare the perspectives"],
    ["it", "Il brief è cambiato: prepara di nuovo le prospettive.", "Prepara le prospettive"],
  ] as const)(
    "asks in %s to prepare the perspectives again when the brief changed",
    async (locale, sentence, action) => {
      const first = proposalVersion(BASE);
      const state: FakeState = {
        current: first,
        history: [first],
        gate: gateFor(first, "APPROVED"),
        readiness: "TEAM_PROPOSAL_REQUIRED",
        briefVersion: 2,
      };
      const api = fakeApi(state);
      const wrapper = mountFlow(api, { locale, sectionsMode: true });
      await flushPromises();

      const needed = wrapper.get('[data-testid="team-proposal-needed"]');
      expect(needed.get("p").text()).toBe(sentence);
      expect(needed.get('[data-testid="generate-team"]').text()).toBe(action);
      expect(wrapper.find('[data-testid="team-decision"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="perspectives-approved"]').exists()).toBe(false);
      expect(wrapper.findAll('[data-testid="perspective-row"]')).toHaveLength(5);
      expect(switchOf(wrapper, "SECURITY").attributes("disabled")).toBeDefined();

      await needed.get('[data-testid="generate-team"]').trigger("click");
      await flushPromises();

      expect(api.generateProjectTeamProposal).toHaveBeenCalledWith("access-token", PROJECT_ID);
      expect(wrapper.find('[data-testid="team-proposal-needed"]').exists()).toBe(false);
      expect(wrapper.emitted("sections-changed")).toHaveLength(1);
      expect(wrapper.find('[data-testid="team-decision"][data-decision="approve"]').exists()).toBe(
        true,
      );
      expect(switchOf(wrapper, "SECURITY").attributes("disabled")).toBeUndefined();
    },
  );

  it("asks to approve the brief first and keeps the switches still meanwhile", async () => {
    const version = proposalVersion(BASE);
    const wrapper = mountFlow(
      fakeApi({
        current: version,
        history: [version],
        gate: null,
        readiness: "BRIEF_APPROVAL_REQUIRED",
      }),
    );
    await flushPromises();

    expect(wrapper.get('[data-testid="team-brief-first"]').text()).toBe(
      "Approve the brief first: the perspectives are derived from the approved brief.",
    );
    expect(wrapper.find('[data-testid="team-decision"]').exists()).toBe(false);
    expect(switchOf(wrapper, "SECURITY").attributes("disabled")).toBeDefined();
  });

  it("offers to prepare the perspectives when there are none yet", async () => {
    const state: FakeState = { current: null, history: [], gate: null };
    const api = fakeApi(state);
    const wrapper = mountFlow(api);
    await flushPromises();

    expect(wrapper.find('[data-testid="team-decision"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="perspective-row"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="perspectives-digest"]').exists()).toBe(false);
    const needed = wrapper.get('[data-testid="team-proposal-needed"]');
    expect(needed.get("p").text()).toBe(
      "The perspectives are derived from the approved brief, and you can change them afterwards.",
    );
    expect(needed.get('[data-testid="generate-team"]').text()).toBe("Prepare the perspectives");
    expect(wrapper.emitted("sections-changed")).toBeUndefined();
    await expectAccessible(wrapper.element);

    await needed.get('[data-testid="generate-team"]').trigger("click");
    await flushPromises();

    expect(api.generateProjectTeamProposal).toHaveBeenCalledWith("access-token", PROJECT_ID);
    expect(wrapper.find('[data-testid="team-proposal-needed"]').exists()).toBe(false);
    expect(wrapper.findAll('[data-testid="perspective-row"]')).toHaveLength(5);
    expect(wrapper.emitted("sections-changed")).toHaveLength(1);
    expect(wrapper.find('[data-testid="team-decision"][data-decision="approve"]').exists()).toBe(
      true,
    );
    await expectAccessible(wrapper.element);
  });

  it("prepares the perspectives of a brief that contradicts itself as a new version with a contested aspect", async () => {
    const state: FakeState = {
      current: null,
      history: [],
      gate: null,
      signals: MIXED,
      issues: [CONTRADICTION],
      selection: MIXED_SELECTED,
    };
    const api = fakeApi(state);
    const wrapper = mountFlow(api, { locale: "it" });
    await flushPromises();

    await wrapper.get('[data-testid="generate-team"]').trigger("click");
    await flushPromises();

    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
    expect(wrapper.find('[class*="fail"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="team-operation-status"]').text()).toBe(
      "Le prospettive sono state preparate.",
    );
    expect(aspectRow(wrapper, "SERVICES").attributes("data-standing")).toBe("CONTESTED");
    expect(isOn(wrapper, "SERVICES")).toBe(false);
    expect(wrapper.get('[data-testid="perspectives-digest"]').text()).toBe(
      "In breve: 4 prospettive applicate su 5. Da decidere: Servizi e dati.",
    );
    expect(wrapper.emitted("sections-changed")).toHaveLength(1);
    expect(
      decisionBar(wrapper, "approve")
        .get('[data-testid="decision-primary"]')
        .attributes("disabled"),
    ).toBeUndefined();
  });

  it.each(["en", "it"] as const)(
    "keeps what each perspective brings closed until asked, in %s",
    async (locale) => {
      const version = proposalVersion(BASE);
      const wrapper = mountFlow(fakeApi({ current: version, history: [version], gate: null }), {
        locale,
      });
      await flushPromises();

      const toggles = wrapper.findAll('[data-testid="perspective-brings-toggle"]');
      const region = (index: number) =>
        wrapper.get(`[id="${toggles[index]!.attributes("aria-controls")}"]`);
      expect(toggles).toHaveLength(5);
      toggles.forEach((toggle, index) => {
        expect(toggle.text()).toBe(locale === "en" ? "What it brings" : "Che cosa porta");
        expect(toggle.attributes("aria-expanded")).toBe("false");
        expect(referencedText(wrapper, toggle.attributes("aria-describedby"))).toBe(
          NAMES[locale][index],
        );
        expect(region(index).text()).toBe("");
      });
      expect(wrapper.text()).not.toContain(BRINGS[locale][0][0]);

      await toggles[0]!.trigger("click");

      expect(toggles[0]!.attributes("aria-expanded")).toBe("true");
      expect(
        region(0)
          .findAll("dt")
          .map((term) => term.text()),
      ).toEqual(BRINGS_LABELS[locale]);
      expect(
        region(0)
          .findAll("dd")
          .map((term) => term.text()),
      ).toEqual(BRINGS[locale][0]);
      expect(toggles[1]!.attributes("aria-expanded")).toBe("false");
      expect(region(1).text()).toBe("");

      for (const toggle of toggles.slice(1)) {
        await toggle.trigger("click");
      }
      toggles.forEach((toggle, index) => {
        expect(toggle.attributes("aria-expanded")).toBe("true");
        expect(
          region(index)
            .findAll("dd")
            .map((term) => term.text()),
        ).toEqual(BRINGS[locale][index]);
      });
      await expectAccessible(wrapper.element);

      await toggles[0]!.trigger("click");

      expect(toggles[0]!.attributes("aria-expanded")).toBe("false");
      expect(region(0).text()).toBe("");
      expect(toggles[1]!.attributes("aria-expanded")).toBe("true");
    },
  );

  it.each(["en", "it"] as const)(
    "uses no word of a team and no internal identifier anywhere, in %s",
    async (locale) => {
      const state: FakeState = {
        current: null,
        history: [],
        gate: null,
        signals: MIXED,
        issues: [CONTRADICTION],
        selection: MIXED_SELECTED,
      };
      const api = fakeApi(state);
      const wrapper = mountFlow(api, { locale, sectionsMode: true });
      const seen: string[] = [];
      const look = async () => {
        await flushPromises();
        seen.push(readableText(wrapper.element));
      };

      await look();
      expect(wrapper.find('[data-testid="team-proposal-needed"]').exists()).toBe(true);
      await wrapper.get('[data-testid="generate-team"]').trigger("click");
      await look();
      expect(wrapper.findAll('[data-testid="unit-brief-words"]')).toHaveLength(4);
      for (const toggle of wrapper.findAll('[data-testid="perspective-brings-toggle"]')) {
        await toggle.trigger("click");
      }
      await openTechnicalDetails(wrapper);
      await switchOf(wrapper, "SERVICES").setValue(true);
      await look();
      expect(wrapper.findAll("dd").length).toBeGreaterThan(10);
      expect(wrapper.find('[data-testid="team-changes"]').exists()).toBe(true);
      await save(wrapper);
      await look();
      await decisionBar(wrapper, "approve")
        .get('[data-testid="decision-primary"]')
        .trigger("click");
      await look();
      expect(wrapper.find('[data-testid="perspectives-approved"]').exists()).toBe(true);
      await switchOf(wrapper, "SECURITY").setValue(true);
      await save(wrapper);
      state.gate = gateFor(state.current!, "PENDING_APPROVAL");
      await refresh(wrapper);
      await decisionBar(wrapper, "approve")
        .get('[data-testid="decision-secondary"]')
        .trigger("click");
      await look();
      expect(wrapper.find('[data-testid="decision-note"]').exists()).toBe(true);
      expect(wrapper.find('[data-testid="team-other-decisions"]').exists()).toBe(true);
      await wrapper.get('[data-testid="team-gate-reason"]').setValue("Not now");
      await wrapper.get('[data-testid="team-reject"]').trigger("click");
      await look();
      expect(wrapper.find('[data-testid="team-gate-notice"]').exists()).toBe(true);
      state.readiness = "TEAM_PROPOSAL_REQUIRED";
      await refresh(wrapper);
      await look();
      expect(wrapper.find('[data-testid="team-proposal-needed"]').exists()).toBe(true);
      api.getAgentCatalog.mockRejectedValueOnce(
        new ApiError(503, "team_proposal_service_unavailable"),
      );
      await refresh(wrapper);
      await look();

      expect(wrapper.find('[role="alert"]').exists()).toBe(true);
      expect(seen).toHaveLength(9);
      const text = seen.join("\n");
      expect([...text.matchAll(FORBIDDEN)].map((match) => match[0])).toEqual([]);
      expect(AGENT_IDENTIFIERS.filter((agentId) => text.includes(agentId))).toEqual([]);
      expect(text).not.toContain("_");
      expect(wrapper.find("img").exists()).toBe(false);
    },
  );

  it("passes the accessibility checks with a pending change, what each perspective brings and the other decisions", async () => {
    const version = proposalVersion(MIXED_SELECTED, 1, {
      signals: MIXED,
      issues: [CONTRADICTION],
    });
    const wrapper = mountFlow(
      fakeApi({ current: version, history: [version], gate: gateFor(version, "PENDING_APPROVAL") }),
    );
    await flushPromises();

    for (const toggle of wrapper.findAll('[data-testid="perspective-brings-toggle"]')) {
      await toggle.trigger("click");
    }
    await switchOf(wrapper, "SERVICES").setValue(true);
    await openTechnicalDetails(wrapper);

    expect(wrapper.find('[data-testid="team-other-decisions"]').exists()).toBe(true);
    await expectAccessible(wrapper.element);
  });

  it.each([
    ["en", "Update the Studio to see the perspectives."],
    ["it", "Aggiorna lo Studio per vedere le prospettive."],
  ] as const)(
    "asks in %s to update the Studio when the proposal carries no perspectives",
    async (locale, sentence) => {
      const version = proposalVersion(BASE, 1, { withoutPerspectives: true });
      const wrapper = mountFlow(fakeApi({ current: version, history: [version], gate: null }), {
        locale,
      });
      await flushPromises();

      expect(wrapper.get('[data-testid="perspectives-unavailable"]').text()).toBe(sentence);
      expect(wrapper.find('[data-testid="perspective-row"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="perspectives-digest"]').exists()).toBe(false);
      expect(wrapper.find('input[role="switch"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="team-selection-form"]').exists()).toBe(false);
    },
  );

  it("tells the page that the sections changed only after a preparation, a save and an approval", async () => {
    const state: FakeState = { current: null, history: [], gate: null };
    const api = fakeApi(state);
    const wrapper = mountFlow(api);
    await flushPromises();
    const emitted = () => wrapper.emitted("sections-changed")?.length ?? 0;

    expect(emitted()).toBe(0);

    await wrapper.get('[data-testid="generate-team"]').trigger("click");
    await flushPromises();
    expect(emitted()).toBe(1);

    await switchOf(wrapper, "SECURITY").setValue(true);
    expect(emitted()).toBe(1);
    await save(wrapper);
    expect(emitted()).toBe(2);

    state.gate = gateFor(state.current!, "PENDING_APPROVAL");
    await refresh(wrapper);
    await wrapper.get('[data-testid="team-pause"]').trigger("click");
    await flushPromises();
    expect(emitted()).toBe(2);

    await decisionBar(wrapper, "resume").get('[data-testid="decision-primary"]').trigger("click");
    await flushPromises();
    expect(emitted()).toBe(2);

    await decisionBar(wrapper, "approve").get('[data-testid="decision-primary"]').trigger("click");
    await flushPromises();
    expect(emitted()).toBe(3);
    expect(api.submitAgentTeamGate).not.toHaveBeenCalled();

    await refresh(wrapper);
    expect(emitted()).toBe(3);
  });

  it("only approves when the perspectives already wait for approval and asks for changes there", async () => {
    const current = proposalVersion(BASE);
    const state: FakeState = {
      current,
      history: [current],
      gate: gateFor(current, "PENDING_APPROVAL"),
    };
    const api = fakeApi(state);
    const wrapper = mountFlow(api);
    await flushPromises();

    const bar = decisionBar(wrapper, "approve");
    expect(bar.attributes("data-gate-pending")).toBe("true");
    expect(bar.get('[data-testid="decision-secondary"]').text()).toBe("Ask for changes");

    await bar.get('[data-testid="decision-secondary"]').trigger("click");
    const note = bar.get('[data-testid="decision-note"]');
    expect(note.attributes("placeholder")).toBe(
      "Write what you would change in the perspectives: the note stays in the history of the decisions.",
    );
    await note.setValue("Add security");
    await bar.get('[data-testid="decision-send"]').trigger("click");
    await flushPromises();

    expect(api.submitAgentTeamGate).not.toHaveBeenCalled();
    expect(api.decideAgentTeamGate).toHaveBeenLastCalledWith(
      "access-token",
      PROJECT_ID,
      "REQUEST_REVISION",
      "Add security",
    );
    expect(wrapper.find('[data-testid="team-decision"]').exists()).toBe(false);
    const notice = wrapper.get('[data-testid="team-gate-notice"]');
    expect(notice.text()).toContain(
      "You asked for changes. Switch the perspectives you want and save: the new version comes back for your approval.",
    );
    expect(notice.text()).toContain("Your note: “Add security”");
    expect(wrapper.emitted("sections-changed")).toBeUndefined();

    state.gate = gateFor(current, "PENDING_APPROVAL");
    await refresh(wrapper);
    await decisionBar(wrapper, "approve").get('[data-testid="decision-primary"]').trigger("click");
    await flushPromises();

    expect(api.submitAgentTeamGate).not.toHaveBeenCalled();
    expect(api.decideAgentTeamGate).toHaveBeenLastCalledWith(
      "access-token",
      PROJECT_ID,
      "APPROVE",
      null,
    );
    expect(wrapper.find('[data-testid="team-decision"]').exists()).toBe(false);
    expect(wrapper.emitted("sections-changed")).toHaveLength(1);
  });

  it("shows the failed approval in plain words and only approves on the next press", async () => {
    const state: FakeState = {
      current: proposalVersion(BASE),
      history: [],
      gate: null,
      failApprovals: 1,
    };
    const api = fakeApi(state);
    const wrapper = mountFlow(api);
    await flushPromises();

    await decisionBar(wrapper, "approve").get('[data-testid="decision-primary"]').trigger("click");
    await flushPromises();

    expect(api.submitAgentTeamGate).toHaveBeenCalledTimes(1);
    expect(api.decideAgentTeamGate).toHaveBeenCalledTimes(1);
    expect(wrapper.get('[role="alert"]').text()).toContain(
      "Error in the perspectives: The approval changed during the request. Refresh the perspectives and check their current state.",
    );
    expect(wrapper.emitted("sections-changed")).toBeUndefined();
    const bar = decisionBar(wrapper, "approve");
    expect(bar.attributes("data-gate-pending")).toBe("true");
    expect(bar.get('[data-testid="decision-primary"]').attributes("disabled")).toBeUndefined();

    await bar.get('[data-testid="decision-primary"]').trigger("click");
    await flushPromises();

    expect(api.submitAgentTeamGate).toHaveBeenCalledTimes(1);
    expect(api.decideAgentTeamGate).toHaveBeenCalledTimes(2);
    expect(api.decideAgentTeamGate).toHaveBeenLastCalledWith(
      "access-token",
      PROJECT_ID,
      "APPROVE",
      null,
    );
    expect(wrapper.find('[data-testid="team-decision"]').exists()).toBe(false);
    expect(wrapper.emitted("sections-changed")).toHaveLength(1);
  });

  it("makes no approval when the submission fails", async () => {
    const state: FakeState = {
      current: proposalVersion(BASE),
      history: [],
      gate: null,
      failSubmit: true,
    };
    const api = fakeApi(state);
    const wrapper = mountFlow(api);
    await flushPromises();

    await decisionBar(wrapper, "approve").get('[data-testid="decision-primary"]').trigger("click");
    await flushPromises();

    expect(api.submitAgentTeamGate).toHaveBeenCalledTimes(1);
    expect(api.decideAgentTeamGate).not.toHaveBeenCalled();
    expect(wrapper.get('[role="alert"]').text()).toContain(
      "The service that approves the perspectives is unavailable.",
    );
    expect(decisionBar(wrapper, "approve").attributes("data-gate-pending")).toBe("false");
    expect(wrapper.emitted("sections-changed")).toBeUndefined();
  });

  it("speaks of an unexpected error in plain words instead of showing its code", async () => {
    const state: FakeState = { current: proposalVersion(BASE), history: [], gate: null };
    const api = fakeApi(state);
    api.submitAgentTeamGate.mockRejectedValueOnce(new ApiError(500, "SOMETHING_INTERNAL"));
    const wrapper = mountFlow(api);
    await flushPromises();

    await decisionBar(wrapper, "approve").get('[data-testid="decision-primary"]').trigger("click");
    await flushPromises();

    const alert = wrapper.get('[role="alert"]').text();
    expect(alert).toContain("Error in the perspectives: An unexpected error occurred.");
    expect(alert).not.toContain("SOMETHING_INTERNAL");
  });

  it("keeps rejection, pause and cancel among the other decisions", async () => {
    const current = proposalVersion(BASE);
    const state: FakeState = {
      current,
      history: [current],
      gate: gateFor(current, "PENDING_APPROVAL"),
    };
    const api = fakeApi(state);
    const wrapper = mountFlow(api);
    await flushPromises();

    const other = wrapper.get('[data-testid="team-other-decisions"]');
    expect(other.attributes("open")).toBeUndefined();
    expect(other.get('[data-testid="team-reject"]').text()).toBe("Reject the perspectives");
    expect(other.get('[data-testid="team-reject"]').attributes("disabled")).toBeDefined();
    expect(other.text()).toContain("Needed to reject the perspectives.");

    await other.get('[data-testid="team-gate-reason"]').setValue("Wrong scope");
    await other.get('[data-testid="team-reject"]').trigger("click");
    await flushPromises();

    expect(api.decideAgentTeamGate).toHaveBeenLastCalledWith(
      "access-token",
      PROJECT_ID,
      "REJECT",
      "Wrong scope",
    );
    expect(wrapper.get('[data-testid="team-gate-notice"]').text()).toContain(
      "You rejected these perspectives. Change them to prepare a new version.",
    );

    state.gate = gateFor(current, "PAUSED");
    await refresh(wrapper);

    expect(decisionBar(wrapper, "resume").get('[data-testid="decision-primary"]').text()).toBe(
      "Resume the decision",
    );
    await wrapper.get('[data-testid="team-cancel"]').trigger("click");
    await flushPromises();

    expect(api.decideAgentTeamGate).toHaveBeenLastCalledWith(
      "access-token",
      PROJECT_ID,
      "CANCEL",
      null,
    );
    expect(wrapper.get('[data-testid="team-gate-notice"]').text()).toContain(
      "You cancelled this decision. Change the perspectives to prepare a new version.",
    );
    expect(wrapper.emitted("sections-changed")).toBeUndefined();
  });

  it("keeps the version, the approval, the brief version and the hashes in the technical details", async () => {
    const first = proposalVersion(BASE);
    const second = proposalVersion([...BASE, "SECURITY_REVIEWER"], 2);
    const state: FakeState = {
      current: second,
      history: [first, second],
      gate: gateFor(second, "PENDING_APPROVAL"),
    };
    record(state, "SUBMIT", "DRAFT", "PENDING_APPROVAL", null);
    const wrapper = mountFlow(fakeApi(state));
    await flushPromises();

    const details = wrapper.get('[data-testid="team-technical-details"]');
    expect(details.get('[data-testid="step-technical-details-toggle"]').text()).toContain(
      "Version 2 · waiting for your decision",
    );

    await openTechnicalDetails(wrapper);

    expect(details.findAll("dt").map((term) => term.text())).toEqual([
      "Revision",
      "Based on version",
      "Brief version",
      "Content hash",
      "Constraint hash",
      "Approval",
    ]);
    expect(details.findAll("dd").map((value) => value.text())).toEqual([
      "Changed by you",
      "1",
      "1",
      "2".repeat(64),
      "c".repeat(64),
      "Pending approval · Decision no. 1",
    ]);
    const text = details.text();
    expect(text).toContain("Versions of the perspectives");
    expect(text).toContain("Version 1 · Prepared by the Studio ·");
    expect(text).toContain("Version 2 · Changed by you ·");
    expect(text).toContain("Previous decisions");
    expect(text).toContain("Sent for approval · Draft → Pending approval ·");
    expect(details.get('[data-testid="team-regenerate"]').text()).toBe(
      "Prepare the perspectives again",
    );
    expect(details.find("img").exists()).toBe(false);
  });

  it("mounts its decision in the bar of the page when the page offers one", async () => {
    const target = document.createElement("div");
    target.id = "step-decision-bar";
    document.body.appendChild(target);
    const host = document.createElement("div");
    document.body.appendChild(host);
    const state: FakeState = { current: proposalVersion(BASE), history: [], gate: null };
    const wrapper = mountFlow(fakeApi(state), { attachTo: host });
    await flushPromises();

    expect(target.querySelector('[data-testid="team-decision"]')).not.toBeNull();
    expect(target.querySelector('[data-testid="decision-bar"]')).not.toBeNull();
    expect(wrapper.element.querySelector('[data-testid="decision-bar"]')).toBeNull();
  });

  it("puts its technical row after the bar of the page and back in the step without it", async () => {
    const bar = document.createElement("div");
    bar.id = "step-decision-bar";
    const row = document.createElement("div");
    row.id = "step-technical-row";
    const host = document.createElement("div");
    document.body.append(bar, row, host);
    const state: FakeState = { current: proposalVersion(BASE), history: [], gate: null };
    const wrapper = mountFlow(fakeApi(state), { attachTo: host });
    await flushPromises();

    expect(
      row.querySelector(
        '[data-testid="team-technical-details"] [data-testid="step-technical-details"]',
      ),
    ).not.toBeNull();
    expect(wrapper.element.querySelector('[data-testid="team-technical-details"]')).toBeNull();
    wrapper.unmount();
    expect(row.childElementCount).toBe(0);
    row.remove();

    const alone = mountFlow(fakeApi(state), { attachTo: host });
    await flushPromises();
    expect(alone.element.querySelector('[data-testid="team-technical-details"]')).not.toBeNull();
    alone.unmount();
    bar.remove();
    host.remove();
  });

  it("takes the bar and the row of the page as soon as its hidden step is shown and active", async () => {
    const bar = document.createElement("div");
    bar.id = "step-decision-bar";
    const row = document.createElement("div");
    row.id = "step-technical-row";
    const host = document.createElement("div");
    document.body.append(bar, row, host);
    const restore = emulateVisibility();
    try {
      const api = fakeApi({ current: proposalVersion(BASE), history: [], gate: null });
      const Stage = defineComponent({
        props: { shown: { type: Boolean, required: true } },
        setup(stage) {
          return () =>
            withDirectives(
              h("div", [
                h(ProjectTeamSelectionFlow, {
                  projectId: PROJECT_ID,
                  api,
                  authorize: executeAuthorized,
                  active: stage.shown,
                }),
              ]),
              [[vShow, stage.shown]],
            );
        },
      });
      const wrapper = mount(Stage, {
        attachTo: host,
        props: { shown: false },
        global: { plugins: [createPinia(), createAppI18n("en")] },
      });
      await flushPromises();

      expect(bar.childElementCount).toBe(0);
      expect(row.childElementCount).toBe(0);
      expect(wrapper.find('[data-testid="team-decision"]').exists()).toBe(true);

      await wrapper.setProps({ shown: true });
      await flushPromises();

      expect(
        bar.querySelector('[data-testid="team-decision"] [data-testid="decision-bar"]'),
      ).not.toBeNull();
      expect(row.querySelector('[data-testid="team-technical-details"]')).not.toBeNull();
      expect(wrapper.find('[data-testid="team-decision"]').exists()).toBe(false);
      wrapper.unmount();
    } finally {
      restore();
      bar.remove();
      row.remove();
      host.remove();
    }
  });

  it("says in plain words what happened to the perspectives and keeps the status in the technical details", async () => {
    const state: FakeState = { current: null, history: [], gate: null };
    const wrapper = mountFlow(fakeApi(state));
    await flushPromises();

    const live = () => wrapper.get('[data-testid="team-operation-live"]');
    expect(wrapper.find('[data-testid="team-operation-status"]').exists()).toBe(false);
    expect(live().text()).toBe("");

    await wrapper.get('[data-testid="generate-team"]').trigger("click");
    await flushPromises();

    expect(wrapper.get('[data-testid="team-operation-status"]').text()).toBe(
      "The perspectives have been prepared.",
    );
    expect(live().text()).toBe("The perspectives have been prepared.");
    expect(wrapper.text()).not.toContain("Latest operation");
    await openTechnicalDetails(wrapper);
    const details = wrapper.get('[data-testid="team-technical-details"]').text();
    expect(details).toContain("Latest operation");
    expect(details).toContain("Created");
    expect(wrapper.get('[data-testid="team-operation-status"]').text()).not.toContain("Created");
  });

  it("tells the preparation, the update, the submission and the decision in Italian", async () => {
    const state: FakeState = { current: null, history: [], gate: null, failApprovals: 1 };
    const wrapper = mountFlow(fakeApi(state), { locale: "it" });
    await flushPromises();

    const status = () => wrapper.get('[data-testid="team-operation-status"]');
    const live = () => wrapper.get('[data-testid="team-operation-live"]');

    await wrapper.get('[data-testid="generate-team"]').trigger("click");
    await flushPromises();
    expect(status().text()).toBe("Le prospettive sono state preparate.");

    await switchOf(wrapper, "SECURITY").setValue(true);
    expect(perspectiveRow(wrapper, "SECURITY").get('[data-testid="unit-pending"]').text()).toBe(
      "Da salvare",
    );
    expect(wrapper.get('[data-testid="team-changes"]').text()).toContain(
      "Hai cambiato le prospettive: salva per crearne la nuova versione.",
    );
    await save(wrapper);
    expect(status().text()).toBe("Le prospettive sono state aggiornate.");
    expect(live().text()).toBe("Le prospettive sono state aggiornate.");
    expect(decisionBar(wrapper, "approve").get('[data-testid="decision-primary"]').text()).toBe(
      "Approva le prospettive",
    );
    expect(decisionBar(wrapper, "approve").text()).toContain(
      "5 prospettive su 5 guideranno requisiti e design. Potrai cambiarle più avanti.",
    );

    await decisionBar(wrapper, "approve").get('[data-testid="decision-primary"]').trigger("click");
    await flushPromises();
    expect(live().text()).toBe("Le prospettive sono state mandate in approvazione.");
    expect(wrapper.get('[role="alert"]').text()).toContain(
      "Errore nelle prospettive: L'approvazione è cambiata durante la richiesta",
    );
    expect(wrapper.find('[data-testid="team-operation-status"]').exists()).toBe(false);

    await decisionBar(wrapper, "approve").get('[data-testid="decision-primary"]').trigger("click");
    await flushPromises();
    expect(status().text()).toBe("La tua decisione sulle prospettive è stata registrata.");
    expect(live().text()).toBe("La tua decisione sulle prospettive è stata registrata.");
    expect(wrapper.text()).not.toContain("Ultima operazione");
  });

  it("shows no sentence for a status it cannot tell in plain words", async () => {
    const state: FakeState = { current: null, history: [], gate: null };
    const api = fakeApi(state);
    api.generateProjectTeamProposal.mockImplementation(async () => {
      state.current = proposalVersion(BASE);
      state.history.push(state.current);
      return { status: "SOMETHING_NEW" as never, version: state.current, issues: [] };
    });
    const wrapper = mountFlow(api);
    await flushPromises();

    await wrapper.get('[data-testid="generate-team"]').trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-testid="team-operation-status"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="team-operation-live"]').text()).toBe("");
    expect(wrapper.emitted("sections-changed")).toBeUndefined();
    await openTechnicalDetails(wrapper);
    expect(wrapper.get('[data-testid="team-technical-details"]').text()).toContain("Something new");
  });

  it("reads the perspectives again once when the brief before them changes, not when it only reloads", async () => {
    const version = proposalVersion(BASE);
    const api = fakeApi({ current: version, history: [version], gate: null });
    const wrapper = mountFlow(api);
    await flushPromises();
    expect(api.getCurrentProjectTeamProposal).toHaveBeenCalledTimes(1);

    await wrapper.setProps({ upstream: "brief-1:PENDING_APPROVAL" });
    await wrapper.setProps({ upstream: null });
    await wrapper.setProps({ upstream: "brief-1:PENDING_APPROVAL" });
    await flushPromises();
    expect(api.getCurrentProjectTeamProposal).toHaveBeenCalledTimes(1);

    await wrapper.setProps({ upstream: "brief-1:APPROVED" });
    await flushPromises();
    expect(api.getCurrentProjectTeamProposal).toHaveBeenCalledTimes(2);
    expect(api.getAgentCatalog).toHaveBeenCalledTimes(2);
    expect(wrapper.emitted("sections-changed")).toBeUndefined();
  });

  it("reads the perspectives again after the action that is running when the brief changes", async () => {
    const version = proposalVersion(BASE);
    const api = fakeApi({ current: version, history: [version], gate: null });
    const wrapper = mountFlow(api);
    await flushPromises();
    await wrapper.setProps({ upstream: "brief-1:PENDING_APPROVAL" });
    let release: () => void = () => undefined;
    api.getAgentCatalog.mockImplementationOnce(
      () =>
        new Promise<AgentCatalogResponse>((resolve) => {
          release = () => resolve(CATALOG);
        }),
    );

    await wrapper.setProps({ upstream: "brief-1:APPROVED" });
    await wrapper.setProps({ upstream: "brief-2:DRAFT" });
    await flushPromises();
    expect(api.getAgentCatalog).toHaveBeenCalledTimes(2);

    release();
    await flushPromises();
    expect(api.getAgentCatalog).toHaveBeenCalledTimes(3);
    expect(api.getCurrentProjectTeamProposal).toHaveBeenCalledTimes(3);
  });
});
