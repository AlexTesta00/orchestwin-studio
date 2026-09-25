import { createPinia, setActivePinia } from "pinia";
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ApiError } from "@/api/client";
import type {
  BriefAssumptionResponse,
  HumanGateResponse,
  ProjectWorkflowApi,
} from "@/api/workflow-contracts";
import { createAppI18n } from "@/i18n";
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
});
