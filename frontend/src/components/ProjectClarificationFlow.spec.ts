import { createPinia, setActivePinia } from "pinia";
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils";
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

import ProjectClarificationFlow from "./ProjectClarificationFlow.vue";

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
    expect(assumptionsSection.attributes("open")).toBeDefined();
    expect(assumptionsSection.text()).toContain("Eventi di comunità.");
    expect(wrapper.find('[data-testid="accept-all-assumptions"]').exists()).toBe(false);
    await assumptionsSection.get("button.bg-ok").trigger("click");
    await flushPromises();
    expect(acceptedId).toBe("assumption-id");
    expect(assumptionsSection.text()).toContain("Accepted");

    await wrapper.get('[aria-labelledby="brief-gate-title"] button').trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("Approval is blocked by these missing fields:");

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

    await wrapper.setProps({
      currentBrief: { id: "brief-2", version_number: 2, content_hash: "hash-2" },
    });
    expect(approval.get("button").text()).toBe("Prepare for approval");
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
    expect(wrapper.get('[aria-labelledby="assumptions-title"]').attributes("open")).toBeDefined();
    expect(wrapper.findAll("button.bg-ok")).toHaveLength(1);
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
