import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { RequirementsApi } from "../api/requirements";
import { requirementsAlignmentApi } from "../api/requirementsAlignment";
import type {
  HumanGatePayload,
  RequirementsReadinessPayload,
  RequirementsSpecificationDiffPayload,
  RequirementsSpecificationVersionPayload,
} from "../types/requirements";
import type { RequirementsAlignmentPayload } from "../types/requirementsAlignment";
import ProjectRequirementsFlow from "./ProjectRequirementsFlow.vue";
import RequirementsTwinAlignment from "./RequirementsTwinAlignment.vue";
import { expectAccessible } from "@/test/axe";

const PROJECT_ID = "00000000-0000-4000-8000-000000000010";
const OWNER_ID = "00000000-0000-4000-8000-000000000001";
const VERSION_ID = "00000000-0000-4000-8000-000000000020";
const REQUIREMENT_ID = "00000000-0000-4000-8000-000000000030";
const DIFF_ID = "00000000-0000-4000-8000-000000000040";
const GATE_ID = "00000000-0000-4000-8000-000000000050";
const NOW = "2026-08-18T12:00:00Z";

const VERSION: RequirementsSpecificationVersionPayload = {
  id: VERSION_ID,
  project_id: PROJECT_ID,
  version_number: 1,
  based_on_version_number: null,
  content_hash: "a".repeat(64),
  created_by_user_id: OWNER_ID,
  created_at: NOW,
  specification: {
    project_id: PROJECT_ID,
    project_brief_reference: {
      kind: "PROJECT_BRIEF",
      artifact_id: "00000000-0000-4000-8000-000000000060",
      version_number: 1,
      content_hash: "b".repeat(64),
    },
    agent_team_reference: {
      kind: "AGENT_TEAM",
      artifact_id: "00000000-0000-4000-8000-000000000070",
      version_number: 1,
      content_hash: "c".repeat(64),
    },
    user_modeling_reference: {
      kind: "USER_MODELING",
      artifact_id: "00000000-0000-4000-8000-000000000080",
      version_number: 1,
      content_hash: "d".repeat(64),
    },
    catalog_version: 1,
    catalog_content_hash: "e".repeat(64),
    user_twin_references: [
      {
        twin_id: "00000000-0000-4000-8000-000000000090",
        version_number: 1,
        content_hash: "f".repeat(64),
        name: "Receptionist Twin",
      },
    ],
    requirements: [
      {
        id: REQUIREMENT_ID,
        code: "REQ-001",
        title: "Create reservations",
        statement: "The system must create reservations.",
        kind: "FUNCTIONAL",
        priority: "MUST",
        sources: [
          {
            kind: "PROJECT_BRIEF",
            source_id: "brief-version",
            source_version: 1,
            content_hash: "b".repeat(64),
            locator: "functional_requirements[0]",
          },
        ],
        user_twin_references: [],
      },
    ],
    user_stories: [],
    acceptance_criteria: [],
    scenarios: [],
    risks: [],
    definition_of_done: [],
  },
};

const PENDING_GATE: HumanGatePayload = {
  id: GATE_ID,
  project_id: PROJECT_ID,
  owner_user_id: OWNER_ID,
  gate_type: "REQUIREMENTS",
  artifact: {
    project_id: PROJECT_ID,
    gate_type: "REQUIREMENTS",
    artifact_id: VERSION_ID,
    version: 1,
    content_hash: VERSION.content_hash,
  },
  iteration: 1,
  max_iterations: 3,
  status: "PENDING_APPROVAL",
  created_at: NOW,
  updated_at: NOW,
  event_sequence: 1,
  resume_status: null,
};

const DIFF: RequirementsSpecificationDiffPayload = {
  id: DIFF_ID,
  project_id: PROJECT_ID,
  base_version_id: VERSION_ID,
  base_version_number: 1,
  base_content_hash: VERSION.content_hash,
  proposed_content_hash: "1".repeat(64),
  proposal_hash: "2".repeat(64),
  status: "PROPOSED",
  proposed_specification: {
    ...VERSION.specification,
    requirements: [
      {
        ...VERSION.specification.requirements[0]!,
        statement: "The system must create guest reservations.",
      },
    ],
  },
  operations: [
    {
      artifact_kind: "REQUIREMENT",
      operation: "REPLACE",
      artifact_id: REQUIREMENT_ID,
      display_code: "REQ-001",
      before: {
        kind: "REQUIREMENT",
        requirement: VERSION.specification.requirements[0]!,
        user_story: null,
        acceptance_criterion: null,
        scenario: null,
        risk: null,
        definition_of_done: null,
      },
      after: {
        kind: "REQUIREMENT",
        requirement: {
          ...VERSION.specification.requirements[0]!,
          statement: "The system must create guest reservations.",
        },
        user_story: null,
        acceptance_criterion: null,
        scenario: null,
        risk: null,
        definition_of_done: null,
      },
    },
  ],
  created_by_user_id: OWNER_ID,
  created_at: NOW,
  decided_by_user_id: null,
  decided_at: null,
  decision_reason: null,
  applied_specification_version_id: null,
};

class FakeApi implements RequirementsApi {
  readinessResult: RequirementsReadinessPayload = {
    status: "REQUIREMENTS_REQUIRED",
    version: null,
    gate: null,
    approved_current_specification: false,
  };
  historyResult: RequirementsSpecificationVersionPayload[] = [];
  diffs: RequirementsSpecificationDiffPayload[] = [];
  proposedSpecification = null as RequirementsSpecificationVersionPayload["specification"] | null;
  decideGateCalls: string[] = [];

  async generate() {
    this.readinessResult = {
      status: "REQUIREMENTS_APPROVAL_REQUIRED",
      version: VERSION,
      gate: null,
      approved_current_specification: false,
    };
    this.historyResult = [VERSION];

    return {
      status: "CREATED" as const,
      version: VERSION,
      issue: null,
      proposal_issue: null,
      persistence_status: null,
    };
  }

  async current() {
    return VERSION;
  }

  async history() {
    return this.historyResult;
  }

  async proposeRevision(
    _projectId: string,
    request: { specification: typeof VERSION.specification },
  ) {
    this.proposedSpecification = request.specification;
    this.diffs = [DIFF];

    return {
      status: "CREATED" as const,
      diff: DIFF,
      version: null,
      issue: null,
      proposal_issue: null,
      diff_persistence_status: null,
      version_persistence_status: null,
    };
  }

  async revisionHistory() {
    return this.diffs;
  }

  async getRevision() {
    return DIFF;
  }

  async decideRevision() {
    return {
      status: "APPLIED" as const,
      diff: {
        ...DIFF,
        status: "APPROVED" as const,
        decided_by_user_id: OWNER_ID,
        decided_at: NOW,
        applied_specification_version_id: VERSION_ID,
      },
      version: VERSION,
      issue: null,
      proposal_issue: null,
      diff_persistence_status: null,
      version_persistence_status: null,
    };
  }

  async traceability() {
    return {
      project_id: PROJECT_ID,
      specification_version_id: VERSION_ID,
      specification_version_number: 1,
      specification_content_hash: VERSION.content_hash,
      content_hash: "3".repeat(64),
      nodes: [],
      links: [],
    };
  }

  async coverage() {
    return {
      project_id: PROJECT_ID,
      specification_version_id: VERSION_ID,
      requirement_count: 1,
      user_story_count: 0,
      acceptance_criterion_count: 0,
      requirement_ids_without_user_stories: [REQUIREMENT_ID],
      requirement_ids_without_acceptance_criteria: [REQUIREMENT_ID],
      user_story_ids_without_acceptance_criteria: [],
      acceptance_criterion_ids_without_scenarios: [],
      has_full_acceptance_coverage: false,
    };
  }

  async submitGate() {
    this.readinessResult = {
      status: "REQUIREMENTS_APPROVAL_REQUIRED",
      version: VERSION,
      gate: PENDING_GATE,
      approved_current_specification: false,
    };

    return {
      status: "SUBMITTED" as const,
      gate: PENDING_GATE,
      events: [],
      issue: null,
    };
  }

  async decideGate(_projectId: string, request: { action: string }) {
    this.decideGateCalls.push(request.action);
    const gate = {
      ...PENDING_GATE,
      status: "APPROVED" as const,
      event_sequence: 2,
    };
    this.readinessResult = {
      status: "READY_FOR_DESIGN_EXPLORATION",
      version: VERSION,
      gate,
      approved_current_specification: true,
    };

    return {
      status: "APPLIED" as const,
      gate,
      event: null,
      issue: null,
    };
  }

  async currentGate() {
    if (this.readinessResult.gate === null) {
      throw new Error("Gate is not configured");
    }

    return this.readinessResult.gate;
  }

  async gateEvents() {
    return [];
  }

  async readiness() {
    return this.readinessResult;
  }
}

const authorize = <T>(operation: (accessToken: string) => Promise<T>): Promise<T> =>
  operation("access-token");

const ALIGNED: RequirementsAlignmentPayload = {
  aligned: true,
  issue: "REQUIREMENTS_ALREADY_ALIGNED",
  requirements_version_number: 1,
  snapshot_version_number: 1,
  twins_approved: true,
};

function mountFlow(api: RequirementsApi, autoLoad = false) {
  return mount(ProjectRequirementsFlow, {
    props: {
      projectId: PROJECT_ID,
      locale: "en",
      autoLoad,
      authorize,
      api,
    },
  });
}

describe("ProjectRequirementsFlow", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.spyOn(requirementsAlignmentApi, "status").mockResolvedValue(ALIGNED);
  });

  it("generates and renders the first governed specification", async () => {
    const api = new FakeApi();
    const wrapper = mountFlow(api);

    await wrapper.get('[data-testid="generate-requirements"]').trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("REQ-001");
    expect(wrapper.text()).toContain("Create reservations");
    expect(wrapper.text()).toContain("Version 1");
  });

  it("creates a full specification diff from an edited requirement", async () => {
    const api = new FakeApi();
    api.readinessResult = {
      status: "REQUIREMENTS_APPROVAL_REQUIRED",
      version: VERSION,
      gate: null,
      approved_current_specification: false,
    };
    api.historyResult = [VERSION];
    const wrapper = mountFlow(api, true);

    await flushPromises();
    await wrapper.get('[data-testid="edit-requirement"]').trigger("click");
    await wrapper
      .get('[data-testid="requirement-statement"]')
      .setValue("The system must create guest reservations.");
    await wrapper.get('[data-testid="submit-requirements-revision"]').trigger("submit");
    await flushPromises();

    expect(api.proposedSpecification?.requirements[0]?.statement).toBe(
      "The system must create guest reservations.",
    );
    expect(wrapper.text()).toContain("REPLACE");
  });

  it("approves Gate 4 and exposes design readiness", async () => {
    const api = new FakeApi();
    api.readinessResult = {
      status: "REQUIREMENTS_APPROVAL_REQUIRED",
      version: VERSION,
      gate: PENDING_GATE,
      approved_current_specification: false,
    };
    api.historyResult = [VERSION];
    const wrapper = mountFlow(api, true);

    await flushPromises();
    await wrapper.get('[data-testid="approve-requirements-gate"]').trigger("click");
    await flushPromises();

    expect(api.decideGateCalls).toEqual(["APPROVE"]);
    expect(wrapper.get('[data-testid="requirements-readiness"]').text()).toContain(
      "The features are approved",
    );
  });

  it("does not send a revision request without a reason", async () => {
    const api = new FakeApi();
    api.readinessResult = {
      status: "REQUIREMENTS_APPROVAL_REQUIRED",
      version: VERSION,
      gate: PENDING_GATE,
      approved_current_specification: false,
    };
    api.historyResult = [VERSION];
    const decide = vi.spyOn(api, "decideGate");
    const wrapper = mountFlow(api, true);

    await flushPromises();
    const revisionButton = wrapper
      .findAll("button")
      .find((button: { text(): string }) => button.text() === "Request revision");

    expect(revisionButton).toBeDefined();
    expect(revisionButton?.attributes("disabled")).toBeDefined();
    expect(decide).not.toHaveBeenCalled();
  });

  it("has no axe violations with a generated specification", async () => {
    const wrapper = mountFlow(new FakeApi());
    await wrapper.get('[data-testid="generate-requirements"]').trigger("click");
    await flushPromises();
    await expectAccessible(wrapper.element);
  });

  it("shows the requirements as text first and as a table on request", async () => {
    const wrapper = mount(ProjectRequirementsFlow, {
      props: {
        projectId: PROJECT_ID,
        locale: "it",
        autoLoad: false,
        authorize,
        api: new FakeApi(),
      },
      attachTo: document.body,
    });
    await wrapper.get('[data-testid="generate-requirements"]').trigger("click");
    await flushPromises();

    expect(wrapper.get('[data-testid="artifact-view-text"]').attributes("aria-selected")).toBe(
      "true",
    );
    expect(wrapper.get('[data-testid="requirements-text-view"]').isVisible()).toBe(true);
    expect(wrapper.find('[data-testid="requirements-table-view"]').exists()).toBe(false);

    await wrapper.get('[data-testid="artifact-view-table"]').trigger("click");

    expect(wrapper.get('[data-testid="requirements-text-view"]').isVisible()).toBe(false);
    const table = wrapper.get('[data-testid="requirements-table-view"]');
    expect(table.attributes("id")).toBe("requirements-view-panel");
    expect(table.text()).toContain("REQ-001");
    expect(table.text()).toContain("Create reservations");
    expect(wrapper.get('[data-testid="artifact-view-table"]').attributes("aria-controls")).toBe(
      "requirements-view-panel",
    );
    wrapper.unmount();
  });

  it("draws the diagrams of the current version of the requirements", async () => {
    const wrapper = mount(ProjectRequirementsFlow, {
      props: {
        projectId: PROJECT_ID,
        locale: "it",
        autoLoad: false,
        authorize,
        api: new FakeApi(),
      },
      global: { stubs: { ProjectDiagramsView: true } },
    });
    await wrapper.get('[data-testid="generate-requirements"]').trigger("click");
    await flushPromises();

    await wrapper.get('[data-testid="artifact-view-diagram"]').trigger("click");

    const diagrams = wrapper.getComponent({ name: "ProjectDiagramsView" });
    expect(diagrams.props()).toMatchObject({
      projectId: PROJECT_ID,
      stage: "requirements",
      locale: "it",
      refreshKey: VERSION.content_hash,
    });
    expect(wrapper.find('[data-testid="requirements-table-view"]').exists()).toBe(false);

    await wrapper.get('[data-testid="artifact-view-text"]').trigger("click");

    expect(wrapper.findComponent({ name: "ProjectDiagramsView" }).exists()).toBe(false);
    expect(wrapper.get('[data-testid="requirements-text-view"]').attributes("id")).toBe(
      "requirements-view-panel",
    );
  });

  it("does not check the twins before the requirements exist", async () => {
    const wrapper = mountFlow(new FakeApi());
    await flushPromises();

    expect(wrapper.findComponent(RequirementsTwinAlignment).exists()).toBe(false);
    expect(requirementsAlignmentApi.status).not.toHaveBeenCalled();
  });

  it("checks the twins again when a proposed change appears", async () => {
    const api = new FakeApi();
    api.readinessResult = {
      status: "REQUIREMENTS_APPROVAL_REQUIRED",
      version: VERSION,
      gate: null,
      approved_current_specification: false,
    };
    api.historyResult = [VERSION];
    const wrapper = mountFlow(api, true);
    await flushPromises();

    await wrapper.get('[data-testid="edit-requirement"]').trigger("click");
    await wrapper.get('[data-testid="submit-requirements-revision"]').trigger("submit");
    await flushPromises();

    expect(wrapper.getComponent(RequirementsTwinAlignment).props("refreshKey")).toBe(
      `${VERSION.content_hash}:1`,
    );
    expect(requirementsAlignmentApi.status).toHaveBeenCalledTimes(2);
  });

  it("updates the requirements to the current twins and reloads them for a new approval", async () => {
    const api = new FakeApi();
    const realignedVersion: RequirementsSpecificationVersionPayload = {
      ...VERSION,
      id: "00000000-0000-4000-8000-000000000021",
      version_number: 2,
      based_on_version_number: 1,
      content_hash: "9".repeat(64),
    };
    api.readinessResult = {
      status: "REQUIREMENTS_APPROVAL_REQUIRED",
      version: VERSION,
      gate: null,
      approved_current_specification: false,
    };
    api.historyResult = [VERSION];
    const status = vi
      .spyOn(requirementsAlignmentApi, "status")
      .mockResolvedValue({ ...ALIGNED, aligned: false, issue: null });
    const realign = vi.spyOn(requirementsAlignmentApi, "realign").mockImplementation(async () => {
      api.readinessResult = { ...api.readinessResult, version: realignedVersion };
      api.historyResult = [VERSION, realignedVersion];
      status.mockResolvedValue({ ...ALIGNED, requirements_version_number: 2 });
      return {
        version_id: realignedVersion.id,
        version_number: 2,
        based_on_version_number: 1,
        content_hash: realignedVersion.content_hash,
        user_modeling_version_number: 2,
        twin_count: 1,
        gate_approval_required: true,
      };
    });
    const readiness = vi.spyOn(api, "readiness");
    const wrapper = mountFlow(api, true);
    await flushPromises();

    const alignment = wrapper.getComponent(RequirementsTwinAlignment);
    expect(alignment.props()).toMatchObject({
      projectId: PROJECT_ID,
      locale: "en",
      refreshKey: `${VERSION.content_hash}:0`,
    });
    expect(status).toHaveBeenCalledWith(PROJECT_ID, "access-token");
    expect(wrapper.get("header").element.nextElementSibling?.getAttribute("data-testid")).toBe(
      "requirements-twin-alignment",
    );
    expect(readiness).toHaveBeenCalledTimes(1);

    await wrapper.get('[data-testid="requirements-twin-alignment-update"]').trigger("click");
    await flushPromises();

    expect(realign).toHaveBeenCalledWith(PROJECT_ID, "access-token");
    expect(readiness).toHaveBeenCalledTimes(2);
    expect(wrapper.text()).toContain("Version 2");
    expect(alignment.props("refreshKey")).toBe(`${realignedVersion.content_hash}:0`);
    expect(status).toHaveBeenCalledTimes(2);
    expect(wrapper.get('[data-testid="requirements-twin-alignment-done"]').text()).toContain(
      "Version 2 of the requirements is ready with the same content. Approve it again below.",
    );
    expect(wrapper.get('[data-testid="submit-requirements-gate"]').text()).toBe(
      "Prepare for approval",
    );
    await expectAccessible(wrapper.element);
  });
});
