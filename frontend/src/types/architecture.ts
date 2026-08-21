export type UUID = string;
export type IsoDateTime = string;

export type ArtifactKind =
  | "REQUIREMENTS_SPECIFICATION"
  | "AGENT_TEAM"
  | "USER_MODELING"
  | "DESIGN_PACKAGE"
  | "DECLARATIVE_PROTOTYPE"
  | "ARCHITECTURE_PACKAGE";

export type ArchitectureStyle =
  "MODULAR_MONOLITH" | "LAYERED_MONOLITH" | "CLIENT_SERVER" | "SINGLE_DEPLOYABLE_APPLICATION";

export type ArchitectureComponentKind =
  | "USER_INTERFACE"
  | "APPLICATION_SERVICE"
  | "DOMAIN_MODULE"
  | "DATA_STORE"
  | "EXTERNAL_SERVICE"
  | "INTEGRATION_ADAPTER"
  | "BACKGROUND_WORKER"
  | "DEVICE_APPLICATION";

export type ArchitectureConnectionKind =
  "CALLS" | "READS_FROM" | "WRITES_TO" | "PUBLISHES_TO" | "CONSUMES_FROM" | "DEPENDS_ON";

export type ApiMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export type RiskLikelihood = "RARE" | "UNLIKELY" | "POSSIBLE" | "LIKELY" | "ALMOST_CERTAIN";
export type RiskImpact = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export type TestEnvironmentKind =
  "LOCAL" | "CONTAINER" | "BROWSER" | "ANDROID_EMULATOR" | "PHYSICAL_DEVICE";

export type TestLevel =
  | "UNIT"
  | "COMPONENT"
  | "CONTRACT"
  | "INTEGRATION"
  | "END_TO_END"
  | "ACCESSIBILITY"
  | "SECURITY"
  | "MANUAL_REVIEW";

export type TestAutomation = "AUTOMATED" | "MANUAL" | "HYBRID";
export type TestPriority = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";

export type ArchitectureChangeKind = "REPLACE";
export type ArchitectureArtifactKind = "ARCHITECTURE" | "TEST_PLAN" | "OPEN_QUESTIONS";
export type ArchitecturePackageDiffStatus = "PROPOSED" | "APPROVED" | "REJECTED";
export type ArchitectureRevisionDecision = "APPROVE" | "REJECT";

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

export type ArchitectureGateDecisionAction = Exclude<HumanGateAction, "SUBMIT">;

export type ArchitectureWorkflowReadiness =
  "ARCHITECTURE_REQUIRED" | "ARCHITECTURE_APPROVAL_REQUIRED" | "READY_FOR_IMPLEMENTATION";

export type ArchitectureGenerationIssue =
  | "PROJECT_NOT_FOUND"
  | "DESIGN_APPROVAL_REQUIRED"
  | "ARCHITECTURE_PACKAGE_ALREADY_EXISTS"
  | "PROPOSAL_REJECTED"
  | "INVALID_PROPOSAL"
  | "CONTEXT_CHANGED"
  | "PERSISTENCE_REJECTED";

export type ArchitectureProposalIssue =
  | "SOFTWARE_ARCHITECT_REQUIRED"
  | "QA_TEST_ENGINEER_REQUIRED"
  | "DESIGN_SELECTION_REQUIRED"
  | "GROUNDED_INPUT_REQUIRED"
  | "INVALID_PROVIDER_OUTPUT";

export type ArchitectureVersionAppendStatus =
  "APPENDED" | "PROJECT_NOT_FOUND" | "VERSION_CONFLICT" | "CONTENT_CONFLICT";

export type ArchitectureRevisionApplicationIssue =
  | "PACKAGE_NOT_FOUND"
  | "DIFF_ALREADY_PENDING"
  | "INVALID_PROPOSAL"
  | "DIFF_NOT_FOUND"
  | "DECISION_REJECTED"
  | "CONTEXT_CHANGED"
  | "PERSISTENCE_REJECTED";

export type ArchitectureRevisionIssue =
  | "PROJECT_MISMATCH"
  | "CONTEXT_CHANGED"
  | "IDENTIFIER_CHANGED"
  | "NO_CHANGES"
  | "DIFF_ALREADY_DECIDED"
  | "BASE_VERSION_STALE"
  | "ACTOR_NOT_OWNER"
  | "REASON_REQUIRED"
  | "REASON_TOO_LONG"
  | "TIMESTAMP_NOT_AWARE"
  | "TIMESTAMP_OUT_OF_ORDER";

export type ArchitectureDiffPersistenceStatus =
  "CREATED" | "UPDATED" | "PROJECT_NOT_FOUND" | "CONTEXT_NOT_FOUND" | "CONFLICT";

export interface VersionedArtifactReferencePayload {
  kind: ArtifactKind;
  artifact_id: UUID;
  version_number: number;
  content_hash: string;
}

export interface UserTwinVersionReferencePayload {
  twin_id: UUID;
  version_number: number;
  content_hash: string;
  name: string;
}

export interface ArchitectureCatalogPayload {
  version: number;
  content_hash: string;
}

export interface ArchitectureGroundingPayload {
  project_id: UUID;
  design_package_reference: VersionedArtifactReferencePayload;
  requirements_reference: VersionedArtifactReferencePayload;
  agent_team_reference: VersionedArtifactReferencePayload;
  user_modeling_reference: VersionedArtifactReferencePayload;
  catalog: ArchitectureCatalogPayload;
  owner_selected_alternative_id: UUID;
  prototype_id: UUID;
  requirement_ids: UUID[];
  user_story_ids: UUID[];
  acceptance_criterion_ids: UUID[];
  user_twin_references: UserTwinVersionReferencePayload[];
}

export interface ArchitectureComponentPayload {
  id: UUID;
  code: string;
  name: string;
  kind: ArchitectureComponentKind;
  responsibility: string;
  technology: string;
  interfaces: string[];
  requirement_ids: UUID[];
  assumptions: string[];
}

export interface ArchitectureConnectionPayload {
  id: UUID;
  code: string;
  source_component_id: UUID;
  target_component_id: UUID;
  kind: ArchitectureConnectionKind;
  description: string;
  data_flows: string[];
  requirement_ids: UUID[];
}

export interface ArchitectureDecisionPayload {
  id: UUID;
  code: string;
  title: string;
  context: string;
  decision: string;
  consequences: string[];
  alternatives_considered: string[];
  requirement_ids: UUID[];
}

export interface ArchitectureDataEntityPayload {
  id: UUID;
  code: string;
  name: string;
  description: string;
  fields: string[];
  owning_component_id: UUID;
  requirement_ids: UUID[];
}

export interface ArchitectureApiOperationPayload {
  id: UUID;
  code: string;
  method: ApiMethod;
  path: string;
  summary: string;
  owning_component_id: UUID;
  request_schema: string | null;
  response_schema: string;
  requirement_ids: UUID[];
  acceptance_criterion_ids: UUID[];
}

export interface ArchitectureRiskPayload {
  id: UUID;
  code: string;
  summary: string;
  likelihood: RiskLikelihood;
  impact: RiskImpact;
  mitigation: string;
  component_ids: UUID[];
  requirement_ids: UUID[];
}

export interface SoftwareArchitecturePayload {
  id: UUID;
  code: string;
  title: string;
  style: ArchitectureStyle;
  summary: string;
  selected_design_alternative_id: UUID;
  prototype_id: UUID;
  requirement_ids: UUID[];
  acceptance_criterion_ids: UUID[];
  components: ArchitectureComponentPayload[];
  connections: ArchitectureConnectionPayload[];
  decisions: ArchitectureDecisionPayload[];
  data_entities: ArchitectureDataEntityPayload[];
  api_operations: ArchitectureApiOperationPayload[];
  risks: ArchitectureRiskPayload[];
  quality_attributes: string[];
  deployment_view: string[];
  assumptions: string[];
  open_questions: string[];
}

export interface TestEnvironmentPayload {
  id: UUID;
  code: string;
  name: string;
  kind: TestEnvironmentKind;
  description: string;
  configuration: string[];
}

export interface PlannedTestCasePayload {
  id: UUID;
  code: string;
  title: string;
  objective: string;
  level: TestLevel;
  automation: TestAutomation;
  priority: TestPriority;
  preconditions: string[];
  steps: string[];
  expected_results: string[];
  requirement_ids: UUID[];
  acceptance_criterion_ids: UUID[];
  architecture_component_ids: UUID[];
  design_alternative_ids: UUID[];
  environment_ids: UUID[];
}

export interface QualityGatePayload {
  id: UUID;
  code: string;
  title: string;
  criterion: string;
  required_test_case_ids: UUID[];
  minimum_pass_rate: number;
  blocking: boolean;
}

export interface TestPlanPayload {
  id: UUID;
  code: string;
  title: string;
  strategy: string;
  architecture_id: UUID;
  selected_design_alternative_id: UUID;
  requirement_ids: UUID[];
  acceptance_criterion_ids: UUID[];
  architecture_component_ids: UUID[];
  environments: TestEnvironmentPayload[];
  test_cases: PlannedTestCasePayload[];
  quality_gates: QualityGatePayload[];
  fixtures: string[];
  assumptions: string[];
  open_questions: string[];
}

export interface ArchitecturePackagePayload {
  schema_version: number;
  project_id: UUID;
  grounding: ArchitectureGroundingPayload;
  architecture: SoftwareArchitecturePayload;
  test_plan: TestPlanPayload;
  open_questions: string[];
}

export interface ArchitecturePackageVersionPayload {
  id: UUID;
  project_id: UUID;
  version_number: number;
  based_on_version_number: number | null;
  content_hash: string;
  package: ArchitecturePackagePayload;
  created_by_user_id: UUID;
  created_at: IsoDateTime;
}

export interface ArchitectureChangePayload {
  kind: ArchitectureChangeKind;
  artifact_kind: ArchitectureArtifactKind;
  artifact_id: UUID;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
}

export interface ArchitecturePackageDiffPayload {
  id: UUID;
  project_id: UUID;
  owner_user_id: UUID;
  base_version_id: UUID;
  base_version_number: number;
  base_content_hash: string;
  proposed_package: ArchitecturePackagePayload;
  proposal_hash: string;
  changes: ArchitectureChangePayload[];
  status: ArchitecturePackageDiffStatus;
  created_at: IsoDateTime;
  decided_by_user_id: UUID | null;
  decided_at: IsoDateTime | null;
  decision_reason: string | null;
  applied_version_id: UUID | null;
  content_hash: string;
}

export interface HumanGateArtifactPayload {
  project_id: UUID;
  gate_type: "ARCHITECTURE";
  artifact_id: UUID;
  version: number;
  content_hash: string;
}

export interface HumanGatePayload {
  id: UUID;
  project_id: UUID;
  owner_user_id: UUID;
  gate_type: "ARCHITECTURE";
  artifact: HumanGateArtifactPayload;
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
  kind: HumanGateAction | "ARTIFACT_SUPERSEDED";
  previous_status: HumanGateStatus;
  resulting_status: HumanGateStatus;
  artifact: HumanGateArtifactPayload;
  occurred_at: IsoDateTime;
  actor_user_id: UUID | null;
  reason: string | null;
}

export interface ArchitectureGenerationPayload {
  status: "CREATED" | "REJECTED";
  version: ArchitecturePackageVersionPayload | null;
  issue: ArchitectureGenerationIssue | null;
  proposal_issue: ArchitectureProposalIssue | null;
  persistence_status: ArchitectureVersionAppendStatus | null;
}

export interface ArchitectureRevisionRequest {
  package: ArchitecturePackagePayload;
}

export interface ArchitectureRevisionDecisionRequest {
  decision: ArchitectureRevisionDecision;
  reason?: string | null;
}

export interface ArchitectureRevisionPayload {
  status: "CREATED" | "APPLIED" | "REJECTED";
  diff: ArchitecturePackageDiffPayload | null;
  version: ArchitecturePackageVersionPayload | null;
  issue: ArchitectureRevisionApplicationIssue | null;
  domain_issue: ArchitectureRevisionIssue | null;
  diff_persistence_status: ArchitectureDiffPersistenceStatus | null;
  version_persistence_status: ArchitectureVersionAppendStatus | null;
}

export interface ArchitectureGateDecisionRequest {
  action: ArchitectureGateDecisionAction;
  reason?: string | null;
}

export interface ArchitectureGateSubmissionPayload {
  status:
    | "SUBMITTED"
    | "ALREADY_PENDING"
    | "ALREADY_APPROVED"
    | "PACKAGE_NOT_FOUND"
    | "NEW_PACKAGE_REQUIRED"
    | "GATE_BLOCKED"
    | "ITERATION_LIMIT_REACHED"
    | "TRANSITION_REJECTED";
  gate: HumanGatePayload | null;
  events: HumanGateEventPayload[];
  issue: string | null;
}

export interface ArchitectureGateDecisionPayload {
  status: "APPLIED" | "GATE_NOT_FOUND" | "PACKAGE_NOT_FOUND" | "ARTIFACT_STALE" | "REJECTED";
  gate: HumanGatePayload | null;
  event: HumanGateEventPayload | null;
  issue: string | null;
}

export interface ArchitectureReadinessPayload {
  status: ArchitectureWorkflowReadiness;
  version: ArchitecturePackageVersionPayload | null;
  gate: HumanGatePayload | null;
  has_package: boolean;
  approved_current_package: boolean;
}
