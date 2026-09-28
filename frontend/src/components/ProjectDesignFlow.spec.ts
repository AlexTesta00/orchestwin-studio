import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DesignApi } from "../api/design";
import type { DesignLoopApi } from "../api/designLoop";
import {
  BASE_DESIGN_PACKAGE,
  DESIGN_ALTERNATIVE_ID,
  DESIGN_CREATED_AT,
  DESIGN_OWNER_ID,
  DESIGN_PROJECT_ID,
  PENDING_DESIGN_GATE,
  PROPOSED_DESIGN_DIFF,
  SECOND_DESIGN_ALTERNATIVE_ID,
  SELECTED_DESIGN_PACKAGE,
  SELECTED_DESIGN_VERSION,
  UNSELECTED_DESIGN_VERSION,
} from "../test/designFixtures";
import type {
  DesignGenerationIssue,
  DesignGenerationPayload,
  DesignPackageDiffPayload,
  DesignPackagePayload,
  DesignPackageVersionPayload,
  DesignReadinessPayload,
} from "../types/design";
import type { DesignEvaluationRunPayload, InsightApplicationPayload } from "../types/designLoop";
import type {
  RequirementsGateDecisionPayload,
  RequirementsGateSubmissionPayload,
  RequirementsReadinessPayload,
  RequirementsSpecificationPayload,
  RequirementsSpecificationVersionPayload,
} from "../types/requirements";
import DesignAlternativeComparison from "./DesignAlternativeComparison.vue";
import ProjectDesignEvaluationPanel from "./ProjectDesignEvaluationPanel.vue";
import ProjectDesignFlow from "./ProjectDesignFlow.vue";
import { buildSelectedDesignPackage } from "../test/prototypeFixtures";
import type { DesignMockupRequest, DesignMockupPayload } from "../types/design";

const authorize = <T>(operation: (accessToken: string) => Promise<T>) => operation("access-token");
const loopApi: DesignLoopApi = {
  evaluate: async () => {
    throw new Error("not evaluated in this spec");
  },
  runs: async () => [],
  comparison: async () => null,
  regenerate: async () => ({ status: "REJECTED", issue: "DESIGN_PACKAGE_NOT_FOUND" }) as never,
  applyInsight: async () => {
    throw new Error("not applied in this spec");
  },
  applications: async () => [],
  validations: async () => [],
  validate: async () => {
    throw new Error("not decided in this spec");
  },
  discussions: async () => [],
  startDiscussion: async () => {
    throw new Error("not discussed in this spec");
  },
  nextDiscussionRound: async () => {
    throw new Error("not discussed in this spec");
  },
  decideDiscussion: async () => {
    throw new Error("not discussed in this spec");
  },
};

const DESIGN_REQUIREMENTS = SELECTED_DESIGN_PACKAGE.grounding.requirements_reference;

function requirementsVersion(
  id: string,
  number: number,
  contentHash: string,
): RequirementsSpecificationVersionPayload {
  return {
    id,
    project_id: DESIGN_PROJECT_ID,
    version_number: number,
    based_on_version_number: number > 1 ? number - 1 : null,
    content_hash: contentHash,
    created_by_user_id: DESIGN_OWNER_ID,
    created_at: DESIGN_CREATED_AT,
    specification: {} as RequirementsSpecificationPayload,
  };
}

const REQUIREMENTS_V1 = requirementsVersion(
  DESIGN_REQUIREMENTS.artifact_id,
  DESIGN_REQUIREMENTS.version_number,
  DESIGN_REQUIREMENTS.content_hash,
);
const REQUIREMENTS_V2 = requirementsVersion(
  "00000000-0000-4000-8000-000000000170",
  2,
  "7".repeat(64),
);

const REGENERATED_DESIGN_VERSION: DesignPackageVersionPayload = {
  ...SELECTED_DESIGN_VERSION,
  id: "00000000-0000-4000-8000-000000000180",
  version_number: 3,
  based_on_version_number: 2,
  content_hash: "8".repeat(64),
  package: {
    ...SELECTED_DESIGN_PACKAGE,
    grounding: {
      ...SELECTED_DESIGN_PACKAGE.grounding,
      requirements_reference: {
        ...DESIGN_REQUIREMENTS,
        artifact_id: REQUIREMENTS_V2.id,
        version_number: REQUIREMENTS_V2.version_number,
        content_hash: REQUIREMENTS_V2.content_hash,
      },
    },
  },
};

function readyRequirements(version: RequirementsSpecificationVersionPayload) {
  return {
    status: "READY_FOR_DESIGN_EXPLORATION" as const,
    version,
    gate: null,
    approved_current_specification: true,
  };
}

class FakeRequirementsGate {
  current: RequirementsReadinessPayload;

  constructor(initial: RequirementsReadinessPayload) {
    this.current = initial;
  }

  readiness = vi.fn(async () => this.current);

  submitGate = vi.fn(async (): Promise<RequirementsGateSubmissionPayload> => {
    return { status: "SUBMITTED", gate: null, events: [], issue: null };
  });

  decideGate = vi.fn(async (): Promise<RequirementsGateDecisionPayload> => {
    this.current = readyRequirements(REQUIREMENTS_V2);
    return { status: "APPLIED", gate: null, event: null, issue: null };
  });
}

function fakeLoopApi(): DesignLoopApi {
  return {
    ...loopApi,
    runs: vi.fn(async () => []),
    regenerate: vi.fn(),
    applyInsight: vi.fn(),
    validations: vi.fn(async () => []),
    discussions: vi.fn(async () => []),
  };
}

function reviewingLoopApi(): DesignLoopApi {
  return { ...fakeLoopApi(), evaluate: vi.fn(async () => evaluationRun()) };
}

function button(wrapper: VueWrapper, label: string) {
  const found = wrapper.findAll("button").find((item) => item.text().includes(label));
  if (found === undefined) {
    throw new Error(`The button "${label}" was not rendered`);
  }
  return found;
}

function rejected(issue: DesignGenerationIssue): DesignGenerationPayload {
  return {
    status: "REJECTED",
    version: null,
    issue,
    proposal_issue: null,
    persistence_status: null,
  };
}

function evaluationRun(): DesignEvaluationRunPayload {
  return {
    schema_version: 1,
    id: "run-1",
    project_id: DESIGN_PROJECT_ID,
    owner_user_id: DESIGN_OWNER_ID,
    design_version_id: SELECTED_DESIGN_VERSION.id,
    design_version_number: SELECTED_DESIGN_VERSION.version_number,
    design_content_hash: SELECTED_DESIGN_VERSION.content_hash,
    alternative_id: DESIGN_ALTERNATIVE_ID,
    alternative_code: "DES-001",
    bundle: {},
    responses: [
      {
        evaluation_run_id: "run-1",
        artifact_bundle_id: "bundle-1",
        artifact_bundle_hash: "b".repeat(64),
        twin_id: "twin-1",
        twin_version: 1,
        evaluator: {
          evaluator_id: "proposer-design-twin-review",
          evaluator_version: "1",
          model_config_ref: "config",
          prompt_version_ref: "prompt",
        },
        findings: [
          {
            finding_id: "UTF-001",
            twin_id: "twin-1",
            twin_version: 1,
            artifact_id: "prototype-1",
            artifact_version: 1,
            location: "SCR-001 Guest name",
            summary: "The guest name lacks a format hint.",
            rationale: "The receptionist types under time pressure.",
            criterion: "comprehensibility",
            severity: "major",
            epistemic_status: "MODEL_INFERRED",
            evidence_refs: [],
            confidence: 0.7,
            confidence_semantics: "MODEL_SELF_ASSESSMENT_UNLESS_CALIBRATED",
            recommended_action: "Add a format hint.",
            requires_human_validation: true,
            model_config_ref: "config",
            prompt_version_ref: "prompt",
            is_simulated_feedback: true,
            content_hash: "9".repeat(64),
          },
        ],
        summary: "The flow is short.",
        evidence_gaps: [],
        is_simulated_feedback: true,
        completed_at: DESIGN_CREATED_AT,
        content_hash: "d".repeat(64),
        disclaimer: "Simulated feedback.",
      },
    ],
    started_at: DESIGN_CREATED_AT,
    completed_at: DESIGN_CREATED_AT,
    content_hash: "e".repeat(64),
  };
}

const REQUIREMENTS_APPLICATION: InsightApplicationPayload = {
  id: "application-1",
  project_id: DESIGN_PROJECT_ID,
  owner_user_id: DESIGN_OWNER_ID,
  source_kind: "SYNTHETIC_FINDING",
  source_id: "run:run-1:twin-1:UTF-001",
  source_twin_id: "twin-1",
  text: "The guest name lacks a format hint.",
  target: "REQUIREMENTS",
  target_field: null,
  target_version_id: REQUIREMENTS_V2.id,
  target_version_number: 2,
  target_code: "REQ-004",
  created_at: DESIGN_CREATED_AT,
  content_hash: "c".repeat(64),
};

class FakeDesignApi implements DesignApi {
  savedMockup: DesignMockupPayload | null = null;
  async generateMockup(_projectId: string, request: DesignMockupRequest) {
    return {
      status: "MOCKUP_GENERATED" as const,
      generation_id: "test-generation",
      design_version_id: request.design_version_id,
      design_content_hash: request.design_content_hash,
      package: buildSelectedDesignPackage(BASE_DESIGN_PACKAGE, request.alternative_id),
    };
  }
  async currentMockup() {
    return this.savedMockup;
  }
  readinessResult: DesignReadinessPayload = {
    status: "DESIGN_REVIEW_REQUIRED",
    version: UNSELECTED_DESIGN_VERSION,
    gate: null,
    has_package: true,
    package_ready_for_gate: false,
    approved_current_package: false,
  };
  historyResult: DesignPackageVersionPayload[] = [UNSELECTED_DESIGN_VERSION];
  diffsResult: DesignPackageDiffPayload[] = [];
  proposedPackage: DesignPackagePayload | null = null;

  async generate() {
    return {
      status: "CREATED" as const,
      version: UNSELECTED_DESIGN_VERSION,
      issue: null,
      proposal_issue: null,
      persistence_status: "APPENDED" as const,
    };
  }

  async current() {
    return this.readinessResult.version ?? UNSELECTED_DESIGN_VERSION;
  }

  async history() {
    return this.historyResult;
  }

  async proposeRevision(_projectId: string, request: { package: DesignPackagePayload }) {
    this.proposedPackage = request.package;
    this.diffsResult = [
      {
        ...PROPOSED_DESIGN_DIFF,
        proposed_package: request.package,
      },
    ];

    return {
      status: "CREATED" as const,
      diff: this.diffsResult[0] ?? null,
      version: null,
      issue: null,
      domain_issue: null,
      diff_persistence_status: "CREATED" as const,
      version_persistence_status: null,
    };
  }

  async revisionHistory() {
    return this.diffsResult;
  }

  async getRevision() {
    return this.diffsResult[0] ?? PROPOSED_DESIGN_DIFF;
  }

  async decideRevision(
    _projectId: string,
    _diffId: string,
    request: { decision: "APPROVE" | "REJECT"; reason?: string | null },
  ) {
    const currentDiff = this.diffsResult[0] ?? PROPOSED_DESIGN_DIFF;
    const approved = {
      ...currentDiff,
      status: request.decision === "APPROVE" ? ("APPROVED" as const) : ("REJECTED" as const),
      decided_by_user_id: DESIGN_OWNER_ID,
      decided_at: DESIGN_CREATED_AT,
      decision_reason: request.reason ?? null,
      applied_version_id: request.decision === "APPROVE" ? SELECTED_DESIGN_VERSION.id : null,
    };
    this.diffsResult = [approved];

    if (request.decision === "APPROVE") {
      this.readinessResult = {
        status: "DESIGN_APPROVAL_REQUIRED",
        version: SELECTED_DESIGN_VERSION,
        gate: null,
        has_package: true,
        package_ready_for_gate: true,
        approved_current_package: false,
      };
      this.historyResult = [UNSELECTED_DESIGN_VERSION, SELECTED_DESIGN_VERSION];
    }

    return {
      status: "APPLIED" as const,
      diff: approved,
      version: request.decision === "APPROVE" ? SELECTED_DESIGN_VERSION : null,
      issue: null,
      domain_issue: null,
      diff_persistence_status: "UPDATED" as const,
      version_persistence_status: request.decision === "APPROVE" ? ("APPENDED" as const) : null,
    };
  }

  async submitGate() {
    this.readinessResult = {
      status: "DESIGN_APPROVAL_REQUIRED",
      version: SELECTED_DESIGN_VERSION,
      gate: PENDING_DESIGN_GATE,
      has_package: true,
      package_ready_for_gate: true,
      approved_current_package: false,
    };

    return {
      status: "SUBMITTED" as const,
      gate: PENDING_DESIGN_GATE,
      events: [],
      issue: null,
    };
  }

  async decideGate() {
    return {
      status: "APPLIED" as const,
      gate: PENDING_DESIGN_GATE,
      event: null,
      issue: null,
    };
  }

  async currentGate() {
    return PENDING_DESIGN_GATE;
  }

  async gateEvents() {
    return [];
  }

  async readiness() {
    return this.readinessResult;
  }
}

describe("ProjectDesignFlow", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("restores a model mockup without changing the approved design or submitting a revision", async () => {
    const api = new FakeDesignApi();
    api.readinessResult.version = SELECTED_DESIGN_VERSION;
    api.savedMockup = {
      status: "MOCKUP_GENERATED",
      generation_id: "persisted-generation",
      design_version_id: SELECTED_DESIGN_VERSION.id,
      design_content_hash: SELECTED_DESIGN_VERSION.content_hash,
      package: {
        ...SELECTED_DESIGN_VERSION.package,
        prototype: {
          ...SELECTED_DESIGN_VERSION.package.prototype!,
          title: "Persisted visual mockup",
        },
      },
    };
    const requirementsApi = new FakeRequirementsGate(readyRequirements(REQUIREMENTS_V1));
    const wrapper = mount(ProjectDesignFlow, {
      props: { projectId: DESIGN_PROJECT_ID, authorize, api, loopApi, requirementsApi },
    });
    await flushPromises();
    expect(wrapper.get("[data-design-mockup]").text()).toContain("Persisted visual mockup");
    expect(wrapper.get("[data-design-mockup]").text()).toContain("not applied");
    expect(api.proposedPackage).toBeNull();
    expect(api.readinessResult.version.id).toBe(SELECTED_DESIGN_VERSION.id);
  });

  it("loads alternatives and proposes an immutable owner selection with prototype", async () => {
    const api = new FakeDesignApi();
    const wrapper = mount(ProjectDesignFlow, {
      props: {
        projectId: DESIGN_PROJECT_ID,
        authorize,
        api,
        loopApi,
        requirementsApi: new FakeRequirementsGate(readyRequirements(REQUIREMENTS_V1)),
      },
    });

    await flushPromises();

    expect(wrapper.text()).toContain("Guided reservation flow");
    expect(wrapper.text()).toContain("simulated feedback");

    await wrapper
      .get(`input[data-alternative-id="${SECOND_DESIGN_ALTERNATIVE_ID}"]`)
      .setValue(true);
    expect(
      wrapper
        .findAll("button")
        .find((button) => button.text().includes("Review this design choice")),
    ).toBeUndefined();
    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Create visual preview"))!
      .trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("Model-generated draft · not applied");
    expect(api.proposedPackage).toBeNull();
    const proposeButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Review this design choice"));

    if (proposeButton === undefined) {
      throw new Error("The design selection action was not rendered");
    }

    await proposeButton.trigger("click");
    await flushPromises();

    expect(api.proposedPackage?.owner_selected_alternative_id).toBe(SECOND_DESIGN_ALTERNATIVE_ID);
    expect(api.proposedPackage?.prototype?.design_alternative_id).toBe(
      SECOND_DESIGN_ALTERNATIVE_ID,
    );
    expect(wrapper.text()).toContain(PROPOSED_DESIGN_DIFF.id);
  });

  it("does not confuse the provider recommendation with owner selection", async () => {
    const api = new FakeDesignApi();
    const wrapper = mount(ProjectDesignFlow, {
      props: {
        projectId: DESIGN_PROJECT_ID,
        authorize,
        api,
        loopApi,
        requirementsApi: new FakeRequirementsGate(readyRequirements(REQUIREMENTS_V1)),
      },
    });

    await flushPromises();

    const recommended = wrapper.get(`input[data-alternative-id="${DESIGN_ALTERNATIVE_ID}"]`);

    expect((recommended.element as HTMLInputElement).checked).toBe(false);
    expect(BASE_DESIGN_PACKAGE.owner_selected_alternative_id).toBeNull();
  });

  it("guides the owner from an insight brought into the requirements to the new design", async () => {
    const api = new FakeDesignApi();
    api.readinessResult.version = SELECTED_DESIGN_VERSION;
    const requirementsApi = new FakeRequirementsGate(readyRequirements(REQUIREMENTS_V1));
    const loop = fakeLoopApi();
    vi.mocked(loop.runs).mockResolvedValue([evaluationRun()]);
    vi.mocked(loop.applyInsight).mockImplementation(async () => {
      requirementsApi.current = {
        status: "REQUIREMENTS_APPROVAL_REQUIRED",
        version: REQUIREMENTS_V2,
        gate: null,
        approved_current_specification: false,
      };
      return REQUIREMENTS_APPLICATION;
    });
    vi.mocked(loop.regenerate).mockImplementation(async () => {
      api.readinessResult = { ...api.readinessResult, version: REGENERATED_DESIGN_VERSION };
      return {
        status: "CREATED",
        version: REGENERATED_DESIGN_VERSION,
        issue: null,
        proposal_issue: null,
        persistence_status: "APPENDED",
      };
    });
    const wrapper = mount(ProjectDesignFlow, {
      props: {
        projectId: DESIGN_PROJECT_ID,
        locale: "it",
        authorize,
        api,
        loopApi: loop,
        requirementsApi,
      },
    });
    await flushPromises();
    expect(wrapper.find('[data-testid="design-evaluation-panel"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="design-discussion-panel"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="design-next-step"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="design-regenerate"]').exists()).toBe(true);
    expect(requirementsApi.readiness).toHaveBeenCalledTimes(1);

    await wrapper
      .get('[data-testid="design-evaluation-panel"] [data-testid="insight-apply-requirements"]')
      .trigger("click");
    await flushPromises();
    expect(requirementsApi.readiness).toHaveBeenCalledTimes(2);
    expect(wrapper.get('[data-testid="design-next-step"]').text()).toContain("REQ-004");
    expect(wrapper.find('[data-testid="design-regenerate"]').exists()).toBe(false);
    expect(
      wrapper.get('[data-testid="design-next-regenerate"]').attributes("disabled"),
    ).toBeDefined();

    await wrapper.get('[data-testid="design-reapprove-requirements"]').trigger("click");
    await flushPromises();
    expect(requirementsApi.submitGate).toHaveBeenCalledTimes(1);
    expect(requirementsApi.decideGate).toHaveBeenCalledTimes(1);
    expect(wrapper.find('[data-testid="design-next-step-1-done"]').exists()).toBe(true);

    await wrapper.get('[data-testid="design-next-regenerate"]').trigger("click");
    await flushPromises();
    expect(loop.regenerate).toHaveBeenCalledTimes(1);
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="design-next-step"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="design-regenerate"]').exists()).toBe(true);
  });

  it("explains a rejected regeneration in plain words instead of showing its code", async () => {
    const api = new FakeDesignApi();
    api.readinessResult.version = SELECTED_DESIGN_VERSION;
    const requirementsApi = new FakeRequirementsGate(readyRequirements(REQUIREMENTS_V1));
    const loop = fakeLoopApi();
    vi.mocked(loop.regenerate)
      .mockImplementationOnce(async () => {
        requirementsApi.current = {
          status: "REQUIREMENTS_APPROVAL_REQUIRED",
          version: REQUIREMENTS_V2,
          gate: null,
          approved_current_specification: false,
        };
        return rejected("REQUIREMENTS_APPROVAL_REQUIRED");
      })
      .mockResolvedValueOnce(rejected("DESIGN_PACKAGE_NOT_FOUND"));
    const wrapper = mount(ProjectDesignFlow, {
      props: {
        projectId: DESIGN_PROJECT_ID,
        locale: "it",
        authorize,
        api,
        loopApi: loop,
        requirementsApi,
      },
    });
    await flushPromises();
    await wrapper.get('[data-testid="design-regenerate"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toBe(
      "I requisiti sono cambiati e aspettano la tua approvazione. Riapprovali, poi rigenera le alternative di design.",
    );
    expect(wrapper.text()).not.toContain("REQUIREMENTS_APPROVAL_REQUIRED");
    expect(requirementsApi.readiness).toHaveBeenCalledTimes(2);
    await wrapper.get('[data-testid="design-reapprove-requirements"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
    await wrapper.get('[data-testid="design-next-regenerate"]').trigger("click");
    await flushPromises();
    expect(loop.regenerate).toHaveBeenCalledTimes(2);
    expect(wrapper.get('[role="alert"]').text()).toBe(
      "Non c'è ancora un design da rigenerare. Genera prima le alternative di design.",
    );
    expect(wrapper.text()).not.toContain("DESIGN_PACKAGE_NOT_FOUND");
  });

  it("reloads the design after an insight is recorded in the design", async () => {
    const api = new FakeDesignApi();
    api.readinessResult.version = SELECTED_DESIGN_VERSION;
    const loop = fakeLoopApi();
    vi.mocked(loop.runs).mockResolvedValue([evaluationRun()]);
    vi.mocked(loop.applyInsight).mockResolvedValue({
      ...REQUIREMENTS_APPLICATION,
      target: "DESIGN",
      target_version_id: SELECTED_DESIGN_VERSION.id,
      target_code: "DRK-002",
    });
    const readiness = vi.spyOn(api, "readiness");
    const wrapper = mount(ProjectDesignFlow, {
      props: {
        projectId: DESIGN_PROJECT_ID,
        authorize,
        api,
        loopApi: loop,
        requirementsApi: new FakeRequirementsGate(readyRequirements(REQUIREMENTS_V1)),
      },
    });
    await flushPromises();
    const loads = readiness.mock.calls.length;
    await wrapper
      .get('[data-testid="design-evaluation-panel"] [data-testid="insight-apply-design"]')
      .trigger("click");
    await flushPromises();
    expect(readiness.mock.calls.length).toBe(loads + 1);
  });

  it("shows the design as text first, then as tables and as diagrams on request", async () => {
    const api = new FakeDesignApi();
    api.readinessResult.version = SELECTED_DESIGN_VERSION;
    const wrapper = mount(ProjectDesignFlow, {
      props: {
        projectId: DESIGN_PROJECT_ID,
        locale: "it",
        authorize,
        api,
        loopApi: fakeLoopApi(),
        requirementsApi: new FakeRequirementsGate(readyRequirements(REQUIREMENTS_V1)),
      },
      global: { stubs: { ProjectDiagramsView: true } },
      attachTo: document.body,
    });
    await flushPromises();

    expect(wrapper.get('[data-testid="design-text-view"]').isVisible()).toBe(true);
    expect(wrapper.get('[data-testid="design-text-view"]').attributes("id")).toBe(
      "design-view-panel",
    );
    expect(wrapper.find('[data-testid="design-table-view"]').exists()).toBe(false);

    await wrapper.get('[data-testid="artifact-view-table"]').trigger("click");

    const table = wrapper.get('[data-testid="design-table-view"]');
    expect(wrapper.get('[data-testid="design-text-view"]').isVisible()).toBe(false);
    expect(table.attributes("id")).toBe("design-view-panel");
    for (const alternative of SELECTED_DESIGN_VERSION.package.alternatives) {
      expect(table.text()).toContain(alternative.code);
      expect(table.text()).toContain(alternative.title);
    }

    await wrapper.get('[data-testid="artifact-view-diagram"]').trigger("click");

    expect(wrapper.find('[data-testid="design-table-view"]').exists()).toBe(false);
    expect(wrapper.getComponent({ name: "ProjectDiagramsView" }).props()).toMatchObject({
      projectId: DESIGN_PROJECT_ID,
      stage: "design",
      locale: "it",
      refreshKey: SELECTED_DESIGN_VERSION.content_hash,
    });
    expect(wrapper.find('[data-testid="design-evaluation-panel"]').exists()).toBe(true);
    wrapper.unmount();
  });

  it("asks the twins to review the design as soon as the owner applies it", async () => {
    const api = new FakeDesignApi();
    const loop = reviewingLoopApi();
    const wrapper = mount(ProjectDesignFlow, {
      props: {
        projectId: DESIGN_PROJECT_ID,
        authorize,
        api,
        loopApi: loop,
        requirementsApi: new FakeRequirementsGate(readyRequirements(REQUIREMENTS_V1)),
      },
    });
    await flushPromises();
    expect(wrapper.find('[data-testid="design-evaluation-panel"]').exists()).toBe(false);

    await wrapper.get(`input[data-alternative-id="${DESIGN_ALTERNATIVE_ID}"]`).setValue(true);
    await button(wrapper, "Create visual preview").trigger("click");
    await flushPromises();
    await button(wrapper, "Review this design choice").trigger("click");
    await flushPromises();
    expect(loop.evaluate).not.toHaveBeenCalled();

    await button(wrapper, "Apply this design").trigger("click");
    await flushPromises();

    expect(wrapper.getComponent(ProjectDesignEvaluationPanel).props()).toMatchObject({
      designVersionId: SELECTED_DESIGN_VERSION.id,
      designContentHash: SELECTED_DESIGN_VERSION.content_hash,
      autoEvaluateVersionId: SELECTED_DESIGN_VERSION.id,
    });
    expect(vi.mocked(loop.evaluate).mock.calls.map((call) => call[1])).toEqual([
      {
        design_version_id: SELECTED_DESIGN_VERSION.id,
        design_content_hash: SELECTED_DESIGN_VERSION.content_hash,
        mode: "TWIN_REVIEW",
        locale: "en-US",
      },
    ]);
    expect(wrapper.findAll('[data-testid="design-evaluation-run"]')).toHaveLength(1);
  });

  it("never asks the twins for a review when an existing design is opened", async () => {
    const api = new FakeDesignApi();
    api.readinessResult.version = SELECTED_DESIGN_VERSION;
    const loop = reviewingLoopApi();
    const wrapper = mount(ProjectDesignFlow, {
      props: {
        projectId: DESIGN_PROJECT_ID,
        authorize,
        api,
        loopApi: loop,
        requirementsApi: new FakeRequirementsGate(readyRequirements(REQUIREMENTS_V1)),
      },
    });
    await flushPromises();

    expect(wrapper.getComponent(ProjectDesignEvaluationPanel).props("autoEvaluateVersionId")).toBe(
      null,
    );
    expect(loop.evaluate).not.toHaveBeenCalled();
    expect(wrapper.getComponent(DesignAlternativeComparison).props("twins")).toEqual(
      SELECTED_DESIGN_VERSION.package.grounding.user_twin_references,
    );
  });
});
