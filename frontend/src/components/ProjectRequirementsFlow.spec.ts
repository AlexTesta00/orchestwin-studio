import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { RequirementsApi } from "../api/requirements";
import type {
  HumanGatePayload,
  RequirementsReadinessPayload,
  RequirementsSpecificationDiffPayload,
  RequirementsSpecificationVersionPayload,
} from "../types/requirements";
import ProjectRequirementsFlow from "./ProjectRequirementsFlow.vue";

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
      "Ready for design exploration",
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
});
