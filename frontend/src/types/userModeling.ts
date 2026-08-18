export type UUID = string;
export type IsoDateTime = string;

export type EpistemicStatus =
  | "USER_PROVIDED"
  | "EMPIRICALLY_SUPPORTED"
  | "HUMAN_VALIDATED"
  | "MODEL_INFERRED"
  | "UNSUPPORTED_ASSUMPTION";

export type EvidenceSourceKind =
  | "PROJECT_BRIEF"
  | "OWNER_INPUT"
  | "EMPIRICAL_RESEARCH"
  | "HUMAN_REVIEW"
  | "MODEL_OUTPUT"
  | "SYSTEM_ARTIFACT";

export type HumanValidationRequirement = "REQUIRED" | "NOT_REQUIRED";

export type ObservationValueKind = "TEXT" | "ITEMS" | "UNKNOWN" | "ABSTAINED";

export type PersonaSource = "OWNER_PROVIDED" | "SYSTEM_PROPOSED";

export type PersonaKind = "PERSONA" | "PROTO_PERSONA";

export type PersonaConfirmationStatus = "PENDING_CONFIRMATION" | "CONFIRMED" | "REJECTED";

export type UserTwinLifecycleStatus =
  | "PROTO_UT"
  | "PROJECT_GROUNDED_UT"
  | "OWNER_APPROVED_UT"
  | "EMPIRICALLY_GROUNDED_UT"
  | "EMPIRICALLY_VALIDATED_UT";

export type UserTwinField =
  | "role"
  | "age_range"
  | "expertise"
  | "goals"
  | "recurring_tasks"
  | "context_of_use"
  | "information_needs"
  | "decision_criteria"
  | "preferred_vocabulary"
  | "frustrations"
  | "pain_points"
  | "trust_concerns"
  | "accessibility_needs"
  | "operational_constraints"
  | "technical_literacy"
  | "risk_sensitivity"
  | "assumptions";

export type PersonaOwnerDecision = "CONFIRM" | "REJECT";

export type ProfileRevisionDecision = "APPROVE" | "REJECT";

export type HumanGateType = "PROJECT_BRIEF" | "AGENT_TEAM" | "USER_MODELING";

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

export type GateDecisionAction = Exclude<HumanGateAction, "SUBMIT">;

export type GateApiOutcome = "APPLIED" | "NO_CHANGE" | "NOT_FOUND" | "STALE" | "REJECTED";

export type UserModelingWorkflowState =
  "USER_MODELING_REQUIRED" | "USER_MODELING_REVIEW_REQUIRED" | "READY_FOR_REQUIREMENTS_DEFINITION";

export interface EvidenceReferencePayload {
  source_kind: EvidenceSourceKind;
  source_id: string;
  source_version: number | null;
  content_hash: string | null;
  locator: string | null;
  summary: string | null;
}

export interface ObservationValuePayload {
  kind: ObservationValueKind;
  text: string | null;
  items: string[];
  reason: string | null;
}

export interface ProfileObservationPayload {
  observation_key: string;
  value: ObservationValuePayload;
  epistemic_status: EpistemicStatus;
  confidence: number;
  provenance: EvidenceReferencePayload[];
  human_validation: HumanValidationRequirement;
  rationale: string | null;
}

export interface ArtifactReferencePayload {
  artifact_id: UUID;
  version_number: number;
  content_hash: string;
}

export interface PersonaProfilePayload {
  name: string;
  source: PersonaSource;
  kind: PersonaKind;
  confirmation_status: PersonaConfirmationStatus;
  rejection_reason: string | null;
  observations: ProfileObservationPayload[];
}

export interface PersonaVersionPayload {
  id: UUID;
  project_id: UUID;
  persona_id: UUID;
  version_number: number;
  based_on_version_number: number | null;
  content_hash: string;
  created_by_user_id: UUID;
  created_at: IsoDateTime;
  profile: PersonaProfilePayload;
}

export interface ConfirmedPersonaReferencePayload {
  persona_id: UUID;
  version_number: number;
  content_hash: string;
  source: PersonaSource;
  kind: PersonaKind;
  confirmation_status: PersonaConfirmationStatus;
}

export interface UserTwinProfilePayload {
  name: string;
  persona_reference: ConfirmedPersonaReferencePayload;
  project_brief_reference: ArtifactReferencePayload;
  agent_team_reference: ArtifactReferencePayload;
  catalog_version: number;
  catalog_content_hash: string;
  validation_status: UserTwinLifecycleStatus;
  observations: ProfileObservationPayload[];
}

export interface UserTwinVersionPayload {
  id: UUID;
  project_id: UUID;
  twin_id: UUID;
  version_number: number;
  based_on_version_number: number | null;
  content_hash: string;
  created_by_user_id: UUID;
  created_at: IsoDateTime;
  profile: UserTwinProfilePayload;
}

export interface UserModelingSnapshotPayload {
  project_id: UUID;
  project_brief_reference: ArtifactReferencePayload;
  agent_team_reference: ArtifactReferencePayload;
  catalog_version: number;
  catalog_content_hash: string;
  persona_count: number;
  twin_count: number;
  persona_versions: PersonaVersionPayload[];
  twin_versions: UserTwinVersionPayload[];
}

export interface UserModelingSnapshotVersionPayload {
  id: UUID;
  project_id: UUID;
  version_number: number;
  based_on_version_number: number | null;
  content_hash: string;
  created_by_user_id: UUID;
  created_at: IsoDateTime;
  snapshot: UserModelingSnapshotPayload;
}

export interface ProfileDiffOperationPayload {
  field: UserTwinField;
  before: ProfileObservationPayload | null;
  after: ProfileObservationPayload;
}

export interface UserTwinProfileDiffPayload {
  id: UUID;
  project_id: UUID;

  base_snapshot_version_id: UUID;
  base_snapshot_version_number: number;
  base_snapshot_content_hash: string;

  twin_id: UUID;
  base_twin_version_id: UUID;
  base_twin_version_number: number;
  base_twin_content_hash: string;

  proposal_hash: string;
  status: "PROPOSED" | "APPROVED" | "REJECTED";

  operations: ProfileDiffOperationPayload[];

  created_by_user_id: UUID;
  created_at: IsoDateTime;

  decided_by_user_id: UUID | null;
  decided_at: IsoDateTime | null;
  decision_reason: string | null;
  applied_snapshot_version_id: UUID | null;
}

export interface GateArtifactPayload {
  project_id: UUID;
  gate_type: HumanGateType;
  artifact_id: UUID;
  version: number;
  content_hash: string;
}

export interface HumanGatePayload {
  id: UUID;
  project_id: UUID;
  owner_user_id: UUID;
  gate_type: HumanGateType;
  artifact: GateArtifactPayload;
  iteration: number;
  max_iterations: number;
  status: HumanGateStatus;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
  event_sequence: number;
}

export interface HumanGateEventPayload {
  id: UUID;
  gate_id: UUID;
  sequence_number: number;
  kind: HumanGateAction | "ARTIFACT_SUPERSEDED";
  previous_status: HumanGateStatus;
  resulting_status: HumanGateStatus;
  artifact: GateArtifactPayload;
  occurred_at: IsoDateTime;
  actor_user_id: UUID | null;
  reason: string | null;
}

export interface PersonaDecisionRequest {
  decision: PersonaOwnerDecision;
  reason?: string | null;
}

export interface ProfileReplacementRequest {
  field: UserTwinField;
  value: ObservationValuePayload;
  epistemic_status: "USER_PROVIDED" | "HUMAN_VALIDATED";
  confidence: number;
  provenance: EvidenceReferencePayload[];
  human_validation: "NOT_REQUIRED";
  rationale?: string | null;
}

export interface ProfileRevisionProposalRequest {
  replacements: ProfileReplacementRequest[];
}

export interface ProfileRevisionDecisionRequest {
  decision: ProfileRevisionDecision;
  reason?: string | null;
}

export interface GateDecisionRequest {
  action: GateDecisionAction;
  reason?: string | null;
}

export interface PersonaProposalCommandPayload {
  status: "CREATED" | "APPLIED" | "NO_CHANGE" | "REJECTED";
  issue: string | null;
  candidate_issue: string | null;
  proposal_issue: string | null;
  versions: PersonaVersionPayload[];
}

export interface PersonaDecisionCommandPayload {
  status: "CREATED" | "APPLIED" | "NO_CHANGE" | "REJECTED";
  issue: string | null;
  decision_issue: string | null;
  version: PersonaVersionPayload | null;
}

export interface SnapshotGenerationCommandPayload {
  status: "CREATED" | "APPLIED" | "NO_CHANGE" | "REJECTED";
  issue: string | null;
  proposal_issue: string | null;
  snapshot_version: UserModelingSnapshotVersionPayload | null;
  twin_versions: UserTwinVersionPayload[];
}

export interface ProfileRevisionCommandPayload {
  status: "CREATED" | "APPLIED" | "NO_CHANGE" | "REJECTED";
  issue: string | null;
  proposal_issue: string | null;
  diff: UserTwinProfileDiffPayload | null;
  twin_version: UserTwinVersionPayload | null;
  snapshot_version: UserModelingSnapshotVersionPayload | null;
}

export interface GateCommandPayload {
  outcome: GateApiOutcome;
  gate: HumanGatePayload | null;
  events: HumanGateEventPayload[];
  issue: string | null;
}

export interface EffectiveTwinLifecyclePayload {
  twin_id: UUID;
  version_number: number;
  persisted_status: UserTwinLifecycleStatus;
  effective_status: UserTwinLifecycleStatus;
}

export interface UserModelingReadinessPayload {
  snapshot_exists: boolean;
  snapshot_version_id: UUID | null;
  snapshot_version_number: number | null;
  snapshot_content_hash: string | null;

  gate_exists: boolean;
  gate_id: UUID | null;
  gate_status: HumanGateStatus | null;

  approved_current_snapshot: boolean;
  workflow_state: UserModelingWorkflowState;

  twins: EffectiveTwinLifecyclePayload[];
}
