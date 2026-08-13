import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import { ApiError } from "@/api/client";
import type {
  BriefAssumptionResponse,
  ClarificationRoundResponse,
  HumanGateResponse,
  ProjectWorkflowApi,
} from "@/api/workflow-contracts";

import { type AuthorizedRequest, useClarificationStore } from "./clarification";

const PROJECT_ID = "project-id";
const ROUND_ID = "round-id";
const GATE_ID = "gate-id";

const ROUND: ClarificationRoundResponse = {
  id: ROUND_ID,
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

const ASSUMPTION: BriefAssumptionResponse = {
  id: "assumption-id",
  project_id: PROJECT_ID,
  brief_version_number: 1,
  field: "budget",
  statement: "Approximately EUR 5,000.",
  source: "OWNER_PROVIDED",
  status: "PROPOSED",
  created_by_user_id: "owner-id",
  created_at: "2026-08-12T12:00:00Z",
  decided_by_user_id: null,
  decided_at: null,
  decision_reason: null,
};

const GATE: HumanGateResponse = {
  id: GATE_ID,
  project_id: PROJECT_ID,
  owner_user_id: "owner-id",
  gate_type: "PROJECT_BRIEF",
  artifact: {
    project_id: PROJECT_ID,
    gate_type: "PROJECT_BRIEF",
    artifact_id: "brief-version-id",
    version: 1,
    content_hash: "a".repeat(64),
  },
  iteration: 1,
  max_iterations: 3,
  status: "PENDING_APPROVAL",
  created_at: "2026-08-12T12:00:00Z",
  updated_at: "2026-08-12T12:01:00Z",
  event_sequence: 1,
  resume_status: null,
};

const authorize: AuthorizedRequest = <T>(
  operation: (accessToken: string) => Promise<T>,
): Promise<T> => operation("access-token");

function buildApi(): ProjectWorkflowApi {
  return {
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
      return ROUND;
    },

    async answerProjectClarificationRound() {
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
      return [ASSUMPTION];
    },

    async createProjectBriefAssumption() {
      return {
        status: "CREATED",
        assumption: ASSUMPTION,
      };
    },

    async acceptProjectBriefAssumption() {
      return {
        status: "ACCEPTED",
        assumption: {
          ...ASSUMPTION,
          status: "ACCEPTED",
        },
        brief_version: null,
      };
    },

    async rejectProjectBriefAssumption() {
      return {
        status: "REJECTED",
        assumption: {
          ...ASSUMPTION,
          status: "REJECTED",
          decision_reason: "Not supported.",
        },
        brief_version: null,
      };
    },

    async submitProjectBriefGate() {
      return {
        status: "ALREADY_PENDING",
        gate: GATE,
        events: [],
        missing_fields: [],
        issue: null,
      };
    },

    async getCurrentProjectBriefGate() {
      return GATE;
    },

    async listProjectBriefGateEvents() {
      return [
        {
          id: "event-id",
          gate_id: GATE_ID,
          sequence_number: 1,
          kind: "SUBMIT",
          previous_status: "DRAFT",
          resulting_status: "PENDING_APPROVAL",
          artifact: GATE.artifact,
          occurred_at: "2026-08-12T12:01:00Z",
          actor_user_id: "owner-id",
          reason: null,
        },
      ];
    },

    async decideProjectBriefGate() {
      return {
        status: "APPLIED",
        gate: {
          ...GATE,
          status: "APPROVED",
          event_sequence: 2,
        },
        event: null,
        issue: null,
      };
    },
  };
}

describe("useClarificationStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("loads rounds, assumptions, gate, and audit events", async () => {
    const store = useClarificationStore();

    const loaded = await store.load(PROJECT_ID, buildApi(), authorize);

    expect(loaded).toBe(true);
    expect(store.currentRound).toEqual(ROUND);
    expect(store.roundHistory).toEqual([ROUND]);
    expect(store.assumptions).toEqual([ASSUMPTION]);
    expect(store.gate).toEqual(GATE);
    expect(store.gateEvents).toHaveLength(1);
    expect(store.errorDetail).toBeNull();
  });

  it("records an applied answer result", async () => {
    const store = useClarificationStore();
    const api = buildApi();

    await store.load(PROJECT_ID, api, authorize);

    const result = await store.answerRound(
      PROJECT_ID,
      [
        {
          question_id: "project-brief.description.v1",
          kind: "text",
          text_value: "A clarified description.",
        },
      ],
      api,
      authorize,
    );

    expect(result?.status).toBe("APPLIED");
    expect(store.lastRoundAnswer?.next_step).toBe("CLARIFICATION_REQUIRED");
  });

  it("treats missing current resources as an empty workflow state", async () => {
    const api = buildApi();

    api.getCurrentProjectClarificationRound = async () => {
      throw new ApiError(404, "clarification_round_not_found");
    };

    api.getCurrentProjectBriefGate = async () => {
      throw new ApiError(404, "project_brief_gate_not_found");
    };

    const store = useClarificationStore();

    const loaded = await store.load(PROJECT_ID, api, authorize);

    expect(loaded).toBe(true);
    expect(store.currentRound).toBeNull();
    expect(store.gate).toBeNull();
    expect(store.gateEvents).toEqual([]);
  });
});
