import { createPinia, setActivePinia } from "pinia";
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ApiError } from "@/api/client";
import type {
  ClarificationAnswerInput,
  ClarificationRoundResponse,
  HumanGateResponse,
  ProjectWorkflowApi,
} from "@/api/workflow-contracts";
import { createAppI18n } from "@/i18n";
import type { AuthorizedRequest } from "@/stores/clarification";
import { useClarificationStore } from "@/stores/clarification";

import ProjectClarificationFlow from "./ProjectClarificationFlow.vue";

enableAutoUnmount(afterEach);

const PROJECT_ID = "project-id";

const ROUND: ClarificationRoundResponse = {
  id: "round-id",
  project_id: PROJECT_ID,
  source_brief_version_number: 1,
  round_number: 1,
  catalog_version: 1,
  questions: [
    {
      question_id: "project-brief.description.v1",
      catalog_version: 1,
      field: "description",
      answer_type: "text",
      priority: 2,
      prompt_key: "clarification.questions.description.prompt",
      hint_key: "clarification.questions.description.hint",
      unknown_allowed: true,
    },
  ],
  status: "OPEN",
  created_by_user_id: "owner-id",
  created_at: "2026-08-12T12:00:00Z",
  answered_at: null,
  resulting_brief_version_number: null,
};

describe("ProjectClarificationFlow", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("submits a typed clarification answer", async () => {
    let currentRoundAvailable = true;
    let submittedAnswers: readonly ClarificationAnswerInput[] = [];

    const api: ProjectWorkflowApi = {
      async startProjectClarificationRound() {
        return {
          status: "OPEN_ROUND_EXISTS",
          round: ROUND,
        };
      },

      async listProjectClarificationRounds() {
        return [ROUND];
      },

      async getCurrentProjectClarificationRound() {
        if (!currentRoundAvailable) {
          throw new ApiError(404, "clarification_round_not_found");
        }

        return ROUND;
      },

      async answerProjectClarificationRound(_accessToken, _projectId, _roundId, answers) {
        submittedAnswers = answers;
        currentRoundAvailable = false;

        return {
          status: "APPLIED",
          round: {
            ...ROUND,
            status: "ANSWERED",
            answered_at: "2026-08-12T12:05:00Z",
            resulting_brief_version_number: 2,
          },
          brief_version: null,
          next_step: "CLARIFICATION_REQUIRED",
          issues: [],
          invalid_question_ids: [],
        };
      },

      async listProjectBriefAssumptions() {
        return [];
      },

      async createProjectBriefAssumption() {
        return {
          status: "CREATED",
          assumption: null,
        };
      },

      async acceptProjectBriefAssumption() {
        return {
          status: "ASSUMPTION_NOT_FOUND",
          assumption: null,
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

    await wrapper
      .get('[data-testid="question-description-text"]')
      .setValue("A clarified description.");

    await wrapper.get('[data-testid="clarification-answer-form"]').trigger("submit");

    await flushPromises();

    expect(submittedAnswers).toEqual([
      {
        question_id: "project-brief.description.v1",
        kind: "text",
        text_value: "A clarified description.",
      },
    ]);

    expect(wrapper.text()).toContain("Another clarification round is required");

    // An approved idea is complete, but editing it must allow a fresh approval.
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
      created_at: ROUND.created_at,
      updated_at: ROUND.created_at,
      resume_status: null,
    } satisfies HumanGateResponse;
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
