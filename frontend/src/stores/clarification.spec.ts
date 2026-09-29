import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import type { ProjectBriefVersionResponse } from "@/api/contracts";
import type {
  BriefAssumptionResponse,
  HumanGateResponse,
  ProjectWorkflowApi,
} from "@/api/workflow-contracts";

import { type AuthorizedRequest, useClarificationStore } from "./clarification";

const PROJECT_ID = "project-id";
const GATE_ID = "gate-id";

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

const BRIEF_VERSION: ProjectBriefVersionResponse = {
  id: "brief-version-2",
  project_id: PROJECT_ID,
  version_number: 2,
  schema_version: 1,
  content_hash: "b".repeat(64),
  created_by_user_id: "owner-id",
  created_at: "2026-08-12T12:02:00Z",
  brief: {
    name: "Project",
    description: null,
    problem: null,
    goals: null,
    target_users: null,
    domain: null,
    technical_constraints: null,
    temporal_constraints: null,
    budget: "Approximately EUR 5,000.",
    functional_requirements: null,
    non_functional_requirements: null,
    risks: null,
    stakeholders: null,
    available_artifacts: null,
    definition_of_done: null,
    unknown_fields: [],
    provided_fields: ["name", "budget"],
    missing_fields: [],
  },
};

const authorize: AuthorizedRequest = <T>(
  operation: (accessToken: string) => Promise<T>,
): Promise<T> => operation("access-token");

function buildApi(): ProjectWorkflowApi {
  let assumptions: readonly BriefAssumptionResponse[] = [ASSUMPTION];

  return {
    async listProjectBriefAssumptions() {
      return assumptions;
    },

    async createProjectBriefAssumption() {
      return {
        status: "CREATED",
        assumption: ASSUMPTION,
      };
    },

    async acceptProjectBriefAssumption() {
      assumptions = [{ ...ASSUMPTION, status: "ACCEPTED" }];

      return {
        status: "ACCEPTED",
        assumption: assumptions[0] ?? null,
        brief_version: null,
      };
    },

    async acceptAllProjectBriefAssumptions() {
      assumptions = [{ ...ASSUMPTION, status: "ACCEPTED" }];

      return {
        status: "ACCEPTED",
        accepted: assumptions,
        skipped: [],
        brief_version: BRIEF_VERSION,
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

  it("loads assumptions, gate, and audit events", async () => {
    const store = useClarificationStore();

    const loaded = await store.load(PROJECT_ID, buildApi(), authorize);

    expect(loaded).toBe(true);
    expect(store.assumptions).toEqual([ASSUMPTION]);
    expect(store.gate).toEqual(GATE);
    expect(store.gateEvents).toHaveLength(1);
    expect(store.errorDetail).toBeNull();
  });

  it("records an accepted assumption and refreshes the list", async () => {
    const store = useClarificationStore();
    const api = buildApi();

    await store.load(PROJECT_ID, api, authorize);

    const result = await store.acceptAssumption(PROJECT_ID, ASSUMPTION.id, null, api, authorize);

    expect(result?.status).toBe("ACCEPTED");
    expect(store.lastAssumptionDecision?.assumption?.status).toBe("ACCEPTED");
    expect(store.assumptions[0]?.status).toBe("ACCEPTED");
  });

  it("accepts every proposal at once and announces the new brief version", async () => {
    const store = useClarificationStore();
    const api = buildApi();
    const acceptAll = vi.spyOn(api, "acceptAllProjectBriefAssumptions");

    await store.load(PROJECT_ID, api, authorize);

    const result = await store.acceptAllAssumptions(
      PROJECT_ID,
      "Confirmed together.",
      api,
      authorize,
    );

    expect(acceptAll).toHaveBeenCalledWith("access-token", PROJECT_ID, "Confirmed together.");
    expect(result?.status).toBe("ACCEPTED");
    expect(store.lastBulkAcceptance).toEqual(result);
    expect(store.lastAssumptionDecision).toEqual({
      status: "ACCEPTED",
      assumption: { ...ASSUMPTION, status: "ACCEPTED" },
      brief_version: BRIEF_VERSION,
    });
    expect(store.assumptions[0]?.status).toBe("ACCEPTED");
    expect(store.busy).toBe(false);
    expect(store.errorDetail).toBeNull();
  });

  it("keeps the brief version untouched when no proposal can be accepted", async () => {
    const store = useClarificationStore();
    const api = buildApi();

    api.acceptAllProjectBriefAssumptions = async () => ({
      status: "NOTHING_TO_ACCEPT",
      accepted: [],
      skipped: [ASSUMPTION],
      brief_version: null,
    });

    await store.load(PROJECT_ID, api, authorize);

    const result = await store.acceptAllAssumptions(PROJECT_ID, null, api, authorize);

    expect(result?.status).toBe("NOTHING_TO_ACCEPT");
    expect(store.lastBulkAcceptance?.skipped).toEqual([ASSUMPTION]);
    expect(store.lastAssumptionDecision).toBeNull();
    expect(store.errorDetail).toBeNull();
  });

  it("forgets the bulk outcome once a single proposal is decided", async () => {
    const store = useClarificationStore();
    const api = buildApi();

    await store.load(PROJECT_ID, api, authorize);
    await store.acceptAllAssumptions(PROJECT_ID, null, api, authorize);
    await store.rejectAssumption(PROJECT_ID, ASSUMPTION.id, "Not supported.", api, authorize);

    expect(store.lastBulkAcceptance).toBeNull();
    expect(store.lastAssumptionDecision?.status).toBe("REJECTED");
  });

  it("treats a missing gate as an empty workflow state", async () => {
    const api = buildApi();

    api.getCurrentProjectBriefGate = async () => {
      throw new ApiError(404, "project_brief_gate_not_found");
    };

    const store = useClarificationStore();

    const loaded = await store.load(PROJECT_ID, api, authorize);

    expect(loaded).toBe(true);
    expect(store.gate).toBeNull();
    expect(store.gateEvents).toEqual([]);
  });
});
