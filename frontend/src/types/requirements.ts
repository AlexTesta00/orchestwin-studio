export type UUID = string;
export type IsoDateTime = string;

export type RequirementsContextKind = "PROJECT_BRIEF" | "AGENT_TEAM" | "USER_MODELING";

export type RequirementSourceKind =
  "PROJECT_BRIEF" | "USER_TWIN" | "OWNER_INPUT" | "MODEL_PROPOSAL" | "SYSTEM_ARTIFACT";

export type RequirementKind = "FUNCTIONAL" | "NON_FUNCTIONAL" | "CONSTRAINT";
export type RequirementPriority = "MUST" | "SHOULD" | "COULD" | "WONT_FOR_NOW";

export type VerificationMethod =
  "AUTOMATED_TEST" | "MANUAL_REVIEW" | "INSPECTION" | "DEMONSTRATION" | "ANALYSIS";

export type RiskLikelihood = "RARE" | "UNLIKELY" | "POSSIBLE" | "LIKELY" | "ALMOST_CERTAIN";
export type RiskImpact = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type RiskReviewStatus = "PROPOSED" | "OWNER_ACKNOWLEDGED" | "OWNER_REJECTED";
export type DefinitionOfDoneApplicability = "REQUIRED" | "CONDITIONAL";

export type RequirementsArtifactKind =
  | "REQUIREMENT"
  | "USER_STORY"
  | "ACCEPTANCE_CRITERION"
  | "SCENARIO"
  | "RISK"
  | "DEFINITION_OF_DONE";

export type RequirementsDiffOperationKind = "ADD" | "REPLACE" | "REMOVE";
export type RequirementsDiffStatus = "PROPOSED" | "APPROVED" | "REJECTED";
export type RequirementsRevisionDecision = "APPROVE" | "REJECT";

export type TraceabilityNodeKind =
  | "USER_TWIN"
  | "USER_STORY"
  | "REQUIREMENT"
  | "ACCEPTANCE_CRITERION"
  | "SCENARIO"
  | "RISK"
  | "DEFINITION_OF_DONE";

export type TraceabilityLinkKind =
  "ACTS_AS" | "MOTIVATES" | "VERIFIED_BY" | "EXERCISES" | "AFFECTS" | "GOVERNS";

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

export type RequirementsGateDecisionAction = Exclude<HumanGateAction, "SUBMIT">;

export type RequirementsWorkflowReadiness =
  "REQUIREMENTS_REQUIRED" | "REQUIREMENTS_APPROVAL_REQUIRED" | "READY_FOR_DESIGN_EXPLORATION";

export interface RequirementsContextReferencePayload {
  kind: RequirementsContextKind;
  artifact_id: UUID;
  version_number: number;
  content_hash: string;
}

export interface RequirementSourcePayload {
  kind: RequirementSourceKind;
  source_id: string;
  source_version: number | null;
  content_hash: string | null;
  locator: string | null;
}

export interface UserTwinVersionReferencePayload {
  twin_id: UUID;
  version_number: number;
  content_hash: string;
  name: string;
}

export interface RequirementPayload {
  id: UUID;
  code: string;
  title: string;
  statement: string;
  kind: RequirementKind;
  priority: RequirementPriority;
  sources: RequirementSourcePayload[];
  user_twin_references: UserTwinVersionReferencePayload[];
}

export interface UserStoryPayload {
  id: UUID;
  code: string;
  user_twin_reference: UserTwinVersionReferencePayload;
  goal: string;
  benefit: string;
  requirement_ids: UUID[];
}

export interface AcceptanceCriterionPayload {
  id: UUID;
  code: string;
  statement: string;
  verification_method: VerificationMethod;
  requirement_ids: UUID[];
  user_story_ids: UUID[];
}

export interface UsageScenarioPayload {
  id: UUID;
  code: string;
  title: string;
  actor: UserTwinVersionReferencePayload;
  preconditions: string[];
  trigger: string;
  steps: string[];
  expected_outcome: string;
  requirement_ids: UUID[];
  acceptance_criterion_ids: UUID[];
}

export interface ProjectRiskPayload {
  id: UUID;
  code: string;
  summary: string;
  likelihood: RiskLikelihood;
  impact: RiskImpact;
  mitigation: string;
  requirement_ids: UUID[];
  sources: RequirementSourcePayload[];
  review_status: RiskReviewStatus;
}

export interface DefinitionOfDoneItemPayload {
  id: UUID;
  code: string;
  statement: string;
  verification_method: VerificationMethod;
  applicability: DefinitionOfDoneApplicability;
  condition: string | null;
  requirement_ids: UUID[];
}

export interface RequirementsSpecificationPayload {
  project_id: UUID;
  project_brief_reference: RequirementsContextReferencePayload;
  agent_team_reference: RequirementsContextReferencePayload;
  user_modeling_reference: RequirementsContextReferencePayload;
  catalog_version: number;
  catalog_content_hash: string;
  user_twin_references: UserTwinVersionReferencePayload[];
  requirements: RequirementPayload[];
  user_stories: UserStoryPayload[];
  acceptance_criteria: AcceptanceCriterionPayload[];
  scenarios: UsageScenarioPayload[];
  risks: ProjectRiskPayload[];
  definition_of_done: DefinitionOfDoneItemPayload[];
}

export interface RequirementsSpecificationVersionPayload {
  id: UUID;
  project_id: UUID;
  version_number: number;
  based_on_version_number: number | null;
  content_hash: string;
  created_by_user_id: UUID;
  created_at: IsoDateTime;
  specification: RequirementsSpecificationPayload;
}

export interface RequirementsArtifactEnvelope {
  kind: RequirementsArtifactKind;
  requirement: RequirementPayload | null;
  user_story: UserStoryPayload | null;
  acceptance_criterion: AcceptanceCriterionPayload | null;
  scenario: UsageScenarioPayload | null;
  risk: ProjectRiskPayload | null;
  definition_of_done: DefinitionOfDoneItemPayload | null;
}

export interface RequirementsDiffOperationPayload {
  artifact_kind: RequirementsArtifactKind;
  operation: RequirementsDiffOperationKind;
  artifact_id: UUID;
  display_code: string;
  before: RequirementsArtifactEnvelope | null;
  after: RequirementsArtifactEnvelope | null;
}

export interface RequirementsSpecificationDiffPayload {
  id: UUID;
  project_id: UUID;
  base_version_id: UUID;
  base_version_number: number;
  base_content_hash: string;
  proposed_content_hash: string;
  proposal_hash: string;
  status: RequirementsDiffStatus;
  proposed_specification: RequirementsSpecificationPayload;
  operations: RequirementsDiffOperationPayload[];
  created_by_user_id: UUID;
  created_at: IsoDateTime;
  decided_by_user_id: UUID | null;
  decided_at: IsoDateTime | null;
  decision_reason: string | null;
  applied_specification_version_id: UUID | null;
}

export interface TraceabilityNodeReferencePayload {
  kind: TraceabilityNodeKind;
  artifact_id: UUID;
}

export interface TraceabilityNodePayload {
  reference: TraceabilityNodeReferencePayload;
  display_code: string;
}

export interface TraceabilityLinkPayload {
  kind: TraceabilityLinkKind;
  source: TraceabilityNodeReferencePayload;
  target: TraceabilityNodeReferencePayload;
}

export interface RequirementsTraceabilityPayload {
  project_id: UUID;
  specification_version_id: UUID;
  specification_version_number: number;
  specification_content_hash: string;
  content_hash: string;
  nodes: TraceabilityNodePayload[];
  links: TraceabilityLinkPayload[];
}

export interface RequirementsCoveragePayload {
  project_id: UUID;
  specification_version_id: UUID;
  requirement_count: number;
  user_story_count: number;
  acceptance_criterion_count: number;
  requirement_ids_without_user_stories: UUID[];
  requirement_ids_without_acceptance_criteria: UUID[];
  user_story_ids_without_acceptance_criteria: UUID[];
  acceptance_criterion_ids_without_scenarios: UUID[];
  has_full_acceptance_coverage: boolean;
}

export interface HumanGateArtifactPayload {
  project_id: UUID;
  gate_type: "REQUIREMENTS";
  artifact_id: UUID;
  version: number;
  content_hash: string;
}

export interface HumanGatePayload {
  id: UUID;
  project_id: UUID;
  owner_user_id: UUID;
  gate_type: "REQUIREMENTS";
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

export interface RequirementsGenerationPayload {
  status: "CREATED" | "REJECTED";
  version: RequirementsSpecificationVersionPayload | null;
  issue: string | null;
  proposal_issue: string | null;
  persistence_status: string | null;
}

export interface RequirementsRevisionRequest {
  specification: RequirementsSpecificationPayload;
}

export interface RequirementsRevisionDecisionRequest {
  decision: RequirementsRevisionDecision;
  reason?: string | null;
}

export interface RequirementsRevisionPayload {
  status: "CREATED" | "APPLIED" | "NO_CHANGE" | "REJECTED";
  diff: RequirementsSpecificationDiffPayload | null;
  version: RequirementsSpecificationVersionPayload | null;
  issue: string | null;
  proposal_issue: string | null;
  diff_persistence_status: string | null;
  version_persistence_status: string | null;
}

export interface RequirementsGateDecisionRequest {
  action: RequirementsGateDecisionAction;
  reason?: string | null;
}

export interface RequirementsGateSubmissionPayload {
  status:
    | "SUBMITTED"
    | "ALREADY_PENDING"
    | "ALREADY_APPROVED"
    | "SPECIFICATION_NOT_FOUND"
    | "NEW_SPECIFICATION_REQUIRED"
    | "GATE_BLOCKED"
    | "ITERATION_LIMIT_REACHED"
    | "TRANSITION_REJECTED";
  gate: HumanGatePayload | null;
  events: HumanGateEventPayload[];
  issue: string | null;
}

export interface RequirementsGateDecisionPayload {
  status: "APPLIED" | "GATE_NOT_FOUND" | "SPECIFICATION_NOT_FOUND" | "ARTIFACT_STALE" | "REJECTED";
  gate: HumanGatePayload | null;
  event: HumanGateEventPayload | null;
  issue: string | null;
}

export interface RequirementsReadinessPayload {
  status: RequirementsWorkflowReadiness;
  version: RequirementsSpecificationVersionPayload | null;
  gate: HumanGatePayload | null;
  approved_current_specification: boolean;
}
