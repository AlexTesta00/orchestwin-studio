import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DesignAlignmentApiError, type DesignAlignmentPayload } from "@/api/designAlignment";
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

function routeMissing(): DesignAlignmentApiError {
  return new DesignAlignmentApiError("The design alignment request failed", {
    status: 404,
    code: null,
    payload: { detail: "Not Found" },
  });
}

function alignmentOf(overrides: Partial<DesignAlignmentPayload> = {}): DesignAlignmentPayload {
  return {
    aligned: false,
    issue: null,
    design_version_number: 4,
    grounded_requirements_version_number: 1,
    requirements_version_number: 2,
    missing_codes: [],
    uncovered_codes: [],
    ...overrides,
  };
}

class FakeAlignment {
  current: DesignAlignmentPayload | Error;

  constructor(initial: DesignAlignmentPayload | Error) {
    this.current = initial;
  }

  status = vi.fn(async (): Promise<DesignAlignmentPayload> => {
    if (this.current instanceof Error) throw this.current;
    return this.current;
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

interface StepProps {
  designRequirementsVersionId: string | null;
  designVersionId: string | null;
  designApproved: boolean;
  locale: "en" | "it";
}

function mountStep(
  api: FakeRequirementsGate,
  props: Partial<StepProps> = {},
  alignment: FakeAlignment = new FakeAlignment(routeMissing()),
) {
  return mount(DesignLoopNextStep, {
    props: {
      projectId: "project-1",
      designRequirementsVersionId: "requirements-1",
      locale: "it",
      authorize,
      api,
      alignmentApi: alignment,
      ...props,
    },
    slots: { default: '<button type="button" data-testid="slot-regenerate">Rigenera</button>' },
  });
}

describe("DesignLoopNextStep on a Studio without the re-anchoring of the design", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("keeps the usual regenerate action when the design follows the approved requirements", async () => {
    const api = new FakeRequirementsGate(ready(version(1)));
    const alignment = new FakeAlignment(routeMissing());
    const wrapper = mountStep(api, {}, alignment);
    await flushPromises();
    expect(api.readiness).toHaveBeenCalledWith("project-1", "token");
    expect(alignment.status).toHaveBeenCalledWith("project-1", "token");
    expect(wrapper.find('[data-testid="design-next-step"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="slot-regenerate"]').exists()).toBe(true);
  });

  it("guides the owner through approving the requirements again and regenerating", async () => {
    remember(application({}));
    const api = new FakeRequirementsGate(pending(gate("STALE", version(1))));
    const wrapper = mountStep(api);
    await flushPromises();
    const panel = wrapper.get('[data-testid="design-next-step"]');
    expect(panel.attributes("data-mode")).toBe("steps");
    expect(panel.text()).toContain("I requisiti sono cambiati");
    expect(panel.text()).toContain("REQ-004 (versione 2)");
    expect(panel.text()).toContain("Vuoi prima controllare la modifica? Apri la Definizione.");
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

  it("sends the owner to the Definition when the approval cannot happen here", async () => {
    const api = new FakeRequirementsGate(pending(gate("PAUSED")));
    const wrapper = mountStep(api, { locale: "en" });
    await flushPromises();
    expect(wrapper.get('[data-testid="design-next-step"]').text()).toContain(
      "Want to check the change first? Open the Definition.",
    );
    await wrapper.get('[data-testid="design-reapprove-requirements"]').trigger("click");
    await flushPromises();
    expect(api.submitGate).not.toHaveBeenCalled();
    expect(api.decideGate).not.toHaveBeenCalled();
    const error = wrapper.get('[data-testid="design-next-step-error"]');
    expect(error.text()).toContain(
      "The requirements need your review in the Definition before they can be approved.",
    );
    expect(error.get("details code").text()).toBe("PAUSED");
    api.current = pending(null);
    api.decision = "ARTIFACT_STALE";
    await wrapper.get('[data-testid="design-reapprove-requirements"]').trigger("click");
    await flushPromises();
    expect(api.submitGate).toHaveBeenCalledTimes(1);
    expect(wrapper.get('[data-testid="design-next-step-error"]').text()).toContain(
      "The requirements could not be approved. Try again, or approve them in the Definition.",
    );
    expect(
      wrapper.get('[data-testid="design-next-regenerate"]').attributes("disabled"),
    ).toBeDefined();
  });

  it.each([
    [
      "it",
      "Il brief ha una nuova versione",
      "Hai aggiunto uno spunto al brief (versione 5). Apri il Brief e approva la nuova versione, poi aggiorna e approva i requisiti nella Definizione. Infine torna qui per aggiornare il design.",
    ],
    [
      "en",
      "The brief has a new version",
      "You added an idea to the brief (version 5). Open the Brief and approve the new version, then update and approve the requirements in the Definition. Then come back here to update the design.",
    ],
  ] as const)(
    "explains a change of the brief without acting on it (%s)",
    async (locale, title, text) => {
      remember(
        application({
          target: "BRIEF",
          target_field: "goals",
          target_code: null,
          target_version_number: 5,
        }),
      );
      const api = new FakeRequirementsGate(pending(gate("STALE", version(1))));
      const wrapper = mountStep(api, { locale });
      await flushPromises();
      const brief = wrapper.get('[data-testid="design-next-step-brief"]');
      expect(brief.get("h4").text()).toBe(title);
      expect(brief.get("p:last-child").text()).toBe(text);
      expect(brief.find("button").exists()).toBe(false);
      expect(wrapper.find('[data-testid="design-next-step"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="slot-regenerate"]').exists()).toBe(true);
      expect(api.submitGate).not.toHaveBeenCalled();
    },
  );

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

  it.each([
    ["the route is missing", routeMissing()],
    ["the network fails", new TypeError("Failed to fetch")],
  ])(
    "offers the regeneration as today when the design follows an older version and %s",
    async (_label, failure) => {
      const api = new FakeRequirementsGate(ready(version(2)));
      const wrapper = mountStep(api, {}, new FakeAlignment(failure));
      await flushPromises();
      expect(wrapper.get('[data-testid="design-next-step"]').attributes("data-mode")).toBe("steps");
      expect(wrapper.find('[data-testid="design-next-step-1-done"]').exists()).toBe(true);
      await wrapper.get('[data-testid="design-next-regenerate"]').trigger("click");
      expect(wrapper.emitted("regenerate")).toHaveLength(1);
      expect(wrapper.find('[data-testid="design-next-step-reanchor"]').exists()).toBe(false);
    },
  );
});

describe("DesignLoopNextStep with the re-anchoring of the design", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it.each([
    [
      "it",
      "I requisiti sono cambiati",
      "I requisiti hanno una nuova versione che non hai ancora approvato. Il design potrà usarla solo dopo la tua approvazione.",
      "Riapprova i requisiti",
      "Vuoi prima controllare la modifica? Apri la Definizione.",
    ],
    [
      "en",
      "The requirements have changed",
      "The requirements have a new version that you have not approved yet. The design can use it only after you approve it.",
      "Approve the requirements again",
      "Want to check the change first? Open the Definition.",
    ],
  ] as const)(
    "asks first to approve the Definition again, without any regeneration (%s)",
    async (locale, title, text, action, hint) => {
      const api = new FakeRequirementsGate(pending(gate("STALE", version(1))));
      const alignment = new FakeAlignment(alignmentOf({ issue: "REQUIREMENTS_APPROVAL_REQUIRED" }));
      const wrapper = mountStep(api, { locale, designApproved: true }, alignment);
      await flushPromises();

      const panel = wrapper.get('[data-testid="design-next-step"]');
      expect(panel.attributes("data-mode")).toBe("approve");
      expect(panel.get("h4").text()).toBe(title);
      expect(panel.text()).toContain(text);
      expect(wrapper.get('[data-testid="design-reapprove-requirements"]').text()).toBe(action);
      expect(panel.text()).toContain(hint);
      expect(wrapper.find('[data-testid="design-next-step-2"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="design-next-regenerate"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="slot-regenerate"]').exists()).toBe(false);
      await expectAccessible(wrapper.element);
    },
  );

  it("approves the Definition and then says how the design is re-anchored", async () => {
    const api = new FakeRequirementsGate(pending(gate("STALE", version(1))));
    const alignment = new FakeAlignment(alignmentOf({ issue: "REQUIREMENTS_APPROVAL_REQUIRED" }));
    api.decideGate.mockImplementation(async () => {
      api.current = ready();
      alignment.current = alignmentOf();
      return { status: "APPLIED", gate: null, event: null, issue: null };
    });
    const wrapper = mountStep(api, { locale: "en", designApproved: true }, alignment);
    await flushPromises();

    await wrapper.get('[data-testid="design-reapprove-requirements"]').trigger("click");
    await flushPromises();

    expect(api.submitGate).toHaveBeenCalledTimes(1);
    expect(api.decideGate).toHaveBeenCalledTimes(1);
    expect(alignment.status).toHaveBeenCalledTimes(2);
    expect(wrapper.emitted("reapproved")).toHaveLength(1);
    expect(wrapper.find('[data-testid="design-next-step"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="design-next-step-reanchor"] p:last-child').text()).toBe(
      "The design is anchored to Definition v1; now there is v2. The alternatives stay: use “Update and confirm” above to re-anchor it.",
    );
    expect(wrapper.find('[data-testid="design-next-regenerate"]').exists()).toBe(false);
  });

  it.each([
    [
      "it",
      true,
      "Il design è agganciato alla Definizione v1; ora c'è la v2. Le alternative restano: usa «Aggiorna e conferma» qui sopra per riagganciarlo.",
    ],
    [
      "en",
      true,
      "The design is anchored to Definition v1; now there is v2. The alternatives stay: use “Update and confirm” above to re-anchor it.",
    ],
    [
      "it",
      false,
      "Il design è agganciato alla Definizione v1; ora c'è la v2. Le alternative restano: approva il design dalla barra in fondo, poi usa «Aggiorna e conferma» qui sopra per riagganciarlo.",
    ],
    [
      "en",
      false,
      "The design is anchored to Definition v1; now there is v2. The alternatives stay: approve the design in the bar at the bottom, then use “Update and confirm” above to re-anchor it.",
    ],
  ] as const)(
    "says in %s that a design approved %s can be re-anchored above, with no button of its own",
    async (locale, designApproved, sentence) => {
      const api = new FakeRequirementsGate(ready(version(2)));
      const wrapper = mountStep(api, { locale, designApproved }, new FakeAlignment(alignmentOf()));
      await flushPromises();

      const notice = wrapper.get('[data-testid="design-next-step-reanchor"]');
      expect(notice.get("h4").text()).toBe(
        locale === "it" ? "Ora aggiorna il design" : "Now update the design",
      );
      expect(notice.get("p:last-child").text()).toBe(sentence);
      expect(wrapper.find("button").exists()).toBe(false);
      expect(wrapper.find('[data-testid="design-next-step"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="slot-regenerate"]').exists()).toBe(false);
      await expectAccessible(wrapper.element);
    },
  );

  it.each([
    [
      "it",
      "REQUIREMENT_NO_LONGER_AVAILABLE",
      ["REQ-003", "REQ-005"],
      "Design e valutazione non si aggiorna da sola: il design cita REQ-003 e REQ-005, che la Definizione non contiene più: rigenera le alternative nel passo Design e valutazione.",
    ],
    [
      "en",
      "REQUIREMENT_NO_LONGER_AVAILABLE",
      ["REQ-003", "REQ-005"],
      "Design & Evaluation cannot be updated by itself: the design cites REQ-003 and REQ-005, which the Definition no longer contains: regenerate the alternatives in the Design & Evaluation step.",
    ],
    [
      "it",
      "TWIN_SET_CHANGED",
      [],
      "Design e valutazione non si aggiorna da sola: i twin non sono più gli stessi.",
    ],
    [
      "en",
      "TWIN_SET_CHANGED",
      [],
      "Design & Evaluation cannot be updated by itself: the twins are no longer the same.",
    ],
  ] as const)(
    "says in %s why the design cannot be re-anchored when the issue is %s and keeps the regeneration",
    async (locale, issue, codes, sentence) => {
      const api = new FakeRequirementsGate(ready(version(2)));
      const alignment = new FakeAlignment(alignmentOf({ issue, missing_codes: [...codes] }));
      const wrapper = mountStep(api, { locale, designApproved: true }, alignment);
      await flushPromises();

      const panel = wrapper.get('[data-testid="design-next-step"]');
      expect(panel.attributes("data-mode")).toBe("blocked");
      expect(panel.get("h4").text()).toBe(
        locale === "it" ? "Ora aggiorna il design" : "Now update the design",
      );
      expect(panel.get(`[id="${panel.attributes("aria-labelledby")}"] + p`).text()).toBe(sentence);
      expect(wrapper.find('[data-testid="design-next-step-1-done"]').exists()).toBe(true);
      expect(wrapper.find('[data-testid="slot-regenerate"]').exists()).toBe(false);
      const regenerate = wrapper.get('[data-testid="design-next-regenerate"]');
      expect(regenerate.text()).toBe(
        locale === "it"
          ? "Rigenera le alternative di design"
          : "Regenerate the design alternatives",
      );
      expect(regenerate.attributes("disabled")).toBeUndefined();
      await expectAccessible(wrapper.element);
      await regenerate.trigger("click");
      expect(wrapper.emitted("regenerate")).toHaveLength(1);
    },
  );

  it.each([
    [
      "it",
      "Requisiti nuovi che il design non copre ancora: REQ-004 e REQ-007. Chiedi una modifica al design per coprirli.",
    ],
    [
      "en",
      "New requirements that the design does not cover yet: REQ-004 and REQ-007. Ask for a change to the design to cover them.",
    ],
  ] as const)(
    "names in %s the new requirements that an aligned design does not cover yet",
    async (locale, sentence) => {
      const api = new FakeRequirementsGate(ready(version(2)));
      const alignment = new FakeAlignment(
        alignmentOf({
          aligned: true,
          issue: "ALREADY_ALIGNED",
          grounded_requirements_version_number: 2,
          uncovered_codes: ["REQ-004", "REQ-007"],
        }),
      );
      const wrapper = mountStep(
        api,
        { locale, designApproved: true, designRequirementsVersionId: "requirements-2" },
        alignment,
      );
      await flushPromises();

      expect(wrapper.get('[data-testid="design-next-step-uncovered"]').text()).toBe(sentence);
      expect(wrapper.find('[data-testid="design-next-step"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="design-next-step-reanchor"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="slot-regenerate"]').exists()).toBe(true);
      await expectAccessible(wrapper.element);
    },
  );

  it("says nothing when the design is aligned and covers every requirement", async () => {
    const api = new FakeRequirementsGate(ready(version(2)));
    const alignment = new FakeAlignment(
      alignmentOf({
        aligned: true,
        issue: "ALREADY_ALIGNED",
        grounded_requirements_version_number: 2,
      }),
    );
    const wrapper = mountStep(api, { designRequirementsVersionId: "requirements-2" }, alignment);
    await flushPromises();

    expect(wrapper.find('[data-testid="design-next-step"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="design-next-step-reanchor"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="design-next-step-uncovered"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="slot-regenerate"]').exists()).toBe(true);
  });

  it("never proposes the regeneration when the design can be re-anchored, even on an older design", async () => {
    const api = new FakeRequirementsGate(ready(version(2)));
    const wrapper = mountStep(api, { designApproved: true }, new FakeAlignment(alignmentOf()));
    await flushPromises();

    expect(wrapper.find('[data-testid="design-next-regenerate"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="slot-regenerate"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("Rigenera");
  });

  it("reads the alignment again when the design version or the refresh key changes", async () => {
    const api = new FakeRequirementsGate(ready(version(2)));
    const alignment = new FakeAlignment(alignmentOf());
    const wrapper = mountStep(
      api,
      { designApproved: true, designVersionId: "design-4" },
      alignment,
    );
    await flushPromises();
    expect(alignment.status).toHaveBeenCalledTimes(1);
    expect(wrapper.find('[data-testid="design-next-step-reanchor"]').exists()).toBe(true);

    alignment.current = alignmentOf({
      aligned: true,
      issue: "ALREADY_ALIGNED",
      grounded_requirements_version_number: 2,
    });
    await wrapper.setProps({ designVersionId: "design-5" });
    await flushPromises();
    expect(alignment.status).toHaveBeenCalledTimes(2);
    expect(wrapper.find('[data-testid="design-next-step-reanchor"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="slot-regenerate"]').exists()).toBe(true);

    await wrapper.setProps({ refreshKey: 3 });
    await flushPromises();
    expect(alignment.status).toHaveBeenCalledTimes(3);
    expect(api.readiness).toHaveBeenCalledTimes(3);
  });
});
