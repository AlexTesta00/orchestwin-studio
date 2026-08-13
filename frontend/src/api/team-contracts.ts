import type { ProjectMode } from "./contracts";
import type {
  BriefField,
  HumanGateAction,
  HumanGateEventResponse,
  HumanGateIssueCode,
  HumanGateResponse,
} from "./workflow-contracts";

export const AGENT_IDENTIFIERS = [
  "WORKFLOW_ORCHESTRATOR",
  "INTAKE_CLARIFICATION_AGENT",
  "TEAM_SELECTOR",
  "HUMAN_GATE_CONTROLLER",
  "ARTIFACT_MANAGER",
  "SANDBOX_CONTROLLER",
  "REQUIREMENTS_ANALYST",
  "UX_RESEARCHER_USER_MODELER",
  "UX_UI_DESIGNER",
  "SOFTWARE_ARCHITECT",
  "FRONTEND_ENGINEER",
  "BACKEND_ENGINEER",
  "MOBILE_ENGINEER",
  "QA_TEST_ENGINEER",
  "SECURITY_REVIEWER",
  "ACCESSIBILITY_REVIEWER",
  "INTEGRATION_ENGINEER",
] as const;

export type AgentIdentifier = (typeof AGENT_IDENTIFIERS)[number];

export type AgentCatalogKind = "PLATFORM_COMPONENT" | "SPECIALIST";

export type AgentSelectionPolicy = "ALWAYS_PRESENT" | "OWNER_SELECTABLE";

export type AgentCapability =
  | "WORKFLOW_ORCHESTRATION"
  | "GOVERNED_ROUTING"
  | "PROJECT_INTAKE"
  | "BRIEF_CLARIFICATION"
  | "TEAM_SELECTION"
  | "HUMAN_APPROVAL"
  | "ARTIFACT_MANAGEMENT"
  | "PROVENANCE_MANAGEMENT"
  | "SANDBOX_CONTROL"
  | "REQUIREMENTS_ANALYSIS"
  | "ACCEPTANCE_CRITERIA"
  | "USER_RESEARCH"
  | "USER_MODELING"
  | "UX_DESIGN"
  | "UI_DESIGN"
  | "SOFTWARE_ARCHITECTURE"
  | "FRONTEND_ENGINEERING"
  | "BACKEND_ENGINEERING"
  | "MOBILE_ENGINEERING"
  | "QUALITY_ASSURANCE"
  | "TEST_ENGINEERING"
  | "SECURITY_REVIEW"
  | "ACCESSIBILITY_REVIEW"
  | "SYSTEM_INTEGRATION";

export interface AgentCatalogEntryResponse {
  readonly agent_id: AgentIdentifier;
  readonly catalog_version: number;
  readonly kind: AgentCatalogKind;
  readonly selection_policy: AgentSelectionPolicy;
  readonly capabilities: readonly AgentCapability[];
  readonly supported_project_modes: readonly ProjectMode[];
  readonly name_key: string;
  readonly description_key: string;
  readonly is_always_present: boolean;
}

export interface AgentCatalogResponse {
  readonly catalog_version: number;
  readonly content_hash: string;
  readonly agents: readonly AgentCatalogEntryResponse[];
}

export type TeamRoleConstraintKind = "MANDATORY" | "OPTIONAL" | "IMPOSSIBLE" | "CONFLICT";

export type TeamSelectionReasonCode =
  | "CATALOG_ALWAYS_PRESENT"
  | "CATALOG_MODE_INCOMPATIBLE"
  | "CORE_REQUIREMENTS_DISCIPLINE"
  | "CORE_USER_CENTERED_DESIGN"
  | "CORE_ARCHITECTURE_DISCIPLINE"
  | "CORE_QUALITY_DISCIPLINE"
  | "BROWNFIELD_INTEGRATION"
  | "USER_INTERFACE_SIGNAL"
  | "WEB_DELIVERY_SIGNAL"
  | "BACKEND_DELIVERY_SIGNAL"
  | "MOBILE_DELIVERY_SIGNAL"
  | "EXTERNAL_INTEGRATION_SIGNAL"
  | "SECURITY_SENSITIVITY_SIGNAL"
  | "ACCESSIBILITY_REQUIREMENT_SIGNAL"
  | "EXPLICIT_SCOPE_EXCLUSION";

export interface RuleEvidenceResponse {
  readonly fields: readonly BriefField[];
  readonly terms: readonly string[];
}

export interface TeamSelectionReasonResponse {
  readonly code: TeamSelectionReasonCode;
  readonly evidence: RuleEvidenceResponse;
}

export interface TeamRoleConstraintResponse {
  readonly agent_id: AgentIdentifier;
  readonly kind: TeamRoleConstraintKind;
  readonly owner_editable: boolean;
  readonly reasons: readonly TeamSelectionReasonResponse[];
}

export type TeamSelectionIssueCode = "CONTRADICTORY_ROLE_SIGNALS";

export interface TeamSelectionIssueResponse {
  readonly code: TeamSelectionIssueCode;
  readonly agent_id: AgentIdentifier;
  readonly mandatory_reasons: readonly TeamSelectionReasonResponse[];
  readonly impossible_reasons: readonly TeamSelectionReasonResponse[];
}

export type TeamProposalProviderKind = "FAKE_DETERMINISTIC" | "MODEL_ADAPTER";

export type TeamProposalMemberSource =
  "DETERMINISTIC_MANDATORY" | "PROPOSER_SUGGESTED" | "OWNER_ADDED";

export type TeamProposalJustificationKind =
  "DETERMINISTIC_RULE" | "PROPOSER_RATIONALE" | "OWNER_RATIONALE";

export interface TeamProposalJustificationResponse {
  readonly kind: TeamProposalJustificationKind;
  readonly code: string;
  readonly evidence_fields: readonly BriefField[];
  readonly evidence_terms: readonly string[];
  readonly statement: string | null;
}

export interface ProposedTeamMemberResponse {
  readonly agent_id: AgentIdentifier;
  readonly source: TeamProposalMemberSource;
  readonly justifications: readonly TeamProposalJustificationResponse[];
}

export type TeamProposalRevisionKind = "PROPOSER_GENERATED" | "OWNER_EDITED";

export interface TeamProposalVersionResponse {
  readonly id: string;
  readonly project_id: string;
  readonly version_number: number;
  readonly revision_kind: TeamProposalRevisionKind;
  readonly based_on_version_number: number | null;

  readonly schema_version: number;
  readonly provider_kind: TeamProposalProviderKind;
  readonly provider_id: string;
  readonly provider_version: number;

  readonly project_mode: ProjectMode;
  readonly brief_version_id: string;
  readonly brief_version_number: number;
  readonly brief_content_hash: string;

  readonly catalog_version: number;
  readonly catalog_content_hash: string;
  readonly constraints_content_hash: string;
  readonly content_hash: string;

  readonly selected_agent_ids: readonly AgentIdentifier[];
  readonly role_constraints: readonly TeamRoleConstraintResponse[];
  readonly constraint_issues: readonly TeamSelectionIssueResponse[];
  readonly members: readonly ProposedTeamMemberResponse[];

  readonly created_by_user_id: string;
  readonly created_at: string;
}

export type TeamProposalApplicationStatus =
  | "CREATED"
  | "UNCHANGED"
  | "PROJECT_NOT_FOUND"
  | "BRIEF_NOT_FOUND"
  | "BRIEF_NOT_APPROVED"
  | "BLOCKED_BY_CONSTRAINTS"
  | "CONTEXT_CHANGED"
  | "INVALID_PROPOSAL";

export interface TeamProposalGenerationResponse {
  readonly status: TeamProposalApplicationStatus;
  readonly version: TeamProposalVersionResponse | null;
  readonly issues: readonly TeamSelectionIssueResponse[];
}

export interface OwnerAgentRationaleInput {
  readonly agent_id: AgentIdentifier;
  readonly statement: string;
}

export interface TeamProposalEditInput {
  readonly selected_agent_ids: readonly AgentIdentifier[];
  readonly owner_rationales: readonly OwnerAgentRationaleInput[];
}

export type TeamEditIssueCode =
  | "DUPLICATE_AGENT"
  | "DUPLICATE_RATIONALE"
  | "MANDATORY_AGENT_MISSING"
  | "AGENT_NOT_SELECTABLE"
  | "RATIONALE_REQUIRED"
  | "UNUSED_RATIONALE";

export interface TeamEditIssueResponse {
  readonly code: TeamEditIssueCode;
  readonly agent_id: AgentIdentifier;
}

export type TeamEditStatus =
  | "UPDATED"
  | "UNCHANGED"
  | "PROJECT_NOT_FOUND"
  | "BRIEF_NOT_FOUND"
  | "BRIEF_NOT_APPROVED"
  | "PROPOSAL_NOT_FOUND"
  | "PROPOSAL_STALE"
  | "CONTEXT_CHANGED"
  | "REJECTED";

export interface TeamEditResponse {
  readonly status: TeamEditStatus;
  readonly version: TeamProposalVersionResponse | null;
  readonly issues: readonly TeamEditIssueResponse[];
  readonly events: readonly HumanGateEventResponse[];
}

export type AgentTeamGateSubmissionStatus =
  | "SUBMITTED"
  | "ALREADY_PENDING"
  | "ALREADY_APPROVED"
  | "PROJECT_NOT_FOUND"
  | "BRIEF_NOT_FOUND"
  | "BRIEF_NOT_APPROVED"
  | "PROPOSAL_NOT_FOUND"
  | "PROPOSAL_STALE"
  | "NEW_PROPOSAL_REQUIRED"
  | "GATE_BLOCKED"
  | "ITERATION_LIMIT_REACHED"
  | "TRANSITION_REJECTED";

export interface AgentTeamGateSubmissionResponse {
  readonly status: AgentTeamGateSubmissionStatus;
  readonly gate: HumanGateResponse | null;
  readonly events: readonly HumanGateEventResponse[];
  readonly issue: HumanGateIssueCode | null;
}

export type AgentTeamGateDecisionAction = Exclude<HumanGateAction, "SUBMIT">;

export type AgentTeamGateDecisionStatus =
  | "APPLIED"
  | "PROJECT_NOT_FOUND"
  | "BRIEF_NOT_FOUND"
  | "BRIEF_NOT_APPROVED"
  | "PROPOSAL_NOT_FOUND"
  | "PROPOSAL_STALE"
  | "GATE_NOT_FOUND"
  | "ARTIFACT_STALE"
  | "REJECTED";

export interface AgentTeamGateDecisionResponse {
  readonly status: AgentTeamGateDecisionStatus;
  readonly gate: HumanGateResponse | null;
  readonly event: HumanGateEventResponse | null;
  readonly issue: HumanGateIssueCode | null;
}

export type ProjectWorkflowReadiness =
  | "PROJECT_NOT_FOUND"
  | "BRIEF_APPROVAL_REQUIRED"
  | "TEAM_PROPOSAL_REQUIRED"
  | "TEAM_APPROVAL_REQUIRED"
  | "READY_FOR_MAIN_WORKFLOW";

export interface ProjectReadinessResponse {
  readonly status: ProjectWorkflowReadiness;
}

export interface AgentTeamApi {
  getAgentCatalog(accessToken: string): Promise<AgentCatalogResponse>;

  generateProjectTeamProposal(
    accessToken: string,
    projectId: string,
  ): Promise<TeamProposalGenerationResponse>;

  listProjectTeamProposals(
    accessToken: string,
    projectId: string,
  ): Promise<readonly TeamProposalVersionResponse[]>;

  getCurrentProjectTeamProposal(
    accessToken: string,
    projectId: string,
  ): Promise<TeamProposalVersionResponse>;

  editCurrentProjectTeamProposal(
    accessToken: string,
    projectId: string,
    input: TeamProposalEditInput,
  ): Promise<TeamEditResponse>;

  submitAgentTeamGate(
    accessToken: string,
    projectId: string,
  ): Promise<AgentTeamGateSubmissionResponse>;

  getCurrentAgentTeamGate(accessToken: string, projectId: string): Promise<HumanGateResponse>;

  listAgentTeamGateEvents(
    accessToken: string,
    projectId: string,
    gateId: string,
  ): Promise<readonly HumanGateEventResponse[]>;

  decideAgentTeamGate(
    accessToken: string,
    projectId: string,
    action: AgentTeamGateDecisionAction,
    reason?: string | null,
  ): Promise<AgentTeamGateDecisionResponse>;

  getProjectWorkflowReadiness(
    accessToken: string,
    projectId: string,
  ): Promise<ProjectReadinessResponse>;
}
