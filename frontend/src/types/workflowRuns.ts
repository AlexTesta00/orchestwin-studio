export type WorkflowProjectMode = "GREENFIELD_GENERATION" | "BROWNFIELD_ASSESSMENT";

export type WorkflowRunStatus =
  | "DRAFT"
  | "RUNNING"
  | "WAITING_FOR_HUMAN"
  | "PAUSED"
  | "PAUSED_NEEDS_HUMAN"
  | "BLOCKED"
  | "FAILED"
  | "CANCELLED"
  | "COMPLETED_PENDING_FINAL_APPROVAL"
  | "APPROVED";

export type WorkflowStage =
  | "INTAKE"
  | "SOURCE_INGESTION"
  | "STACK_DETECTION"
  | "ARCHITECTURE_RECOVERY"
  | "REQUIREMENTS_INFERENCE"
  | "BASELINE_EXECUTION"
  | "BRIEF_APPROVAL"
  | "TEAM_SELECTION"
  | "TEAM_APPROVAL"
  | "USER_MODELING"
  | "USER_TWIN_APPROVAL"
  | "REQUIREMENTS"
  | "REQUIREMENTS_APPROVAL"
  | "DESIGN_EXPLORATION"
  | "PATCH_PLANNING"
  | "DESIGN_APPROVAL"
  | "ARCHITECTURE_AND_TEST_PLAN"
  | "ARCHITECTURE_APPROVAL"
  | "IMPLEMENTATION"
  | "EXECUTION"
  | "SYNTHETIC_EVALUATION"
  | "REVISION_DECISION"
  | "FINAL_REVIEW"
  | "FINAL_APPROVAL"
  | "EXPORT";

export type WorkflowLifecycleAction = "pause" | "resume" | "cancel";

export interface WorkflowArtifactReferencePayload {
  artifact_type: string;
  artifact_id: string;
  version_number: number;
  content_hash: string;
}

export interface WorkflowFailureCounterPayload {
  failure_signature: string;
  repair_count: number;
  identical_failure_count: number;
}

export interface WorkflowIterationCountersPayload {
  clarification_count: number;
  requirements_revision_count: number;
  design_cycle_count: number;
  architecture_revision_count: number;
  failure_counters: WorkflowFailureCounterPayload[];
}

export interface WorkflowBudgetStatePayload {
  model_calls: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_micros: number;
  sandbox_elapsed_seconds: number;
  project_elapsed_seconds: number;
}

export interface WorkflowCapabilityStatePayload {
  selected_profile: Record<string, unknown> | null;
  capability_status: "VALIDATED_LEVEL_D" | "EXPERIMENTAL_LEVEL_D" | "DESIGN_ONLY_LEVEL_C" | null;
  unsupported_requirements: string[];
  owner_decision_required: boolean;
}

export interface WorkflowBlockingIssuePayload {
  source: string;
  code: string;
  summary: string;
  requires_owner_action: boolean;
}

export interface WorkflowErrorSummaryPayload {
  code: string;
  summary: string;
  retryable: boolean;
}

export interface WorkflowRunPayload {
  id: string;
  project_id: string;
  owner_user_id: string;
  project_mode: WorkflowProjectMode;
  current_stage: WorkflowStage;
  status: WorkflowRunStatus;
  artifact_references: WorkflowArtifactReferencePayload[];
  pending_gate_id: string | null;
  latest_source_revision_id: string | null;
  latest_execution_attempt_id: string | null;
  latest_evaluation_run_id: string | null;
  iteration_counters: WorkflowIterationCountersPayload;
  budget_state: WorkflowBudgetStatePayload;
  capability_state: WorkflowCapabilityStatePayload;
  blocking_issues: WorkflowBlockingIssuePayload[];
  last_error: WorkflowErrorSummaryPayload | null;
  state_version: number;
  checkpoint_sequence: number;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
  resume_status: WorkflowRunStatus | null;
}

export interface WorkflowCheckpointPayload {
  id: string;
  run_id: string;
  project_id: string;
  owner_user_id: string;
  sequence_number: number;
  state_version: number;
  created_at: string;
  parent_checkpoint_id: string | null;
  state_hash: string;
}

export interface WorkflowEventPayload {
  id: string;
  run_id: string;
  project_id: string;
  owner_user_id: string;
  sequence_number: number;
  event_type: string;
  occurred_at: string;
  payload: Record<string, unknown>;
  payload_hash: string;
}

export interface CreateWorkflowRunInput {
  run_id: string;
  project_mode: WorkflowProjectMode;
  created_at: string;
}

export interface WorkflowLifecycleInput {
  command_id: string;
  project_id: string;
  expected_state_version: number;
  expected_checkpoint_sequence: number;
  occurred_at: string;
  reason: string | null;
  authorization_reference: string | null;
}
