import { describe, expect, it, vi } from "vitest";

import type { WorkflowRunPayload } from "../types/workflowRuns";
import { createWorkflowRunsApi, WorkflowRunsApiError } from "./workflowRuns";

function run(): WorkflowRunPayload {
  return {
    id: "run-1",
    project_id: "project-1",
    owner_user_id: "owner-1",
    project_mode: "GREENFIELD_GENERATION",
    current_stage: "INTAKE",
    status: "RUNNING",
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
    state_version: 2,
    checkpoint_sequence: 1,
    created_at: "2026-08-30T13:00:00+00:00",
    updated_at: "2026-08-30T13:00:01+00:00",
    started_at: "2026-08-30T13:00:01+00:00",
    completed_at: null,
    resume_status: null,
  };
}

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("workflow runs API", () => {
  it("sends authenticated resource and lifecycle requests", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/checkpoints")) {
        return jsonResponse({ items: [] });
      }
      if (url.includes("/projects/") && url.endsWith("/runs")) {
        return jsonResponse({ items: [run()] });
      }
      return jsonResponse({ snapshot: run(), status: "COMMAND_APPLIED", message: "Applied." });
    });
    const api = createWorkflowRunsApi({ fetchImpl });

    expect((await api.runs("project-1", "token"))[0]?.id).toBe("run-1");
    expect((await api.run("run-1", "token")).status).toBe("RUNNING");
    expect(await api.checkpoints("run-1", "token")).toEqual([]);
    await api.applyLifecycle(
      "run-1",
      "pause",
      {
        command_id: "command-1",
        project_id: "project-1",
        expected_state_version: 2,
        expected_checkpoint_sequence: 1,
        occurred_at: "2026-08-30T13:00:02+00:00",
        reason: "Pause.",
        authorization_reference: null,
      },
      "token",
    );

    const lifecycleCall = fetchImpl.mock.calls.at(-1);
    expect(String(lifecycleCall?.[0])).toBe("/api/v1/runs/run-1/pause");
    const request = lifecycleCall?.[1];
    expect(request?.method).toBe("POST");
    expect(new Headers(request?.headers).get("Authorization")).toBe("Bearer token");
  });

  it("parses ordered SSE data and reports typed failures", async () => {
    const eventText = [
      'id: 2\nevent: workflow.waiting_for_human\ndata: {"id":"event-2","run_id":"run-1","project_id":"project-1","owner_user_id":"owner-1","sequence_number":2,"event_type":"workflow.waiting_for_human","occurred_at":"2026-08-30T13:00:02+00:00","payload":{},"payload_hash":"hash-2"}',
      'id: 3\nevent: workflow.resumed\ndata: {"id":"event-3","run_id":"run-1","project_id":"project-1","owner_user_id":"owner-1","sequence_number":3,"event_type":"workflow.resumed","occurred_at":"2026-08-30T13:00:03+00:00","payload":{},"payload_hash":"hash-3"}',
    ].join("\n\n");
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(new Response(eventText));
    const api = createWorkflowRunsApi({ fetchImpl });

    const events = await api.replayEvents("run-1", 1, "token");
    expect(events.map((event) => event.sequence_number)).toEqual([2, 3]);
    expect(String(fetchImpl.mock.calls[0]?.[0])).toContain("after_sequence=1");

    await expect(api.replayEvents("run-1", -1, "token")).rejects.toMatchObject({
      code: "WORKFLOW_EVENT_CURSOR_INVALID",
    });

    const failingApi = createWorkflowRunsApi({
      fetchImpl: vi
        .fn()
        .mockResolvedValue(jsonResponse({ detail: { code: "WORKFLOW_RUN_NOT_FOUND" } }, 404)),
    });
    await expect(failingApi.run("missing", "token")).rejects.toBeInstanceOf(WorkflowRunsApiError);
  });
});
