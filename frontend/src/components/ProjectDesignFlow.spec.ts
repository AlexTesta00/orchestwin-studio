import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it } from "vitest";

import type { DesignApi } from "../api/design";
import {
  BASE_DESIGN_PACKAGE,
  DESIGN_ALTERNATIVE_ID,
  DESIGN_CREATED_AT,
  DESIGN_OWNER_ID,
  DESIGN_PROJECT_ID,
  PENDING_DESIGN_GATE,
  PROPOSED_DESIGN_DIFF,
  SECOND_DESIGN_ALTERNATIVE_ID,
  SELECTED_DESIGN_VERSION,
  UNSELECTED_DESIGN_VERSION,
} from "../test/designFixtures";
import type {
  DesignPackageDiffPayload,
  DesignPackagePayload,
  DesignPackageVersionPayload,
  DesignReadinessPayload,
} from "../types/design";
import ProjectDesignFlow from "./ProjectDesignFlow.vue";

const authorize = <T>(operation: (accessToken: string) => Promise<T>) => operation("access-token");

class FakeDesignApi implements DesignApi {
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

  it("loads alternatives and proposes an immutable owner selection with prototype", async () => {
    const api = new FakeDesignApi();
    const wrapper = mount(ProjectDesignFlow, {
      props: {
        projectId: DESIGN_PROJECT_ID,
        authorize,
        api,
      },
    });

    await flushPromises();

    expect(wrapper.text()).toContain("Guided reservation flow");
    expect(wrapper.text()).toContain("simulated feedback");

    await wrapper
      .get(`input[data-alternative-id="${SECOND_DESIGN_ALTERNATIVE_ID}"]`)
      .setValue(true);
    const proposeButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Create selection and prototype diff"));

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
      },
    });

    await flushPromises();

    const recommended = wrapper.get(`input[data-alternative-id="${DESIGN_ALTERNATIVE_ID}"]`);

    expect((recommended.element as HTMLInputElement).checked).toBe(false);
    expect(BASE_DESIGN_PACKAGE.owner_selected_alternative_id).toBeNull();
  });
});
