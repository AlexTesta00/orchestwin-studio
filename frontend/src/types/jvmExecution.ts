export type JvmExecutionTarget = "JVM_JAVA" | "JVM_KOTLIN" | "JVM_SCALA";
export type JvmCapabilityStatus = "DESIGN_ONLY_LEVEL_C" | "VALIDATED_LEVEL_D";
export type JvmExecutionReportStatus = "PASSED" | "FAILED" | "INCOMPLETE";
export type JvmPhaseResultStatus =
  | "PASSED"
  | "FAILED"
  | "SKIPPED"
  | "TIMED_OUT"
  | "RESOURCE_LIMIT_EXCEEDED"
  | "CANCELLED"
  | "RUNTIME_ERROR"
  | "POLICY_BLOCKED"
  | "NOT_RUN";
export type JvmExecutionPhase =
  "VALIDATE" | "SETUP" | "STATIC_CHECKS" | "BUILD" | "TEST" | "RUN" | "COLLECT_ARTIFACTS";
export type JvmSourceChangeOperation = "ADD" | "REPLACE" | "DELETE";

export interface JvmProfilePayload {
  profile_id: string;
  profile_version: string;
  target: JvmExecutionTarget;
  capability_status: JvmCapabilityStatus;
  language?: string;
  language_version?: string;
  build_system?: string;
  jdk_major?: number;
  validation_evidence_refs?: string[];
}

export interface JvmTargetSelectionPayload {
  target: JvmExecutionTarget;
  language: string;
  build_system: string;
  layout: string;
  jdk_major: number;
}

export interface JvmSourceFilePayload {
  normalized_path: string;
  sha256_digest: string;
  size_bytes: number;
  storage_key: string;
  media_type: string;
}

export interface JvmSourceProvenancePayload {
  kind: string;
  reference_id: string;
  version_number: number;
  content_hash: string;
}

export interface JvmSourceRevisionReferencePayload {
  revision_id: string;
  project_id: string;
  version_number: number;
  content_hash: string;
  source_tree_hash: string;
}

export interface JvmSourceRevisionPayload {
  id: string;
  project_id: string;
  created_by_user_id?: string;
  version_number: number;
  based_on: JvmSourceRevisionReferencePayload | null;
  target_selection: JvmTargetSelectionPayload;
  validation_scope_hash?: string;
  origin: string;
  files: JvmSourceFilePayload[];
  provenance_references: JvmSourceProvenancePayload[];
  related_failure_signature: string | null;
  created_at?: string;
  source_tree_hash: string;
  content_hash: string;
}

export interface JvmEvidenceReferencePayload {
  storage_key: string;
  sha256_digest: string;
  size_bytes: number;
  media_type: string;
}

export interface JvmNormalizedFindingPayload {
  code: string;
  message: string;
  source_tool: string;
  location: string | null;
}

export interface JvmPhaseResultPayload {
  phase: JvmExecutionPhase;
  status: JvmPhaseResultStatus;
  command_plan_hash: string;
  started_at: string | null;
  completed_at: string | null;
  exit_codes: number[];
  stdout_refs: JvmEvidenceReferencePayload[];
  stderr_refs: JvmEvidenceReferencePayload[];
  artifact_refs: JvmEvidenceReferencePayload[];
  findings: JvmNormalizedFindingPayload[];
  failure_category: string | null;
  failure_code: string | null;
  normalized_summary: string;
}

export interface JvmFailureSignaturePayload {
  category: string;
  phase: JvmExecutionPhase;
  failure_code: string;
  normalized_message: string;
  signature: string;
}

export interface JvmExecutionReportPayload {
  target_selection: JvmTargetSelectionPayload;
  execution_plan_content_hash: string;
  status: JvmExecutionReportStatus;
  phase_results: JvmPhaseResultPayload[];
  failure_signatures: JvmFailureSignaturePayload[];
  content_hash?: string;
}

export interface JvmExecutionAttemptPayload {
  id: string;
  project_id: string;
  created_by_user_id?: string;
  attempt_number: number;
  previous_attempt_id: string | null;
  source_revision: JvmSourceRevisionReferencePayload;
  profile_id: string;
  profile_version: string;
  profile_validation_content_hash: string;
  execution_plan_content_hash: string;
  runner_id: string;
  runner_version: string;
  runner_image_digest: string;
  policy_content_hash: string;
  trigger: string;
  executed_phases: JvmExecutionPhase[];
  report: JvmExecutionReportPayload;
  started_at: string;
  completed_at: string;
  content_hash: string;
}

export interface JvmRepairChangePayload {
  normalized_path: string;
  operation: JvmSourceChangeOperation;
  content_sha256: string | null;
  size_bytes: number | null;
  storage_key: string | null;
  media_type: string | null;
}

export interface JvmRepairProposalPayload {
  id: string;
  project_id: string;
  created_by_user_id?: string;
  base_revision: JvmSourceRevisionReferencePayload;
  failure_signature: JvmFailureSignaturePayload;
  change_set?: {
    id: string;
    content_hash: string;
    changes: JvmRepairChangePayload[];
    rationale: string;
  };
  changes?: JvmRepairChangePayload[];
  attempt_number: number;
  identical_failure_occurrences: number;
  created_at: string;
  content_hash?: string;
}

export interface CreateJvmSourceRevisionInput {
  target: JvmExecutionTarget;
  rationale: string;
  files: Array<{
    normalized_path: string;
    content: string;
    media_type: string;
  }>;
  provenance_references: Array<{
    kind: string;
    reference_id: string;
    version_number: number;
    content_hash: string;
  }>;
}

export interface StartJvmExecutionInput {
  source_revision_id: string;
  profile_id: string;
  profile_version: string;
  policy_content_hash: string;
  runner_image_digest: string;
  purpose: "PROFILE_VALIDATION" | "OWNER_PROJECT";
  trigger: "INITIAL" | "PROFILE_VALIDATION" | "REPAIR_RERUN" | "MANUAL_RERUN";
  authorization_id: string | null;
  rerun_phases: JvmExecutionPhase[] | null;
}

export interface CreateJvmRepairProposalInput {
  base_revision_content_hash: string;
  failure_signature: string;
  changes: Array<{
    operation: JvmSourceChangeOperation;
    normalized_path: string;
    content: string | null;
    media_type: string | null;
  }>;
  rationale: string;
}

export interface ApplyJvmRepairProposalInput {
  base_revision_content_hash: string;
  proposal_content_hash: string;
  approval_id: string | null;
}
