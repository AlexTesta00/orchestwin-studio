import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { JvmExecutionApi } from "../api/jvmExecution";
import type {
  JvmExecutionAttemptPayload,
  JvmExecutionReportPayload,
  JvmSourceRevisionPayload,
} from "../types/jvmExecution";
import { useJvmExecutionStore } from "./jvmExecution";

const authorize = async <T>(operation: (accessToken: string) => Promise<T>): Promise<T> =>
  operation("token");
const selection = {
  target: "JVM_KOTLIN" as const,
  language: "KOTLIN",
  build_system: "GRADLE_KOTLIN_DSL",
  layout: "SINGLE_MODULE",
  jdk_major: 21,
};

function revision(id: string, version: number): JvmSourceRevisionPayload {
  return {
    id,
    project_id: "project-1",
    version_number: version,
    based_on: null,
    target_selection: selection,
    origin: "DETERMINISTIC_FIXTURE",
    files: [],
    provenance_references: [],
    related_failure_signature: null,
    source_tree_hash: "a".repeat(64),
    content_hash: "b".repeat(64),
  };
}
function report(status: "PASSED" | "FAILED" = "PASSED"): JvmExecutionReportPayload {
  return {
    target_selection: selection,
    execution_plan_content_hash: "c".repeat(64),
    status,
    phase_results: [],
    failure_signatures: [],
  };
}
function execution(id: string, attemptNumber: number): JvmExecutionAttemptPayload {
  return {
    id,
    project_id: "project-1",
    attempt_number: attemptNumber,
    previous_attempt_id: attemptNumber === 1 ? null : "execution-1",
    source_revision: {
      revision_id: "revision-1",
      project_id: "project-1",
      version_number: 1,
      content_hash: "b".repeat(64),
      source_tree_hash: "a".repeat(64),
    },
    profile_id: "jvm.kotlin-gradle",
    profile_version: "1.0.0",
    profile_validation_content_hash: "d".repeat(64),
    execution_plan_content_hash: "c".repeat(64),
    runner_id: "jvm.gradle",
    runner_version: "1.0.0",
    runner_image_digest: "e".repeat(64),
    policy_content_hash: "f".repeat(64),
    trigger: "PROFILE_VALIDATION",
    executed_phases: ["VALIDATE"],
    report: report(),
    started_at: "2026-08-28T19:00:00+00:00",
    completed_at: "2026-08-28T19:00:01+00:00",
    content_hash: "1".repeat(64),
  };
}
function api(): JvmExecutionApi {
  return {
    profiles: vi.fn().mockResolvedValue([
      {
        profile_id: "jvm.kotlin-gradle",
        profile_version: "1.0.0",
        target: "JVM_KOTLIN",
        capability_status: "DESIGN_ONLY_LEVEL_C",
      },
    ]),
    sourceRevisions: vi
      .fn()
      .mockResolvedValue([revision("revision-2", 2), revision("revision-1", 1)]),
    sourceRevision: vi.fn().mockResolvedValue(revision("revision-1", 1)),
    createSourceRevision: vi.fn().mockResolvedValue(revision("revision-3", 3)),
    executions: vi
      .fn()
      .mockResolvedValue([execution("execution-2", 2), execution("execution-1", 1)]),
    execution: vi.fn().mockResolvedValue(execution("execution-2", 2)),
    executionReport: vi.fn().mockResolvedValue(report("FAILED")),
    startExecution: vi.fn().mockResolvedValue(execution("execution-3", 3)),
    repairProposals: vi.fn().mockResolvedValue([
      {
        id: "proposal-1",
        project_id: "project-1",
        base_revision: execution("execution-1", 1).source_revision,
        failure_signature: {
          category: "TEST",
          phase: "TEST",
          failure_code: "JVM_TEST_FAILED",
          normalized_message: "test failed",
          signature: "2".repeat(64),
        },
        attempt_number: 1,
        identical_failure_occurrences: 1,
        created_at: "2026-08-28T19:00:00+00:00",
      },
    ]),
    createRepairProposal: vi.fn().mockResolvedValue({
      id: "proposal-2",
      project_id: "project-1",
      base_revision: execution("execution-1", 1).source_revision,
      failure_signature: {
        category: "TEST",
        phase: "TEST",
        failure_code: "JVM_TEST_FAILED",
        normalized_message: "test failed",
        signature: "2".repeat(64),
      },
      attempt_number: 1,
      identical_failure_occurrences: 1,
      created_at: "2026-08-28T19:00:00+00:00",
    }),
    applyRepairProposal: vi.fn().mockResolvedValue(revision("revision-3", 3)),
  };
}

describe("JVM execution store", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("loads sorted profiles, revisions, executions, and current selections", async () => {
    const store = useJvmExecutionStore();
    await store.loadProject("project-1", authorize, api());
    expect(store.sourceRevisions.map((item) => item.id)).toEqual(["revision-1", "revision-2"]);
    expect(store.executions.map((item) => item.id)).toEqual(["execution-1", "execution-2"]);
    expect(store.selectedProfile?.profile_id).toBe("jvm.kotlin-gradle");
  });

  it("loads normalized evidence and repair proposals", async () => {
    const store = useJvmExecutionStore();
    const client = api();
    await store.loadProject("project-1", authorize, client);
    await store.loadExecution("project-1", "execution-2", authorize, client);
    expect(store.selectedReport?.status).toBe("FAILED");
    expect(store.repairProposals[0]?.id).toBe("proposal-1");
  });

  it("records source, execution, and repair mutations in project state", async () => {
    const store = useJvmExecutionStore();
    const client = api();
    await store.loadProject("project-1", authorize, client);
    await store.createSourceRevision(
      "project-1",
      { target: "JVM_KOTLIN", rationale: "Create revision.", files: [], provenance_references: [] },
      authorize,
      client,
    );
    await store.startExecution(
      "project-1",
      {
        source_revision_id: "revision-3",
        profile_id: "jvm.kotlin-gradle",
        profile_version: "1.0.0",
        policy_content_hash: "f".repeat(64),
        runner_image_digest: "e".repeat(64),
        purpose: "PROFILE_VALIDATION",
        trigger: "PROFILE_VALIDATION",
        authorization_id: "authorization-1",
        rerun_phases: null,
      },
      authorize,
      client,
    );
    await store.createRepairProposal(
      "project-1",
      "execution-3",
      {
        base_revision_content_hash: "b".repeat(64),
        failure_signature: "2".repeat(64),
        changes: [],
        rationale: "Repair.",
      },
      authorize,
      client,
    );
    await store.applyRepairProposal(
      "project-1",
      "execution-3",
      "proposal-2",
      {
        base_revision_content_hash: "b".repeat(64),
        proposal_content_hash: "3".repeat(64),
        approval_id: null,
      },
      authorize,
      client,
    );
    expect(store.currentSourceRevision?.id).toBe("revision-3");
    expect(store.currentExecution?.id).toBe("execution-3");
    expect(store.repairProposals.at(-1)?.id).toBe("proposal-2");
  });
});
