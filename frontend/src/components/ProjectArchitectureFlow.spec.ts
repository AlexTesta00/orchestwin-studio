import { createPinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type { ArchitectureApi } from "../api/architecture";
import {
  ARCHITECTURE_DIFF,
  ARCHITECTURE_PACKAGE,
  ARCHITECTURE_PROJECT_ID,
  ARCHITECTURE_READINESS,
  ARCHITECTURE_VERSION,
  PENDING_ARCHITECTURE_GATE,
} from "../test/architectureFixtures";
import type {
  ArchitectureGateDecisionRequest,
  ArchitecturePackagePayload,
  ArchitectureReadinessPayload,
  ArchitectureRevisionDecisionRequest,
  ArchitectureRevisionRequest,
} from "../types/architecture";
import ProjectArchitectureFlow from "./ProjectArchitectureFlow.vue";

class FakeArchitectureApi implements ArchitectureApi {
  proposedPackage: ArchitecturePackagePayload | null = null;
  gateDecision: ArchitectureGateDecisionRequest | null = null;
  diffDecision: ArchitectureRevisionDecisionRequest | null = null;
  readinessValue: ArchitectureReadinessPayload = ARCHITECTURE_READINESS;

  async generate() {
    return {
      status: "CREATED" as const,
      version: ARCHITECTURE_VERSION,
      issue: null,
      proposal_issue: null,
      persistence_status: "APPENDED" as const,
    };
  }

  async current() {
    return ARCHITECTURE_VERSION;
  }

  async history() {
    return [ARCHITECTURE_VERSION];
  }

  async proposeRevision(_projectId: string, request: ArchitectureRevisionRequest) {
    this.proposedPackage = request.package;

    return {
      status: "CREATED" as const,
      diff: ARCHITECTURE_DIFF,
      version: null,
      issue: null,
      domain_issue: null,
      diff_persistence_status: "CREATED" as const,
      version_persistence_status: null,
    };
  }

  async revisionHistory() {
    return this.proposedPackage === null ? [] : [ARCHITECTURE_DIFF];
  }

  async getRevision() {
    return ARCHITECTURE_DIFF;
  }

  async decideRevision(
    _projectId: string,
    _diffId: string,
    request: ArchitectureRevisionDecisionRequest,
  ) {
    this.diffDecision = request;

    return {
      status: "APPLIED" as const,
      diff: {
        ...ARCHITECTURE_DIFF,
        status: request.decision === "APPROVE" ? ("APPROVED" as const) : ("REJECTED" as const),
      },
      version: request.decision === "APPROVE" ? ARCHITECTURE_VERSION : null,
      issue: null,
      domain_issue: null,
      diff_persistence_status: "UPDATED" as const,
      version_persistence_status: request.decision === "APPROVE" ? ("APPENDED" as const) : null,
    };
  }

  async submitGate() {
    return {
      status: "SUBMITTED" as const,
      gate: PENDING_ARCHITECTURE_GATE,
      events: [],
      issue: null,
    };
  }

  async decideGate(_projectId: string, request: ArchitectureGateDecisionRequest) {
    this.gateDecision = request;

    return {
      status: "APPLIED" as const,
      gate: {
        ...PENDING_ARCHITECTURE_GATE,
        status:
          request.action === "APPROVE" ? ("APPROVED" as const) : PENDING_ARCHITECTURE_GATE.status,
      },
      event: null,
      issue: null,
    };
  }

  async currentGate() {
    return PENDING_ARCHITECTURE_GATE;
  }

  async gateEvents() {
    return [];
  }

  async readiness() {
    return this.readinessValue;
  }
}

const authorize = async <T>(operation: (accessToken: string) => Promise<T>): Promise<T> =>
  operation("access-token");

function mountFlow(api: FakeArchitectureApi) {
  return mount(ProjectArchitectureFlow, {
    global: {
      plugins: [createPinia()],
    },
    props: {
      projectId: ARCHITECTURE_PROJECT_ID,
      authorize,
      api,
    },
  });
}

describe("ProjectArchitectureFlow", () => {
  it("loads and renders the architecture, test plan, and Gate 6 state", async () => {
    const wrapper = mountFlow(new FakeArchitectureApi());

    await flushPromises();

    expect(wrapper.text()).toContain("Reservation platform architecture");
    expect(wrapper.text()).toContain("Create a reservation end to end");
    expect(wrapper.text()).toContain("PENDING_APPROVAL");
    expect(wrapper.text()).toContain("not empirical user validation");
  });

  it("proposes package-level open questions as an immutable revision", async () => {
    const api = new FakeArchitectureApi();
    const wrapper = mountFlow(api);

    await flushPromises();

    const questions = wrapper.get("textarea");
    await questions.setValue("Confirm the selected execution profile.\nReview deployment risks.");

    const propose = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Propose Architecture Package revision"));

    if (propose === undefined) {
      throw new Error("The Architecture revision action was not rendered");
    }

    await propose.trigger("click");
    await flushPromises();

    expect(api.proposedPackage?.grounding).toEqual(ARCHITECTURE_PACKAGE.grounding);
    expect(api.proposedPackage?.open_questions).toEqual([
      "Confirm the selected execution profile.",
      "Review deployment risks.",
    ]);
    expect(wrapper.text()).toContain(ARCHITECTURE_DIFF.id);
  });

  it("requires a reason before requesting a Gate 6 revision", async () => {
    const api = new FakeArchitectureApi();
    const wrapper = mountFlow(api);

    await flushPromises();

    const requestRevision = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Request revision"));

    if (requestRevision === undefined) {
      throw new Error("The Gate 6 revision action was not rendered");
    }

    await requestRevision.trigger("click");
    await flushPromises();

    expect(wrapper.get('[role="alert"]').text()).toContain("A reason is required");
    expect(api.gateDecision).toBeNull();
  });
});
