export type UUID = string;
export type IsoDateTime = string;

export type JsonValue =
  string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };

export type ExecutionCapabilityStatus =
  "VALIDATED_LEVEL_D" | "EXPERIMENTAL_LEVEL_D" | "DESIGN_ONLY_LEVEL_C";

export type CapabilityNegotiationStatus =
  | "VALIDATED_LEVEL_D_SELECTED"
  | "EXPERIMENTAL_LEVEL_D_SELECTED"
  | "DESIGN_ONLY_LEVEL_C_SELECTED"
  | "HUMAN_DECISION_REQUIRED"
  | "UNSUPPORTED";

export type ExecutionTarget =
  | "WEB_STATIC"
  | "WEB_VUE"
  | "WEB_NODE_EXPRESS"
  | "WEB_PHP"
  | "WEB_VUE_NODE"
  | "JVM_JAVA"
  | "JVM_KOTLIN"
  | "JVM_SCALA"
  | "ANDROID_JAVA"
  | "ANDROID_KOTLIN"
  | "CUSTOM_DECLARATIVE";

export type SandboxRunStatus =
  "SUCCEEDED" | "FAILED" | "TIMED_OUT" | "RESOURCE_LIMIT_EXCEEDED" | "CANCELLED" | "RUNTIME_ERROR";

export type HighImpactOperationKind =
  "SANDBOX_EXECUTION" | "PROFILE_ACTIVATION" | "WORKSPACE_MUTATION" | "RUNTIME_POLICY_OVERRIDE";

export type HighImpactClassification =
  "ALLOWED_WITHOUT_APPROVAL" | "REQUIRES_OWNER_APPROVAL" | "FORBIDDEN_BY_POLICY";

export type HighImpactApprovalReadiness =
  | "REQUEST_NOT_FOUND"
  | "FORBIDDEN_BY_POLICY"
  | "APPROVAL_NOT_REQUIRED"
  | "OWNER_APPROVAL_REQUIRED"
  | "APPROVED"
  | "REJECTED"
  | "REVISION_REQUESTED"
  | "PAUSED"
  | "CANCELLED"
  | "STALE";

export type HumanGateStatus =
  | "DRAFT"
  | "PENDING_APPROVAL"
  | "APPROVED"
  | "REJECTED"
  | "REVISION_REQUESTED"
  | "PAUSED"
  | "CANCELLED"
  | "STALE"
  | "PAUSED_NEEDS_HUMAN";

export type HumanGateAction =
  "SUBMIT" | "APPROVE" | "REJECT" | "REQUEST_REVISION" | "PAUSE" | "RESUME" | "CANCEL";

export interface ExecutionProfileReferencePayload {
  profile_id: string;
  profile_version: string;
  content_hash: string;
}

export interface SandboxResourceLimitsPayload {
  cpu_count: number;
  memory_mib: number;
  pids_limit: number;
  writable_tmpfs_mib: number;
}

export interface ExecutionProfilePayload {
  profile_id: string;
  name: string;
  version: string;
  capability_status: ExecutionCapabilityStatus;
  supported_targets: ExecutionTarget[];
  file_indicators: string[];
  required_runners: string[];
  base_images: string[];
  network_policy: Record<string, JsonValue>;
  resource_defaults: SandboxResourceLimitsPayload;
  command_schema_version: number;
  maintainer: string;
  license_notes: string;
  validation_evidence_refs: string[];
  requires_owner_approval: boolean;
  content_hash: string;
}

export interface BrownfieldIntakeSummaryPayload {
  id: UUID;
  project_id: UUID;
  version_number: number;
  based_on_version_number: number | null;
  content_hash: string;
  archive_sha256: string;
  archive_size_bytes: number;
  archive_storage_key: string;
  inventory_content_hash: string;
  capability_status: CapabilityNegotiationStatus;
  effective_capability_status: ExecutionCapabilityStatus;
  selected_profile_reference: ExecutionProfileReferencePayload | null;
  created_by_user_id: UUID;
  created_at: IsoDateTime;
}

export interface BrownfieldIntakeListPayload {
  items: BrownfieldIntakeSummaryPayload[];
}

export interface BrownfieldInventoryPayload {
  intake: BrownfieldIntakeSummaryPayload;
  inventory: Record<string, JsonValue>;
}

export interface BrownfieldCapabilityPayload {
  intake: BrownfieldIntakeSummaryPayload;
  capability: Record<string, JsonValue>;
}

export interface SnapshotPayload<T> {
  snapshot: T;
}

export interface SnapshotListPayload<T> {
  items: T[];
}

export interface SandboxCommandResultPayload {
  run_id: UUID;
  ordinal: number;
  command_id: string;
  status: SandboxRunStatus;
  started_at: IsoDateTime;
  finished_at: IsoDateTime;
  exit_code: number | null;
  output_parser_id: string | null;
  failure_message: string | null;
  stdout_log: Record<string, JsonValue>;
  stderr_log: Record<string, JsonValue>;
  artifacts: Record<string, JsonValue>[];
}

export interface SandboxRunPayload {
  run_id: UUID;
  project_id: UUID;
  intake_reference: Record<string, JsonValue> | null;
  schema_version: number;
  evidence_content_hash: string;
  evidence_snapshot: Record<string, JsonValue>;
  created_by_user_id: UUID;
  recorded_at: IsoDateTime;
  command_results: SandboxCommandResultPayload[];
}

export interface SandboxLogsPayload {
  run_id: UUID;
  logs: Array<{
    command_id: string;
    stdout: Record<string, JsonValue>;
    stderr: Record<string, JsonValue>;
  }>;
}

export interface HighImpactOperationPayload {
  version: {
    id: UUID;
    project_id: UUID;
    version_number: number;
    based_on_version_number: number | null;
    content_hash: string;
    request: Record<string, JsonValue>;
    created_by_user_id: UUID;
    created_at: IsoDateTime;
  };
  classification: {
    request_reference: Record<string, JsonValue>;
    policy_content_hash: string;
    classification: HighImpactClassification;
    reasons: Record<string, JsonValue>[];
  };
}

export interface HumanGatePayload {
  id: UUID;
  project_id: UUID;
  owner_user_id: UUID;
  gate_type: "HIGH_IMPACT_OPERATION";
  artifact: Record<string, JsonValue>;
  iteration: number;
  max_iterations: number;
  status: HumanGateStatus;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
  event_sequence: number;
  resume_status: HumanGateStatus | null;
}

export interface HumanGateEventPayload {
  id: UUID;
  gate_id: UUID;
  sequence_number: number;
  kind: HumanGateAction;
  previous_status: HumanGateStatus;
  resulting_status: HumanGateStatus;
  artifact: Record<string, JsonValue>;
  occurred_at: IsoDateTime;
  actor_user_id: UUID | null;
  reason: string | null;
}

export interface HighImpactOperationResponsePayload {
  status: string;
  operation: HighImpactOperationPayload;
  gate: HumanGatePayload | null;
  event: HumanGateEventPayload | null;
}

export interface HighImpactReadinessPayload {
  status: HighImpactApprovalReadiness;
  operation: HighImpactOperationPayload | null;
  gate: HumanGatePayload | null;
}

export interface SourceArchiveUploadOptions {
  requestedTarget?: ExecutionTarget;
  availableRunners?: string[];
}

export interface HighImpactOperationInput {
  operation_kind: HighImpactOperationKind;
  summary: string;
  profile_reference: ExecutionProfileReferencePayload;
  capability_status: ExecutionCapabilityStatus;
  command_plan_id: string | null;
  command_plan_content_hash: string | null;
  image_reference: string | null;
  network_mode: "DISABLED" | "CONTROLLED";
  secret_reference_ids: string[];
  resources: SandboxResourceLimitsPayload;
  destructive_workspace_paths: string[];
  requests_privileged_container: boolean;
  requests_docker_socket_mount: boolean;
  requests_host_filesystem_mount: boolean;
  requests_arbitrary_host_command: boolean;
}

export interface HighImpactExpectedReferenceInput {
  version_number: number;
  content_hash: string;
}

export interface HighImpactDecisionInput extends HighImpactExpectedReferenceInput {
  action: Exclude<HumanGateAction, "SUBMIT">;
  reason: string | null;
}
