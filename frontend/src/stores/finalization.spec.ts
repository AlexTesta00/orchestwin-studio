import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { FinalizationApi } from "../api/finalization";
import type {
  EvaluationAggregationPayload,
  FinalReviewPayload,
  SyntheticEvaluationRunPayload,
  SyntheticFindingPayload,
} from "../types/finalization";
import { useFinalizationStore } from "./finalization";

const authorize = async <T>(operation: (accessToken: string) => Promise<T>): Promise<T> =>
  operation("token");

function review(version: number): FinalReviewPayload {
  return {
    review_id: `review-${version}`,
    project_id: "project-1",
    workflow_run_id: "run-1",
    owner_user_id: "owner-1",
    version_number: version,
    parent_review_id: version === 1 ? null : `review-${version - 1}`,
    parent_content_hash: version === 1 ? null : "b".repeat(64),
    workflow_state_version: version + 2,
    checks: [],
    unresolved_issues: [],
    accepted_limitations: [],
    latest_execution_attempt_id: "execution-1",
    latest_evaluation_run_id: "evaluation-1",
    evaluation_aggregation_hash: "a".repeat(64),
    capability_status: "DESIGN_ONLY_LEVEL_C",
    human_validation_status: "PLANNED",
    created_at: "2026-08-31T04:00:00Z",
    content_hash: "c".repeat(64),
    ready_for_gate8: true,
    blocking_check_ids: [],
    blocking_issue_ids: [],
    owner_approval_is_empirical_validation: false,
  };
}

function api(): FinalizationApi {
  const evaluation: SyntheticEvaluationRunPayload = {
    id: "evaluation-1",
    project_id: "project-1",
    workflow_run_id: "run-1",
    owner_user_id: "owner-1",
    artifact_bundle_id: "bundle-1",
    artifact_bundle_hash: "a".repeat(64),
    status: "COMPLETED",
    response_count: 2,
    finding_count: 2,
    started_at: "2026-08-31T03:00:00Z",
    completed_at: "2026-08-31T03:00:01Z",
    content_hash: "b".repeat(64),
    simulated_feedback: true,
  };
  const findings: SyntheticFindingPayload[] = [
    {
      finding_id: "UTF-001",
      twin_id: "twin-1",
      twin_version: 1,
      artifact_id: "artifact-1",
      artifact_version: 1,
      location: "screen:home",
      summary: "Model finding.",
      rationale: "Role-specific rationale.",
      criterion: "usefulness",
      severity: "moderate",
      epistemic_status: "MODEL_INFERRED",
      evidence_refs: ["evidence:1"],
      confidence: 0.7,
      recommended_action: "Review the flow.",
      requires_human_validation: true,
      model_config_ref: "model-1",
      prompt_version_ref: "prompt-1",
      origin: "MODEL_GENERATED",
    },
    {
      finding_id: "DET-001",
      twin_id: "twin-1",
      twin_version: 1,
      artifact_id: "artifact-1",
      artifact_version: 1,
      location: "test:primary",
      summary: "Deterministic failure.",
      rationale: "The test failed.",
      criterion: "task_alignment",
      severity: "major",
      epistemic_status: "USER_PROVIDED",
      evidence_refs: ["test:1"],
      confidence: 1,
      recommended_action: "Repair the failing behavior.",
      requires_human_validation: false,
      model_config_ref: "deterministic",
      prompt_version_ref: "none",
      origin: "DETERMINISTIC",
    },
  ];
  const aggregation: EvaluationAggregationPayload = {
    evaluation_run_id: "evaluation-1",
    evaluation_run_hash: "b".repeat(64),
    shared_finding_groups: [],
    role_specific_finding_ids: ["UTF-001"],
    direct_conflicts: [],
    unresolved_trade_offs: [],
    evidence_gaps: [],
    human_validation_questions: ["Can a target user complete the task?"],
    content_hash: "d".repeat(64),
    disclaimer: "Simulated feedback, not empirical evidence.",
  };
  return {
    evaluationRun: vi.fn().mockResolvedValue(evaluation),
    findings: vi.fn().mockResolvedValue(findings),
    aggregation: vi.fn().mockResolvedValue(aggregation),
    finalReviews: vi.fn().mockResolvedValue([review(2), review(1)]),
    submitFinalReview: vi.fn().mockResolvedValue({
      gate_id: "gate-1",
      review_id: "review-2",
      review_version: 2,
      review_hash: "c".repeat(64),
      status: "PENDING_APPROVAL",
      updated_at: "2026-08-31T04:01:00Z",
    }),
    decideFinalApproval: vi.fn().mockResolvedValue({
      gate_id: "gate-1",
      review_id: "review-2",
      review_version: 2,
      review_hash: "c".repeat(64),
      status: "APPROVED",
      updated_at: "2026-08-31T04:02:00Z",
    }),
    createExport: vi.fn().mockResolvedValue({
      id: "export-1",
      project_id: "project-1",
      workflow_run_id: "run-1",
      owner_user_id: "owner-1",
      manifest_id: "manifest-1",
      manifest_hash: "e".repeat(64),
      archive_hash: "f".repeat(64),
      archive_size_bytes: 512,
      created_at: "2026-08-31T04:03:00Z",
    }),
    exportBundle: vi.fn(),
    downloadExport: vi.fn().mockResolvedValue({
      blob: new Blob(["archive"]),
      filename: "export.zip",
      etag: null,
    }),
  };
}

describe("finalization store", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("keeps deterministic and model-generated findings separate", async () => {
    const store = useFinalizationStore();
    await store.loadEvaluation("evaluation-1", authorize, api());

    expect(store.modelGeneratedFindings.map((item) => item.finding_id)).toEqual(["UTF-001"]);
    expect(store.deterministicFindings.map((item) => item.finding_id)).toEqual(["DET-001"]);
    expect(store.ownerApprovalIsEmpiricalValidation).toBe(false);
  });

  it("sorts final reviews and applies exact Gate 8 and export commands", async () => {
    const store = useFinalizationStore();
    const client = api();
    await store.loadFinalReviews("project-1", authorize, client);
    expect(store.finalReviews.map((item) => item.version_number)).toEqual([1, 2]);
    expect(store.selectedReview?.review_id).toBe("review-2");

    await store.submitGate8(
      {
        expected_version: 2,
        expected_content_hash: "c".repeat(64),
        gate_id: "gate-1",
        event_id: "event-1",
        occurred_at: "2026-08-31T04:01:00Z",
      },
      authorize,
      client,
    );
    await store.decideGate8(
      {
        action: "APPROVE",
        expected_review_id: "review-2",
        expected_review_version: 2,
        expected_review_hash: "c".repeat(64),
        event_id: "event-2",
        occurred_at: "2026-08-31T04:02:00Z",
        reason: null,
      },
      authorize,
      client,
    );
    await store.createExport(
      "project-1",
      {
        export_id: "export-1",
        final_review_id: "review-2",
        expected_review_version: 2,
        expected_review_hash: "c".repeat(64),
        final_approval_gate_id: "gate-1",
        final_approval_event_id: "event-2",
        occurred_at: "2026-08-31T04:03:00Z",
      },
      authorize,
      client,
    );

    expect(store.finalApproval?.status).toBe("APPROVED");
    expect(store.exportBundle?.archive_hash).toBe("f".repeat(64));
  });
});
