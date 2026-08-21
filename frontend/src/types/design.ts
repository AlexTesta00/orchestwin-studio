export type UUID = string;
export type IsoDateTime = string;

export type ArtifactKind =
  | "REQUIREMENTS_SPECIFICATION"
  | "AGENT_TEAM"
  | "USER_MODELING"
  | "DESIGN_PACKAGE"
  | "DECLARATIVE_PROTOTYPE"
  | "ARCHITECTURE_PACKAGE";

export type DesignApproach =
  "GUIDED_WORKFLOW" | "DASHBOARD_FIRST" | "TASK_FOCUSED" | "INFORMATION_RICH";

export type DesignCritiqueKind = "SYNTHETIC_USER_TWIN";

export type EvidenceSourceKind =
  | "PROJECT_BRIEF"
  | "OWNER_INPUT"
  | "EMPIRICAL_RESEARCH"
  | "HUMAN_REVIEW"
  | "MODEL_OUTPUT"
  | "SYSTEM_ARTIFACT";

export type EpistemicStatus =
  | "USER_PROVIDED"
  | "EMPIRICALLY_SUPPORTED"
  | "HUMAN_VALIDATED"
  | "MODEL_INFERRED"
  | "UNSUPPORTED_ASSUMPTION";

export type HumanValidationRequirement = "REQUIRED" | "NOT_REQUIRED";

export type PrototypeElementKind =
  "HEADING" | "TEXT" | "TEXT_INPUT" | "SELECT" | "BUTTON" | "LINK" | "LIST" | "CARD" | "STATUS";

export type PrototypeViewport = "MOBILE" | "TABLET" | "DESKTOP";
export type PrototypeScreenState = "DEFAULT" | "EMPTY" | "ERROR" | "SUCCESS";

export type DesignChangeKind = "ADD" | "REPLACE" | "REMOVE";
export type DesignArtifactKind =
  "ALTERNATIVE" | "CRITIQUE" | "CONCERN" | "PROTOTYPE" | "SELECTION" | "OPEN_QUESTIONS";
export type DesignPackageDiffStatus = "PROPOSED" | "APPROVED" | "REJECTED";
export type DesignRevisionDecision = "APPROVE" | "REJECT";

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

export type DesignGateDecisionAction = Exclude<HumanGateAction, "SUBMIT">;

export type DesignWorkflowReadiness =
  | "DESIGN_REQUIRED"
  | "DESIGN_REVIEW_REQUIRED"
  | "DESIGN_APPROVAL_REQUIRED"
  | "READY_FOR_ARCHITECTURE_PLANNING";

export type DesignGenerationIssue =
  | "PROJECT_NOT_FOUND"
  | "REQUIREMENTS_APPROVAL_REQUIRED"
  | "DESIGN_PACKAGE_ALREADY_EXISTS"
  | "PROPOSAL_REJECTED"
  | "INVALID_PROPOSAL"
  | "CONTEXT_CHANGED"
  | "PERSISTENCE_REJECTED";

export type DesignProposalIssue =
  "UX_DESIGNER_REQUIRED" | "GROUNDED_INPUT_REQUIRED" | "INVALID_PROVIDER_OUTPUT";

export type DesignVersionAppendStatus =
  "APPENDED" | "PROJECT_NOT_FOUND" | "VERSION_CONFLICT" | "CONTENT_CONFLICT";

export type DesignRevisionApplicationIssue =
  | "PACKAGE_NOT_FOUND"
  | "DIFF_ALREADY_PENDING"
  | "INVALID_PROPOSAL"
  | "DIFF_NOT_FOUND"
  | "DECISION_REJECTED"
  | "CONTEXT_CHANGED"
  | "PERSISTENCE_REJECTED";

export type DesignRevisionIssue =
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

export type DesignDiffPersistenceStatus =
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

export interface DesignCatalogPayload {
  version: number;
  content_hash: string;
}

export interface DesignGroundingPayload {
  requirements_reference: VersionedArtifactReferencePayload;
  agent_team_reference: VersionedArtifactReferencePayload;
  user_modeling_reference: VersionedArtifactReferencePayload;
  catalog: DesignCatalogPayload;
  requirement_ids: UUID[];
  user_story_ids: UUID[];
  acceptance_criterion_ids: UUID[];
  user_twin_references: UserTwinVersionReferencePayload[];
}

export interface DesignWorkflowPayload {
  id: UUID;
  code: string;
  title: string;
  steps: string[];
  requirement_ids: UUID[];
  user_story_ids: UUID[];
}

export interface DesignAlternativePayload {
  id: UUID;
  code: string;
  approach: DesignApproach;
  title: string;
  summary: string;
  rationale: string;
  requirement_ids: UUID[];
  user_story_ids: UUID[];
  acceptance_criterion_ids: UUID[];
  user_twin_references: UserTwinVersionReferencePayload[];
  workflows: DesignWorkflowPayload[];
  information_architecture: string[];
  accessibility_considerations: string[];
  security_considerations: string[];
  advantages: string[];
  trade_offs: string[];
  assumptions: string[];
  open_questions: string[];
}

export interface EvidenceReferencePayload {
  source_kind: EvidenceSourceKind;
  source_id: string;
  source_version: number | null;
  content_hash: string | null;
  locator: string | null;
  summary: string | null;
}

export interface SyntheticDesignCritiquePayload {
  id: UUID;
  code: string;
  kind: DesignCritiqueKind;
  design_alternative_id: UUID;
  user_twin_reference: UserTwinVersionReferencePayload;
  strengths: string[];
  concerns: string[];
  unmet_needs: string[];
  accessibility_observations: string[];
  trust_concerns: string[];
  questions: string[];
  suggested_changes: string[];
  provenance: EvidenceReferencePayload[];
  confidence: number;
  epistemic_status: EpistemicStatus;
  human_validation: HumanValidationRequirement;
  rationale: string;
}

export interface PrototypeElementPayload {
  id: UUID;
  code: string;
  kind: PrototypeElementKind;
  content: string;
  accessible_name: string | null;
  requirement_ids: UUID[];
  user_story_ids: UUID[];
  acceptance_criterion_ids: UUID[];
  field_name: string | null;
  required: boolean;
  options: string[];
}

export interface PrototypeScreenPayload {
  id: UUID;
  code: string;
  title: string;
  state: PrototypeScreenState;
  elements: PrototypeElementPayload[];
  requirement_ids: UUID[];
  user_story_ids: UUID[];
  acceptance_criterion_ids: UUID[];
}

export interface PrototypeTransitionPayload {
  id: UUID;
  code: string;
  source_screen_id: UUID;
  trigger_element_id: UUID;
  target_screen_id: UUID;
  outcome: string;
}

export interface DeclarativePrototypePayload {
  id: UUID;
  code: string;
  title: string;
  design_alternative_id: UUID;
  entry_screen_id: UUID;
  screens: PrototypeScreenPayload[];
  transitions: PrototypeTransitionPayload[];
  supported_viewports: PrototypeViewport[];
}

export interface DesignConcernPayload {
  id: UUID;
  code: string;
  summary: string;
  mitigation: string;
  requirement_ids: UUID[];
  design_alternative_ids: UUID[];
}

export interface DesignPackagePayload {
  schema_version: number;
  project_id: UUID;
  grounding: DesignGroundingPayload;
  alternatives: DesignAlternativePayload[];
  critiques: SyntheticDesignCritiquePayload[];
  recommended_alternative_id: UUID | null;
  owner_selected_alternative_id: UUID | null;
  prototype: DeclarativePrototypePayload | null;
  concerns: DesignConcernPayload[];
  open_questions: string[];
}

export interface DesignPackageVersionPayload {
  id: UUID;
  project_id: UUID;
  version_number: number;
  based_on_version_number: number | null;
  content_hash: string;
  package: DesignPackagePayload;
  created_by_user_id: UUID;
  created_at: IsoDateTime;
  ready_for_gate: boolean;
}

export interface DesignChangePayload {
  kind: DesignChangeKind;
  artifact_kind: DesignArtifactKind;
  artifact_id: UUID;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
}

export interface DesignPackageDiffPayload {
  id: UUID;
  project_id: UUID;
  owner_user_id: UUID;
  base_version_id: UUID;
  base_version_number: number;
  base_content_hash: string;
  proposed_package: DesignPackagePayload;
  proposal_hash: string;
  changes: DesignChangePayload[];
  status: DesignPackageDiffStatus;
  created_at: IsoDateTime;
  decided_by_user_id: UUID | null;
  decided_at: IsoDateTime | null;
  decision_reason: string | null;
  applied_version_id: UUID | null;
  content_hash: string;
}

export interface HumanGateArtifactPayload {
  project_id: UUID;
  gate_type: "DESIGN";
  artifact_id: UUID;
  version: number;
  content_hash: string;
}

export interface HumanGatePayload {
  id: UUID;
  project_id: UUID;
  owner_user_id: UUID;
  gate_type: "DESIGN";
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

export interface DesignGenerationPayload {
  status: "CREATED" | "REJECTED";
  version: DesignPackageVersionPayload | null;
  issue: DesignGenerationIssue | null;
  proposal_issue: DesignProposalIssue | null;
  persistence_status: DesignVersionAppendStatus | null;
}

export interface DesignRevisionRequest {
  package: DesignPackagePayload;
}

export interface DesignRevisionDecisionRequest {
  decision: DesignRevisionDecision;
  reason?: string | null;
}

export interface DesignRevisionPayload {
  status: "CREATED" | "APPLIED" | "REJECTED";
  diff: DesignPackageDiffPayload | null;
  version: DesignPackageVersionPayload | null;
  issue: DesignRevisionApplicationIssue | null;
  domain_issue: DesignRevisionIssue | null;
  diff_persistence_status: DesignDiffPersistenceStatus | null;
  version_persistence_status: DesignVersionAppendStatus | null;
}

export interface DesignGateDecisionRequest {
  action: DesignGateDecisionAction;
  reason?: string | null;
}

export interface DesignGateSubmissionPayload {
  status:
    | "SUBMITTED"
    | "ALREADY_PENDING"
    | "ALREADY_APPROVED"
    | "PACKAGE_NOT_FOUND"
    | "PACKAGE_NOT_READY"
    | "NEW_PACKAGE_REQUIRED"
    | "GATE_BLOCKED"
    | "ITERATION_LIMIT_REACHED"
    | "TRANSITION_REJECTED";
  gate: HumanGatePayload | null;
  events: HumanGateEventPayload[];
  issue: string | null;
}

export interface DesignGateDecisionPayload {
  status: "APPLIED" | "GATE_NOT_FOUND" | "PACKAGE_NOT_FOUND" | "ARTIFACT_STALE" | "REJECTED";
  gate: HumanGatePayload | null;
  event: HumanGateEventPayload | null;
  issue: string | null;
}

export interface DesignReadinessPayload {
  status: DesignWorkflowReadiness;
  version: DesignPackageVersionPayload | null;
  gate: HumanGatePayload | null;
  has_package: boolean;
  package_ready_for_gate: boolean;
  approved_current_package: boolean;
}
