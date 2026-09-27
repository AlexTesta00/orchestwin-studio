import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { expectAccessible } from "@/test/axe";
import { useDesignLoopStore } from "@/stores/designLoop";
import type { InsightApplicationPayload } from "@/types/designLoop";
import type {
  HumanGatePayload,
  HumanGateStatus,
  RequirementsGateDecisionPayload,
  RequirementsGateSubmissionPayload,
  RequirementsReadinessPayload,
  RequirementsSpecificationPayload,
  RequirementsSpecificationVersionPayload,
} from "@/types/requirements";
import DesignLoopNextStep from "./DesignLoopNextStep.vue";

const authorize = <T>(operation: (accessToken: string) => Promise<T>) => operation("token");

function version(number: number): RequirementsSpecificationVersionPayload {
  return {
    id: `requirements-${number}`,
    project_id: "project-1",
    version_number: number,
    based_on_version_number: number > 1 ? number - 1 : null,
    content_hash: String(number).repeat(64),
    created_by_user_id: "owner-1",
    created_at: "2026-09-26T10:00:00Z",
    specification: {} as RequirementsSpecificationPayload,
  };
}

function gate(status: HumanGateStatus, target = version(2)): HumanGatePayload {
  return {
    id: "gate-1",
    project_id: "project-1",
    owner_user_id: "owner-1",
    gate_type: "REQUIREMENTS",
    artifact: {
      project_id: "project-1",
      gate_type: "REQUIREMENTS",
      artifact_id: target.id,
      version: target.version_number,
      content_hash: target.content_hash,
    },
    iteration: 1,
    max_iterations: 3,
    status,
    created_at: "2026-09-26T10:00:00Z",
    updated_at: "2026-09-26T10:00:00Z",
    event_sequence: 1,
    resume_status: null,
  };
}

function ready(target = version(2)): RequirementsReadinessPayload {
  return {
    status: "READY_FOR_DESIGN_EXPLORATION",
    version: target,
    gate: gate("APPROVED", target),
    approved_current_specification: true,
  };
}

function pending(currentGate: HumanGatePayload | null): RequirementsReadinessPayload {
  return {
    status: "REQUIREMENTS_APPROVAL_REQUIRED",
    version: version(2),
    gate: currentGate,
    approved_current_specification: false,
  };
}

class FakeRequirementsGate {
  current: RequirementsReadinessPayload;
  submission: RequirementsGateSubmissionPayload["status"] = "SUBMITTED";
  decision: RequirementsGateDecisionPayload["status"] = "APPLIED";

  constructor(initial: RequirementsReadinessPayload) {
    this.current = initial;
  }

  readiness = vi.fn(async () => this.current);

  submitGate = vi.fn(async (): Promise<RequirementsGateSubmissionPayload> => {
    if (this.submission === "SUBMITTED") this.current = pending(gate("PENDING_APPROVAL"));
    return { status: this.submission, gate: null, events: [], issue: null };
  });

  decideGate = vi.fn(async (): Promise<RequirementsGateDecisionPayload> => {
    if (this.decision === "APPLIED") this.current = ready();
    return { status: this.decision, gate: null, event: null, issue: null };
  });
}

function application(overrides: Partial<InsightApplicationPayload>): InsightApplicationPayload {
  return {
    id: "application-1",
    project_id: "project-1",
    owner_user_id: "owner-1",
    source_kind: "SYNTHETIC_FINDING",
    source_id: "run:run-1:twin-1:UTF-001",
    source_twin_id: "twin-1",
    text: "Show the date format.",
    target: "REQUIREMENTS",
    target_field: null,
    target_version_id: "requirements-2",
    target_version_number: 2,
    target_code: "REQ-004",
    created_at: "2026-09-26T10:00:00Z",
    content_hash: "c".repeat(64),
    ...overrides,
  };
}

function remember(value: InsightApplicationPayload): void {
  const store = useDesignLoopStore();
  store.reset("project-1");
  store.lastApplication = value;
}

function mountStep(
  api: FakeRequirementsGate,
  props: Partial<{ designRequirementsVersionId: string | null; locale: "en" | "it" }> = {},
) {
  return mount(DesignLoopNextStep, {
    props: {
      projectId: "project-1",
      designRequirementsVersionId: "requirements-1",
      locale: "it",
      authorize,
      api,
      ...props,
    },
    slots: { default: '<button type="button" data-testid="slot-regenerate">Rigenera</button>' },
  });
}

describe("DesignLoopNextStep", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("keeps the usual regenerate action when the design follows the approved requirements", async () => {
    const api = new FakeRequirementsGate(ready(version(1)));
    const wrapper = mountStep(api);
    await flushPromises();
    expect(api.readiness).toHaveBeenCalledWith("project-1", "token");
    expect(wrapper.find('[data-testid="design-next-step"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="slot-regenerate"]').exists()).toBe(true);
  });

  it("guides the owner through approving the requirements again and regenerating", async () => {
    remember(application({}));
    const api = new FakeRequirementsGate(pending(gate("STALE", version(1))));
    const wrapper = mountStep(api);
    await flushPromises();
    const panel = wrapper.get('[data-testid="design-next-step"]');
    expect(panel.text()).toContain("I requisiti sono cambiati");
    expect(panel.text()).toContain("REQ-004 (versione 2)");
    expect(wrapper.find('[data-testid="slot-regenerate"]').exists()).toBe(false);
    const regenerate = () => wrapper.get('[data-testid="design-next-regenerate"]');
    expect(regenerate().text()).toBe("Rigenera le alternative di design");
    expect(regenerate().attributes("disabled")).toBeDefined();
    expect(wrapper.get('[data-testid="design-next-step-2"]').text()).toContain(
      "Disponibile dopo il passo 1.",
    );
    await regenerate().trigger("click");
    expect(wrapper.emitted("regenerate")).toBeUndefined();
    await expectAccessible(wrapper.element);
    const reapprove = wrapper.get('[data-testid="design-reapprove-requirements"]');
    expect(reapprove.text()).toBe("Riapprova i requisiti");
    await reapprove.trigger("click");
    await flushPromises();
    expect(api.submitGate).toHaveBeenCalledTimes(1);
    expect(api.decideGate).toHaveBeenCalledWith(
      "project-1",
      { action: "APPROVE", reason: null },
      "token",
    );
    expect(wrapper.get('[data-testid="design-next-step-1-done"]').text()).toContain(
      "Requisiti approvati",
    );
    expect(wrapper.emitted("reapproved")).toHaveLength(1);
    expect(wrapper.get('[data-testid="design-next-step"]').text()).toContain(
      "Ora aggiorna il design",
    );
    expect(regenerate().attributes("disabled")).toBeUndefined();
    await wrapper.setProps({ busy: true });
    expect(regenerate().attributes("disabled")).toBeDefined();
    await wrapper.setProps({ busy: false });
    await regenerate().trigger("click");
    expect(wrapper.emitted("regenerate")).toHaveLength(1);
  });

  it("approves a gate that is already waiting without submitting it again", async () => {
    const api = new FakeRequirementsGate(pending(gate("PENDING_APPROVAL")));
    const wrapper = mountStep(api, { designRequirementsVersionId: null, locale: "en" });
    await flushPromises();
    expect(wrapper.get('[data-testid="design-next-step"]').text()).toContain(
      "The requirements have a new version that you have not approved yet.",
    );
    await wrapper.get('[data-testid="design-reapprove-requirements"]').trigger("click");
    await flushPromises();
    expect(api.submitGate).not.toHaveBeenCalled();
    expect(api.decideGate).toHaveBeenCalledTimes(1);
    expect(wrapper.find('[data-testid="design-next-step-1-done"]').exists()).toBe(true);
    expect(
      wrapper.get('[data-testid="design-next-regenerate"]').attributes("disabled"),
    ).toBeUndefined();
  });

  it("sends the owner to the requirements step when the approval cannot happen here", async () => {
    const api = new FakeRequirementsGate(pending(gate("PAUSED")));
    const wrapper = mountStep(api, { locale: "en" });
    await flushPromises();
    await wrapper.get('[data-testid="design-reapprove-requirements"]').trigger("click");
    await flushPromises();
    expect(api.submitGate).not.toHaveBeenCalled();
    expect(api.decideGate).not.toHaveBeenCalled();
    const error = wrapper.get('[data-testid="design-next-step-error"]');
    expect(error.text()).toContain("need your review in the Requirements step");
    expect(error.get("details code").text()).toBe("PAUSED");
    api.current = pending(null);
    api.decision = "ARTIFACT_STALE";
    await wrapper.get('[data-testid="design-reapprove-requirements"]').trigger("click");
    await flushPromises();
    expect(api.submitGate).toHaveBeenCalledTimes(1);
    expect(wrapper.get('[data-testid="design-next-step-error"]').text()).toContain(
      "could not be approved",
    );
    expect(
      wrapper.get('[data-testid="design-next-regenerate"]').attributes("disabled"),
    ).toBeDefined();
  });

  it("explains a change of the brief without acting on it", async () => {
    remember(
      application({
        target: "BRIEF",
        target_field: "goals",
        target_code: null,
        target_version_number: 5,
      }),
    );
    const api = new FakeRequirementsGate(pending(gate("STALE", version(1))));
    const wrapper = mountStep(api);
    await flushPromises();
    const brief = wrapper.get('[data-testid="design-next-step-brief"]');
    expect(brief.text()).toContain("Il brief ha una nuova versione");
    expect(brief.text()).toContain("versione 5");
    expect(brief.text()).toContain("Apri il passo Brief");
    expect(brief.find("button").exists()).toBe(false);
    expect(wrapper.find('[data-testid="design-next-step"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="slot-regenerate"]').exists()).toBe(true);
    expect(api.submitGate).not.toHaveBeenCalled();
  });

  it("reads the readiness again when an insight is applied", async () => {
    const api = new FakeRequirementsGate(ready(version(1)));
    const wrapper = mountStep(api);
    await flushPromises();
    expect(wrapper.find('[data-testid="design-next-step"]').exists()).toBe(false);
    api.current = pending(gate("STALE", version(1)));
    await wrapper.setProps({ refreshKey: 1 });
    await flushPromises();
    expect(api.readiness).toHaveBeenCalledTimes(2);
    expect(wrapper.find('[data-testid="design-reapprove-requirements"]').exists()).toBe(true);
  });

  it("offers the regeneration when the design follows an older approved version", async () => {
    const api = new FakeRequirementsGate(ready(version(2)));
    const wrapper = mountStep(api);
    await flushPromises();
    expect(wrapper.find('[data-testid="design-next-step-1-done"]').exists()).toBe(true);
    await wrapper.get('[data-testid="design-next-regenerate"]').trigger("click");
    expect(wrapper.emitted("regenerate")).toHaveLength(1);
  });
});
