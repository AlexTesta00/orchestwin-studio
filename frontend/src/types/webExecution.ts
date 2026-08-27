export type WebExecutionTarget =
  "WEB_STATIC" | "WEB_VUE" | "WEB_NODE_EXPRESS" | "WEB_PHP" | "WEB_VUE_NODE";

export type WebImplementationLanguage = "STATIC_ASSETS" | "JAVASCRIPT" | "TYPESCRIPT" | "PHP";

export type WebProjectLayout = "SINGLE_ROOT" | "FRONTEND_BACKEND";
export type WebCapabilityStatus =
  "VALIDATED_LEVEL_D" | "EXPERIMENTAL_LEVEL_D" | "DESIGN_ONLY_LEVEL_C";
export type WebExecutionPurpose = "OWNER_PROJECT" | "PROFILE_VALIDATION";
export type WebExecutionTrigger =
  "INITIAL" | "PROFILE_VALIDATION" | "REPAIR_RERUN" | "MANUAL_RERUN";
export type WebExecutionPhase =
  | "VALIDATE"
  | "SETUP"
  | "STATIC_CHECK"
  | "BUILD"
  | "TEST"
  | "RUN"
  | "HEALTH_CHECK"
  | "BROWSER_EVIDENCE"
  | "COLLECT_ARTIFACTS";
export type WebPhaseResultStatus =
  | "PASSED"
  | "FAILED"
  | "SKIPPED"
  | "TIMED_OUT"
  | "RESOURCE_LIMIT_EXCEEDED"
  | "CANCELLED"
  | "RUNTIME_ERROR"
  | "POLICY_BLOCKED"
  | "NOT_RUN";
export type WebExecutionReportStatus = "PASSED" | "FAILED" | "INCOMPLETE";
export type WebSourceChangeOperation = "ADD" | "REPLACE" | "DELETE";
export type WebBrowserEvidenceStatus = "COLLECTED" | "PARTIAL" | "FAILED";

export interface WebLanguageConfigurationPayload {
  frontend: WebImplementationLanguage | null;
  backend: WebImplementationLanguage | null;
}

export interface WebTargetSelectionPayload {
  target: WebExecutionTarget;
  language_configuration: WebLanguageConfigurationPayload;
  layout: WebProjectLayout;
}

export interface WebSourceRevisionReferencePayload {
  revision_id: string;
  project_id: string;
  version_number: number;
  content_hash: string;
  source_tree_hash: string;
}

export interface WebSourceFilePayload {
  normalized_path: string;
  sha256_digest: string;
  size_bytes: number;
  storage_key: string;
  media_type: string;
}

export interface WebSourceProvenancePayload {
  kind:
    | "PROJECT_BRIEF"
    | "REQUIREMENTS"
    | "DESIGN"
    | "ARCHITECTURE"
    | "TEST_PLAN"
    | "SOURCE_PLAN"
    | "FAILURE_SIGNATURE"
    | "OWNER_DECISION";
  reference_id: string;
  version_number: number;
  content_hash: string;
}

export interface WebSourceRevisionPayload {
  id: string;
  project_id: string;
  created_by_user_id: string;
  version_number: number;
  based_on: WebSourceRevisionReferencePayload | null;
  target_selection: WebTargetSelectionPayload;
  validation_scope_hash: string;
  origin: "GENERATED_PLAN" | "IMPORTED_BROWNFIELD" | "REPAIR_CHANGE_SET" | "DETERMINISTIC_FIXTURE";
  files: WebSourceFilePayload[];
  provenance_references: WebSourceProvenancePayload[];
  related_failure_signature: string | null;
  created_at: string;
  source_tree_hash: string;
  content_hash: string;
}

export interface WebEvidenceReferencePayload {
  storage_key: string;
  sha256_digest: string;
  size_bytes: number;
  media_type: string;
}

export interface WebNormalizedFindingPayload {
  code: string;
  message: string;
  source_tool: string;
  location: string | null;
}

export interface WebFailureSignaturePayload {
  category: string;
  phase: WebExecutionPhase;
  profile_id: string;
  profile_version: string;
  failure_code: string;
  normalized_message: string;
  subject_refs: string[];
  digest: string;
}

export interface WebPhaseResultPayload {
  phase: WebExecutionPhase;
  status: WebPhaseResultStatus;
  command_plan_hashes: string[];
  started_at: string | null;
  completed_at: string | null;
  exit_codes: number[];
  stdout_refs: WebEvidenceReferencePayload[];
  stderr_refs: WebEvidenceReferencePayload[];
  artifact_refs: WebEvidenceReferencePayload[];
  findings: WebNormalizedFindingPayload[];
  failure_category: string | null;
  failure_code: string | null;
  normalized_summary: string;
}

export interface WebExecutionReportPayload {
  source_revision_content_hash: string;
  source_tree_hash: string;
  profile_id: string;
  profile_version: string;
  runner_image_digest: string;
  policy_content_hash: string;
  status: WebExecutionReportStatus;
  phase_results: WebPhaseResultPayload[];
  failure_signatures: WebFailureSignaturePayload[];
}

export interface WebExecutionAttemptPayload {
  id: string;
  project_id: string;
  created_by_user_id: string;
  attempt_number: number;
  previous_attempt_id: string | null;
  source_revision: WebSourceRevisionReferencePayload;
  profile_validation_content_hash: string;
  execution_plan_content_hash: string;
  trigger: WebExecutionTrigger;
  executed_phases: WebExecutionPhase[];
  report: WebExecutionReportPayload;
  started_at: string;
  completed_at: string;
  content_hash: string;
}

export interface WebBrowserRoutePayload {
  route_id: string;
  path: string;
}

export interface WebBrowserConsoleMessagePayload {
  level: "DEBUG" | "INFO" | "WARNING" | "ERROR";
  message: string;
  location: string | null;
}

export interface WebBrowserFailedRequestPayload {
  method: string;
  path: string;
  failure_text: string;
}

export interface WebAccessibilityFindingPayload {
  rule_id: string;
  impact: "CRITICAL" | "SERIOUS" | "MODERATE" | "MINOR" | "UNKNOWN";
  description: string;
  help_text: string;
  targets: string[];
}

export interface WebBrowserRouteEvidencePayload {
  route: WebBrowserRoutePayload;
  status: "COLLECTED" | "FAILED";
  final_path: string | null;
  screenshot_ref: WebEvidenceReferencePayload | null;
  dom_snapshot_ref: WebEvidenceReferencePayload | null;
  raw_playwright_ref: WebEvidenceReferencePayload;
  accessibility_report_ref: WebEvidenceReferencePayload | null;
  console_messages: WebBrowserConsoleMessagePayload[];
  failed_requests: WebBrowserFailedRequestPayload[];
  accessibility_findings: WebAccessibilityFindingPayload[];
  failure_code: string | null;
  failure_message: string | null;
}

export interface WebBrowserEvidencePayload {
  request: {
    source_revision_content_hash: string;
    source_tree_hash: string;
    runner_image_digest: string;
    base_url: string;
    routes: WebBrowserRoutePayload[];
    policy: {
      maximum_routes: number;
      maximum_console_messages_per_route: number;
      maximum_failed_requests_per_route: number;
      maximum_accessibility_findings_per_route: number;
    };
    content_hash: string;
  };
  status: WebBrowserEvidenceStatus;
  routes: WebBrowserRouteEvidencePayload[];
  normalized_findings: WebNormalizedFindingPayload[];
  content_hash: string;
}

export interface WebSourceChangePayload {
  normalized_path: string;
  operation: WebSourceChangeOperation;
  content_sha256: string | null;
  size_bytes: number | null;
  storage_key: string | null;
  media_type: string | null;
}

export interface WebRepairProposalPayload {
  id: string;
  project_id: string;
  created_by_user_id: string;
  base_revision: WebSourceRevisionReferencePayload;
  failure_signature: WebFailureSignaturePayload;
  change_set: {
    id: string;
    project_id: string;
    base_revision: WebSourceRevisionReferencePayload;
    changes: WebSourceChangePayload[];
    rationale: string;
    provenance_references: string[];
    content_hash: string;
  };
  attempt_number: number;
  identical_failure_occurrences: number;
  provenance_references: WebSourceProvenancePayload[];
  created_at: string;
}

export interface CreateWebSourceRevisionInput {
  target_selection: WebTargetSelectionPayload;
  rationale: string;
  files: Array<{
    normalized_path: string;
    content: string;
    media_type: string;
  }>;
  provenance_references: WebSourceProvenancePayload[];
}

export interface StartWebExecutionInput {
  source_revision_id: string;
  profile_id: string;
  profile_version: string;
  policy_content_hash: string;
  runners: {
    execution_runner_image_digest: string;
    browser_runner_image_digest: string | null;
  };
  purpose: WebExecutionPurpose;
  trigger: WebExecutionTrigger;
  authorization_id: string | null;
  rerun_phases: WebExecutionPhase[] | null;
  declared_routes: WebBrowserRoutePayload[];
}

export interface CreateWebRepairProposalInput {
  base_revision_content_hash: string;
  failure_signature_digest: string;
  changes: Array<{
    operation: WebSourceChangeOperation;
    normalized_path: string;
    content: string | null;
    media_type: string | null;
  }>;
  rationale: string;
}

export interface ApplyWebRepairProposalInput {
  base_revision_content_hash: string;
  proposal_content_hash: string;
  approval_id: string | null;
}

export interface WebCommandResponse<T> {
  status: "SOURCE_REVISION_CREATED" | "EXECUTION_RECORDED" | "REPAIR_PROPOSED" | "REPAIR_APPLIED";
  snapshot: T;
  message: string;
}

export interface WebSnapshotResponse<T> {
  snapshot: T;
}

export interface WebSnapshotListResponse<T> {
  items: T[];
}
