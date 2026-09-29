import { createPinia, setActivePinia } from "pinia";
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils";
import { defineComponent, h, vShow, withDirectives } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AgentCatalogResponse,
  AgentIdentifier,
  AgentTeamApi,
  OwnerAgentRationaleInput,
  TeamProposalVersionResponse,
  TeamSelectionReasonResponse,
} from "@/api/team-contracts";
import type { HumanGateResponse, HumanGateStatus } from "@/api/workflow-contracts";
import { ApiError } from "@/api/client";
import { createAppI18n } from "@/i18n";
import { useTeamStore, type TeamAuthorizedRequest } from "@/stores/team";

import ProjectTeamSelectionFlow from "./ProjectTeamSelectionFlow.vue";
import { expectAccessible } from "@/test/axe";

enableAutoUnmount(afterEach);

const PROJECT_ID = "project-id";

const CATALOG: AgentCatalogResponse = {
  catalog_version: 1,
  content_hash: "a".repeat(64),
  agents: [
    {
      agent_id: "REQUIREMENTS_ANALYST",
      catalog_version: 1,
      kind: "SPECIALIST",
      selection_policy: "OWNER_SELECTABLE",
      capabilities: ["REQUIREMENTS_ANALYSIS"],
      supported_project_modes: ["GREENFIELD_GENERATION"],
      name_key: "agentCatalog.roles.requirements_analyst.name",
      description_key: "agentCatalog.roles.requirements_analyst.description",
      is_always_present: false,
    },
    {
      agent_id: "MOBILE_ENGINEER",
      catalog_version: 1,
      kind: "SPECIALIST",
      selection_policy: "OWNER_SELECTABLE",
      capabilities: ["MOBILE_ENGINEERING"],
      supported_project_modes: ["GREENFIELD_GENERATION"],
      name_key: "agentCatalog.roles.mobile_engineer.name",
      description_key: "agentCatalog.roles.mobile_engineer.description",
      is_always_present: false,
    },
  ],
};

const ACCESSIBILITY_CATALOG: AgentCatalogResponse = {
  ...CATALOG,
  agents: [
    ...CATALOG.agents,
    {
      agent_id: "ACCESSIBILITY_REVIEWER",
      catalog_version: 1,
      kind: "SPECIALIST",
      selection_policy: "OWNER_SELECTABLE",
      capabilities: ["ACCESSIBILITY_REVIEW"],
      supported_project_modes: ["GREENFIELD_GENERATION"],
      name_key: "agentCatalog.roles.accessibility_reviewer.name",
      description_key: "agentCatalog.roles.accessibility_reviewer.description",
      is_always_present: false,
    },
  ],
};

function proposalVersion(
  selectedAgentIds: readonly AgentIdentifier[],
  versionNumber = 1,
): TeamProposalVersionResponse {
  return {
    id: versionNumber === 1 ? "proposal-id" : `proposal-id-${versionNumber}`,
    project_id: PROJECT_ID,
    version_number: versionNumber,
    revision_kind: versionNumber === 1 ? "PROPOSER_GENERATED" : "OWNER_EDITED",
    based_on_version_number: versionNumber === 1 ? null : 1,

    schema_version: 1,
    provider_kind: "FAKE_DETERMINISTIC",
    provider_id: "fake-deterministic-team-proposal",
    provider_version: 1,

    project_mode: "GREENFIELD_GENERATION",
    brief_version_id: "brief-version-id",
    brief_version_number: 1,
    brief_content_hash: "b".repeat(64),

    catalog_version: 1,
    catalog_content_hash: "a".repeat(64),
    constraints_content_hash: "c".repeat(64),
    content_hash: String(versionNumber).repeat(64),

    selected_agent_ids: selectedAgentIds,
    role_constraints: [
      {
        agent_id: "REQUIREMENTS_ANALYST",
        kind: "MANDATORY",
        owner_editable: false,
        reasons: [
          {
            code: "CORE_REQUIREMENTS_DISCIPLINE",
            evidence: {
              fields: [],
              terms: [],
            },
          },
        ],
      },
      {
        agent_id: "MOBILE_ENGINEER",
        kind: "OPTIONAL",
        owner_editable: true,
        reasons: [],
      },
    ],
    constraint_issues: [],
    members: [
      {
        agent_id: "REQUIREMENTS_ANALYST",
        source: "DETERMINISTIC_MANDATORY",
        justifications: [
          {
            kind: "DETERMINISTIC_RULE",
            code: "CORE_REQUIREMENTS_DISCIPLINE",
            evidence_fields: [],
            evidence_terms: [],
            statement: null,
          },
        ],
      },
      ...(selectedAgentIds.includes("MOBILE_ENGINEER")
        ? [
            {
              agent_id: "MOBILE_ENGINEER" as const,
              source: "OWNER_ADDED" as const,
              justifications: [
                {
                  kind: "OWNER_RATIONALE" as const,
                  code: "OWNER_SELECTED_ROLE",
                  evidence_fields: [],
                  evidence_terms: [],
                  statement: "The owner wants an optional mobile companion.",
                },
              ],
            },
          ]
        : []),
    ],

    created_by_user_id: "owner-id",
    created_at: "2026-08-12T12:00:00Z",
  };
}

function accessibilityVersion(briefAsksForAccessibility: boolean): TeamProposalVersionResponse {
  const version = proposalVersion(["REQUIREMENTS_ANALYST"]);
  const reasons: TeamSelectionReasonResponse[] = [
    { code: "CORE_ACCESSIBILITY_DISCIPLINE", evidence: { fields: [], terms: [] } },
  ];
  if (briefAsksForAccessibility) {
    reasons.push({
      code: "ACCESSIBILITY_REQUIREMENT_SIGNAL",
      evidence: { fields: ["non_functional_requirements"], terms: ["wcag"] },
    });
  }
  return {
    ...version,
    selected_agent_ids: [...version.selected_agent_ids, "ACCESSIBILITY_REVIEWER"],
    role_constraints: [
      ...version.role_constraints,
      { agent_id: "ACCESSIBILITY_REVIEWER", kind: "MANDATORY", owner_editable: false, reasons },
    ],
    members: [
      ...version.members,
      {
        agent_id: "ACCESSIBILITY_REVIEWER",
        source: "DETERMINISTIC_MANDATORY",
        justifications: reasons.map((reason) => ({
          kind: "DETERMINISTIC_RULE" as const,
          code: reason.code,
          evidence_fields: reason.evidence.fields,
          evidence_terms: reason.evidence.terms,
          statement: null,
        })),
      },
    ],
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

interface FakeState {
  current: TeamProposalVersionResponse | null;
  history: TeamProposalVersionResponse[];
  gate: HumanGateResponse | null;
  failSubmit?: boolean;
  failApprovals?: number;
}

function fakeApi(state: FakeState) {
  const api = {
    getAgentCatalog: vi.fn(async () => CATALOG),
    generateProjectTeamProposal: vi.fn(async () => {
      if (state.current === null) {
        state.current = proposalVersion(["REQUIREMENTS_ANALYST"]);
        state.history.push(state.current);
      }
      return { status: "CREATED" as const, version: state.current, issues: [] };
    }),
    listProjectTeamProposals: vi.fn(async () => state.history),
    getCurrentProjectTeamProposal: vi.fn(async () => {
      if (state.current === null) throw new ApiError(404, "team_proposal_not_found");
      return state.current;
    }),
    editCurrentProjectTeamProposal: vi.fn(
      async (
        _accessToken: string,
        _projectId: string,
        input: {
          selected_agent_ids: readonly AgentIdentifier[];
          owner_rationales: readonly OwnerAgentRationaleInput[];
        },
      ) => {
        state.current = proposalVersion(input.selected_agent_ids, state.history.length + 1);
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
      return { status: "SUBMITTED" as const, gate: state.gate, events: [], issue: null };
    }),
    getCurrentAgentTeamGate: vi.fn(async () => {
      if (state.gate === null) throw new ApiError(404, "agent_team_gate_not_found");
      return state.gate;
    }),
    listAgentTeamGateEvents: vi.fn(async () => []),
    decideAgentTeamGate: vi.fn(async (_accessToken: string, _projectId: string, action: string) => {
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
      state.gate = gateFor(state.current, next[action] ?? state.gate.status);
      return { status: "APPLIED" as const, gate: state.gate, event: null, issue: null };
    }),
    getProjectWorkflowReadiness: vi.fn(async () => ({
      status:
        state.gate?.status === "APPROVED"
          ? ("READY_FOR_MAIN_WORKFLOW" as const)
          : ("TEAM_APPROVAL_REQUIRED" as const),
    })),
  } satisfies AgentTeamApi;
  return api;
}

const executeAuthorized: TeamAuthorizedRequest = <T>(
  operation: (accessToken: string) => Promise<T>,
): Promise<T> => operation("access-token");

function mountFlow(api: AgentTeamApi, attachTo?: HTMLElement, locale: "en" | "it" = "en") {
  return mount(ProjectTeamSelectionFlow, {
    ...(attachTo === undefined ? {} : { attachTo }),
    props: {
      projectId: PROJECT_ID,
      api,
      authorize: executeAuthorized,
    },
    global: {
      plugins: [createPinia(), createAppI18n(locale)],
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

describe("ProjectTeamSelectionFlow", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    document.body.innerHTML = "";
  });

  it("submits the complete team and rationale for a new optional role", async () => {
    let currentVersion = proposalVersion(["REQUIREMENTS_ANALYST"]);
    const history = [currentVersion];
    let submittedAgentIds: readonly AgentIdentifier[] = [];
    let submittedRationales: readonly OwnerAgentRationaleInput[] = [];

    const api: AgentTeamApi = {
      async getAgentCatalog() {
        return CATALOG;
      },

      async generateProjectTeamProposal() {
        return {
          status: "UNCHANGED",
          version: currentVersion,
          issues: [],
        };
      },

      async listProjectTeamProposals() {
        return history;
      },

      async getCurrentProjectTeamProposal() {
        return currentVersion;
      },

      async editCurrentProjectTeamProposal(_accessToken, _projectId, input) {
        submittedAgentIds = input.selected_agent_ids;
        submittedRationales = input.owner_rationales;

        currentVersion = proposalVersion(input.selected_agent_ids, 2);
        history.push(currentVersion);

        return {
          status: "UPDATED",
          version: currentVersion,
          issues: [],
          events: [],
        };
      },

      async submitAgentTeamGate() {
        return {
          status: "PROPOSAL_NOT_FOUND",
          gate: null,
          events: [],
          issue: null,
        };
      },

      async getCurrentAgentTeamGate() {
        throw new ApiError(404, "agent_team_gate_not_found");
      },

      async listAgentTeamGateEvents() {
        return [];
      },

      async decideAgentTeamGate() {
        return {
          status: "GATE_NOT_FOUND",
          gate: null,
          event: null,
          issue: null,
        };
      },

      async getProjectWorkflowReadiness() {
        return {
          status: "TEAM_APPROVAL_REQUIRED",
        };
      },
    };

    const wrapper = mountFlow(api);

    await flushPromises();
    await expectAccessible(wrapper.element);

    expect(wrapper.find('[data-testid="role-REQUIREMENTS_ANALYST"]').exists()).toBe(false);
    expect(
      wrapper
        .get('[data-team-group="core"][data-agent-id="REQUIREMENTS_ANALYST"]')
        .find("input")
        .exists(),
    ).toBe(false);
    expect(wrapper.find('[data-testid="save-team-changes"]').exists()).toBe(false);
    await wrapper.get('[data-testid="team-selection-form"]').trigger("submit");
    expect(submittedAgentIds).toEqual([]);
    expect(
      wrapper
        .get('[data-testid="team-technical-details"] [data-testid="step-technical-details-toggle"]')
        .attributes("aria-expanded"),
    ).toBe("false");

    const mobile = wrapper.get('[data-testid="role-MOBILE_ENGINEER"]');
    expect(mobile.attributes("role")).toBe("switch");
    expect((mobile.element as HTMLInputElement).checked).toBe(false);
    expect(mobile.isVisible()).toBe(true);

    await mobile.setValue(true);

    await wrapper
      .get('[data-testid="rationale-MOBILE_ENGINEER"]')
      .setValue("The owner wants an optional mobile companion.");
    expect(wrapper.get('[data-testid="save-team-changes"]').attributes("disabled")).toBeUndefined();

    await wrapper.get('[data-testid="team-selection-form"]').trigger("submit");

    await flushPromises();

    expect(submittedAgentIds).toEqual(["REQUIREMENTS_ANALYST", "MOBILE_ENGINEER"]);

    expect(submittedRationales).toEqual([
      {
        agent_id: "MOBILE_ENGINEER",
        statement: "The owner wants an optional mobile companion.",
      },
    ]);

    await openTechnicalDetails(wrapper);
    expect(wrapper.text()).toContain("Owner edited");
    expect(wrapper.find('[data-testid="save-team-changes"]').exists()).toBe(false);
    const store = useTeamStore();
    store.gate = gateFor(currentVersion, "APPROVED");
    await flushPromises();
    expect(wrapper.find('[data-testid="team-decision"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="team-gate-reason"]').exists()).toBe(false);
    store.currentVersion = proposalVersion(["REQUIREMENTS_ANALYST", "MOBILE_ENGINEER"], 3);
    await flushPromises();
    expect(wrapper.find('[data-testid="team-decision"][data-decision="approve"]').exists()).toBe(
      true,
    );
  });

  it("shows the essential roles as cards with their robot, what they do and where they work", async () => {
    const state: FakeState = {
      current: proposalVersion(["REQUIREMENTS_ANALYST"]),
      history: [],
      gate: null,
    };
    const wrapper = mountFlow(fakeApi(state));
    await flushPromises();

    const card = wrapper.get('[data-team-group="core"][data-agent-id="REQUIREMENTS_ANALYST"]');
    expect(card.get("img").attributes("src")).toBe("/team/an.webp");
    expect(card.get("img").attributes("alt")).toBe("");
    expect(card.get("h3").text()).toBe("Needs analyst");
    expect(card.text()).toContain("Turns the brief into clear requirements");
    expect(card.text()).toContain("Works in: Requirements");

    const row = wrapper.get('[data-team-group="extra"][data-agent-id="MOBILE_ENGINEER"]');
    expect(row.get("img").attributes("src")).toBe("/team/fe.webp");
    expect(row.get('[data-testid="team-role-tag"]').text()).toBe("Optional");
    expect(wrapper.get('[data-testid="team-count"]').text()).toBe(
      "1 assistant in the team. The essential roles are already included; you can add other specialists.",
    );

    await wrapper.get('[data-testid="role-MOBILE_ENGINEER"]').setValue(true);

    expect(wrapper.get('[data-testid="team-count"]').text()).toContain("2 assistants in the team.");
    expect(row.get('[data-testid="team-role-tag"]').text()).toBe("To be saved");
    expect(row.attributes("data-selected")).toBe("true");
  });

  it("approves the team with one press that submits it and then approves it", async () => {
    const state: FakeState = {
      current: proposalVersion(["REQUIREMENTS_ANALYST"]),
      history: [],
      gate: null,
    };
    const api = fakeApi(state);
    const wrapper = mountFlow(api);
    await flushPromises();

    const bar = decisionBar(wrapper, "approve");
    expect(bar.attributes("data-gate-pending")).toBe("false");
    expect(bar.find('[data-testid="decision-secondary"]').exists()).toBe(false);
    expect(bar.get('[data-testid="decision-primary"]').text()).toBe("Approve the team");
    expect(bar.text()).toContain(
      "1 assistant will work on the project. You can change the team later.",
    );
    expect(wrapper.text()).not.toContain("Prepare for approval");

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
    expect(wrapper.find('[data-testid="team-decision"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="team-other-decisions"]').exists()).toBe(false);
    expect(
      wrapper
        .get('[data-testid="team-technical-details"] [data-testid="step-technical-details-toggle"]')
        .text(),
    ).toContain("Version 1 · approved");
    await expectAccessible(wrapper.element);
  });

  it("only approves when the team already waits for approval and asks for changes there", async () => {
    const current = proposalVersion(["REQUIREMENTS_ANALYST"]);
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
      "Write what you would change in the team: the note stays in the history of the decisions.",
    );
    await note.setValue("Add a security specialist");
    await bar.get('[data-testid="decision-send"]').trigger("click");
    await flushPromises();

    expect(api.submitAgentTeamGate).not.toHaveBeenCalled();
    expect(api.decideAgentTeamGate).toHaveBeenLastCalledWith(
      "access-token",
      PROJECT_ID,
      "REQUEST_REVISION",
      "Add a security specialist",
    );
    expect(wrapper.find('[data-testid="team-decision"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="team-gate-notice"]').text()).toContain(
      "You asked for changes.",
    );

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
  });

  it("shows the failed approval in plain words and only approves on the next press", async () => {
    const state: FakeState = {
      current: proposalVersion(["REQUIREMENTS_ANALYST"]),
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
      "The gate changed during the request. Refresh the team and review its current state.",
    );
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
  });

  it("makes no approval when the submission fails", async () => {
    const state: FakeState = {
      current: proposalVersion(["REQUIREMENTS_ANALYST"]),
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
      "The Agent Team service is unavailable.",
    );
    expect(decisionBar(wrapper, "approve").attributes("data-gate-pending")).toBe("false");
  });

  it("keeps the decision disabled while the team has unsaved changes", async () => {
    const state: FakeState = {
      current: proposalVersion(["REQUIREMENTS_ANALYST"]),
      history: [],
      gate: null,
    };
    const wrapper = mountFlow(fakeApi(state));
    await flushPromises();

    await wrapper.get('[data-testid="role-MOBILE_ENGINEER"]').setValue(true);

    const bar = decisionBar(wrapper, "approve");
    expect(bar.get('[data-testid="decision-primary"]').attributes("disabled")).toBeDefined();
    expect(bar.text()).toContain("Save the changes to the team before deciding.");

    const changes = wrapper.get('[data-testid="team-changes"]');
    await changes.findAll("button")[0]!.trigger("click");

    expect(wrapper.find('[data-testid="team-changes"]').exists()).toBe(false);
    expect(
      (wrapper.get('[data-testid="role-MOBILE_ENGINEER"]').element as HTMLInputElement).checked,
    ).toBe(false);
    expect(
      decisionBar(wrapper, "approve")
        .get('[data-testid="decision-primary"]')
        .attributes("disabled"),
    ).toBeUndefined();
  });

  it("keeps rejection, pause and cancel among the other decisions", async () => {
    const current = proposalVersion(["REQUIREMENTS_ANALYST"]);
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
    expect(other.get('[data-testid="team-reject"]').attributes("disabled")).toBeDefined();

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
      "You rejected this team.",
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
  });

  it("offers to propose the team when there is none yet", async () => {
    const state: FakeState = { current: null, history: [], gate: null };
    const api = fakeApi(state);
    const wrapper = mountFlow(api);
    await flushPromises();

    expect(wrapper.find('[data-testid="team-decision"]').exists()).toBe(false);
    const needed = wrapper.get('[data-testid="team-proposal-needed"]');
    expect(needed.text()).toContain("The team is not ready yet");

    await needed.get('[data-testid="generate-team"]').trigger("click");
    await flushPromises();

    expect(api.generateProjectTeamProposal).toHaveBeenCalledWith("access-token", PROJECT_ID);
    expect(wrapper.find('[data-testid="team-proposal-needed"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="team-decision"][data-decision="approve"]').exists()).toBe(
      true,
    );
    await expectAccessible(wrapper.element);
  });

  it("mounts its decision in the bar of the page when the page offers one", async () => {
    const target = document.createElement("div");
    target.id = "step-decision-bar";
    document.body.appendChild(target);
    const host = document.createElement("div");
    document.body.appendChild(host);
    const state: FakeState = {
      current: proposalVersion(["REQUIREMENTS_ANALYST"]),
      history: [],
      gate: null,
    };
    const wrapper = mountFlow(fakeApi(state), host);
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
    const state: FakeState = {
      current: proposalVersion(["REQUIREMENTS_ANALYST"]),
      history: [],
      gate: null,
    };
    const wrapper = mountFlow(fakeApi(state), host);
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

    const alone = mountFlow(fakeApi(state), host);
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
      const api = fakeApi({
        current: proposalVersion(["REQUIREMENTS_ANALYST"]),
        history: [],
        gate: null,
      });
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

  it("says in plain words what happened to the team and keeps the status in the technical details", async () => {
    const state: FakeState = { current: null, history: [], gate: null };
    const wrapper = mountFlow(fakeApi(state));
    await flushPromises();

    const live = () => wrapper.get('[data-testid="team-operation-live"]');
    expect(wrapper.find('[data-testid="team-operation-status"]').exists()).toBe(false);
    expect(live().text()).toBe("");

    await wrapper.get('[data-testid="generate-team"]').trigger("click");
    await flushPromises();

    expect(wrapper.get('[data-testid="team-operation-status"]').text()).toBe(
      "The team has been prepared.",
    );
    expect(live().text()).toBe("The team has been prepared.");
    expect(wrapper.text()).not.toContain("Latest operation");
    await openTechnicalDetails(wrapper);
    const details = wrapper.get('[data-testid="team-technical-details"]').text();
    expect(details).toContain("Latest operation");
    expect(details).toContain("Created");
    expect(wrapper.get('[data-testid="team-operation-status"]').text()).not.toContain("Created");
  });

  it("tells the preparation, the update, the submission and the decision in Italian", async () => {
    const state: FakeState = { current: null, history: [], gate: null, failApprovals: 1 };
    const wrapper = mountFlow(fakeApi(state), undefined, "it");
    await flushPromises();

    const status = () => wrapper.get('[data-testid="team-operation-status"]');
    const live = () => wrapper.get('[data-testid="team-operation-live"]');

    await wrapper.get('[data-testid="generate-team"]').trigger("click");
    await flushPromises();
    expect(status().text()).toBe("La squadra è stata preparata.");

    await wrapper.get('[data-testid="role-MOBILE_ENGINEER"]').setValue(true);
    await wrapper
      .get('[data-testid="rationale-MOBILE_ENGINEER"]')
      .setValue("Serve anche sul telefono.");
    await wrapper.get('[data-testid="team-selection-form"]').trigger("submit");
    await flushPromises();
    expect(status().text()).toBe("La squadra è stata aggiornata.");
    expect(live().text()).toBe("La squadra è stata aggiornata.");

    await decisionBar(wrapper, "approve").get('[data-testid="decision-primary"]').trigger("click");
    await flushPromises();
    expect(live().text()).toBe("La squadra è stata mandata in approvazione.");
    expect(wrapper.get('[role="alert"]').text()).toContain(
      "Il gate è cambiato durante la richiesta",
    );
    expect(wrapper.find('[data-testid="team-operation-status"]').exists()).toBe(false);

    await decisionBar(wrapper, "approve").get('[data-testid="decision-primary"]').trigger("click");
    await flushPromises();
    expect(status().text()).toBe("La tua decisione sulla squadra è stata registrata.");
    expect(live().text()).toBe("La tua decisione sulla squadra è stata registrata.");
    expect(wrapper.text()).not.toContain("Ultima operazione");
  });

  it("shows no sentence for a status it cannot tell in plain words", async () => {
    const state: FakeState = { current: null, history: [], gate: null };
    const api = fakeApi(state);
    api.generateProjectTeamProposal.mockImplementation(async () => {
      state.current = proposalVersion(["REQUIREMENTS_ANALYST"]);
      state.history.push(state.current);
      return { status: "SOMETHING_NEW" as never, version: state.current, issues: [] };
    });
    const wrapper = mountFlow(api);
    await flushPromises();

    await wrapper.get('[data-testid="generate-team"]').trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-testid="team-operation-status"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="team-operation-live"]').text()).toBe("");
    await openTechnicalDetails(wrapper);
    expect(wrapper.get('[data-testid="team-technical-details"]').text()).toContain("Something new");
  });

  it("reads the team again once when the brief before it changes, not when it only reloads", async () => {
    const version = proposalVersion(["REQUIREMENTS_ANALYST"]);
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
  });

  it("reads the team again after the action that is running when the brief changes", async () => {
    const version = proposalVersion(["REQUIREMENTS_ANALYST"]);
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

  it("keeps the accessibility specialist among the essential roles with what the brief asks", async () => {
    const api = fakeApi({ current: accessibilityVersion(true), history: [], gate: null });
    api.getAgentCatalog.mockImplementation(async () => ACCESSIBILITY_CATALOG);
    const wrapper = mountFlow(api);
    await flushPromises();

    const card = wrapper.get('[data-team-group="core"][data-agent-id="ACCESSIBILITY_REVIEWER"]');
    expect(card.get("h3").text()).toBe("Accessibility specialist");
    expect(card.text()).toContain("Why: The brief contains accessibility requirements");
    expect(wrapper.find('[data-testid="role-ACCESSIBILITY_REVIEWER"]').exists()).toBe(false);

    await openTechnicalDetails(wrapper);
    expect(wrapper.get('[data-testid="team-technical-details"]').text()).toContain(
      "Accessibility is part of every project · The brief contains accessibility requirements",
    );
  });

  it("says in Italian that accessibility is part of every project", async () => {
    const api = fakeApi({ current: accessibilityVersion(false), history: [], gate: null });
    api.getAgentCatalog.mockImplementation(async () => ACCESSIBILITY_CATALOG);
    const wrapper = mountFlow(api, undefined, "it");
    await flushPromises();

    const card = wrapper.get('[data-team-group="core"][data-agent-id="ACCESSIBILITY_REVIEWER"]');
    expect(card.get("h3").text()).toBe("Specialista dell'accessibilità");
    expect(card.text()).not.toContain("Perché:");

    await openTechnicalDetails(wrapper);
    expect(wrapper.get('[data-testid="team-technical-details"]').text()).toContain(
      "L'accessibilità fa parte di ogni progetto",
    );
  });
});
