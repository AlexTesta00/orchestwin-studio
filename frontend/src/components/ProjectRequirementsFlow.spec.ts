import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent, h, vShow, withDirectives } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearFollowedGenerations,
  generationJobsApi,
  type GenerationRequestJob,
} from "../api/generationJobs";
import {
  createRequirementsApi,
  RequirementsApiError,
  type RequirementsApi,
} from "../api/requirements";
import { requirementsAlignmentApi } from "../api/requirementsAlignment";
import type {
  HumanGateEventPayload,
  HumanGatePayload,
  HumanGateStatus,
  RequirementPriority,
  RequirementsReadinessPayload,
  RequirementsRevisionDecisionRequest,
  RequirementsRevisionPayload,
  RequirementsSpecificationDiffPayload,
  RequirementsSpecificationPayload,
  RequirementsSpecificationVersionPayload,
} from "../types/requirements";
import type { RequirementsAlignmentPayload } from "../types/requirementsAlignment";
import ProjectRequirementsFlow from "./ProjectRequirementsFlow.vue";
import RequirementsTwinAlignment from "./RequirementsTwinAlignment.vue";
import { createAppI18n } from "@/i18n";
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

const RESULTING_STATUS: Record<string, HumanGateStatus> = {
  APPROVE: "APPROVED",
  REQUEST_REVISION: "REVISION_REQUESTED",
  REJECT: "REJECTED",
  PAUSE: "PAUSED",
  RESUME: "PENDING_APPROVAL",
  CANCEL: "CANCELLED",
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

const VERSION_2: RequirementsSpecificationVersionPayload = {
  ...VERSION,
  id: "00000000-0000-4000-8000-000000000022",
  version_number: 2,
  based_on_version_number: 1,
  content_hash: "8".repeat(64),
  specification: DIFF.proposed_specification,
};

const CHANGE_PROPOSED: RequirementsRevisionPayload = {
  status: "CREATED",
  diff: DIFF,
  version: null,
  issue: null,
  proposal_issue: null,
  diff_persistence_status: "APPENDED",
  version_persistence_status: null,
};

type ChangeOutcome = "missing" | "proposed" | Error;

function refusal(code: string | null, status: number): RequirementsApiError {
  return new RequirementsApiError(code ?? `Requirements API request failed with status ${status}`, {
    status,
    code,
    payload: code === null ? { detail: "Not Found" } : { detail: { code } },
  });
}

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
  decideGateReasons: (string | null)[] = [];
  submitCalls = 0;
  events: HumanGateEventPayload[] = [];
  calls: string[] = [];
  changeRequests: string[] = [];
  changeOutcome: ChangeOutcome = "missing";
  changeGate: Promise<void> | null = null;
  nextVersion: RequirementsSpecificationVersionPayload | null = null;

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

  async requestChange(_projectId: string, request: string): Promise<RequirementsRevisionPayload> {
    this.calls.push("request-change");
    this.changeRequests.push(request);

    if (this.changeGate !== null) {
      await this.changeGate;
    }

    if (this.changeOutcome === "missing") {
      throw refusal(null, 404);
    }

    if (this.changeOutcome instanceof Error) {
      throw this.changeOutcome;
    }

    this.diffs = [DIFF];
    return CHANGE_PROPOSED;
  }

  async revisionHistory() {
    return this.diffs;
  }

  async getRevision() {
    return DIFF;
  }

  async decideRevision(
    _projectId: string,
    diffId: string,
    request: RequirementsRevisionDecisionRequest,
  ): Promise<RequirementsRevisionPayload> {
    const approved = request.decision === "APPROVE";
    const applied = approved ? (this.nextVersion ?? VERSION) : null;
    const decided: RequirementsSpecificationDiffPayload = {
      ...(this.diffs.find((diff) => diff.id === diffId) ?? DIFF),
      status: approved ? "APPROVED" : "REJECTED",
      decided_by_user_id: OWNER_ID,
      decided_at: NOW,
      decision_reason: request.reason ?? null,
      applied_specification_version_id: applied?.id ?? null,
    };
    this.diffs = this.diffs.map((diff) => (diff.id === diffId ? decided : diff));

    if (applied !== null && this.nextVersion !== null) {
      this.readinessResult = { ...this.readinessResult, version: applied };
      this.historyResult = [...this.historyResult, applied];
    }

    return {
      status: approved ? "APPLIED" : "REJECTED",
      diff: decided,
      version: applied,
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
    this.submitCalls += 1;
    this.calls.push("submit");
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

  async decideGate(_projectId: string, request: { action: string; reason?: string | null }) {
    this.decideGateCalls.push(request.action);
    this.decideGateReasons.push(request.reason ?? null);
    this.calls.push(`decide:${request.action}`);
    const approved = request.action === "APPROVE";
    const gate = {
      ...PENDING_GATE,
      status: RESULTING_STATUS[request.action] ?? ("PENDING_APPROVAL" as const),
      event_sequence: 2,
    };
    this.events = [
      ...this.events,
      {
        id: `00000000-0000-4000-8000-0000000001${String(this.events.length).padStart(2, "0")}`,
        gate_id: GATE_ID,
        sequence_number: this.events.length + 2,
        kind: request.action as HumanGateEventPayload["kind"],
        previous_status: "PENDING_APPROVAL",
        resulting_status: gate.status,
        artifact: PENDING_GATE.artifact,
        occurred_at: NOW,
        actor_user_id: OWNER_ID,
        reason: request.reason ?? null,
      },
    ];
    this.readinessResult = {
      status: approved ? "READY_FOR_DESIGN_EXPLORATION" : "REQUIREMENTS_APPROVAL_REQUIRED",
      version: this.readinessResult.version ?? VERSION,
      gate,
      approved_current_specification: approved,
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
    return this.events;
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

const TWIN = VERSION.specification.user_twin_references[0]!;
const SECOND_REQUIREMENT_ID = "00000000-0000-4000-8000-000000000031";
const STORY_ID = "00000000-0000-4000-8000-000000000032";
const CRITERION_ID = "00000000-0000-4000-8000-000000000033";

const RICH_SPECIFICATION: RequirementsSpecificationPayload = {
  ...VERSION.specification,
  requirements: [
    {
      ...VERSION.specification.requirements[0]!,
      user_twin_references: [TWIN],
    },
    {
      id: SECOND_REQUIREMENT_ID,
      code: "REQ-002",
      title: "Works on tablets",
      statement: "The desk can use the app on a tablet.",
      kind: "NON_FUNCTIONAL",
      priority: "SHOULD",
      sources: [],
      user_twin_references: [TWIN],
    },
  ],
  user_stories: [
    {
      id: STORY_ID,
      code: "USR-001",
      user_twin_reference: TWIN,
      goal: "book a room quickly",
      benefit: "serve the queue faster",
      requirement_ids: [REQUIREMENT_ID],
    },
  ],
  acceptance_criteria: [
    {
      id: CRITERION_ID,
      code: "AC-001",
      statement: "A booking is saved with the guest name.",
      verification_method: "DEMONSTRATION",
      requirement_ids: [REQUIREMENT_ID],
      user_story_ids: [STORY_ID],
    },
  ],
  scenarios: [],
  risks: [
    {
      id: "00000000-0000-4000-8000-000000000034",
      code: "RSK-001",
      summary: "Double bookings at peak time",
      likelihood: "LIKELY",
      impact: "HIGH",
      mitigation: "lock the room while it is being booked",
      requirement_ids: [REQUIREMENT_ID],
      sources: [],
      review_status: "PROPOSED",
    },
  ],
  definition_of_done: [
    {
      id: "00000000-0000-4000-8000-000000000035",
      code: "DOD-001",
      statement: "Every essential requirement has a passing check.",
      verification_method: "INSPECTION",
      applicability: "REQUIRED",
      condition: null,
      requirement_ids: [REQUIREMENT_ID],
    },
  ],
};

const RICH_VERSION: RequirementsSpecificationVersionPayload = {
  ...VERSION,
  specification: RICH_SPECIFICATION,
};

function readyApi(
  gate: HumanGatePayload | null = null,
  version: RequirementsSpecificationVersionPayload = VERSION,
): FakeApi {
  const api = new FakeApi();
  api.readinessResult = {
    status: "REQUIREMENTS_APPROVAL_REQUIRED",
    version,
    gate,
    approved_current_specification: false,
  };
  api.historyResult = [version];
  return api;
}

function mountFlow(
  api: RequirementsApi,
  autoLoad = false,
  options: { locale?: "en" | "it"; attach?: boolean; sectionsMode?: boolean } = {},
) {
  const locale = options.locale ?? "en";
  return mount(ProjectRequirementsFlow, {
    props: {
      projectId: PROJECT_ID,
      locale,
      autoLoad,
      authorize,
      api,
      ...(options.sectionsMode === undefined ? {} : { sectionsMode: options.sectionsMode }),
    },
    global: { plugins: [createAppI18n(locale)] },
    ...(options.attach ? { attachTo: document.body } : {}),
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

const REVISION_GATE: HumanGatePayload = {
  ...PENDING_GATE,
  status: "REVISION_REQUESTED",
  event_sequence: 2,
};

function requestEvent(reason: string): HumanGateEventPayload {
  return {
    id: "00000000-0000-4000-8000-000000000150",
    gate_id: GATE_ID,
    sequence_number: 2,
    kind: "REQUEST_REVISION",
    previous_status: "PENDING_APPROVAL",
    resulting_status: "REVISION_REQUESTED",
    artifact: PENDING_GATE.artifact,
    occurred_at: NOW,
    actor_user_id: OWNER_ID,
    reason,
  };
}

function revisionApi(reason: string): FakeApi {
  const api = readyApi(REVISION_GATE);
  api.events = [requestEvent(reason)];
  return api;
}

async function askFor(wrapper: ReturnType<typeof mountFlow>, request: string): Promise<void> {
  await wrapper.get('[data-testid="decision-secondary"]').trigger("click");
  await wrapper.get('[data-testid="decision-note"]').setValue(request);
  await wrapper.get('[data-testid="decision-send"]').trigger("click");
  await flushPromises();
}

function noteOf(wrapper: ReturnType<typeof mountFlow>): string {
  return (wrapper.get('[data-testid="decision-note"]').element as HTMLTextAreaElement).value;
}

function rowOf(wrapper: ReturnType<typeof mountFlow>, code: string) {
  return wrapper.get(`[data-testid="requirement-row"][data-requirements-item="${code}"]`);
}

async function openRow(wrapper: ReturnType<typeof mountFlow>, code: string): Promise<void> {
  await rowOf(wrapper, code).get('[data-testid="requirement-toggle"]').trigger("click");
}

function spokenText(element: Element): string {
  const copy = element.cloneNode(true) as Element;
  copy.querySelectorAll('[aria-hidden="true"]').forEach((hidden) => hidden.remove());
  return (copy.textContent ?? "").trim();
}

function expandedOf(wrapper: ReturnType<typeof mountFlow>): (string | undefined)[] {
  return wrapper
    .findAll('[data-testid="requirement-toggle"]')
    .map((toggle) => toggle.attributes("aria-expanded"));
}

function prioritized(
  priorities: readonly RequirementPriority[],
): RequirementsSpecificationVersionPayload {
  return {
    ...VERSION,
    specification: {
      ...VERSION.specification,
      requirements: priorities.map((priority, index) => ({
        ...VERSION.specification.requirements[0]!,
        id: `00000000-0000-4000-8000-0000000004${String(index).padStart(2, "0")}`,
        code: `REQ-${String(index + 1).padStart(3, "0")}`,
        title: `Requirement ${index + 1}`,
        priority,
      })),
    },
  };
}

describe("ProjectRequirementsFlow", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.spyOn(requirementsAlignmentApi, "status").mockResolvedValue(ALIGNED);
  });

  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("generates and renders the first governed specification", async () => {
    const api = new FakeApi();
    const wrapper = mountFlow(api);

    await wrapper.get('[data-testid="generate-requirements"]').trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("REQ-001");
    expect(wrapper.text()).toContain("Create reservations");
    expect(wrapper.text()).toContain("Version 1");
    expect(api.submitCalls).toBe(0);
  });

  it("shows who prepares the requirements and waits for the approved profiles before preparing them", async () => {
    const wrapper = mount(ProjectRequirementsFlow, {
      props: {
        projectId: PROJECT_ID,
        locale: "it",
        autoLoad: false,
        prerequisiteReady: false,
        authorize,
        api: new FakeApi(),
      },
      global: { plugins: [createAppI18n("it")] },
    });
    await flushPromises();

    const empty = wrapper.get('[data-testid="requirements-empty"]');
    expect(empty.get('[data-testid="agent-message"]').text()).toContain("Analista delle esigenze");
    expect(empty.text()).toContain("Approva prima i profili dei tuoi utenti");
    expect(wrapper.get('[data-testid="generate-requirements"]').text()).toBe("Prepara i requisiti");
    expect(
      wrapper.get('[data-testid="generate-requirements"]').attributes("disabled"),
    ).toBeDefined();
    expect(wrapper.find('[data-testid="decision-bar"]').exists()).toBe(false);
  });

  it("creates a full specification diff from an edited requirement", async () => {
    const api = readyApi();
    const wrapper = mountFlow(api, true);

    await flushPromises();
    await openRow(wrapper, "REQ-001");
    await rowOf(wrapper, "REQ-001").get('[data-testid="edit-requirement"]').trigger("click");
    expect(
      wrapper
        .find('[data-testid="requirement-row"] [data-testid="requirement-edit-form"]')
        .exists(),
    ).toBe(true);
    await wrapper
      .get('[data-testid="requirement-statement"]')
      .setValue("The system must create guest reservations.");
    await wrapper.get('[data-testid="submit-requirements-revision"]').trigger("submit");
    await flushPromises();

    expect(api.proposedSpecification?.requirements[0]?.statement).toBe(
      "The system must create guest reservations.",
    );
    const change = wrapper.get('[data-testid="requirements-pending-change"]');
    expect(change.text()).toContain("Before · REQ-001");
    expect(change.text()).toContain("After · Changed");
    expect(change.text()).toContain("The system must create guest reservations.");
    expect(wrapper.get('[data-testid="decision-bar"]').text()).toContain(
      "A proposed change is waiting above",
    );
    expect(wrapper.find('[data-testid="requirement-edit-form"]').exists()).toBe(false);
  });

  it("applies a proposed change and discards one only with a reason", async () => {
    const api = readyApi();
    api.diffs = [DIFF];
    const decide = vi.spyOn(api, "decideRevision");
    const wrapper = mountFlow(api, true);
    await flushPromises();

    const discard = wrapper.get('[data-testid="reject-requirements-diff"]');
    expect(discard.attributes("disabled")).toBeDefined();
    await wrapper.get('[data-testid="approve-requirements-diff"]').trigger("click");
    await flushPromises();

    expect(decide).toHaveBeenCalledWith(
      PROJECT_ID,
      DIFF_ID,
      { decision: "APPROVE", reason: null },
      "access-token",
    );
  });

  it("approves Gate 4 and exposes design readiness", async () => {
    const api = readyApi(PENDING_GATE);
    const wrapper = mountFlow(api, true);

    await flushPromises();
    const bar = wrapper.get('[data-testid="decision-bar"]');
    expect(bar.text()).toContain("The decision is yours");
    expect(wrapper.get('[data-testid="decision-primary"]').text()).toBe("Approve the requirements");
    await wrapper.get('[data-testid="decision-primary"]').trigger("click");
    await flushPromises();

    expect(api.decideGateCalls).toEqual(["APPROVE"]);
    expect(api.submitCalls).toBe(0);
    expect(wrapper.get('[data-testid="requirements-readiness"]').text()).toContain(
      "Requirements approved by you",
    );
    expect(wrapper.find('[data-testid="decision-bar"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="step-technical-details"]').text()).toContain(
      "Version 1 · approved",
    );
  });

  it("approves a new version in one decision: it first brings it to approval, then approves it", async () => {
    const api = readyApi();
    const wrapper = mountFlow(api, true);
    await flushPromises();

    expect(wrapper.get('[data-testid="step-technical-details"]').text()).toContain(
      "Version 1 · waiting for your decision",
    );
    await wrapper.get('[data-testid="decision-primary"]').trigger("click");
    await flushPromises();

    expect(api.submitCalls).toBe(1);
    expect(api.decideGateCalls).toEqual(["APPROVE"]);
    expect(wrapper.get('[data-testid="requirements-readiness"]').text()).toBe(
      "Requirements approved by you. Next: Design & Evaluation.",
    );
    expect(wrapper.emitted("sections-changed")).toHaveLength(1);
  });

  it("does not send a revision request without a reason", async () => {
    const api = readyApi(PENDING_GATE);
    const decide = vi.spyOn(api, "decideGate");
    const wrapper = mountFlow(api, true, { attach: true });

    await flushPromises();
    await wrapper.get('[data-testid="decision-secondary"]').trigger("click");
    await flushPromises();
    const send = wrapper.get('[data-testid="decision-send"]');

    expect(wrapper.find('[data-testid="decision-note"]').exists()).toBe(true);
    expect(send.attributes("disabled")).toBeDefined();
    await send.trigger("click");
    expect(decide).not.toHaveBeenCalled();

    await wrapper.get('[data-testid="decision-note"]').setValue("  Add the search by name.  ");
    await wrapper.get('[data-testid="decision-send"]').trigger("click");
    await flushPromises();

    expect(api.decideGateCalls).toEqual(["REQUEST_REVISION"]);
    expect(api.decideGateReasons).toEqual(["Add the search by name."]);
    const closed = wrapper.get('[data-testid="requirements-gate-closed"]');
    expect(closed.text()).toContain("You asked for changes");
    expect(closed.get('[data-testid="requirements-gate-note"] blockquote').text()).toBe(
      "Add the search by name.",
    );
    expect(closed.text()).not.toContain("«");
    expect(wrapper.find('[data-testid="decision-bar"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("brings a new version to approval before it records the requested change", async () => {
    const api = readyApi();
    const wrapper = mountFlow(api, true, { attach: true, locale: "it" });
    await flushPromises();

    await wrapper.get('[data-testid="decision-secondary"]').trigger("click");
    await wrapper.get('[data-testid="decision-note"]').setValue("Aggiungi la ricerca per nome.");
    await wrapper.get('[data-testid="decision-send"]').trigger("click");
    await flushPromises();

    expect(api.submitCalls).toBe(1);
    expect(api.decideGateCalls).toEqual(["REQUEST_REVISION"]);
    expect(api.calls).toEqual(["submit", "decide:REQUEST_REVISION", "request-change"]);
    expect(wrapper.get('[data-testid="requirements-gate-closed"]').text()).toContain(
      "Hai chiesto modifiche",
    );
    wrapper.unmount();
  });

  it("keeps a paused approval in a notice with resume and cancel instead of the bar", async () => {
    const api = readyApi({ ...PENDING_GATE, status: "PAUSED", resume_status: "PENDING_APPROVAL" });
    const wrapper = mountFlow(api, true);
    await flushPromises();

    expect(wrapper.find('[data-testid="decision-bar"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="requirements-gate-paused"]').text()).toContain(
      "The approval of these requirements is paused.",
    );
    await wrapper.get('[data-testid="resume-requirements-gate"]').trigger("click");
    await flushPromises();

    expect(api.decideGateCalls).toEqual(["RESUME"]);
    expect(wrapper.find('[data-testid="decision-bar"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="requirements-more-actions"]').exists()).toBe(true);
  });

  it("keeps rejecting, pausing and cancelling a pending approval under the other choices", async () => {
    const api = readyApi(PENDING_GATE);
    const wrapper = mountFlow(api, true);
    await flushPromises();

    const more = wrapper.get('[data-testid="requirements-more-actions"]');
    expect(more.element.tagName).toBe("DETAILS");
    expect(more.attributes("open")).toBeUndefined();
    const reject = more
      .findAll("button")
      .find((button) => button.text() === "Reject the requirements");
    expect(reject?.attributes("disabled")).toBeDefined();

    await more.get("textarea").setValue("They miss the payments.");
    await more
      .findAll("button")
      .find((button) => button.text() === "Reject the requirements")!
      .trigger("click");
    await flushPromises();

    expect(api.decideGateCalls).toEqual(["REJECT"]);
    expect(api.decideGateReasons).toEqual(["They miss the payments."]);
    expect(wrapper.get('[data-testid="requirements-gate-closed"]').text()).toContain(
      "You rejected these requirements",
    );
  });

  it("shows the requirements by priority, who asked for them and how they are checked", async () => {
    const api = readyApi(null, RICH_VERSION);
    const wrapper = mountFlow(api, true, { attach: true });
    await flushPromises();

    expect(wrapper.get('[data-testid="requirements-summary"]').text()).toBe(
      "Prepared by the Needs analyst · 2 requirements, 1 story, 1 acceptance criterion",
    );
    expect(wrapper.findAll('[data-testid="requirements-groups"] h2').map((h) => h.text())).toEqual([
      "Must do",
      "Should do",
    ]);
    const rows = wrapper.findAll('[data-testid="requirement-row"]');
    expect(rows.map((row) => row.attributes("data-requirements-item"))).toEqual([
      "REQ-001",
      "REQ-002",
    ]);
    expect(
      rows.map((row) => spokenText(row.get('[data-testid="requirement-toggle"]').element)),
    ).toEqual(["REQ-001 Create reservations", "REQ-002 Works on tablets"]);
    expect(rows.map((row) => row.get('[data-testid="requirement-detail"]').isVisible())).toEqual([
      false,
      false,
    ]);

    await wrapper.get('[data-testid="requirements-toggle-all"]').trigger("click");

    expect(rows[0]!.get('[data-testid="requirement-meta"]').text()).toContain("Asked by");
    expect(rows[0]!.get('[data-testid="requirement-twin"]').text()).toBe("Receptionist Twin");
    expect(rows[0]!.get('[data-testid="requirement-twin"]').classes()).toContain("border-dashed");
    expect(rows[0]!.get('[data-testid="requirement-meta"]').text()).toContain("Check: AC-001");
    expect(rows[1]!.get('[data-testid="requirement-meta"]').text()).toContain(
      "No acceptance criterion",
    );
    expect(rows[1]!.get('[data-testid="edit-requirement"]').text()).toBe("Propose a change");

    const notice = wrapper.get('[data-testid="requirements-coverage-notice"]');
    expect(notice.text()).toContain("One requirement has no way to be checked yet");
    expect(notice.text()).toContain(
      "REQ-002 has no acceptance criterion; REQ-002 is not linked to a story.",
    );
    expect(notice.find("button").exists()).toBe(false);

    const checks = wrapper.get('[data-testid="requirements-checks"]');
    expect(checks.attributes("open")).toBeUndefined();
    await checks.get("summary").trigger("click");
    expect(checks.attributes("open")).toBeDefined();
    expect(
      wrapper
        .findAll('[data-testid="requirements-check"]')
        .map((card) => card.findAll("p").map((line) => line.text())),
    ).toEqual([
      ["How we check it · AC-001", "A booking is saved with the guest name."],
      [
        "Risk · RSK-001",
        "Double bookings at peak time",
        "Remedy: lock the room while it is being booked",
      ],
      ["When it is finished · DOD-001", "Every essential requirement has a passing check."],
    ]);
    const stories = wrapper.get('[data-testid="requirements-stories"]');
    expect(stories.attributes("open")).toBeUndefined();
    expect(stories.get("summary").text()).toContain("1 story");
    expect(wrapper.get('[data-testid="decision-bar"]').text()).toContain(
      "One requirement has no way to be checked yet: if you approve now, it stays unchecked.",
    );
    wrapper.unmount();
  });

  it("counts the gaps in words and lists the codes in Italian", async () => {
    const orphan = {
      ...RICH_SPECIFICATION.requirements[1]!,
      id: "00000000-0000-4000-8000-000000000036",
      code: "REQ-003",
    };
    const version = {
      ...RICH_VERSION,
      specification: {
        ...RICH_SPECIFICATION,
        requirements: [...RICH_SPECIFICATION.requirements, orphan],
      },
    };
    const wrapper = mountFlow(readyApi(null, version), true, { locale: "it" });
    await flushPromises();

    const notice = wrapper.get('[data-testid="requirements-coverage-notice"]');
    expect(notice.text()).toContain("Due requisiti non hanno ancora un modo per essere verificati");
    expect(notice.text()).toContain(
      "REQ-002 e REQ-003 sono senza criterio di verifica; REQ-002 e REQ-003 non sono legati a una storia.",
    );
    expect(wrapper.get('[data-testid="requirements-summary"]').text()).toBe(
      "Preparati dall'Analista delle esigenze · 3 requisiti, 1 storia, 1 criterio di verifica",
    );
  });

  it("brings the person from a node of the diagram to the item in the text", async () => {
    const api = readyApi(null, RICH_VERSION);
    const wrapper = mount(ProjectRequirementsFlow, {
      props: { projectId: PROJECT_ID, locale: "en", autoLoad: true, authorize, api },
      global: { plugins: [createAppI18n("en")], stubs: { ProjectDiagramsView: true } },
      attachTo: document.body,
    });
    await flushPromises();

    await wrapper.get('[data-testid="artifact-view-diagram"]').trigger("click");
    const diagrams = wrapper.getComponent({ name: "ProjectDiagramsView" });
    expect(diagrams.props("links")).toEqual(
      expect.arrayContaining([
        { code: "REQ-001", label: "REQ-001 · Create reservations: read it in the text" },
        { code: "USR-001", label: "USR-001 · book a room quickly: read it in the text" },
        {
          code: "AC-001",
          label: "AC-001 · A booking is saved with the guest name.: read it in the text",
        },
      ]),
    );

    diagrams.vm.$emit("select-node", "USR-001");
    await flushPromises();

    expect(wrapper.findComponent({ name: "ProjectDiagramsView" }).exists()).toBe(false);
    expect(wrapper.get('[data-testid="requirements-text-view"]').isVisible()).toBe(true);
    expect(wrapper.get('[data-testid="requirements-stories"]').attributes("open")).toBeDefined();
    const story = wrapper.get('[data-requirements-item="USR-001"]');
    expect(document.activeElement).toBe(story.element);
    expect(story.classes()).toContain("ring-petrol-on-night/60");

    await wrapper.get('[data-testid="artifact-view-diagram"]').trigger("click");
    wrapper.getComponent({ name: "ProjectDiagramsView" }).vm.$emit("select-node", "AC-001");
    await flushPromises();

    expect(wrapper.get('[data-testid="requirements-checks"]').attributes("open")).toBeDefined();
    expect(document.activeElement?.getAttribute("data-requirements-item")).toBe("AC-001");
    wrapper.unmount();
  });

  it("mounts the decision in the bar of the page when the page offers one", async () => {
    const target = document.createElement("div");
    target.id = "step-decision-bar";
    document.body.append(target);
    const wrapper = mountFlow(readyApi(), true, { attach: true });
    await flushPromises();

    expect(target.querySelector('[data-testid="decision-bar"]')).not.toBeNull();
    expect(wrapper.find('[data-testid="decision-bar"]').exists()).toBe(false);
    target
      .querySelector<HTMLButtonElement>('[data-testid="decision-primary"]')
      ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await flushPromises();

    expect(target.querySelector('[data-testid="decision-bar"]')).toBeNull();
    expect(wrapper.find('[data-testid="requirements-readiness"]').exists()).toBe(true);
    wrapper.unmount();
  });

  it("puts its technical row after the bar of the page and back in the step without it", async () => {
    const row = document.createElement("div");
    row.id = "step-technical-row";
    document.body.append(row);
    const wrapper = mountFlow(readyApi(), true, { attach: true });
    await flushPromises();

    expect(row.querySelector('[data-testid="step-technical-details"]')).not.toBeNull();
    expect(wrapper.find('[data-testid="step-technical-details"]').exists()).toBe(false);
    wrapper.unmount();
    expect(row.childElementCount).toBe(0);
    row.remove();

    const alone = mountFlow(readyApi(), true, { attach: true });
    await flushPromises();
    expect(alone.find('[data-testid="step-technical-details"]').exists()).toBe(true);
    alone.unmount();
  });

  it("keeps the bar of a hidden step out of the bar of the page", async () => {
    const target = document.createElement("div");
    target.id = "step-decision-bar";
    document.body.append(target);
    const original = Object.getOwnPropertyDescriptor(Element.prototype, "checkVisibility");
    Object.defineProperty(Element.prototype, "checkVisibility", {
      configurable: true,
      value(this: Element) {
        return this.getAttribute("data-testid") !== "requirements-flow";
      },
    });
    try {
      const wrapper = mountFlow(readyApi(), true, { attach: true });
      await flushPromises();

      expect(target.querySelector('[data-testid="decision-bar"]')).toBeNull();
      expect(wrapper.find('[data-testid="decision-bar"]').exists()).toBe(true);
      wrapper.unmount();
    } finally {
      if (original === undefined) {
        Reflect.deleteProperty(Element.prototype, "checkVisibility");
      } else {
        Object.defineProperty(Element.prototype, "checkVisibility", original);
      }
    }
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
      const api = readyApi();
      const Stage = defineComponent({
        props: { shown: { type: Boolean, required: true } },
        setup(stage) {
          return () =>
            withDirectives(
              h("div", [
                h(ProjectRequirementsFlow, {
                  projectId: PROJECT_ID,
                  locale: "en",
                  autoLoad: true,
                  authorize,
                  api,
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
        global: { plugins: [createAppI18n("en")] },
      });
      await flushPromises();

      expect(bar.childElementCount).toBe(0);
      expect(row.childElementCount).toBe(0);
      expect(wrapper.find('[data-testid="decision-bar"]').exists()).toBe(true);

      await wrapper.setProps({ shown: true });
      await flushPromises();

      expect(bar.querySelector('[data-testid="decision-bar"]')).not.toBeNull();
      expect(row.querySelector('[data-testid="step-technical-details"]')).not.toBeNull();
      expect(wrapper.find('[data-testid="decision-bar"]').exists()).toBe(false);
      wrapper.unmount();
    } finally {
      restore();
      bar.remove();
      row.remove();
      host.remove();
    }
  });

  it("says in the note that the analyst writes a new version for the person to decide on", async () => {
    const wrapper = mountFlow(readyApi(PENDING_GATE), true, { attach: true });
    await flushPromises();

    await wrapper.get('[data-testid="decision-secondary"]').trigger("click");
    const note = wrapper.get('[data-testid="decision-note"]');
    expect(note.attributes("placeholder")).toBe(
      "Write what to change: the analyst writes the requirements again and you decide whether to apply the new version.",
    );
    wrapper.unmount();
  });

  it("keeps the written change request when sending it fails", async () => {
    const api = readyApi(PENDING_GATE);
    vi.spyOn(api, "decideGate").mockRejectedValueOnce(new Error("Network unreachable"));
    const wrapper = mountFlow(api, true, { attach: true });
    await flushPromises();

    await wrapper.get('[data-testid="decision-secondary"]').trigger("click");
    await wrapper.get('[data-testid="decision-note"]').setValue("Add the search by name.");
    await wrapper.get('[data-testid="decision-send"]').trigger("click");
    await flushPromises();

    expect(wrapper.get('[data-testid="requirements-error"]').text()).toBe(
      "Your request for changes could not be recorded. Your note is still there: try again in a moment.",
    );
    const note = wrapper.get('[data-testid="decision-note"]').element as HTMLTextAreaElement;
    expect(note.value).toBe("Add the search by name.");
    expect(api.changeRequests).toEqual([]);
    wrapper.unmount();
  });

  it("does not approve when bringing the requirements to approval fails", async () => {
    const api = readyApi();
    vi.spyOn(api, "submitGate").mockRejectedValueOnce(new Error("GATE_BLOCKED"));
    const decide = vi.spyOn(api, "decideGate");
    const wrapper = mountFlow(api, true);
    await flushPromises();

    await wrapper.get('[data-testid="decision-primary"]').trigger("click");
    await flushPromises();

    expect(decide).not.toHaveBeenCalled();
    expect(wrapper.get('[data-testid="requirements-error"]').text()).toBe(
      "The requirements could not be brought to your approval, so nothing was approved. Try again in a moment.",
    );
    expect(wrapper.text()).not.toContain("GATE_BLOCKED");
    expect(wrapper.find('[data-testid="requirements-readiness"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="decision-primary"]').text()).toBe("Approve the requirements");
  });

  it("approves with the same button when only the approval failed the first time", async () => {
    const api = readyApi();
    const decide = vi
      .spyOn(api, "decideGate")
      .mockRejectedValueOnce(new Error("Requirements API request failed with status 503"));
    const wrapper = mountFlow(api, true);
    await flushPromises();

    await wrapper.get('[data-testid="decision-primary"]').trigger("click");
    await flushPromises();

    expect(api.submitCalls).toBe(1);
    expect(decide).toHaveBeenCalledTimes(1);
    expect(wrapper.get('[data-testid="requirements-error"]').text()).toBe(
      "The requirements are ready for your approval, but the approval did not go through. Press “Approve the requirements” again.",
    );
    expect(wrapper.find('[data-testid="requirements-readiness"]').exists()).toBe(false);

    await wrapper.get('[data-testid="decision-primary"]').trigger("click");
    await flushPromises();

    expect(api.submitCalls).toBe(1);
    expect(decide).toHaveBeenCalledTimes(2);
    expect(api.decideGateCalls).toEqual(["APPROVE"]);
    expect(wrapper.find('[data-testid="requirements-error"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="requirements-readiness"]').exists()).toBe(true);
  });

  it("keeps the bar busy while the requirements are brought to approval and approved", async () => {
    const api = readyApi();
    const submit = api.submitGate.bind(api);
    let release: () => void = () => undefined;
    const waiting = new Promise<void>((resolve) => {
      release = resolve;
    });
    vi.spyOn(api, "submitGate").mockImplementation(async () => {
      await waiting;
      return submit();
    });
    const wrapper = mountFlow(api, true);
    await flushPromises();

    await wrapper.get('[data-testid="decision-primary"]').trigger("click");
    await flushPromises();

    expect(wrapper.get('[data-testid="decision-bar"]').attributes("aria-busy")).toBe("true");
    expect(wrapper.get('[data-testid="decision-primary"]').attributes("disabled")).toBeDefined();
    await wrapper.get('[data-testid="decision-primary"]').trigger("click");
    release();
    await flushPromises();

    expect(api.submitCalls).toBe(1);
    expect(api.decideGateCalls).toEqual(["APPROVE"]);
    expect(wrapper.find('[data-testid="decision-bar"]').exists()).toBe(false);
  });

  it("keeps the decision at the end of the step when the page has no bar", async () => {
    const wrapper = mountFlow(readyApi(), true);
    await flushPromises();

    const flow = wrapper.get('[data-testid="requirements-flow"]').element;
    const bar = wrapper.get('[data-testid="decision-bar"]').element;
    const details = wrapper.get('[data-testid="step-technical-details"]').element;
    expect(flow.contains(bar)).toBe(true);
    expect(bar.compareDocumentPosition(details) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(
      wrapper.get('[data-testid="requirements-text-view"]').element.compareDocumentPosition(bar) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("keeps hash, versions and sources in the technical details, closed until asked", async () => {
    const wrapper = mountFlow(readyApi(PENDING_GATE, RICH_VERSION), true);
    await flushPromises();

    const details = wrapper.get('[data-testid="step-technical-details"]');
    expect(details.text()).not.toContain(VERSION.content_hash);
    await details.get('[data-testid="step-technical-details-toggle"]').trigger("click");

    const content = details.get('[data-testid="step-technical-details-content"]');
    expect(content.text()).toContain(VERSION.content_hash);
    expect(content.text()).toContain("Waiting for your approval · Decision no. 1");
    expect(content.text()).not.toContain("1 of 3");
    expect(content.text()).toContain("Sources: functional_requirements[0]");
    expect(content.text()).toContain("Receptionist Twin v1");
    expect(content.find('[data-testid="version-comparison"]').exists()).toBe(false);
    expect(content.text()).toContain("At least two versions are required");
    expect(wrapper.text()).not.toContain("REPLACE");
  });

  it("has no axe violations with a generated specification", async () => {
    const wrapper = mountFlow(new FakeApi());
    await wrapper.get('[data-testid="generate-requirements"]').trigger("click");
    await flushPromises();
    await expectAccessible(wrapper.element);
  });

  it("has no axe violations with gaps, a proposed change and open details", async () => {
    const api = readyApi(PENDING_GATE, RICH_VERSION);
    api.diffs = [DIFF];
    const wrapper = mountFlow(api, true, { attach: true });
    await flushPromises();
    await wrapper.get('[data-testid="step-technical-details-toggle"]').trigger("click");
    (wrapper.get('[data-testid="requirements-stories"]').element as HTMLDetailsElement).open = true;
    (wrapper.get('[data-testid="requirements-checks"]').element as HTMLDetailsElement).open = true;
    await wrapper.get('[data-testid="requirements-toggle-all"]').trigger("click");

    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });

  it("shows the requirements as text first and as a table on request", async () => {
    const wrapper = mountFlow(new FakeApi(), false, { locale: "it", attach: true });
    await wrapper.get('[data-testid="generate-requirements"]').trigger("click");
    await flushPromises();

    expect(wrapper.get('[data-testid="artifact-view-text"]').attributes("aria-selected")).toBe(
      "true",
    );
    expect(wrapper.get('[data-testid="artifact-view-switch"]').attributes("aria-label")).toBe(
      "Vista dei requisiti",
    );
    const text = wrapper.get('[data-testid="requirements-text-view"]');
    expect(text.isVisible()).toBe(true);
    expect(text.attributes("role")).toBe("tabpanel");
    expect(text.attributes("aria-labelledby")).toBe(
      wrapper.get('[data-testid="artifact-view-text"]').attributes("id"),
    );
    expect(wrapper.find('[data-testid="requirements-table-view"]').exists()).toBe(false);

    await wrapper.get('[data-testid="artifact-view-table"]').trigger("click");

    expect(wrapper.get('[data-testid="requirements-text-view"]').isVisible()).toBe(false);
    const table = wrapper.get('[data-testid="requirements-table-view"]');
    expect(table.attributes("id")).toBe("requirements-view-panel");
    expect(table.attributes("role")).toBe("tabpanel");
    expect(table.text()).toContain("REQ-001");
    expect(table.text()).toContain("Create reservations");
    expect(wrapper.get('[data-testid="artifact-view-table"]').attributes("aria-controls")).toBe(
      "requirements-view-panel",
    );
    expect(wrapper.find('[data-testid="requirements-coverage-notice"]').exists()).toBe(true);
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
      global: { plugins: [createAppI18n("it")], stubs: { ProjectDiagramsView: true } },
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
      links: [{ code: "REQ-001", label: "REQ-001 · Create reservations: leggilo nel testo" }],
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

  it("reads the requirements and their alignment with the twins again once when the twins change", async () => {
    const api = readyApi();
    const readiness = vi.spyOn(api, "readiness");
    const wrapper = mountFlow(api, true);
    await flushPromises();
    expect(readiness).toHaveBeenCalledTimes(1);
    expect(requirementsAlignmentApi.status).toHaveBeenCalledTimes(1);

    await wrapper.setProps({ upstream: "twins-1:APPROVED" });
    await wrapper.setProps({ upstream: null });
    await wrapper.setProps({ upstream: "twins-1:APPROVED" });
    await flushPromises();
    expect(readiness).toHaveBeenCalledTimes(1);
    expect(requirementsAlignmentApi.status).toHaveBeenCalledTimes(1);

    await wrapper.setProps({ upstream: "twins-2:APPROVED" });
    await flushPromises();
    expect(readiness).toHaveBeenCalledTimes(2);
    expect(requirementsAlignmentApi.status).toHaveBeenCalledTimes(2);
    expect(wrapper.getComponent(RequirementsTwinAlignment).props("refreshKey")).toBe(
      `${VERSION.content_hash}:0:1`,
    );
    wrapper.unmount();
  });

  it("checks the twins again when a proposed change appears", async () => {
    const api = readyApi();
    const wrapper = mountFlow(api, true);
    await flushPromises();

    await openRow(wrapper, "REQ-001");
    await wrapper.get('[data-testid="edit-requirement"]').trigger("click");
    await wrapper.get('[data-testid="submit-requirements-revision"]').trigger("submit");
    await flushPromises();

    expect(wrapper.getComponent(RequirementsTwinAlignment).props("refreshKey")).toBe(
      `${VERSION.content_hash}:1:0`,
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
      refreshKey: `${VERSION.content_hash}:0:0`,
    });
    expect(status).toHaveBeenCalledWith(PROJECT_ID, "access-token");
    expect(
      wrapper
        .get('[data-testid="requirements-flow"]')
        .element.firstElementChild?.getAttribute("data-testid"),
    ).toBe("requirements-twin-alignment");
    expect(readiness).toHaveBeenCalledTimes(1);

    await wrapper.get('[data-testid="requirements-twin-alignment-update"]').trigger("click");
    await flushPromises();

    expect(realign).toHaveBeenCalledWith(PROJECT_ID, "access-token");
    expect(readiness).toHaveBeenCalledTimes(2);
    expect(wrapper.text()).toContain("Version 2");
    expect(alignment.props("refreshKey")).toBe(`${realignedVersion.content_hash}:0:0`);
    expect(status).toHaveBeenCalledTimes(2);
    expect(wrapper.get('[data-testid="requirements-twin-alignment-done"]').text()).toContain(
      "Version 2 of the requirements is ready with the same content. Approve it again below.",
    );
    expect(wrapper.get('[data-testid="decision-primary"]').text()).toBe("Approve the requirements");
    expect(wrapper.get('[data-testid="decision-primary"]').attributes("disabled")).toBeUndefined();
    await expectAccessible(wrapper.element);
  });
});

describe("ProjectRequirementsFlow and the titles first", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.spyOn(requirementsAlignmentApi, "status").mockResolvedValue(ALIGNED);
  });

  afterEach(() => {
    document.body.innerHTML = "";
  });

  it.each([
    [
      "several things it must do and several it should do",
      "en",
      ["MUST", "MUST", "MUST", "SHOULD", "COULD"],
      "In short: 3 things the application must do and 2 it should do. The titles are below: open a row to read the detail or propose a change.",
    ],
    [
      "several things it must do and several it should do",
      "it",
      ["MUST", "MUST", "MUST", "SHOULD", "COULD"],
      "In breve: 3 cose che l'applicazione deve fare e 2 che dovrebbe fare. Qui sotto trovi i titoli: apri una riga per leggere il dettaglio o proporre una modifica.",
    ],
    [
      "one thing it must do and one it should do",
      "en",
      ["MUST", "SHOULD"],
      "In short: 1 thing the application must do and 1 it should do. The titles are below: open a row to read the detail or propose a change.",
    ],
    [
      "one thing it must do and one it should do",
      "it",
      ["MUST", "SHOULD"],
      "In breve: 1 cosa che l'applicazione deve fare e 1 che dovrebbe fare. Qui sotto trovi i titoli: apri una riga per leggere il dettaglio o proporre una modifica.",
    ],
    [
      "only things it must do",
      "en",
      ["MUST", "MUST"],
      "In short: 2 things the application must do. The titles are below: open a row to read the detail or propose a change.",
    ],
    [
      "only things it must do",
      "it",
      ["MUST", "MUST"],
      "In breve: 2 cose che l'applicazione deve fare. Qui sotto trovi i titoli: apri una riga per leggere il dettaglio o proporre una modifica.",
    ],
    [
      "a single thing it must do",
      "en",
      ["MUST"],
      "In short: 1 thing the application must do. The title is below: open the row to read the detail or propose a change.",
    ],
    [
      "a single thing it must do",
      "it",
      ["MUST"],
      "In breve: 1 cosa che l'applicazione deve fare. Qui sotto trovi il titolo: apri la riga per leggere il dettaglio o proporre una modifica.",
    ],
    [
      "only things it should do",
      "en",
      ["SHOULD", "WONT_FOR_NOW"],
      "In short: 2 things the application should do. The titles are below: open a row to read the detail or propose a change.",
    ],
    [
      "only things it should do",
      "it",
      ["SHOULD", "WONT_FOR_NOW"],
      "In breve: 2 cose che l'applicazione dovrebbe fare. Qui sotto trovi i titoli: apri una riga per leggere il dettaglio o proporre una modifica.",
    ],
    [
      "a single thing it should do",
      "en",
      ["COULD"],
      "In short: 1 thing the application should do. The title is below: open the row to read the detail or propose a change.",
    ],
    [
      "a single thing it should do",
      "it",
      ["COULD"],
      "In breve: 1 cosa che l'applicazione dovrebbe fare. Qui sotto trovi il titolo: apri la riga per leggere il dettaglio o proporre una modifica.",
    ],
  ] as const)(
    "opens the text with a digest of %s in %s",
    async (_case, locale, priorities, sentence) => {
      const wrapper = mountFlow(readyApi(null, prioritized(priorities)), true, { locale });
      await flushPromises();

      const text = wrapper.get('[data-testid="requirements-text-view"]');
      const digest = text.get('[data-testid="requirements-digest"]');
      expect(digest.text()).toBe(sentence);
      expect(text.element.firstElementChild?.contains(digest.element)).toBe(true);
      expect(
        wrapper
          .get('[data-testid="requirements-summary"]')
          .element.compareDocumentPosition(digest.element) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
      expect(wrapper.find('[data-testid="requirements-toggle-all"]').exists()).toBe(
        priorities.length > 1,
      );
    },
  );

  it("shows each requirement as a closed row with its code and title that opens on click", async () => {
    const wrapper = mountFlow(readyApi(null, RICH_VERSION), true, { attach: true, locale: "it" });
    await flushPromises();

    const row = rowOf(wrapper, "REQ-001");
    const toggle = row.get('[data-testid="requirement-toggle"]');
    const detail = row.get('[data-testid="requirement-detail"]');
    expect(toggle.element.tagName).toBe("BUTTON");
    expect(toggle.attributes("type")).toBe("button");
    expect(spokenText(toggle.element)).toBe("REQ-001 Create reservations");
    expect(toggle.attributes("aria-expanded")).toBe("false");
    expect(toggle.attributes("aria-controls")).toBe(detail.attributes("id"));
    expect(detail.isVisible()).toBe(false);
    expect(row.get("p").isVisible()).toBe(false);

    await toggle.trigger("click");

    expect(toggle.attributes("aria-expanded")).toBe("true");
    expect(detail.isVisible()).toBe(true);
    expect(detail.get("p").text()).toBe("The system must create reservations.");
    const meta = detail.get('[data-testid="requirement-meta"]');
    expect(meta.text()).toContain("Chiesto da");
    expect(meta.get('[data-testid="requirement-twin"]').text()).toBe("Receptionist Twin");
    expect(meta.text()).toContain("Verifica: AC-001");
    expect(detail.get('[data-testid="edit-requirement"]').text()).toBe("Proponi modifica");
    expect(expandedOf(wrapper)).toEqual(["true", "false"]);

    await toggle.trigger("click");

    expect(toggle.attributes("aria-expanded")).toBe("false");
    expect(detail.isVisible()).toBe(false);
    wrapper.unmount();
  });

  it.each([
    ["en", "Open every detail", "Close every detail"],
    ["it", "Apri tutti i dettagli", "Chiudi tutti i dettagli"],
  ] as const)("opens and closes every row at once in %s", async (locale, openAll, closeAll) => {
    const wrapper = mountFlow(readyApi(null, RICH_VERSION), true, { attach: true, locale });
    await flushPromises();

    const all = wrapper.get('[data-testid="requirements-toggle-all"]');
    const details = () =>
      wrapper.findAll('[data-testid="requirement-detail"]').map((detail) => detail.isVisible());
    expect(all.element.tagName).toBe("BUTTON");
    expect(all.attributes("type")).toBe("button");
    expect(all.text()).toBe(openAll);
    expect(all.attributes("aria-expanded")).toBe("false");
    expect(
      all.element.compareDocumentPosition(
        wrapper.get('[data-testid="requirements-groups"]').element,
      ) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    await all.trigger("click");

    expect(expandedOf(wrapper)).toEqual(["true", "true"]);
    expect(details()).toEqual([true, true]);
    expect(all.text()).toBe(closeAll);
    expect(all.attributes("aria-expanded")).toBe("true");

    await all.trigger("click");

    expect(expandedOf(wrapper)).toEqual(["false", "false"]);
    expect(details()).toEqual([false, false]);
    expect(all.text()).toBe(openAll);
    expect(all.attributes("aria-expanded")).toBe("false");

    await openRow(wrapper, "REQ-001");
    expect(all.text()).toBe(openAll);
    await openRow(wrapper, "REQ-002");
    expect(all.text()).toBe(closeAll);
    expect(all.attributes("aria-expanded")).toBe("true");
    wrapper.unmount();
  });

  it("opens the row of a requirement and the block of the checks that the diagram points to", async () => {
    const wrapper = mount(ProjectRequirementsFlow, {
      props: {
        projectId: PROJECT_ID,
        locale: "it",
        autoLoad: true,
        authorize,
        api: readyApi(null, RICH_VERSION),
      },
      global: { plugins: [createAppI18n("it")], stubs: { ProjectDiagramsView: true } },
      attachTo: document.body,
    });
    await flushPromises();

    await wrapper.get('[data-testid="artifact-view-diagram"]').trigger("click");
    wrapper.getComponent({ name: "ProjectDiagramsView" }).vm.$emit("select-node", "REQ-002");
    await flushPromises();

    const row = rowOf(wrapper, "REQ-002");
    const detail = row.get('[data-testid="requirement-detail"]');
    expect(wrapper.get('[data-testid="requirements-text-view"]').isVisible()).toBe(true);
    expect(expandedOf(wrapper)).toEqual(["false", "true"]);
    expect(detail.isVisible()).toBe(true);
    expect(detail.text()).toContain("The desk can use the app on a tablet.");
    expect(document.activeElement).toBe(row.element);
    expect(row.classes()).toContain("ring-petrol-on-night/60");
    const checks = wrapper.get('[data-testid="requirements-checks"]');
    expect(checks.attributes("open")).toBeUndefined();

    await wrapper.get('[data-testid="artifact-view-diagram"]').trigger("click");
    wrapper.getComponent({ name: "ProjectDiagramsView" }).vm.$emit("select-node", "AC-001");
    await flushPromises();

    const card = checks.get('[data-requirements-item="AC-001"]');
    expect(checks.attributes("open")).toBeDefined();
    expect(card.isVisible()).toBe(true);
    expect(document.activeElement).toBe(card.element);
    expect(card.classes()).toContain("ring-petrol-on-night/60");
    expect(expandedOf(wrapper)).toEqual(["false", "true"]);
    wrapper.unmount();
  });

  it("proposes a change from inside an open row and keeps the row open", async () => {
    const api = readyApi(null, RICH_VERSION);
    const wrapper = mountFlow(api, true, { attach: true, locale: "it" });
    await flushPromises();

    await openRow(wrapper, "REQ-001");
    const row = rowOf(wrapper, "REQ-001");
    await row.get('[data-testid="edit-requirement"]').trigger("click");

    const form = row.get('[data-testid="requirement-edit-form"]');
    expect(form.isVisible()).toBe(true);
    expect(row.find('[data-testid="edit-requirement"]').exists()).toBe(false);
    await form
      .get('[data-testid="requirement-statement"]')
      .setValue("The system must create guest reservations.");
    await form.get('[data-testid="submit-requirements-revision"]').trigger("submit");
    await flushPromises();

    expect(api.proposedSpecification?.requirements.map((item) => item.statement)).toEqual([
      "The system must create guest reservations.",
      "The desk can use the app on a tablet.",
    ]);
    expect(wrapper.get('[data-testid="requirements-pending-change"]').text()).toContain(
      "Prima · REQ-001",
    );
    expect(row.find('[data-testid="requirement-edit-form"]').exists()).toBe(false);
    expect(expandedOf(wrapper)).toEqual(["true", "false"]);
    expect(row.get('[data-testid="requirement-detail"]').isVisible()).toBe(true);
    expect(row.get('[data-testid="edit-requirement"]').text()).toBe("Proponi modifica");
    wrapper.unmount();
  });

  it("opens by itself the row of a requirement with a change waiting for a decision", async () => {
    const api = readyApi(PENDING_GATE, RICH_VERSION);
    api.diffs = [DIFF];
    const readiness = vi.spyOn(api, "readiness");
    const wrapper = mountFlow(api, true, { attach: true });
    await flushPromises();

    expect(wrapper.get('[data-testid="requirements-pending-change"]').text()).toContain(
      "Before · REQ-001",
    );
    expect(expandedOf(wrapper)).toEqual(["true", "false"]);
    const row = rowOf(wrapper, "REQ-001");
    expect(row.get('[data-testid="requirement-detail"]').isVisible()).toBe(true);

    await row.get('[data-testid="requirement-toggle"]').trigger("click");
    await wrapper.setProps({ upstream: "twins-1:APPROVED" });
    await wrapper.setProps({ upstream: "twins-2:APPROVED" });
    await flushPromises();

    expect(readiness).toHaveBeenCalledTimes(2);
    expect(wrapper.find('[data-testid="requirements-pending-change"]').exists()).toBe(true);
    expect(expandedOf(wrapper)).toEqual(["false", "false"]);
    wrapper.unmount();
  });

  it.each([
    [
      "en",
      "Acceptance criteria, risks and completion conditions (3)",
      "They serve whoever writes the code and the automatic checks of ut test.",
    ],
    [
      "it",
      "Criteri di verifica, rischi e condizioni di fine lavoro (3)",
      "Servono a chi scrive il codice e ai controlli automatici di ut test.",
    ],
  ] as const)(
    "keeps the criteria, the risks and the completion conditions in a collapsed block in %s",
    async (locale, summary, purpose) => {
      const wrapper = mountFlow(readyApi(null, RICH_VERSION), true, { attach: true, locale });
      await flushPromises();

      const checks = wrapper.get('[data-testid="requirements-checks"]');
      const cards = () =>
        wrapper.findAll('[data-testid="requirements-check"]').map((card) => card.isVisible());
      expect(checks.element.tagName).toBe("DETAILS");
      expect(checks.attributes("open")).toBeUndefined();
      expect(spokenText(checks.get("summary").element)).toBe(summary);
      expect(cards()).toEqual([false, false, false]);
      expect(
        wrapper
          .get('[data-testid="requirements-groups"]')
          .element.compareDocumentPosition(checks.element) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
      expect(
        checks.element.compareDocumentPosition(
          wrapper.get('[data-testid="requirements-stories"]').element,
        ) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();

      await checks.get("summary").trigger("click");
      await flushPromises();

      expect(checks.attributes("open")).toBeDefined();
      const content = checks.element.querySelector("summary + div");
      expect(content?.firstElementChild?.getAttribute("data-testid")).toBe(
        "requirements-checks-purpose",
      );
      const first = checks.get('[data-testid="requirements-checks-purpose"]');
      expect(first.text()).toBe(purpose);
      expect(first.findAll("code").map((item) => item.text())).toEqual(["ut test"]);
      expect(cards()).toEqual([true, true, true]);
      wrapper.unmount();
    },
  );

  it("has no axe violations on the text with every row closed and with one row open", async () => {
    const wrapper = mountFlow(readyApi(PENDING_GATE, RICH_VERSION), true, {
      attach: true,
      locale: "it",
    });
    await flushPromises();

    const text = wrapper.get('[data-testid="requirements-text-view"]');
    expect(expandedOf(wrapper)).toEqual(["false", "false"]);
    await expectAccessible(text.element);

    await openRow(wrapper, "REQ-002");

    expect(expandedOf(wrapper)).toEqual(["false", "true"]);
    await expectAccessible(text.element);
    wrapper.unmount();
  });
});

describe("ProjectRequirementsFlow and a change asked in words", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.spyOn(requirementsAlignmentApi, "status").mockResolvedValue(ALIGNED);
  });

  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("records the request, asks the analyst once and shows the new version under the request", async () => {
    const api = readyApi(PENDING_GATE);
    api.changeOutcome = "proposed";
    const wrapper = mountFlow(api, true, { attach: true, locale: "it" });
    await flushPromises();

    await wrapper.get('[data-testid="decision-secondary"]').trigger("click");
    expect(wrapper.get('[data-testid="decision-note"]').attributes("placeholder")).toBe(
      "Scrivi che cosa cambiare: l'analista riscrive i requisiti e decidi tu se applicare la nuova versione.",
    );
    await wrapper
      .get('[data-testid="decision-note"]')
      .setValue("  Aggiungi la ricerca per nome.  ");
    await wrapper.get('[data-testid="decision-send"]').trigger("click");
    await flushPromises();

    expect(api.calls).toEqual(["decide:REQUEST_REVISION", "request-change"]);
    expect(api.decideGateReasons).toEqual(["Aggiungi la ricerca per nome."]);
    expect(api.changeRequests).toEqual(["Aggiungi la ricerca per nome."]);
    const change = wrapper.get('[data-testid="requirements-pending-change"]');
    expect(change.attributes("data-origin")).toBe("request");
    const request = change.get('[data-testid="requirements-change-request"]');
    expect(request.get("p").text()).toBe("La tua richiesta");
    expect(request.get("blockquote").text()).toBe("Aggiungi la ricerca per nome.");
    expect(change.text()).not.toContain("«");
    expect(change.text().indexOf("Aggiungi la ricerca per nome.")).toBeLessThan(
      change.text().indexOf("Prima · REQ-001"),
    );
    const apply = change.get('[data-testid="approve-requirements-diff"]');
    expect(apply.text()).toBe("Applica la nuova versione");
    expect(apply.attributes("data-variant")).toBe("pill");
    const discard = change.get('[data-testid="reject-requirements-diff"]');
    expect(discard.text()).toBe("Scarta");
    expect(discard.attributes("data-variant")).toBe("quiet");
    expect(wrapper.find('[data-testid="requirements-change"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="requirements-gate-closed"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="decision-note"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="decision-bar"]').text()).toContain(
      "La nuova versione aspetta qui sopra: applicala, poi approva qui i requisiti.",
    );
    expect(wrapper.get('[data-testid="decision-primary"]').attributes("disabled")).toBeDefined();
    wrapper.unmount();
  });

  it("shows the analyst at work and keeps the request and the approval closed while it writes", async () => {
    const api = readyApi(PENDING_GATE);
    api.changeOutcome = "proposed";
    let release: () => void = () => undefined;
    api.changeGate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const wrapper = mountFlow(api, true, { attach: true });
    await flushPromises();

    await askFor(wrapper, "Add the search by name.");

    const running = wrapper.get('[data-testid="requirements-change"]');
    const analyst = running.get('[data-testid="agent-message"]');
    expect(analyst.text()).toContain("Needs analyst");
    expect(analyst.get('[role="status"]').text()).toBe(
      "I am writing the requirements again with your request.",
    );
    expect(running.get('[data-testid="requirements-change-request"] blockquote').text()).toBe(
      "Add the search by name.",
    );
    const bar = wrapper.get('[data-testid="decision-bar"]');
    expect(bar.attributes("aria-busy")).toBe("true");
    expect(bar.text()).toContain(
      "The analyst is writing the requirements again: when the new version arrives, you decide whether to apply it.",
    );
    expect(wrapper.get('[data-testid="decision-note"]').attributes("disabled")).toBeDefined();
    expect(noteOf(wrapper)).toBe("Add the search by name.");
    expect(wrapper.get('[data-testid="decision-send"]').attributes("disabled")).toBeDefined();
    expect(wrapper.find('[data-testid="decision-primary"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="requirements-gate-closed"]').exists()).toBe(false);

    await wrapper.get('[data-testid="decision-send"]').trigger("click");
    release();
    await flushPromises();

    expect(api.changeRequests).toEqual(["Add the search by name."]);
    expect(wrapper.find('[data-testid="requirements-change"]').exists()).toBe(false);
    expect(
      wrapper.get('[data-testid="requirements-pending-change"]').attributes("data-origin"),
    ).toBe("request");
    wrapper.unmount();
  });

  it("applies the new version with one gesture and then offers the approval as today", async () => {
    const api = revisionApi("Add the search by name.");
    api.diffs = [DIFF];
    api.nextVersion = VERSION_2;
    const decide = vi.spyOn(api, "decideRevision");
    const wrapper = mountFlow(api, true, { attach: true });
    await flushPromises();

    const change = wrapper.get('[data-testid="requirements-pending-change"]');
    expect(change.get('[data-testid="requirements-change-request"] blockquote').text()).toBe(
      "Add the search by name.",
    );
    expect(wrapper.get('[data-testid="decision-primary"]').attributes("disabled")).toBeDefined();
    expect(expandedOf(wrapper)).toEqual(["true"]);

    await change.get('[data-testid="approve-requirements-diff"]').trigger("click");
    await flushPromises();

    expect(decide).toHaveBeenCalledOnce();
    expect(decide).toHaveBeenCalledWith(
      PROJECT_ID,
      DIFF_ID,
      { decision: "APPROVE", reason: null },
      "access-token",
    );
    expect(wrapper.find('[data-testid="requirements-pending-change"]').exists()).toBe(false);
    const detail = rowOf(wrapper, "REQ-001").get('[data-testid="requirement-detail"]');
    expect(detail.isVisible()).toBe(true);
    expect(detail.text()).toContain("The system must create guest reservations.");
    const primary = wrapper.get('[data-testid="decision-primary"]');
    expect(primary.text()).toBe("Approve the requirements");
    expect(primary.attributes("disabled")).toBeUndefined();
    expect(wrapper.get('[data-testid="step-technical-details"]').text()).toContain(
      "Version 2 · waiting for your decision",
    );
    wrapper.unmount();
  });

  it("discards the new version with a reason and lets the person ask the analyst again", async () => {
    const api = revisionApi("Add the search by name.");
    api.diffs = [DIFF];
    api.changeOutcome = "proposed";
    const decide = vi.spyOn(api, "decideRevision");
    const wrapper = mountFlow(api, true, { attach: true });
    await flushPromises();

    const change = wrapper.get('[data-testid="requirements-pending-change"]');
    expect(
      change.get('[data-testid="reject-requirements-diff"]').attributes("disabled"),
    ).toBeDefined();
    await change.get("textarea").setValue("It forgets the phone number.");
    await change.get('[data-testid="reject-requirements-diff"]').trigger("click");
    await flushPromises();

    expect(decide).toHaveBeenCalledWith(
      PROJECT_ID,
      DIFF_ID,
      { decision: "REJECT", reason: "It forgets the phone number." },
      "access-token",
    );
    expect(wrapper.find('[data-testid="requirements-pending-change"]').exists()).toBe(false);
    const closed = wrapper.get('[data-testid="requirements-gate-closed"]');
    expect(closed.get('[data-testid="requirements-gate-note"] blockquote').text()).toBe(
      "Add the search by name.",
    );
    expect(wrapper.get('[data-testid="decision-bar"]').text()).toContain(
      "To approve, you need a new version: ask the analyst for one or propose the change on a requirement.",
    );
    expect(wrapper.get('[data-testid="decision-primary"]').attributes("disabled")).toBeDefined();
    await wrapper.get('[data-testid="step-technical-details-toggle"]').trigger("click");
    const decided = wrapper.get('[data-testid="requirements-decided-note"]');
    expect(decided.element.tagName).toBe("BLOCKQUOTE");
    expect(decided.text()).toBe("It forgets the phone number.");
    expect(wrapper.get('[data-testid="step-technical-details-content"]').text()).not.toContain("«");

    await askFor(wrapper, "Add the search by name and by phone.");

    expect(api.calls).toEqual(["request-change"]);
    expect(api.changeRequests).toEqual(["Add the search by name and by phone."]);
    expect(
      wrapper
        .get(
          '[data-testid="requirements-pending-change"] [data-testid="requirements-change-request"] blockquote',
        )
        .text(),
    ).toBe("Add the search by name and by phone.");
    wrapper.unmount();
  });

  it("says that a new version is already waiting and keeps the request without recording it", async () => {
    const api = readyApi(PENDING_GATE);
    api.diffs = [DIFF];
    api.changeOutcome = "proposed";
    const wrapper = mountFlow(api, true, { attach: true, locale: "it" });
    await flushPromises();

    await askFor(wrapper, "Aggiungi la ricerca per nome.");

    expect(api.calls).toEqual([]);
    const failure = wrapper.get('[data-testid="requirements-change-failure"]');
    expect(failure.attributes("role")).toBe("alert");
    expect(failure.attributes("data-code")).toBe("REQUIREMENTS_REVISION_PENDING");
    expect(failure.text()).toBe(
      "C'è già una nuova versione da decidere: applicala o scartala prima di chiedere un'altra modifica.",
    );
    expect(noteOf(wrapper)).toBe("Aggiungi la ricerca per nome.");

    await wrapper.get('[data-testid="approve-requirements-diff"]').trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-testid="requirements-change-failure"]').exists()).toBe(false);
    expect(noteOf(wrapper)).toBe("Aggiungi la ricerca per nome.");
    wrapper.unmount();
  });

  it("says it and shows the waiting version when the server finds one", async () => {
    const api = readyApi(PENDING_GATE);
    const waiting = { ...DIFF, created_at: "2026-08-18T11:00:00Z" };
    vi.spyOn(api, "requestChange").mockImplementation(async (_projectId, request) => {
      api.calls.push("request-change");
      api.changeRequests.push(request);
      api.diffs = [waiting];
      throw refusal("REQUIREMENTS_REVISION_PENDING", 409);
    });
    const wrapper = mountFlow(api, true, { attach: true });
    await flushPromises();

    await askFor(wrapper, "Add the search by name.");

    expect(api.calls).toEqual(["decide:REQUEST_REVISION", "request-change"]);
    expect(wrapper.get('[data-testid="requirements-change-failure"]').text()).toBe(
      "A new version is already waiting for your decision: apply it or discard it before you ask for another change.",
    );
    expect(
      wrapper.get('[data-testid="requirements-pending-change"]').attributes("data-origin"),
    ).toBe("edit");
    expect(noteOf(wrapper)).toBe("Add the search by name.");
    expect(wrapper.find('[data-testid="requirements-error"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("says that the analyst changed nothing and sends the request again when asked", async () => {
    const api = readyApi(PENDING_GATE);
    api.changeOutcome = refusal("REQUIREMENTS_UNCHANGED", 409);
    const wrapper = mountFlow(api, true, { attach: true });
    await flushPromises();

    await askFor(wrapper, "Add the search by name.");

    expect(wrapper.get('[data-testid="requirements-change-failure"]').text()).toBe(
      "The analyst found nothing to change with this request. Try to describe the change in another way.",
    );
    expect(noteOf(wrapper)).toBe("Add the search by name.");
    expect(wrapper.text()).not.toContain("REQUIREMENTS_UNCHANGED");

    api.changeOutcome = "proposed";
    await wrapper
      .get('[data-testid="decision-note"]')
      .setValue("Add a search field for the name of the guest.");
    await wrapper.get('[data-testid="decision-send"]').trigger("click");
    await flushPromises();

    expect(api.calls).toEqual(["decide:REQUEST_REVISION", "request-change", "request-change"]);
    expect(api.changeRequests).toEqual([
      "Add the search by name.",
      "Add a search field for the name of the guest.",
    ]);
    expect(wrapper.find('[data-testid="requirements-change-failure"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="requirements-change-request"] blockquote').text()).toBe(
      "Add a search field for the name of the guest.",
    );
    wrapper.unmount();
  });

  it.each([
    [
      "the context changed",
      refusal("REQUIREMENTS_CONTEXT_CHANGED", 409),
      "The generation of the requirements did not succeed.",
      "The request could not be completed. You can try again.",
    ],
    [
      "the model did not answer",
      refusal("TIMEOUT", 503),
      "The generation of the requirements did not succeed.",
      "Generation timed out. Check model status before retrying.",
    ],
    [
      "the generation stopped",
      refusal("GENERATION_JOB_NOT_FOUND", 404),
      "The generation of the requirements stopped, perhaps because the Studio was restarted.",
      "It does not start again on its own: you can start it again whenever you want.",
    ],
  ])("uses the sentences of the requirements when %s", async (_case, error, title, text) => {
    const api = readyApi(PENDING_GATE);
    api.changeOutcome = error;
    const wrapper = mountFlow(api, true, { attach: true });
    await flushPromises();

    await askFor(wrapper, "Add the search by name.");

    const failure = wrapper.get('[data-testid="generation-job-failure"]');
    expect(failure.text()).toContain(title);
    expect(failure.text()).toContain(text);
    expect(noteOf(wrapper)).toBe("Add the search by name.");
    expect(wrapper.find('[data-testid="requirements-error"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain(error.message);

    await failure.get('[data-testid="generation-job-dismiss"]').trigger("click");

    expect(wrapper.find('[data-testid="requirements-change"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("behaves as today when the server cannot write the requirements again", async () => {
    const api = readyApi(PENDING_GATE);
    api.nextVersion = VERSION_2;
    const wrapper = mountFlow(api, true, { attach: true });
    await flushPromises();

    await askFor(wrapper, "Add the search by name.");

    expect(api.calls).toEqual(["decide:REQUEST_REVISION", "request-change"]);
    const closed = wrapper.get('[data-testid="requirements-gate-closed"]');
    expect(closed.text()).toContain("You asked for changes");
    expect(closed.text()).toContain(
      "To change them, propose the change on each requirement: the new version comes back here for your approval.",
    );
    expect(wrapper.find('[data-testid="decision-bar"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="requirements-change"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="requirements-error"]').exists()).toBe(false);

    await openRow(wrapper, "REQ-001");
    await wrapper.get('[data-testid="edit-requirement"]').trigger("click");
    await wrapper.get('[data-testid="submit-requirements-revision"]').trigger("submit");
    await flushPromises();
    await wrapper.get('[data-testid="approve-requirements-diff"]').trigger("click");
    await flushPromises();
    await wrapper.get('[data-testid="decision-secondary"]').trigger("click");

    expect(wrapper.get('[data-testid="decision-note"]').attributes("placeholder")).toBe(
      "Write what is wrong: the request is recorded with your note. Then you can propose the change on the requirements.",
    );
    wrapper.unmount();
  });

  it("has no axe violations while the analyst writes and with the new version to decide", async () => {
    const api = readyApi(PENDING_GATE);
    api.changeOutcome = "proposed";
    let release: () => void = () => undefined;
    api.changeGate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const wrapper = mountFlow(api, true, { attach: true });
    await flushPromises();
    await askFor(wrapper, "Add the search by name.");

    await expectAccessible(wrapper.element);

    release();
    await flushPromises();

    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });
});

describe("ProjectRequirementsFlow in sections mode", () => {
  const APPROVED_GATE: HumanGatePayload = {
    ...PENDING_GATE,
    status: "APPROVED",
    event_sequence: 2,
  };

  const CHECKED_VERSION: RequirementsSpecificationVersionPayload = {
    ...VERSION,
    specification: {
      ...RICH_SPECIFICATION,
      requirements: [RICH_SPECIFICATION.requirements[0]!],
    },
  };

  function approvedApi(): FakeApi {
    const api = new FakeApi();
    api.readinessResult = {
      status: "READY_FOR_DESIGN_EXPLORATION",
      version: VERSION,
      gate: APPROVED_GATE,
      approved_current_specification: true,
    };
    api.historyResult = [VERSION];
    return api;
  }

  beforeEach(() => {
    setActivePinia(createPinia());
    vi.spyOn(requirementsAlignmentApi, "status").mockResolvedValue(ALIGNED);
  });

  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("offers no change request on an approved specification outside sections mode", async () => {
    const wrapper = mountFlow(approvedApi(), true, { attach: true });
    await flushPromises();

    expect(wrapper.get('[data-testid="requirements-readiness"]').text()).toBe(
      "Requirements approved by you. Next: Design & Evaluation.",
    );
    expect(wrapper.find('[data-testid="decision-bar"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="decision-secondary"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it.each([
    [
      "en",
      "You approved these requirements. You can still ask for a change in words: the new version comes back here for your approval.",
      "Ask for changes",
      "Approve the requirements",
    ],
    [
      "it",
      "Hai approvato questi requisiti. Puoi ancora chiedere una modifica a parole: la nuova versione torna qui per la tua approvazione.",
      "Chiedi modifiche",
      "Approva i requisiti",
    ],
  ] as const)(
    "offers in %s the change in words on an approved specification in sections mode",
    async (locale, sentence, secondary, primary) => {
      const wrapper = mountFlow(approvedApi(), true, { attach: true, locale, sectionsMode: true });
      await flushPromises();

      const bar = wrapper.get('[data-testid="decision-bar"]');
      expect(bar.text()).toContain(sentence);
      expect(bar.get('[data-testid="decision-secondary"]').text()).toBe(secondary);
      expect(bar.get('[data-testid="decision-primary"]').text()).toBe(primary);
      expect(bar.get('[data-testid="decision-primary"]').attributes("disabled")).toBeDefined();
      expect(wrapper.find('[data-testid="requirements-readiness"]').exists()).toBe(true);
      await expectAccessible(wrapper.element);
      wrapper.unmount();
    },
  );

  it("asks the analyst for the change without recording a request and approves the new version with one gesture", async () => {
    const api = approvedApi();
    api.changeOutcome = "proposed";
    api.nextVersion = VERSION_2;
    const decideRevision = api.decideRevision.bind(api);
    vi.spyOn(api, "decideRevision").mockImplementation(async (...args) => {
      const result = await decideRevision(...args);
      api.readinessResult = {
        ...api.readinessResult,
        status: "REQUIREMENTS_APPROVAL_REQUIRED",
        approved_current_specification: false,
      };
      return result;
    });
    const wrapper = mountFlow(api, true, { attach: true, sectionsMode: true });
    await flushPromises();

    await askFor(wrapper, "Add the search by name.");

    expect(api.calls).toEqual(["request-change"]);
    expect(api.changeRequests).toEqual(["Add the search by name."]);
    expect(api.decideGateCalls).toEqual([]);
    const change = wrapper.get('[data-testid="requirements-pending-change"]');
    expect(change.get('[data-testid="requirements-change-request"] blockquote').text()).toBe(
      "Add the search by name.",
    );
    expect(wrapper.get('[data-testid="decision-bar"]').text()).toContain(
      "The new version is waiting above: apply it, then approve the requirements here.",
    );
    expect(wrapper.emitted("sections-changed")).toHaveLength(1);

    await change.get('[data-testid="approve-requirements-diff"]').trigger("click");
    await flushPromises();

    expect(wrapper.emitted("sections-changed")).toHaveLength(2);
    const primary = wrapper.get('[data-testid="decision-primary"]');
    expect(primary.text()).toBe("Approve the requirements");
    expect(primary.attributes("disabled")).toBeUndefined();

    await primary.trigger("click");
    await flushPromises();

    expect(api.calls).toEqual(["request-change", "submit", "decide:APPROVE"]);
    expect(wrapper.find('[data-testid="requirements-readiness"]').exists()).toBe(true);
    expect(wrapper.emitted("sections-changed")).toHaveLength(3);
    wrapper.unmount();
  });

  it.each([
    [
      "en",
      false,
      "When you approve, the designer prepares the design alternatives and the twins try them.",
    ],
    [
      "en",
      true,
      "When you approve, the sections that follow are updated with one gesture, without losing their content.",
    ],
    ["it", false, "Approvando, il designer prepara le alternative di design e i twin le provano."],
    [
      "it",
      true,
      "Approvando, le sezioni che seguono si aggiornano con un gesto, senza perdere i contenuti.",
    ],
  ] as const)(
    "says in %s what follows the approval, in sections mode %s",
    async (locale, sectionsMode, sentence) => {
      const wrapper = mountFlow(readyApi(PENDING_GATE, CHECKED_VERSION), true, {
        locale,
        sectionsMode,
      });
      await flushPromises();

      expect(wrapper.get('[data-testid="decision-bar"]').text()).toContain(sentence);
      wrapper.unmount();
    },
  );

  it.each([
    ["en", "Perspectives", /\bTeam\b/],
    ["it", "Prospettive", /Squadra/],
  ] as const)(
    "names in %s the perspectives the requirements follow in the technical details",
    async (locale, label, old) => {
      const wrapper = mountFlow(readyApi(PENDING_GATE), true, { locale });
      await flushPromises();

      await wrapper.get('[data-testid="step-technical-details-toggle"]').trigger("click");
      const content = wrapper.get('[data-testid="step-technical-details-content"]');
      expect(content.findAll("dt").map((item) => item.text())).toContain(label);
      expect(content.text()).not.toMatch(old);
      wrapper.unmount();
    },
  );

  it.each([
    ["en", "The Definition could not be loaded."],
    ["it", "Non è stato possibile caricare la Definizione."],
  ] as const)("says in %s that the Definition could not be loaded", async (locale, sentence) => {
    const api = new FakeApi();
    vi.spyOn(api, "readiness").mockRejectedValue("offline");
    const wrapper = mountFlow(api, true, { locale });
    await flushPromises();

    expect(wrapper.get('[data-testid="requirements-error"]').text()).toContain(sentence);
    wrapper.unmount();
  });
});

describe("ProjectRequirementsFlow and requirements still being written", () => {
  function requirementsJob(overrides: Partial<GenerationRequestJob> = {}): GenerationRequestJob {
    return {
      job_id: "00000000-0000-4000-8000-0000000009cc",
      kind: "REQUEST",
      operation: "REQUIREMENTS_PROPOSAL",
      status: "RUNNING",
      stage: "GENERATING",
      attempt: 1,
      started_at: NOW,
      finished_at: null,
      alternative_id: null,
      failure: null,
      response: null,
      ...overrides,
    };
  }

  beforeEach(() => {
    setActivePinia(createPinia());
    vi.spyOn(requirementsAlignmentApi, "status").mockResolvedValue(ALIGNED);
    clearFollowedGenerations();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    clearFollowedGenerations();
    document.body.innerHTML = "";
  });

  it("waits for the requirements of a generation started before a reload", async () => {
    const api = new FakeApi();
    const generate = vi.spyOn(api, "generate");
    vi.spyOn(generationJobsApi, "list").mockResolvedValue([requirementsJob()]);
    vi.spyOn(generationJobsApi, "job")
      .mockResolvedValueOnce(requirementsJob())
      .mockImplementationOnce(async () => {
        api.readinessResult = {
          status: "REQUIREMENTS_APPROVAL_REQUIRED",
          version: VERSION,
          gate: null,
          approved_current_specification: false,
        };
        api.historyResult = [VERSION];
        return requirementsJob({
          status: "SUCCEEDED",
          stage: null,
          finished_at: NOW,
          response: { status_code: 201, body: { status: "CREATED" } },
        });
      });
    const wrapper = mountFlow(api, false, { locale: "it" });
    await vi.advanceTimersByTimeAsync(50);

    const notice = wrapper.get('[data-testid="generation-job-notice"]');
    expect(notice.text()).toContain("Lo Studio sta generando i requisiti.");
    expect(notice.text()).toContain("Puoi lasciare questa pagina e tornare più tardi");
    const button = wrapper.get('[data-testid="generate-requirements"]');
    expect(button.attributes("disabled")).toBeDefined();
    await button.trigger("click");

    await vi.advanceTimersByTimeAsync(4000);

    expect(wrapper.find('[data-testid="generation-job-notice"]').exists()).toBe(false);
    expect(wrapper.text()).toContain("REQ-001");
    expect(generate).not.toHaveBeenCalled();
  });

  it("says that the generation stopped and lets the owner start it again", async () => {
    const api = new FakeApi();
    vi.spyOn(generationJobsApi, "list").mockResolvedValue([requirementsJob()]);
    vi.spyOn(generationJobsApi, "job").mockResolvedValue(
      requirementsJob({
        status: "FAILED",
        stage: null,
        failure: { code: "GENERATION_JOB_CANCELLED", reasons: [] },
      }),
    );
    const readiness = vi.spyOn(api, "readiness");
    const wrapper = mountFlow(api);
    await vi.advanceTimersByTimeAsync(2050);

    const failure = wrapper.get('[data-testid="generation-job-failure"]');
    expect(failure.attributes("data-lost")).toBe("true");
    expect(failure.text()).toContain("The generation of the requirements stopped");
    expect(readiness).toHaveBeenCalled();
    const button = wrapper.get('[data-testid="generate-requirements"]');
    expect(button.attributes("disabled")).toBeUndefined();
    expect(wrapper.find('[data-testid="requirements-error"]').exists()).toBe(false);
  });

  it("resumes after a reload the new version being written and sends nothing again", async () => {
    const api = revisionApi("Aggiungi la ricerca per nome.");
    const requestChange = vi.spyOn(api, "requestChange");
    const decideGate = vi.spyOn(api, "decideGate");
    const running = requirementsJob({ operation: "REQUIREMENTS_CHANGE" });
    vi.spyOn(generationJobsApi, "list").mockResolvedValue([running]);
    vi.spyOn(generationJobsApi, "job")
      .mockResolvedValueOnce(running)
      .mockImplementationOnce(async () => {
        api.diffs = [DIFF];
        return requirementsJob({
          operation: "REQUIREMENTS_CHANGE",
          status: "SUCCEEDED",
          stage: null,
          finished_at: NOW,
          response: { status_code: 201, body: CHANGE_PROPOSED },
        });
      });
    const wrapper = mountFlow(api, true, { locale: "it" });
    await vi.advanceTimersByTimeAsync(50);

    const notice = wrapper.get('[data-testid="generation-job-notice"]');
    expect(notice.attributes("data-operation")).toBe("REQUIREMENTS_CHANGE");
    expect(notice.text()).toContain("Analista delle esigenze");
    expect(notice.get('[role="status"]').text()).toBe(
      "Sto riscrivendo i requisiti con la tua richiesta.",
    );
    expect(notice.text()).toContain("Puoi lasciare questa pagina e tornare più tardi");
    expect(notice.get('[data-testid="requirements-change-request"] blockquote').text()).toBe(
      "Aggiungi la ricerca per nome.",
    );
    expect(wrapper.get('[data-testid="decision-bar"]').attributes("aria-busy")).toBe("true");
    expect(wrapper.get('[data-testid="decision-primary"]').attributes("disabled")).toBeDefined();
    expect(wrapper.get('[data-testid="decision-secondary"]').attributes("disabled")).toBeDefined();
    expect(wrapper.find('[data-testid="requirements-gate-closed"]').exists()).toBe(false);

    await vi.advanceTimersByTimeAsync(4000);

    expect(wrapper.find('[data-testid="generation-job-notice"]').exists()).toBe(false);
    const change = wrapper.get('[data-testid="requirements-pending-change"]');
    expect(change.get('[data-testid="requirements-change-request"] blockquote').text()).toBe(
      "Aggiungi la ricerca per nome.",
    );
    expect(change.get('[data-testid="approve-requirements-diff"]').text()).toBe(
      "Applica la nuova versione",
    );
    expect(requestChange).not.toHaveBeenCalled();
    expect(decideGate).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("follows its own request as a background job while the analyst speaks", async () => {
    const api = readyApi(PENDING_GATE);
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      const posted = init?.method === "POST";

      if (!posted) {
        api.diffs = [DIFF];
      }

      const job = posted
        ? requirementsJob({ operation: "REQUIREMENTS_CHANGE" })
        : requirementsJob({
            operation: "REQUIREMENTS_CHANGE",
            status: "SUCCEEDED",
            stage: null,
            finished_at: NOW,
            response: { status_code: 201, body: CHANGE_PROPOSED },
          });

      return new Response(JSON.stringify(job), {
        status: posted ? 202 : 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    const client = createRequirementsApi({ fetchImpl: fetchMock });
    vi.spyOn(api, "requestChange").mockImplementation((projectId, request) => {
      api.calls.push("request-change");
      api.changeRequests.push(request);
      return client.requestChange(projectId, request, "access-token");
    });
    vi.spyOn(generationJobsApi, "list").mockResolvedValue([]);
    const wrapper = mountFlow(api, true, { attach: true });
    await vi.advanceTimersByTimeAsync(50);

    await wrapper.get('[data-testid="decision-secondary"]').trigger("click");
    await wrapper.get('[data-testid="decision-note"]').setValue("Add the search by name.");
    await wrapper.get('[data-testid="decision-send"]').trigger("click");
    await vi.advanceTimersByTimeAsync(50);

    const notice = wrapper.get('[data-testid="generation-job-notice"]');
    expect(notice.attributes("data-operation")).toBe("REQUIREMENTS_CHANGE");
    expect(notice.get('[role="status"]').text()).toBe(
      "I am writing the requirements again with your request.",
    );
    expect(notice.get('[data-testid="generation-job-since"]').text()).toMatch(/^Started at .+\.$/);
    expect(notice.get('[data-testid="requirements-change-request"] blockquote').text()).toBe(
      "Add the search by name.",
    );
    expect(wrapper.get('[data-testid="decision-note"]').attributes("disabled")).toBeDefined();
    expect(wrapper.get('[data-testid="decision-send"]').attributes("disabled")).toBeDefined();

    await vi.advanceTimersByTimeAsync(2000);

    const posts = fetchMock.mock.calls.filter(([, init]) => init?.method === "POST");
    expect(posts).toHaveLength(1);
    expect(posts[0]?.[0]).toBe(`/api/v1/projects/${PROJECT_ID}/requirements/change-requests`);
    expect(api.calls).toEqual(["decide:REQUEST_REVISION", "request-change"]);
    expect(wrapper.find('[data-testid="generation-job-notice"]').exists()).toBe(false);
    expect(
      wrapper.get('[data-testid="requirements-pending-change"]').attributes("data-origin"),
    ).toBe("request");
    wrapper.unmount();
  });
});

describe("ProjectRequirementsFlow and a refused proposal", () => {
  const NO_ANALYST = { code: "PROPOSAL_REJECTED", proposal_issue: "REQUIREMENTS_ANALYST_REQUIRED" };
  const FEW_FACTS = { code: "PROPOSAL_REJECTED", proposal_issue: "GROUNDED_INPUT_REQUIRED" };
  const NO_REASON = { code: "PROPOSAL_REJECTED" };
  const ANALYST_MISSING = {
    en: "The Product perspective is missing: open Perspectives and prepare them again.",
    it: "Manca la prospettiva Prodotto: apri Prospettive e preparale di nuovo.",
  };
  const FACTS_MISSING = {
    en: "The approved steps do not give the model enough facts for this proposal. Add details to the brief or to the earlier steps, then try again.",
    it: "I passi approvati non danno al modello abbastanza informazioni per questa proposta. Aggiungi dettagli al brief o ai passi precedenti, poi riprova.",
  };
  const NOT_PREPARED = {
    en: "The model could not prepare this proposal from the approved steps. Your project is unchanged. You can try again.",
    it: "Il modello non è riuscito a preparare questa proposta a partire dai passi approvati. Il progetto è invariato. Puoi riprovare.",
  };
  const NOT_SUCCEEDED = {
    en: "The generation of the requirements did not succeed.",
    it: "La generazione dei requisiti non è riuscita.",
  };
  const CHANGE = "Add the search by name.";

  function refusedJob(
    operation: GenerationRequestJob["operation"],
    detail: Record<string, string> | null,
  ): GenerationRequestJob {
    return {
      job_id: "00000000-0000-4000-8000-0000000009cd",
      kind: "REQUEST",
      operation,
      status: detail === null ? "RUNNING" : "FAILED",
      stage: detail === null ? "GENERATING" : null,
      attempt: 1,
      started_at: NOW,
      finished_at: detail === null ? null : NOW,
      alternative_id: null,
      failure: null,
      response: detail === null ? null : { status_code: 409, body: { detail } },
    };
  }

  function refusing(
    operation: GenerationRequestJob["operation"],
    detail: Record<string, string>,
    background: boolean,
  ) {
    return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      if (!background) {
        return new Response(JSON.stringify({ detail }), { status: 409 });
      }
      const posted = init?.method === "POST";
      return new Response(JSON.stringify(refusedJob(operation, posted ? null : detail)), {
        status: posted ? 202 : 200,
      });
    });
  }

  async function proposeRefused(
    detail: Record<string, string>,
    background: boolean,
    locale: "en" | "it",
  ) {
    const api = new FakeApi();
    const fetchImpl = refusing("REQUIREMENTS_PROPOSAL", detail, background);
    const real = createRequirementsApi({ fetchImpl });
    vi.spyOn(api, "generate").mockImplementation(((projectId: string, token: string) =>
      real.generate(projectId, token)) as unknown as FakeApi["generate"]);
    const wrapper = mountFlow(api, false, { locale });
    await vi.advanceTimersByTimeAsync(50);

    await wrapper.get('[data-testid="generate-requirements"]').trigger("click");
    await vi.advanceTimersByTimeAsync(2050);

    expect(fetchImpl.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
    expect(wrapper.find('[data-testid="requirements-empty"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="generation-job-notice"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="generation-job-failure"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("PROPOSAL_REJECTED");
    return wrapper;
  }

  async function changeRefused(
    detail: Record<string, string>,
    background: boolean,
    locale: "en" | "it",
  ) {
    const api = readyApi(PENDING_GATE);
    const real = createRequirementsApi({
      fetchImpl: refusing("REQUIREMENTS_CHANGE", detail, background),
    });
    vi.spyOn(api, "requestChange").mockImplementation((projectId, request) => {
      api.calls.push("request-change");
      api.changeRequests.push(request);
      return real.requestChange(projectId, request, "access-token");
    });
    const wrapper = mountFlow(api, true, { locale, attach: true });
    await vi.advanceTimersByTimeAsync(50);

    await wrapper.get('[data-testid="decision-secondary"]').trigger("click");
    await wrapper.get('[data-testid="decision-note"]').setValue(CHANGE);
    await wrapper.get('[data-testid="decision-send"]').trigger("click");
    await vi.advanceTimersByTimeAsync(2050);

    expect(api.calls).toEqual(["decide:REQUEST_REVISION", "request-change"]);
    expect(api.changeRequests).toEqual([CHANGE]);
    expect(noteOf(wrapper)).toBe(CHANGE);
    expect(wrapper.find('[data-testid="requirements-error"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("PROPOSAL_REJECTED");
    return { wrapper, failure: wrapper.get('[data-testid="generation-job-failure"]') };
  }

  beforeEach(() => {
    setActivePinia(createPinia());
    vi.spyOn(requirementsAlignmentApi, "status").mockResolvedValue(ALIGNED);
    clearFollowedGenerations();
    vi.useFakeTimers();
    vi.spyOn(generationJobsApi, "list").mockResolvedValue([]);
  });

  afterEach(() => {
    vi.useRealTimers();
    clearFollowedGenerations();
    document.body.innerHTML = "";
  });

  it.each([
    { how: "at once", background: false, locale: "en" },
    { how: "at once", background: false, locale: "it" },
    { how: "through a job", background: true, locale: "en" },
    { how: "through a job", background: true, locale: "it" },
  ] as const)(
    "says that the Product perspective is missing when the first proposal is refused $how ($locale)",
    async ({ background, locale }) => {
      const wrapper = await proposeRefused(NO_ANALYST, background, locale);

      expect(wrapper.get('[data-testid="requirements-error"]').text()).toBe(
        ANALYST_MISSING[locale],
      );
      expect(wrapper.text()).not.toContain("REQUIREMENTS_ANALYST_REQUIRED");
      wrapper.unmount();
    },
  );

  it.each([
    { how: "at once", background: false, locale: "en" },
    { how: "at once", background: false, locale: "it" },
    { how: "through a job", background: true, locale: "en" },
    { how: "through a job", background: true, locale: "it" },
  ] as const)(
    "says that the approved steps give too few facts when a change is refused $how ($locale)",
    async ({ background, locale }) => {
      const { wrapper, failure } = await changeRefused(FEW_FACTS, background, locale);

      expect(failure.attributes("data-lost")).toBe("false");
      expect(failure.text()).toContain(NOT_SUCCEEDED[locale]);
      expect(failure.text()).toContain(FACTS_MISSING[locale]);
      expect(wrapper.text()).not.toContain("GROUNDED_INPUT_REQUIRED");
      wrapper.unmount();
    },
  );

  it("says that the first proposal could not be prepared when it is refused without a reason", async () => {
    const wrapper = await proposeRefused(NO_REASON, false, "en");

    expect(wrapper.get('[data-testid="requirements-error"]').text()).toBe(NOT_PREPARED.en);
    wrapper.unmount();
  });

  it("says that the change could not be prepared when a job refuses it without a reason", async () => {
    const { wrapper, failure } = await changeRefused(NO_REASON, true, "it");

    expect(failure.text()).toContain(NOT_SUCCEEDED.it);
    expect(failure.text()).toContain(NOT_PREPARED.it);
    wrapper.unmount();
  });

  it("says why a change still being written before a reload was refused", async () => {
    const api = revisionApi("Aggiungi la ricerca per nome.");
    const requestChange = vi.spyOn(api, "requestChange");
    vi.spyOn(generationJobsApi, "list").mockResolvedValue([
      refusedJob("REQUIREMENTS_CHANGE", null),
    ]);
    vi.spyOn(generationJobsApi, "job").mockResolvedValue(
      refusedJob("REQUIREMENTS_CHANGE", FEW_FACTS),
    );
    const wrapper = mountFlow(api, true, { locale: "it" });
    await vi.advanceTimersByTimeAsync(2050);

    const failure = wrapper.get('[data-testid="generation-job-failure"]');
    expect(failure.text()).toContain(NOT_SUCCEEDED.it);
    expect(failure.text()).toContain(FACTS_MISSING.it);
    expect(wrapper.text()).not.toContain("GROUNDED_INPUT_REQUIRED");
    expect(wrapper.text()).not.toContain("PROPOSAL_REJECTED");
    expect(wrapper.find('[data-testid="requirements-error"]').exists()).toBe(false);
    expect(requestChange).not.toHaveBeenCalled();
    wrapper.unmount();
  });
});
