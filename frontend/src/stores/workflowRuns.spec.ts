import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { WorkflowRunsApi } from "../api/workflowRuns";
import type { WorkflowEventPayload, WorkflowRunPayload } from "../types/workflowRuns";
import { useWorkflowRunsStore } from "./workflowRuns";

const authorize = async <T>(operation: (accessToken: string) => Promise<T>): Promise<T> =>
  operation("token");

function run(id: string, status: WorkflowRunPayload["status"] = "RUNNING"): WorkflowRunPayload {
  return {
    id,
    project_id: "project-1",
    owner_user_id: "owner-1",
    project_mode: "GREENFIELD_GENERATION",
    current_stage: "INTAKE",
    status,
    artifact_references: [],
    pending_gate_id: null,
    latest_source_revision_id: null,
    latest_execution_attempt_id: null,
    latest_evaluation_run_id: null,
    iteration_counters: {
      clarification_count: 0,
      requirements_revision_count: 0,
      design_cycle_count: 0,
      architecture_revision_count: 0,
      failure_counters: [],
    },
    budget_state: {
      model_calls: 0,
      input_tokens: 0,
      output_tokens: 0,
      estimated_cost_micros: 0,
      sandbox_elapsed_seconds: 0,
      project_elapsed_seconds: 0,
    },
    capability_state: {
      selected_profile: null,
      capability_status: null,
      unsupported_requirements: [],
      owner_decision_required: false,
    },
    blocking_issues: [],
    last_error: null,
    state_version: status === "PAUSED" ? 3 : 2,
    checkpoint_sequence: status === "PAUSED" ? 2 : 1,
    created_at: id === "run-1" ? "2026-08-30T12:00:00Z" : "2026-08-30T13:00:00Z",
    updated_at: "2026-08-30T13:00:00Z",
    started_at: "2026-08-30T12:00:01Z",
    completed_at: null,
    resume_status: status === "PAUSED" ? "RUNNING" : null,
  };
}

function event(sequence: number): WorkflowEventPayload {
  return {
    id: `event-${sequence}`,
    run_id: "run-2",
    project_id: "project-1",
    owner_user_id: "owner-1",
    sequence_number: sequence,
    event_type: sequence === 1 ? "workflow.run.started" : "workflow.paused",
    occurred_at: `2026-08-30T13:00:0${sequence}Z`,
    payload: {},
    payload_hash: `hash-${sequence}`,
  };
}

function api(): WorkflowRunsApi {
  return {
    createRun: vi.fn().mockResolvedValue(run("run-3")),
    runs: vi.fn().mockResolvedValue([run("run-2"), run("run-1")]),
    run: vi.fn().mockResolvedValue(run("run-2")),
    checkpoints: vi.fn().mockResolvedValue([
      {
        id: "checkpoint-1",
        run_id: "run-2",
        project_id: "project-1",
        owner_user_id: "owner-1",
        sequence_number: 1,
        state_version: 2,
        created_at: "2026-08-30T13:00:01Z",
        parent_checkpoint_id: null,
        state_hash: "hash",
      },
    ]),
    applyLifecycle: vi.fn().mockResolvedValue(run("run-2", "PAUSED")),
    replayEvents: vi.fn().mockResolvedValue([event(2), event(1)]),
  };
}

describe("workflow runs store", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("loads and selects durable workflow resources", async () => {
    const store = useWorkflowRunsStore();
    const client = api();

    await store.loadProject("project-1", authorize, client);
    expect(store.runs.map((item) => item.id)).toEqual(["run-1", "run-2"]);

    await store.selectRun("run-2", authorize, client);
    expect(store.selectedRun?.id).toBe("run-2");
    expect(store.checkpoints[0]?.sequence_number).toBe(1);
    expect(store.canPause).toBe(true);
  });

  it("applies lifecycle commands and merges replayed events idempotently", async () => {
    const store = useWorkflowRunsStore();
    const client = api();
    await store.loadProject("project-1", authorize, client);
    await store.selectRun("run-2", authorize, client);

    await store.replayEvents(authorize, client);
    await store.replayEvents(authorize, client);
    expect(store.events.map((item) => item.sequence_number)).toEqual([1, 2]);

    await store.applyLifecycle(
      "pause",
      {
        command_id: "command-1",
        project_id: "project-1",
        expected_state_version: 2,
        expected_checkpoint_sequence: 1,
        occurred_at: "2026-08-30T13:00:03Z",
        reason: "Pause.",
        authorization_reference: null,
      },
      authorize,
      client,
    );
    expect(store.selectedRun?.status).toBe("PAUSED");
    expect(store.canResume).toBe(true);
  });
});
