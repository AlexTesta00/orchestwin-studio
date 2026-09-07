import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type {
  WorkflowCheckpointPayload,
  WorkflowEventPayload,
  WorkflowRunPayload,
} from "@/types/workflowRuns";
import WorkflowRunTimeline from "./WorkflowRunTimeline.vue";

function run(status: WorkflowRunPayload["status"] = "RUNNING"): WorkflowRunPayload {
  return {
    id: "run-1",
    project_id: "project-1",
    owner_user_id: "owner-1",
    project_mode: "GREENFIELD_GENERATION",
    current_stage: "SYNTHETIC_EVALUATION",
    status,
    artifact_references: [],
    pending_gate_id: null,
    latest_source_revision_id: null,
    latest_execution_attempt_id: null,
    latest_evaluation_run_id: null,
    iteration_counters: {
      clarification_count: 0,
      requirements_revision_count: 0,
      design_cycle_count: 1,
      architecture_revision_count: 0,
      failure_counters: [],
    },
    budget_state: {
      model_calls: 2,
      input_tokens: 100,
      output_tokens: 50,
      estimated_cost_micros: 1000,
      sandbox_elapsed_seconds: 8,
      project_elapsed_seconds: 20,
    },
    capability_state: {
      selected_profile: null,
      capability_status: "DESIGN_ONLY_LEVEL_C",
      unsupported_requirements: [],
      owner_decision_required: false,
    },
    blocking_issues: [],
    last_error: null,
    state_version: 3,
    checkpoint_sequence: 2,
    created_at: "2026-08-30T13:00:00Z",
    updated_at: "2026-08-30T13:00:03Z",
    started_at: "2026-08-30T13:00:01Z",
    completed_at: null,
    resume_status: status === "PAUSED" ? "RUNNING" : null,
  };
}

const checkpoints: WorkflowCheckpointPayload[] = [
  {
    id: "checkpoint-2",
    run_id: "run-1",
    project_id: "project-1",
    owner_user_id: "owner-1",
    sequence_number: 2,
    state_version: 3,
    created_at: "2026-08-30T13:00:03Z",
    parent_checkpoint_id: "checkpoint-1",
    state_hash: "hash-2",
  },
  {
    id: "checkpoint-1",
    run_id: "run-1",
    project_id: "project-1",
    owner_user_id: "owner-1",
    sequence_number: 1,
    state_version: 2,
    created_at: "2026-08-30T13:00:01Z",
    parent_checkpoint_id: null,
    state_hash: "hash-1",
  },
];

const events: WorkflowEventPayload[] = [
  {
    id: "event-2",
    run_id: "run-1",
    project_id: "project-1",
    owner_user_id: "owner-1",
    sequence_number: 2,
    event_type: "workflow.waiting_for_human",
    occurred_at: "2026-08-30T13:00:03Z",
    payload: {},
    payload_hash: "hash-2",
  },
  {
    id: "event-1",
    run_id: "run-1",
    project_id: "project-1",
    owner_user_id: "owner-1",
    sequence_number: 1,
    event_type: "workflow.run.started",
    occurred_at: "2026-08-30T13:00:01Z",
    payload: {},
    payload_hash: "hash-1",
  },
];

describe("WorkflowRunTimeline", () => {
  it("renders an ordered textual alternative for checkpoints and events", () => {
    const wrapper = mount(WorkflowRunTimeline, {
      props: { run: run(), checkpoints, events },
    });

    expect(wrapper.get("[data-testid='workflow-stage']").text()).toBe("SYNTHETIC_EVALUATION");
    expect(
      wrapper
        .findAll("[data-event-sequence]")
        .map((item) => item.attributes("data-event-sequence")),
    ).toEqual(["1", "2"]);
    expect(wrapper.text().indexOf("Checkpoint 1")).toBeLessThan(
      wrapper.text().indexOf("Checkpoint 2"),
    );
    expect(wrapper.text()).toContain("distinct from empirical target-user validation");
  });

  it("emits only currently legal owner controls", async () => {
    const running = mount(WorkflowRunTimeline, { props: { run: run() } });
    const buttons = running.findAll("button");

    expect(buttons[0]?.attributes("disabled")).toBeUndefined();
    expect(buttons[1]?.attributes("disabled")).toBeDefined();
    await buttons[0]?.trigger("click");
    await buttons[2]?.trigger("click");
    await buttons[3]?.trigger("click");

    expect(running.emitted("lifecycle")).toEqual([["pause"], ["cancel"]]);
    expect(running.emitted("replay")).toEqual([[]]);

    const paused = mount(WorkflowRunTimeline, { props: { run: run("PAUSED") } });
    const pausedButtons = paused.findAll("button");
    expect(pausedButtons[0]?.attributes("disabled")).toBeDefined();
    expect(pausedButtons[1]?.attributes("disabled")).toBeUndefined();
  });

  it("renders Italian labels without changing technical state values", () => {
    const wrapper = mount(WorkflowRunTimeline, {
      props: { run: run(), locale: "it", events },
    });

    expect(wrapper.text()).toContain("Timeline e controlli della run");
    expect(wrapper.text()).toContain("Riproduci nuovi eventi");
    expect(wrapper.text()).toContain("SYNTHETIC_EVALUATION");
    expect(wrapper.text()).toContain("validazione empirica con utenti target");
  });
});
