import { createPinia, setActivePinia } from "pinia";
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils";
import { defineComponent, h, vShow, withDirectives } from "vue";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ApiError } from "@/api/client";
import type { ProjectBriefVersionResponse } from "@/api/contracts";
import type {
  BriefAssumptionBulkAcceptanceResponse,
  BriefAssumptionResponse,
  BriefField,
  HumanGateResponse,
  ProjectWorkflowApi,
} from "@/api/workflow-contracts";
import { createAppI18n, type SupportedLocale } from "@/i18n";
import type { AuthorizedRequest } from "@/stores/clarification";
import { useClarificationStore } from "@/stores/clarification";
import { expectAccessible } from "@/test/axe";

import ProjectClarificationFlow from "./ProjectClarificationFlow.vue";
import UiDecisionBar from "./UiDecisionBar.vue";

enableAutoUnmount(afterEach);

const PROJECT_ID = "project-id";

const ASSUMPTION: BriefAssumptionResponse = {
  id: "assumption-id",
  project_id: PROJECT_ID,
  brief_version_number: 2,
  field: "domain",
  statement: "Eventi di comunità.",
  source: "MODEL_PROPOSED",
  status: "PROPOSED",
  created_by_user_id: "owner-id",
  created_at: "2026-09-25T10:00:00Z",
  decided_by_user_id: null,
  decided_at: null,
  decision_reason: null,
};

function proposal(id: string, field: BriefField, statement: string): BriefAssumptionResponse {
  return { ...ASSUMPTION, id, field, statement };
}

function accepted(assumption: BriefAssumptionResponse): BriefAssumptionResponse {
  return {
    ...assumption,
    status: "ACCEPTED",
    decided_by_user_id: "owner-id",
    decided_at: "2026-09-25T10:05:00Z",
  };
}

function briefVersion(versionNumber: number): ProjectBriefVersionResponse {
  return {
    id: `brief-${versionNumber}`,
    project_id: PROJECT_ID,
    version_number: versionNumber,
    schema_version: 1,
    content_hash: `hash-${versionNumber}`,
    created_by_user_id: "owner-id",
    created_at: "2026-09-25T10:05:00Z",
    brief: {
      name: "Guest list",
      description: null,
      problem: null,
      goals: null,
      target_users: null,
      domain: "Eventi di comunità.",
      technical_constraints: null,
      temporal_constraints: null,
      budget: null,
      functional_requirements: null,
      non_functional_requirements: null,
      risks: null,
      stakeholders: null,
      available_artifacts: null,
      definition_of_done: null,
      unknown_fields: [],
      provided_fields: ["name", "domain"],
      missing_fields: [],
    },
  };
}

type BulkOutcome = readonly [
  BriefAssumptionBulkAcceptanceResponse,
  readonly BriefAssumptionResponse[],
];

function workflowApi(
  initial: readonly BriefAssumptionResponse[],
  outcomes: readonly BulkOutcome[],
): ProjectWorkflowApi & { readonly acceptAllCalls: string[] } {
  let assumptions = initial;
  const pending = [...outcomes];
  const acceptAllCalls: string[] = [];

  return {
    acceptAllCalls,

    async listProjectBriefAssumptions() {
      return assumptions;
    },

    async createProjectBriefAssumption() {
      return { status: "CREATED", assumption: null };
    },

    async acceptProjectBriefAssumption() {
      return { status: "ASSUMPTION_NOT_FOUND", assumption: null, brief_version: null };
    },

    async acceptAllProjectBriefAssumptions(_accessToken, projectId) {
      acceptAllCalls.push(projectId);

      const [response, next] = pending.shift() ?? [
        { status: "NOTHING_TO_ACCEPT", accepted: [], skipped: [], brief_version: null },
        assumptions,
      ];

      assumptions = next;

      return response;
    },

    async rejectProjectBriefAssumption() {
      return { status: "ASSUMPTION_NOT_FOUND", assumption: null, brief_version: null };
    },

    async submitProjectBriefGate() {
      return {
        status: "BRIEF_INCOMPLETE",
        gate: null,
        events: [],
        missing_fields: [],
        issue: null,
      };
    },

    async getCurrentProjectBriefGate() {
      throw new ApiError(404, "project_brief_gate_not_found");
    },

    async listProjectBriefGateEvents() {
      return [];
    },

    async decideProjectBriefGate() {
      return { status: "GATE_NOT_FOUND", gate: null, event: null, issue: null };
    },
  };
}

function mountFlow(api: ProjectWorkflowApi, locale: SupportedLocale) {
  const authorize: AuthorizedRequest = <T>(
    operation: (accessToken: string) => Promise<T>,
  ): Promise<T> => operation("access-token");

  return mount(ProjectClarificationFlow, {
    props: {
      projectId: PROJECT_ID,
      api,
      authorize,
    },
    global: {
      plugins: [createPinia(), createAppI18n(locale)],
    },
  });
}

describe("ProjectClarificationFlow", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("shows the proposed assumptions and only the approval actions that apply", async () => {
    let assumptions: readonly BriefAssumptionResponse[] = [ASSUMPTION];
    let acceptedId: string | null = null;

    const api: ProjectWorkflowApi = {
      async listProjectBriefAssumptions() {
        return assumptions;
      },

      async createProjectBriefAssumption() {
        return {
          status: "CREATED",
          assumption: null,
        };
      },

      async acceptProjectBriefAssumption(_accessToken, _projectId, assumptionId) {
        acceptedId = assumptionId;
        assumptions = [{ ...ASSUMPTION, status: "ACCEPTED", decided_by_user_id: "owner-id" }];

        return {
          status: "ACCEPTED",
          assumption: assumptions[0] ?? null,
          brief_version: null,
        };
      },

      async acceptAllProjectBriefAssumptions() {
        return {
          status: "NOTHING_TO_ACCEPT",
          accepted: [],
          skipped: [],
          brief_version: null,
        };
      },

      async rejectProjectBriefAssumption() {
        return {
          status: "ASSUMPTION_NOT_FOUND",
          assumption: null,
          brief_version: null,
        };
      },

      async submitProjectBriefGate() {
        return {
          status: "BRIEF_INCOMPLETE",
          gate: null,
          events: [],
          missing_fields: ["problem"],
          issue: null,
        };
      },

      async getCurrentProjectBriefGate() {
        throw new ApiError(404, "project_brief_gate_not_found");
      },

      async listProjectBriefGateEvents() {
        return [];
      },

      async decideProjectBriefGate() {
        return {
          status: "GATE_NOT_FOUND",
          gate: null,
          event: null,
          issue: null,
        };
      },
    };

    const authorize: AuthorizedRequest = <T>(
      operation: (accessToken: string) => Promise<T>,
    ): Promise<T> => operation("access-token");

    const wrapper = mount(ProjectClarificationFlow, {
      props: {
        projectId: PROJECT_ID,
        api,
        authorize,
      },
      global: {
        plugins: [createPinia(), createAppI18n()],
      },
    });

    await flushPromises();

    expect(wrapper.find('[data-testid="clarification-answer-form"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("See the remaining questions");
    const assumptionsSection = wrapper.get('[aria-labelledby="assumptions-title"]');
    expect(assumptionsSection.get('[data-testid="assumption-focus"]').isVisible()).toBe(true);
    expect(assumptionsSection.text()).toContain("Eventi di comunità.");
    expect(wrapper.find('[data-testid="accept-all-assumptions"]').exists()).toBe(false);
    await assumptionsSection.get('[data-testid="assumption-accept"]').trigger("click");
    await flushPromises();
    expect(acceptedId).toBe("assumption-id");
    expect(assumptionsSection.find('[data-testid="assumption-focus"]').exists()).toBe(false);
    expect(assumptionsSection.get('[data-testid="assumptions-decided"]').text()).toContain(
      "1 accepted · 0 left open.",
    );

    expect(wrapper.find('[aria-labelledby="brief-gate-title"] button').exists()).toBe(false);
    await wrapper
      .findComponent(UiDecisionBar)
      .get('[data-testid="decision-primary"]')
      .trigger("click");
    await flushPromises();
    expect(wrapper.get('[data-testid="brief-decision-problem"]').text()).toContain(
      "Approval is blocked by these missing fields:",
    );
    expect(wrapper.get('[data-testid="brief-decision-problem"]').text()).toContain("The problem");

    const store = useClarificationStore();
    store.gate = {
      id: "gate-id",
      project_id: PROJECT_ID,
      owner_user_id: "owner-id",
      gate_type: "PROJECT_BRIEF",
      status: "APPROVED",
      artifact: {
        project_id: PROJECT_ID,
        gate_type: "PROJECT_BRIEF",
        artifact_id: "brief-1",
        version: 1,
        content_hash: "hash-1",
      },
      iteration: 1,
      max_iterations: 5,
      event_sequence: 1,
      created_at: "2026-09-25T10:00:00Z",
      updated_at: "2026-09-25T10:00:00Z",
      resume_status: null,
    } satisfies HumanGateResponse;
    store.lastGateSubmission = null;
    await wrapper.setProps({
      currentBrief: { id: "brief-1", version_number: 1, content_hash: "hash-1" },
    });
    const approval = wrapper.get('[aria-labelledby="brief-gate-title"]');
    expect(approval.findAll("button")).toHaveLength(0);
    expect(approval.findAll("textarea")).toHaveLength(0);
    expect(wrapper.findComponent(UiDecisionBar).exists()).toBe(false);

    await wrapper.setProps({
      currentBrief: { id: "brief-2", version_number: 2, content_hash: "hash-2" },
    });
    const bar = wrapper.findComponent(UiDecisionBar);
    expect(bar.get('[data-testid="decision-primary"]').text()).toBe("Approve the brief");
    expect(bar.find('[data-testid="decision-secondary"]').exists()).toBe(false);
    expect(approval.findAll("button")).toHaveLength(0);
    expect(approval.findAll("textarea")).toHaveLength(0);
  });

  it("accepts every proposal at once and reports the new brief version", async () => {
    const domain = proposal("domain-id", "domain", "Eventi di comunità.");
    const budget = proposal("budget-id", "budget", "Circa 5.000 euro.");
    const laterBudget = proposal("later-budget-id", "budget", "Circa 8.000 euro.");
    const api = workflowApi(
      [domain, budget, laterBudget],
      [
        [
          {
            status: "ACCEPTED",
            accepted: [accepted(domain), accepted(budget)],
            skipped: [laterBudget],
            brief_version: briefVersion(3),
          },
          [accepted(domain), accepted(budget), laterBudget],
        ],
      ],
    );

    const wrapper = mountFlow(api, "en");
    await flushPromises();

    const store = useClarificationStore();
    const button = wrapper.get('[data-testid="accept-all-assumptions"]');
    expect(button.text()).toBe("Accept all proposals");
    expect(button.attributes("disabled")).toBeUndefined();

    store.busy = true;
    await flushPromises();
    expect(button.attributes("disabled")).toBeDefined();
    store.busy = false;
    await flushPromises();

    await button.trigger("click");
    await flushPromises();

    expect(api.acceptAllCalls).toEqual([PROJECT_ID]);
    expect(wrapper.get('[data-testid="accept-all-outcome"]').text()).toBe(
      "Accepted proposals: 2. The brief is now version 3. Proposals left to decide: 1.",
    );
    expect(wrapper.find('[data-testid="accept-all-assumptions"]').exists()).toBe(false);
    expect(wrapper.findAll('[data-testid="assumption-pending"]')).toHaveLength(1);
    expect(wrapper.get('[data-testid="assumption-focus"]').text()).toContain("Circa 8.000 euro.");
    expect(store.lastAssumptionDecision?.brief_version?.version_number).toBe(3);
  });

  it("tells the owner in Italian when there is nothing to accept and when all is accepted", async () => {
    const domain = proposal("domain-id", "domain", "Eventi di comunità.");
    const goals = proposal("goals-id", "goals", "Vendere i biglietti online.");
    const api = workflowApi(
      [domain, goals],
      [
        [
          {
            status: "NOTHING_TO_ACCEPT",
            accepted: [],
            skipped: [domain, goals],
            brief_version: null,
          },
          [domain, goals],
        ],
        [
          {
            status: "ACCEPTED",
            accepted: [accepted(domain), accepted(goals)],
            skipped: [],
            brief_version: briefVersion(4),
          },
          [accepted(domain), accepted(goals)],
        ],
      ],
    );

    const wrapper = mountFlow(api, "it");
    await flushPromises();

    const outcome = wrapper.get('[data-testid="accept-all-outcome"]');
    expect(outcome.text()).toBe("");

    await wrapper.get('[data-testid="accept-all-assumptions"]').trigger("click");
    await flushPromises();
    expect(outcome.text()).toBe("Non ci sono proposte da accettare.");

    const button = wrapper.get('[data-testid="accept-all-assumptions"]');
    expect(button.text()).toBe("Accetta tutte le proposte");

    await button.trigger("click");
    await flushPromises();
    expect(outcome.text()).toBe("Proposte accettate: 2. Il brief è alla versione 4.");
    expect(wrapper.find('[data-testid="accept-all-assumptions"]').exists()).toBe(false);
  });
});

function pendingGate(status: HumanGateResponse["status"]): HumanGateResponse {
  return {
    id: "gate-id",
    project_id: PROJECT_ID,
    owner_user_id: "owner-id",
    gate_type: "PROJECT_BRIEF",
    status,
    artifact: {
      project_id: PROJECT_ID,
      gate_type: "PROJECT_BRIEF",
      artifact_id: "brief-2",
      version: 2,
      content_hash: "hash-2",
    },
    iteration: 1,
    max_iterations: 5,
    event_sequence: 1,
    created_at: "2026-09-25T10:00:00Z",
    updated_at: "2026-09-25T10:00:00Z",
    resume_status: null,
  };
}

function decisionApi(
  initial: readonly BriefAssumptionResponse[],
  gate: HumanGateResponse | null,
  decide: (action: string) => HumanGateResponse | Error = () => pendingGate("APPROVED"),
  submit: () => HumanGateResponse | Error = () => pendingGate("PENDING_APPROVAL"),
) {
  let assumptions = [...initial];
  let current = gate;
  const calls = {
    accept: [] as [string, string | null | undefined][],
    reject: [] as [string, string][],
    decide: [] as [string, string | null | undefined][],
    order: [] as string[],
  };
  const api: ProjectWorkflowApi = {
    async listProjectBriefAssumptions() {
      return assumptions;
    },
    async createProjectBriefAssumption() {
      return { status: "CREATED", assumption: null };
    },
    async acceptProjectBriefAssumption(_accessToken, _projectId, assumptionId, reason) {
      calls.accept.push([assumptionId, reason]);
      assumptions = assumptions.map((item) => (item.id === assumptionId ? accepted(item) : item));
      return {
        status: "ACCEPTED",
        assumption: assumptions.find((item) => item.id === assumptionId) ?? null,
        brief_version: null,
      };
    },
    async acceptAllProjectBriefAssumptions() {
      return { status: "NOTHING_TO_ACCEPT", accepted: [], skipped: [], brief_version: null };
    },
    async rejectProjectBriefAssumption(_accessToken, _projectId, assumptionId, reason) {
      calls.reject.push([assumptionId, reason]);
      assumptions = assumptions.map((item) =>
        item.id === assumptionId ? { ...item, status: "REJECTED", decision_reason: reason } : item,
      );
      return {
        status: "REJECTED",
        assumption: assumptions.find((item) => item.id === assumptionId) ?? null,
        brief_version: null,
      };
    },
    async submitProjectBriefGate() {
      calls.order.push("SUBMIT");
      const outcome = submit();
      if (outcome instanceof Error) throw outcome;
      current = outcome;
      return { status: "SUBMITTED", gate: outcome, events: [], missing_fields: [], issue: null };
    },
    async getCurrentProjectBriefGate() {
      if (current === null) throw new ApiError(404, "project_brief_gate_not_found");
      return current;
    },
    async listProjectBriefGateEvents() {
      return [];
    },
    async decideProjectBriefGate(_accessToken, _projectId, action, reason) {
      calls.order.push(action);
      calls.decide.push([action, reason]);
      const outcome = decide(action);
      if (outcome instanceof Error) throw outcome;
      current = outcome;
      return { status: "APPLIED", gate: outcome, event: null, issue: null };
    },
  };
  return { api, calls };
}

const REFERENCE = {
  ...briefVersion(2),
  brief: {
    ...briefVersion(2).brief,
    problem: "Nessuno sa chi è arrivato.",
    goals: ["Vedere la lista", "Segnare gli arrivi"],
    unknown_fields: ["budget", "risks", "definition_of_done", "stakeholders"] as BriefField[],
  },
};

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

function mountBrief(
  api: ProjectWorkflowApi,
  locale: SupportedLocale = "en",
  options: { sectionsMode?: boolean } = {},
) {
  const authorize: AuthorizedRequest = <T>(
    operation: (accessToken: string) => Promise<T>,
  ): Promise<T> => operation("access-token");

  return mount(ProjectClarificationFlow, {
    attachTo: document.body,
    props: {
      projectId: PROJECT_ID,
      currentBrief: REFERENCE,
      api,
      authorize,
      ...(options.sectionsMode === undefined ? {} : { sectionsMode: options.sectionsMode }),
    },
    global: { plugins: [createPinia(), createAppI18n(locale)] },
  });
}

describe("ProjectClarificationFlow brief and decision", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("shows the brief as a list and proposes the missing points one at a time", async () => {
    const budget = proposal("budget-id", "budget", "Circa 5.000 euro.");
    const risks = proposal("risks-id", "risks", "I volontari cambiano spesso.");
    const done = {
      ...proposal("done-id", "definition_of_done", "Quando la lista funziona."),
      status: "REJECTED" as const,
      decision_reason: "Lo decidiamo dopo.",
    };
    const { api } = decisionApi([budget, risks, done], null);
    const wrapper = mountBrief(api);
    await flushPromises();

    const summary = wrapper.get('[data-testid="brief-summary"]');
    expect(summary.get("h2").text()).toBe("Your idea");
    expect(
      summary.findAll("[data-brief-field]").map((row) => row.attributes("data-brief-field")),
    ).toEqual([
      "name",
      "problem",
      "goals",
      "domain",
      "budget",
      "risks",
      "definition_of_done",
      "stakeholders",
    ]);
    expect(
      summary
        .get('[data-brief-field="goals"] dd')
        .findAll("span")
        .map((line) => line.text()),
    ).toEqual(["Vedere la lista", "Segnare gli arrivi"]);
    expect(summary.get('[data-brief-field="definition_of_done"]').text()).toContain(
      "Left open: you will complete it later.",
    );
    expect(summary.get('[data-brief-field="definition_of_done"]').text()).toContain(
      "Lo decidiamo dopo.",
    );
    expect(summary.get('[data-brief-field="stakeholders"]').text()).toContain(
      "Open point: you will complete it later.",
    );

    const focus = wrapper.get('[data-testid="assumption-focus"]');
    expect(focus.attributes("data-claim-status")).toBe("hypothesis");
    expect(focus.text()).toContain("Proposal 1 of 3");
    expect(focus.get("h3").text()).toBe("Budget");
    expect(focus.text()).toContain("Circa 5.000 euro.");
    const pending = wrapper.findAll('[data-testid="assumption-pending"]');
    expect(pending.map((row) => row.text())).toEqual([
      "Proposal waiting for your decision",
      "Proposal waiting for your decision",
    ]);
    expect(pending[0]!.attributes("aria-current")).toBe("true");
    await pending[1]!.trigger("click");
    await flushPromises();
    expect(focus.get("h3").text()).toBe("Risks");
    expect(focus.text()).toContain("Proposal 2 of 3");
    expect(document.activeElement).toBe(focus.get("h3").element);
    expect(pending[1]!.attributes("aria-current")).toBe("true");
    expect(pending[0]!.attributes("aria-current")).toBeUndefined();
    await expectAccessible(wrapper.element);
  });

  it("accepts the proposal on screen and moves to the next one", async () => {
    const budget = proposal("budget-id", "budget", "Circa 5.000 euro.");
    const risks = proposal("risks-id", "risks", "I volontari cambiano spesso.");
    const { api, calls } = decisionApi([budget, risks], null);
    const wrapper = mountBrief(api);
    await flushPromises();

    await wrapper.get('[data-testid="assumption-reason-toggle"]').trigger("click");
    await wrapper.get('[data-testid="assumption-reason"]').setValue("Va bene così.");
    await wrapper.get('[data-testid="assumption-accept"]').trigger("click");
    await flushPromises();
    expect(calls.accept).toEqual([["budget-id", "Va bene così."]]);
    expect(wrapper.get('[data-testid="assumption-focus"] h3').text()).toBe("Risks");
    expect(wrapper.get('[data-testid="assumption-reason"]').isVisible()).toBe(false);
    await wrapper.get('[data-testid="assumption-accept"]').trigger("click");
    await flushPromises();
    expect(calls.accept).toEqual([
      ["budget-id", "Va bene così."],
      ["risks-id", null],
    ]);
    expect(wrapper.get('[data-testid="assumptions-decided"]').text()).toContain(
      "2 accepted · 0 left open.",
    );
  });

  it("asks for the reason before leaving a proposal open", async () => {
    const budget = proposal("budget-id", "budget", "Circa 5.000 euro.");
    const risks = proposal("risks-id", "risks", "I volontari cambiano spesso.");
    const { api, calls } = decisionApi([budget, risks], null);
    const wrapper = mountBrief(api, "it");
    await flushPromises();

    const toggle = wrapper.get('[data-testid="assumption-reason-toggle"]');
    expect(toggle.attributes("aria-expanded")).toBe("false");
    expect(wrapper.get('[data-testid="assumption-reason"]').isVisible()).toBe(false);
    await wrapper.get('[data-testid="assumption-reject"]').trigger("click");
    await flushPromises();
    expect(calls.reject).toEqual([]);
    expect(wrapper.get('[role="alert"]').text()).toContain(
      "Per lasciare aperta una proposta scrivi il motivo.",
    );
    expect(toggle.attributes("aria-expanded")).toBe("true");
    expect(wrapper.get('[data-testid="assumption-reason"]').isVisible()).toBe(true);
    await wrapper.get('[data-testid="assumption-reason"]').setValue("Non serve adesso.");
    await wrapper.get('[data-testid="assumption-reject"]').trigger("click");
    await flushPromises();
    expect(calls.reject).toEqual([["budget-id", "Non serve adesso."]]);
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="assumption-focus"] h3').text()).toBe("Rischi");
    expect(wrapper.get('[data-brief-field="budget"]').text()).toContain(
      "Lasciato aperto: lo completerai più avanti.",
    );
  });

  it("puts the approval in the decision bar and keeps a change request that failed", async () => {
    const budget = proposal("budget-id", "budget", "Circa 5.000 euro.");
    let failures = 1;
    const { api, calls } = decisionApi([budget], pendingGate("PENDING_APPROVAL"), (action) => {
      if (action === "REQUEST_REVISION" && failures > 0) {
        failures -= 1;
        return new ApiError(503, "brief_gate_service_unavailable");
      }
      return pendingGate(action === "APPROVE" ? "APPROVED" : "REVISION_REQUESTED");
    });
    const wrapper = mountBrief(api);
    await flushPromises();

    const bar = wrapper.findComponent(UiDecisionBar);
    expect(bar.exists()).toBe(true);
    expect(bar.get('[data-testid="decision-primary"]').text()).toBe("Approve the brief");
    expect(bar.text()).toContain(
      "1 proposal is still to decide: if you approve now, that point stays open.",
    );
    expect(wrapper.get('[aria-labelledby="brief-gate-title"]').text()).toContain(
      "approve it or ask for changes in the bar at the bottom",
    );
    expect(wrapper.text()).not.toContain("Prepare for approval");

    await bar.get('[data-testid="decision-secondary"]').trigger("click");
    expect(bar.get("textarea").attributes("placeholder")).toBe(
      "The request is recorded with this note as its reason: then you update the brief and approve it again.",
    );
    await bar.get("textarea").setValue("Aggiungi il budget.");
    await bar.get('[data-testid="decision-send"]').trigger("click");
    await flushPromises();
    expect(calls.decide).toEqual([["REQUEST_REVISION", "Aggiungi il budget."]]);
    expect(wrapper.findAll('[role="alert"]')).toHaveLength(1);
    expect(wrapper.get('[role="alert"]').text()).toBe(
      "Could not complete the action: The Project Brief gate service is unavailable.",
    );
    expect((bar.get("textarea").element as HTMLTextAreaElement).value).toBe("Aggiungi il budget.");

    await bar.get('[data-testid="decision-send"]').trigger("click");
    await flushPromises();
    expect(calls.decide).toEqual([
      ["REQUEST_REVISION", "Aggiungi il budget."],
      ["REQUEST_REVISION", "Aggiungi il budget."],
    ]);
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
    const after = wrapper.findComponent(UiDecisionBar);
    expect(after.find("textarea").exists()).toBe(false);
    expect(after.get('[data-testid="decision-primary"]').text()).toBe("Approve the brief");
    expect(after.find('[data-testid="decision-secondary"]').exists()).toBe(false);
    expect(wrapper.get('[aria-labelledby="brief-gate-title"]').text()).toContain(
      "You asked for changes: update the brief and approve it again in the bar at the bottom.",
    );
  });

  it("approves a pending brief with one press and makes no preparation", async () => {
    const { api, calls } = decisionApi([], pendingGate("PENDING_APPROVAL"));
    const wrapper = mountBrief(api, "it");
    await flushPromises();

    const bar = wrapper.findComponent(UiDecisionBar);
    expect(bar.text()).toContain(
      "Il brief è completo. Approvandolo, potrai preparare le prospettive.",
    );
    expect(bar.text()).not.toMatch(/squadra|team/i);
    expect(bar.get('[data-testid="decision-secondary"]').text()).toBe("Chiedi modifiche");
    await expectAccessible(wrapper.element);
    expect(wrapper.emitted("sections-changed")).toBeUndefined();
    await bar.get('[data-testid="decision-primary"]').trigger("click");
    await flushPromises();
    expect(calls.order).toEqual(["APPROVE"]);
    expect(calls.decide).toEqual([["APPROVE", null]]);
    expect(wrapper.findComponent(UiDecisionBar).exists()).toBe(false);
    expect(wrapper.emitted("sections-changed")).toHaveLength(1);
  });

  it("says in English that the perspectives follow the approval of a complete brief", async () => {
    const { api } = decisionApi([], pendingGate("PENDING_APPROVAL"));
    const wrapper = mountBrief(api, "en");
    await flushPromises();

    const bar = wrapper.findComponent(UiDecisionBar);
    expect(bar.text()).toContain(
      "The brief is complete. Once you approve it, you can prepare the perspectives.",
    );
    expect(bar.text()).not.toMatch(/team|assistant/i);
  });

  it("tells the page after each decision on a proposal that the sections may have changed", async () => {
    const budget = proposal("budget-id", "budget", "Circa 5.000 euro.");
    const risks = proposal("risks-id", "risks", "I volontari cambiano spesso.");
    const { api, calls } = decisionApi([budget, risks], null);
    const wrapper = mountBrief(api);
    await flushPromises();

    await wrapper.get('[data-testid="assumption-reject"]').trigger("click");
    await flushPromises();
    expect(calls.reject).toEqual([]);
    expect(wrapper.emitted("sections-changed")).toBeUndefined();

    await wrapper.get('[data-testid="assumption-accept"]').trigger("click");
    await flushPromises();
    expect(wrapper.emitted("sections-changed")).toHaveLength(1);

    await wrapper.get('[data-testid="assumption-reason"]').setValue("Lo decidiamo dopo.");
    await wrapper.get('[data-testid="assumption-reject"]').trigger("click");
    await flushPromises();
    expect(calls.reject).toEqual([["risks-id", "Lo decidiamo dopo."]]);
    expect(wrapper.emitted("sections-changed")).toHaveLength(2);
  });

  it.each([
    ["en", false, "This step is paused."],
    ["en", true, "This section is paused."],
    ["it", false, "Questo passo è in pausa."],
    ["it", true, "Questa sezione è in pausa."],
  ] as const)(
    "names a paused brief in %s as a step or, in sections mode %s, as a section",
    async (locale, sectionsMode, sentence) => {
      const { api } = decisionApi([], pendingGate("PAUSED"));
      const wrapper = mountBrief(api, locale, { sectionsMode });
      await flushPromises();

      expect(wrapper.get('[data-testid="brief-gate-text"]').text()).toBe(sentence);
    },
  );

  it("approves a brief still to prepare with one press: it prepares it and then approves it", async () => {
    let releaseSubmit!: () => void;
    let releaseApprove: (() => void) | null = null;
    const { api, calls } = decisionApi([], null);
    const submit = api.submitProjectBriefGate.bind(api);
    const decide = api.decideProjectBriefGate.bind(api);
    api.submitProjectBriefGate = (...args) =>
      new Promise((resolve) => (releaseSubmit = () => resolve(submit(...args))));
    api.decideProjectBriefGate = (...args) =>
      new Promise((resolve) => (releaseApprove = () => resolve(decide(...args))));
    const wrapper = mountBrief(api);
    await flushPromises();

    const bar = wrapper.findComponent(UiDecisionBar);
    expect(bar.get('[data-testid="decision-primary"]').text()).toBe("Approve the brief");
    expect(bar.find('[data-testid="decision-secondary"]').exists()).toBe(false);
    expect(wrapper.find('[aria-labelledby="brief-gate-title"] button').exists()).toBe(false);
    await bar.get('[data-testid="decision-primary"]').trigger("click");
    await flushPromises();
    expect(bar.get("section").attributes("aria-busy")).toBe("true");
    expect(releaseApprove).toBeNull();
    releaseSubmit();
    await flushPromises();
    expect(calls.order).toEqual(["SUBMIT"]);
    expect(releaseApprove).not.toBeNull();
    expect(wrapper.findComponent(UiDecisionBar).get("section").attributes("aria-busy")).toBe(
      "true",
    );
    releaseApprove!();
    await flushPromises();
    expect(calls.order).toEqual(["SUBMIT", "APPROVE"]);
    expect(calls.decide).toEqual([["APPROVE", null]]);
    expect(wrapper.findComponent(UiDecisionBar).exists()).toBe(false);
  });

  it("leaves the brief pending and ready to approve when the approval after the preparation fails", async () => {
    const { api, calls } = decisionApi([], null, (action) =>
      action === "APPROVE"
        ? new ApiError(503, "brief_gate_service_unavailable")
        : pendingGate("REVISION_REQUESTED"),
    );
    const wrapper = mountBrief(api, "it");
    await flushPromises();

    await wrapper
      .findComponent(UiDecisionBar)
      .get('[data-testid="decision-primary"]')
      .trigger("click");
    await flushPromises();
    expect(calls.order).toEqual(["SUBMIT", "APPROVE"]);
    const store = useClarificationStore();
    expect(store.gate?.status).toBe("PENDING_APPROVAL");
    const bar = wrapper.findComponent(UiDecisionBar);
    expect(bar.get('[data-testid="decision-primary"]').text()).toBe("Approva il brief");
    expect(bar.get('[data-testid="decision-primary"]').attributes("disabled")).toBeUndefined();
    expect(bar.get('[data-testid="decision-secondary"]').text()).toBe("Chiedi modifiche");
    expect(wrapper.findAll('[role="alert"]')).toHaveLength(1);
    expect(wrapper.get('[role="alert"]').text()).toBe(
      "Il brief è stato preparato per l'approvazione, ma l'approvazione non è riuscita. Premi di nuovo «Approva il brief».",
    );
    await bar.get('[data-testid="decision-primary"]').trigger("click");
    await flushPromises();
    expect(calls.order).toEqual(["SUBMIT", "APPROVE", "APPROVE"]);
  });

  it("makes no approval when the preparation fails", async () => {
    const { api, calls } = decisionApi(
      [],
      null,
      () => pendingGate("APPROVED"),
      () => new ApiError(503, "brief_gate_service_unavailable"),
    );
    const wrapper = mountBrief(api);
    await flushPromises();

    await wrapper
      .findComponent(UiDecisionBar)
      .get('[data-testid="decision-primary"]')
      .trigger("click");
    await flushPromises();
    expect(calls.order).toEqual(["SUBMIT"]);
    expect(calls.decide).toEqual([]);
    const bar = wrapper.findComponent(UiDecisionBar);
    expect(bar.find('[data-testid="decision-secondary"]').exists()).toBe(false);
    expect(wrapper.get('[role="alert"]').text()).toBe(
      "Could not complete the action: The Project Brief gate service is unavailable.",
    );
  });

  it("sends the decision bar to the page target when the page offers one", async () => {
    const target = document.createElement("div");
    target.id = "step-decision-bar";
    document.body.appendChild(target);
    const { api } = decisionApi([], pendingGate("PENDING_APPROVAL"));
    const wrapper = mountBrief(api);
    await flushPromises();

    const bar = target.querySelector('[data-testid="decision-bar"]');
    expect(bar).not.toBeNull();
    expect(wrapper.element.contains(bar)).toBe(false);
    wrapper.unmount();
    expect(target.querySelector('[data-testid="decision-bar"]')).toBeNull();
    target.remove();
  });

  it("puts the technical row of the brief, with versions and decisions, after the bar of the page", async () => {
    const row = document.createElement("div");
    row.id = "step-technical-row";
    document.body.appendChild(row);
    const { api } = decisionApi([], pendingGate("PENDING_APPROVAL"));
    const authorize: AuthorizedRequest = <T>(
      operation: (accessToken: string) => Promise<T>,
    ): Promise<T> => operation("access-token");
    const wrapper = mount(ProjectClarificationFlow, {
      attachTo: document.body,
      props: {
        projectId: PROJECT_ID,
        currentBrief: REFERENCE,
        history: [briefVersion(1), briefVersion(2)],
        api,
        authorize,
      },
      global: { plugins: [createPinia(), createAppI18n("it")] },
    });
    await flushPromises();

    const details = row.querySelector<HTMLElement>('[data-testid="brief-technical-details"]');
    expect(details).not.toBeNull();
    expect(wrapper.element.querySelector('[data-testid="brief-technical-details"]')).toBeNull();
    expect(wrapper.get('[aria-labelledby="brief-gate-title"]').text()).not.toContain(
      "Decisioni precedenti",
    );
    const toggle = details!.querySelector<HTMLButtonElement>(
      '[data-testid="step-technical-details-toggle"]',
    )!;
    expect(toggle.textContent).toContain("Versione 2 · in attesa della tua decisione");
    toggle.click();
    await flushPromises();
    expect(details!.textContent).toContain("hash-2");
    expect(details!.querySelectorAll('[data-testid="brief-version"]')).toHaveLength(2);
    const decisions = details!.querySelector('[data-testid="brief-decision-history"]');
    expect(decisions?.textContent).toContain("Decisioni precedenti");
    expect(decisions?.textContent).toContain("La decisione riguarda la versione 2 · hash-2");
    wrapper.unmount();
    expect(row.childElementCount).toBe(0);
    row.remove();

    const alone = mountBrief(api);
    await flushPromises();
    expect(alone.find('[data-testid="brief-technical-details"]').exists()).toBe(true);
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
      const { api } = decisionApi([], pendingGate("PENDING_APPROVAL"));
      const authorize: AuthorizedRequest = <T>(
        operation: (accessToken: string) => Promise<T>,
      ): Promise<T> => operation("access-token");
      const Stage = defineComponent({
        props: { shown: { type: Boolean, required: true } },
        setup(stage) {
          return () =>
            withDirectives(
              h("div", [
                h(ProjectClarificationFlow, {
                  projectId: PROJECT_ID,
                  currentBrief: REFERENCE,
                  api,
                  authorize,
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
      expect(wrapper.find('[data-testid="decision-bar"]').exists()).toBe(true);

      await wrapper.setProps({ shown: true });
      await flushPromises();

      expect(bar.querySelector('[data-testid="decision-bar"]')).not.toBeNull();
      expect(row.querySelector('[data-testid="brief-technical-details"]')).not.toBeNull();
      expect(wrapper.find('[data-testid="decision-bar"]').exists()).toBe(false);
      wrapper.unmount();
    } finally {
      restore();
      bar.remove();
      row.remove();
      host.remove();
    }
  });
});
