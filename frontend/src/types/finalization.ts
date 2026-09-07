export type SyntheticFindingCriterion =
  | "usefulness"
  | "comprehensibility"
  | "actionability"
  | "cognitive_load"
  | "trust"
  | "accessibility"
  | "task_alignment";

export type SyntheticFindingSeverity = "critical" | "major" | "moderate" | "minor" | "observation";

export type SyntheticFindingEpistemicStatus =
  | "USER_PROVIDED"
  | "EMPIRICALLY_SUPPORTED"
  | "HUMAN_VALIDATED"
  | "MODEL_INFERRED"
  | "UNSUPPORTED_ASSUMPTION";

export interface SyntheticFindingPayload {
  finding_id: string;
  twin_id: string;
  twin_version: number;
  artifact_id: string;
  artifact_version: number;
  location: string;
  summary: string;
  rationale: string;
  criterion: SyntheticFindingCriterion;
  severity: SyntheticFindingSeverity;
  epistemic_status: SyntheticFindingEpistemicStatus;
  evidence_refs: string[];
  confidence: number;
  recommended_action: string;
  requires_human_validation: boolean;
  model_config_ref: string;
  prompt_version_ref: string;
  origin?: "MODEL_GENERATED" | "DETERMINISTIC";
}

export interface SyntheticEvaluationRunPayload {
  id: string;
  project_id: string;
  workflow_run_id: string;
  owner_user_id: string;
  artifact_bundle_id: string;
  artifact_bundle_hash: string;
  status: string;
  response_count: number;
  finding_count: number;
  started_at: string;
  completed_at: string;
  content_hash: string;
  simulated_feedback: boolean;
}

export interface FindingConflictPayload {
  conflict_id: string;
  finding_ids: string[];
  summary: string;
  evidence_refs: string[];
  requires_owner_decision: boolean;
}

export interface EvaluationAggregationPayload {
  evaluation_run_id: string;
  evaluation_run_hash: string;
  shared_finding_groups: Array<{ group_id: string; finding_ids: string[]; summary: string }>;
  role_specific_finding_ids: string[];
  direct_conflicts: FindingConflictPayload[];
  unresolved_trade_offs: string[];
  evidence_gaps: string[];
  human_validation_questions: string[];
  content_hash: string;
  disclaimer: string;
}

export type FinalReviewCheckStatus =
  "SATISFIED" | "NOT_SATISFIED" | "NOT_APPLICABLE" | "ACCEPTED_LIMITATION";

export interface FinalReviewCheckPayload {
  check_id: string;
  kind: string;
  status: FinalReviewCheckStatus;
  summary: string;
  evidence_refs: string[];
  blocking: boolean;
  blocks_gate8: boolean;
}

export interface FinalReviewIssuePayload {
  issue_id: string;
  severity: "CRITICAL" | "MAJOR" | "MODERATE" | "MINOR";
  summary: string;
  source_ref: string;
  blocks_gate8: boolean;
}

export interface AcceptedFinalLimitationPayload {
  limitation_id: string;
  summary: string;
  rationale: string;
}

export interface FinalReviewPayload {
  review_id: string;
  project_id: string;
  workflow_run_id: string;
  owner_user_id: string;
  version_number: number;
  parent_review_id: string | null;
  parent_content_hash: string | null;
  workflow_state_version: number;
  checks: FinalReviewCheckPayload[];
  unresolved_issues: FinalReviewIssuePayload[];
  accepted_limitations: AcceptedFinalLimitationPayload[];
  latest_execution_attempt_id: string | null;
  latest_evaluation_run_id: string | null;
  evaluation_aggregation_hash: string | null;
  capability_status: "VALIDATED_LEVEL_D" | "EXPERIMENTAL_LEVEL_D" | "DESIGN_ONLY_LEVEL_C" | null;
  human_validation_status: "NOT_RECORDED" | "PLANNED" | "COMPLETED";
  created_at: string;
  content_hash: string;
  ready_for_gate8: boolean;
  blocking_check_ids: string[];
  blocking_issue_ids: string[];
  owner_approval_is_empirical_validation: false;
}

export interface FinalApprovalPayload {
  gate_id: string;
  review_id: string;
  review_version: number;
  review_hash: string;
  status:
    | "DRAFT"
    | "PENDING_APPROVAL"
    | "APPROVED"
    | "REJECTED"
    | "REVISION_REQUESTED"
    | "PAUSED"
    | "CANCELLED"
    | "STALE";
  updated_at: string;
}

export interface FinalExportEntryPayload {
  path: string;
  category: string;
  artifact_id: string;
  artifact_version: number;
  content_hash: string;
  media_type: string;
  size_bytes: number;
  required: boolean;
}

export interface FinalExportOmissionPayload {
  category: string;
  reason: string;
  accepted_limitation_id: string | null;
}

export interface FinalExportManifestPayload {
  schema_version: number;
  manifest_id: string;
  project_id: string;
  workflow_run_id: string;
  owner_user_id: string;
  final_review: { id: string; version: number; content_hash: string };
  final_approval: { gate_id: string; event_id: string };
  capability_status: string | null;
  entries: FinalExportEntryPayload[];
  omissions: FinalExportOmissionPayload[];
  accepted_limitation_ids: string[];
  content_hash: string;
  synthetic_feedback_disclaimer: string;
  owner_approval_is_empirical_validation: false;
}

export interface FinalExportPayload {
  id: string;
  project_id: string;
  workflow_run_id: string;
  owner_user_id: string;
  manifest_id: string;
  manifest_hash: string;
  archive_hash: string;
  archive_size_bytes: number;
  created_at: string;
  manifest?: FinalExportManifestPayload;
}

export interface SubmitFinalReviewInput {
  expected_version: number;
  expected_content_hash: string;
  gate_id: string;
  event_id: string;
  occurred_at: string;
}

export interface DecideFinalApprovalInput {
  action: "APPROVE" | "REJECT" | "REQUEST_REVISION" | "PAUSE" | "CANCEL";
  expected_review_id: string;
  expected_review_version: number;
  expected_review_hash: string;
  event_id: string;
  occurred_at: string;
  reason: string | null;
}

export interface CreateFinalExportInput {
  export_id: string;
  final_review_id: string;
  expected_review_version: number;
  expected_review_hash: string;
  final_approval_gate_id: string;
  final_approval_event_id: string;
  occurred_at: string;
}

export interface FinalExportDownloadPayload {
  blob: Blob;
  filename: string;
  etag: string | null;
}
