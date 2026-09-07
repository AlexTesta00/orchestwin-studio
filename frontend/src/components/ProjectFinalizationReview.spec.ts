import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type {
  EvaluationAggregationPayload,
  FinalApprovalPayload,
  FinalExportPayload,
  FinalReviewPayload,
  SyntheticFindingPayload,
} from "@/types/finalization";
import ProjectFinalizationReview from "./ProjectFinalizationReview.vue";

const findings: SyntheticFindingPayload[] = [
  {
    finding_id: "DET-001",
    twin_id: "twin-1",
    twin_version: 1,
    artifact_id: "artifact-1",
    artifact_version: 1,
    location: "test:primary",
    summary: "The primary deterministic test fails.",
    rationale: "The recorded test report contains one failure.",
    criterion: "task_alignment",
    severity: "major",
    epistemic_status: "USER_PROVIDED",
    evidence_refs: ["test-report:1"],
    confidence: 1,
    recommended_action: "Repair the failing behaviour.",
    requires_human_validation: false,
    model_config_ref: "deterministic",
    prompt_version_ref: "none",
    origin: "DETERMINISTIC",
  },
  {
    finding_id: "UTF-001",
    twin_id: "twin-1",
    twin_version: 1,
    artifact_id: "artifact-1",
    artifact_version: 1,
    location: "screen:home",
    summary: "The role may need a clearer recovery action.",
    rationale: "The approved profile prioritizes concise recovery guidance.",
    criterion: "actionability",
    severity: "moderate",
    epistemic_status: "MODEL_INFERRED",
    evidence_refs: ["profile:1"],
    confidence: 0.72,
    recommended_action: "Add an explicit recovery action.",
    requires_human_validation: true,
    model_config_ref: "model-1",
    prompt_version_ref: "prompt-1",
    origin: "MODEL_GENERATED",
  },
];

const aggregation: EvaluationAggregationPayload = {
  evaluation_run_id: "evaluation-1",
  evaluation_run_hash: "a".repeat(64),
  shared_finding_groups: [],
  role_specific_finding_ids: ["UTF-001"],
  direct_conflicts: [
    {
      conflict_id: "conflict-1",
      finding_ids: ["UTF-001", "UTF-002"],
      summary: "Expert and novice workflows prefer different information density.",
      evidence_refs: ["profile:1", "profile:2"],
      requires_owner_decision: true,
    },
  ],
  unresolved_trade_offs: ["Information density versus novice comprehensibility."],
  evidence_gaps: ["No empirical target-user walkthrough is recorded."],
  human_validation_questions: ["Can a target user recover without assistance?"],
  content_hash: "b".repeat(64),
  disclaimer: "Simulated feedback, not empirical evidence.",
};

function review(readyForGate8 = true): FinalReviewPayload {
  return {
    review_id: "review-1",
    project_id: "project-1",
    workflow_run_id: "run-1",
    owner_user_id: "owner-1",
    version_number: 1,
    parent_review_id: null,
    parent_content_hash: null,
    workflow_state_version: 8,
    checks: [
      {
        check_id: "check-dod",
        kind: "DEFINITION_OF_DONE",
        status: readyForGate8 ? "SATISFIED" : "NOT_SATISFIED",
        summary: "Definition of Done is complete.",
        evidence_refs: ["dod:1"],
        blocking: true,
        blocks_gate8: !readyForGate8,
      },
    ],
    unresolved_issues: [],
    accepted_limitations: [
      {
        limitation_id: "limitation-1",
        summary: "Target-user validation remains future work.",
        rationale: "Owner approval is not empirical validation.",
      },
    ],
    latest_execution_attempt_id: "execution-1",
    latest_evaluation_run_id: "evaluation-1",
    evaluation_aggregation_hash: "b".repeat(64),
    capability_status: "DESIGN_ONLY_LEVEL_C",
    human_validation_status: "PLANNED",
    created_at: "2026-08-31T04:00:00Z",
    content_hash: "c".repeat(64),
    ready_for_gate8: readyForGate8,
    blocking_check_ids: readyForGate8 ? [] : ["check-dod"],
    blocking_issue_ids: [],
    owner_approval_is_empirical_validation: false,
  };
}

const pendingApproval: FinalApprovalPayload = {
  gate_id: "gate-1",
  review_id: "review-1",
  review_version: 1,
  review_hash: "c".repeat(64),
  status: "PENDING_APPROVAL",
  updated_at: "2026-08-31T04:01:00Z",
};

const approved: FinalApprovalPayload = {
  ...pendingApproval,
  status: "APPROVED",
};

const exportBundle: FinalExportPayload = {
  id: "export-1",
  project_id: "project-1",
  workflow_run_id: "run-1",
  owner_user_id: "owner-1",
  manifest_id: "manifest-1",
  manifest_hash: "d".repeat(64),
  archive_hash: "e".repeat(64),
  archive_size_bytes: 1024,
  created_at: "2026-08-31T04:02:00Z",
  manifest: {
    schema_version: 1,
    manifest_id: "manifest-1",
    project_id: "project-1",
    workflow_run_id: "run-1",
    owner_user_id: "owner-1",
    final_review: {
      id: "review-1",
      version: 1,
      content_hash: "c".repeat(64),
    },
    final_approval: {
      gate_id: "gate-1",
      event_id: "event-1",
    },
    capability_status: "DESIGN_ONLY_LEVEL_C",
    entries: [
      {
        path: "reports/final-review.json",
        category: "FINAL_REVIEW",
        artifact_id: "review-1",
        artifact_version: 1,
        content_hash: "c".repeat(64),
        media_type: "application/json",
        size_bytes: 512,
        required: true,
      },
    ],
    omissions: [
      {
        category: "EMPIRICAL_VALIDATION",
        reason: "No empirical target-user study was performed.",
        accepted_limitation_id: "limitation-1",
      },
    ],
    accepted_limitation_ids: ["limitation-1"],
    content_hash: "d".repeat(64),
    synthetic_feedback_disclaimer: "Simulated feedback, not empirical evidence.",
    owner_approval_is_empirical_validation: false,
  },
};

describe("ProjectFinalizationReview", () => {
  it("keeps deterministic and model-generated findings visibly separate", () => {
    const wrapper = mount(ProjectFinalizationReview, {
      props: {
        findings,
        aggregation,
        review: review(),
      },
    });

    expect(wrapper.findAll("[data-finding-origin='DETERMINISTIC']")).toHaveLength(1);
    expect(wrapper.findAll("[data-finding-origin='MODEL_GENERATED']")).toHaveLength(1);
    expect(wrapper.get("[data-testid='synthetic-feedback-disclaimer']").text()).toContain(
      "not empirical evidence",
    );
    expect(wrapper.findAll("[data-testid='direct-conflict']")).toHaveLength(1);
    expect(wrapper.text()).toContain("Human validation required");
  });

  it("enables only legal Gate 8 and export controls", async () => {
    const ready = mount(ProjectFinalizationReview, {
      props: {
        review: review(),
      },
    });
    const readyButtons = ready.findAll("button");

    expect(readyButtons[0]?.attributes("disabled")).toBeUndefined();
    expect(readyButtons[1]?.attributes("disabled")).toBeDefined();

    await readyButtons[0]?.trigger("click");

    expect(ready.emitted("submitGate8")).toEqual([[]]);

    const pending = mount(ProjectFinalizationReview, {
      props: {
        review: review(),
        approval: pendingApproval,
      },
    });
    const pendingButtons = pending.findAll("button");

    expect(pendingButtons[0]?.attributes("disabled")).toBeDefined();
    expect(pendingButtons[1]?.attributes("disabled")).toBeUndefined();

    await pendingButtons[1]?.trigger("click");
    await pendingButtons[3]?.trigger("click");

    expect(pending.emitted("decideGate8")).toEqual([["APPROVE"], ["REQUEST_REVISION"]]);

    const approvedWrapper = mount(ProjectFinalizationReview, {
      props: {
        review: review(),
        approval: approved,
      },
    });
    const approvedButtons = approvedWrapper.findAll("button");

    expect(approvedButtons[6]?.attributes("disabled")).toBeUndefined();

    await approvedButtons[6]?.trigger("click");

    expect(approvedWrapper.emitted("createExport")).toEqual([[]]);
  });

  it("renders the canonical manifest and an Italian textual alternative", async () => {
    const wrapper = mount(ProjectFinalizationReview, {
      props: {
        findings,
        aggregation,
        review: review(),
        approval: approved,
        exportBundle,
        locale: "it",
      },
    });

    expect(wrapper.text()).toContain("Revisione finale, Gate 8 ed esportazione");
    expect(wrapper.text()).toContain("reports/final-review.json");
    expect(wrapper.text()).toContain("EMPIRICAL_VALIDATION");
    expect(wrapper.get("[data-testid='finalization-text-alternative']").text()).toContain(
      "Riepilogo testuale",
    );
    expect(wrapper.text()).toMatch(/non equivale a validazione empirica/i);

    const buttons = wrapper.findAll("button");

    expect(buttons[7]?.attributes("disabled")).toBeUndefined();

    await buttons[7]?.trigger("click");

    expect(wrapper.emitted("downloadExport")).toEqual([[]]);
  });
});
