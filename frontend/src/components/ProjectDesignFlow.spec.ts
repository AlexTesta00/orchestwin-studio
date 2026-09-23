import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

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
import { buildSelectedDesignPackage } from "../test/prototypeFixtures";
import type { DesignMockupRequest, DesignMockupPayload } from "../types/design";
import { useDesignStore } from "../stores/design";
import { useWebExecutionStore } from "../stores/webExecution";
import type { WebSourceRevisionPayload } from "../types/webExecution";
import type { SourceDesignApi, SourceDesignReferencePayload } from "../api/webDesignReference";
import { expectAccessible } from "@/test/axe";

const authorize = <T>(operation: (accessToken: string) => Promise<T>) => operation("access-token");

function sourceReference(): SourceDesignReferencePayload {
  const artifact = {
    artifact_id: SELECTED_DESIGN_VERSION.id,
    version_number: 2,
    content_hash: SELECTED_DESIGN_VERSION.content_hash,
  };
  return {
    source: {
      revision_id: "source-1",
      version_number: 3,
      content_hash: "source-hash",
      origin: "OWNER_EDIT",
    },
    architecture: artifact,
    design: artifact,
    prototype: {
      ...SELECTED_DESIGN_VERSION.package.prototype!,
      title: "Historical approved prototype",
    },
    current_design: artifact,
    design_status: "CURRENT",
    visual_conformance: "NOT_ASSESSED",
    structure_contract: "NOT_ASSESSED",
    owner_mockup: null,
  };
}

function mountWithSource(reference: SourceDesignReferencePayload, sourceApi?: SourceDesignApi) {
  const api = new FakeDesignApi();
  api.savedMockup = {
    status: "MOCKUP_GENERATED",
    generation_id: "latest-draft",
    design_version_id: SELECTED_DESIGN_VERSION.id,
    design_content_hash: SELECTED_DESIGN_VERSION.content_hash,
    package: {
      ...SELECTED_DESIGN_VERSION.package,
      prototype: { ...SELECTED_DESIGN_VERSION.package.prototype!, title: "New unapproved mockup" },
    },
  };
  useDesignStore().$patch({ projectId: DESIGN_PROJECT_ID, current: SELECTED_DESIGN_VERSION });
  const web = useWebExecutionStore();
  web.$patch({
    activeProjectId: DESIGN_PROJECT_ID,
    sourceRevisions: [
      {
        id: reference.source.revision_id,
        project_id: DESIGN_PROJECT_ID,
        version_number: reference.source.version_number,
        content_hash: reference.source.content_hash,
      } as WebSourceRevisionPayload,
    ],
  });
  const wrapper = mount(ProjectDesignFlow, {
    props: {
      projectId: DESIGN_PROJECT_ID,
      authorize,
      api,
      autoLoad: false,
      sourceApi: sourceApi ?? { reference: vi.fn().mockResolvedValue(reference) },
    },
  });
  return { wrapper, web };
}

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

  it("keeps the source-bound design primary and a newer mockup in a separate collapsed draft", async () => {
    const { wrapper } = mountWithSource(sourceReference());
    await flushPromises();
    const applied = wrapper.get("[data-source-design]");
    expect(applied.text()).toContain("Design used for app version 3");
    expect(applied.text()).toContain("Historical approved prototype");
    expect(applied.text()).not.toContain("New unapproved mockup");
    const draft = wrapper.get("[data-unapplied-mockup]");
    expect(draft.text()).toContain("New unapproved mockup");
    expect(draft.text()).toContain("not applied to this app");
    expect((draft.element as HTMLDetailsElement).open).toBe(false);
    await applied
      .findAll("button")
      .find((button) => button.text() === "Try the app")!
      .trigger("click");
    expect(wrapper.emitted("show-result")).toHaveLength(1);
    wrapper.unmount();
  });

  it("shows the explicitly chosen owner mockup without presenting it as a new Gate 5 approval", async () => {
    const reference = sourceReference();
    reference.owner_mockup = {
      generation_id: "chosen-generation",
      design_version_id: SELECTED_DESIGN_VERSION.id,
      design_content_hash: SELECTED_DESIGN_VERSION.content_hash,
      prototype_id: "chosen-prototype",
      prototype_content_hash: "prototype-hash",
      package_content_hash: "package-hash",
      prototype: { ...reference.prototype!, title: "Chosen calculator screens" },
    };
    const { wrapper } = mountWithSource(reference);
    await flushPromises();
    expect(wrapper.get("[data-source-design]").text()).toContain(
      "Preview chosen for app version 3",
    );
    expect(wrapper.get("[data-source-design]").text()).toContain("Chosen calculator screens");
    expect(wrapper.get("[data-source-design]").text()).toContain(
      "previously approved design remains unchanged",
    );
    expect(wrapper.get("[data-source-design]").text()).toContain("not automatically verified");
    expect(wrapper.get("[data-source-design]").text()).not.toContain(
      "Historical approved prototype",
    );
    wrapper.unmount();
  });

  it("warns when source ancestry uses a previous design", async () => {
    const reference = sourceReference();
    reference.design_status = "STALE";
    const { wrapper } = mountWithSource(reference);
    await flushPromises();
    expect(wrapper.get("[data-source-design]").text()).toContain("uses an earlier design version");
    wrapper.unmount();
  });

  it("does not show the source's chosen mockup again as an unapplied draft", async () => {
    const reference = sourceReference();
    reference.structure_contract = "VERIFIED";
    reference.owner_mockup = {
      generation_id: "latest-draft",
      design_version_id: SELECTED_DESIGN_VERSION.id,
      design_content_hash: SELECTED_DESIGN_VERSION.content_hash,
      prototype_id: "chosen-prototype",
      prototype_content_hash: "prototype-hash",
      package_content_hash: "package-hash",
      prototype: { ...reference.prototype!, title: "Chosen calculator screens" },
    };
    const { wrapper } = mountWithSource(reference);
    await flushPromises();
    expect(wrapper.get("[data-source-design]").text()).toContain("Chosen calculator screens");
    expect(wrapper.get("[data-source-design]").text()).toContain(
      "includes the preview's screens and controls",
    );
    expect(wrapper.get("[data-source-design]").text()).toContain("compare their appearance");
    expect(wrapper.find("[data-unapplied-mockup]").exists()).toBe(false);
    expect(wrapper.text()).not.toContain("Model-generated draft · not applied");
    expect(
      wrapper.findAll("button").some((button) => button.text() === "Review this design choice"),
    ).toBe(false);
    wrapper.unmount();
  });

  it("does not label an unrelated revision response as this source's design", async () => {
    const reference = sourceReference();
    const sourceApi = {
      reference: vi.fn().mockResolvedValue({
        ...reference,
        source: { ...reference.source, revision_id: "wrong-source" },
      }),
    };
    const { wrapper } = mountWithSource(reference, sourceApi);
    await flushPromises();
    expect(wrapper.get("[data-source-design] [role='alert']").text()).toContain(
      "could not be loaded",
    );
    expect(wrapper.get("[data-source-design]").text()).not.toContain(
      "Historical approved prototype",
    );
    expect(wrapper.find("[data-unapplied-mockup]").exists()).toBe(true);
    wrapper.unmount();
  });

  it("ignores a late design reference after switching source revisions", async () => {
    const first = sourceReference();
    let finish!: (value: SourceDesignReferencePayload) => void;
    const pending = new Promise<SourceDesignReferencePayload>((resolve) => {
      finish = resolve;
    });
    const next = {
      ...first,
      source: {
        ...first.source,
        revision_id: "next-source",
        content_hash: "next-hash",
        version_number: 4,
      },
      prototype: { ...first.prototype!, title: "Next source design" },
    };
    const sourceApi = { reference: vi.fn().mockReturnValueOnce(pending).mockResolvedValue(next) };
    const { wrapper, web } = mountWithSource(first, sourceApi);
    await flushPromises();
    web.sourceRevisions = [
      {
        ...web.sourceRevisions[0]!,
        id: "next-source",
        content_hash: "next-hash",
        version_number: 4,
      },
    ];
    await flushPromises();
    finish(first);
    await flushPromises();
    expect(wrapper.get("[data-source-design]").text()).toContain("Next source design");
    expect(wrapper.get("[data-source-design]").text()).not.toContain(
      "Historical approved prototype",
    );
    wrapper.unmount();
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
    const wrapper = mount(ProjectDesignFlow, {
      props: { projectId: DESIGN_PROJECT_ID, authorize, api },
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
      },
    });

    await flushPromises();

    const recommended = wrapper.get(`input[data-alternative-id="${DESIGN_ALTERNATIVE_ID}"]`);

    expect((recommended.element as HTMLInputElement).checked).toBe(false);
    expect(BASE_DESIGN_PACKAGE.owner_selected_alternative_id).toBeNull();
  });

  it("has no axe violations with a source-bound design", async () => {
    const { wrapper } = mountWithSource(sourceReference());
    await flushPromises();
    await expectAccessible(wrapper.element);
  });
});
