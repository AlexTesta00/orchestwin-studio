import type { ProjectBriefVersionResponse } from "./contracts";

export const BRIEF_FIELDS = [
  "name",
  "description",
  "problem",
  "goals",
  "target_users",
  "domain",
  "technical_constraints",
  "temporal_constraints",
  "budget",
  "functional_requirements",
  "non_functional_requirements",
  "risks",
  "stakeholders",
  "available_artifacts",
  "definition_of_done",
] as const;

export type BriefField = (typeof BRIEF_FIELDS)[number];

export type ClarificationAnswerType = "text" | "item_list";

export type ClarificationAnswerKind = "text" | "item_list" | "unknown";

export type ClarificationRoundStatus = "OPEN" | "ANSWERED";

export interface ClarificationQuestionResponse {
  readonly question_id: string;
  readonly catalog_version: number;
  readonly field: BriefField;
  readonly answer_type: ClarificationAnswerType;
  readonly priority: number;
  readonly prompt_key: string;
  readonly hint_key: string;
  readonly unknown_allowed: boolean;
}

export interface ClarificationRoundResponse {
  readonly id: string;
  readonly project_id: string;
  readonly source_brief_version_number: number;
  readonly round_number: number;
  readonly catalog_version: number;
  readonly questions: readonly ClarificationQuestionResponse[];
  readonly status: ClarificationRoundStatus;
  readonly created_by_user_id: string;
  readonly created_at: string;
  readonly answered_at: string | null;
  readonly resulting_brief_version_number: number | null;
}

export type ClarificationRoundStartStatus =
  "STARTED" | "OPEN_ROUND_EXISTS" | "BRIEF_NOT_FOUND" | "BRIEF_COMPLETE" | "LIMIT_REACHED";

export interface ClarificationRoundStartResponse {
  readonly status: ClarificationRoundStartStatus;
  readonly round: ClarificationRoundResponse | null;
}

export interface ClarificationAnswerInput {
  readonly question_id: string;
  readonly kind: ClarificationAnswerKind;
  readonly text_value?: string | null;
  readonly item_values?: readonly string[] | null;
}

export type ClarificationAnswerIssueCode =
  | "unknown_question"
  | "duplicate_field"
  | "field_not_missing"
  | "answer_type_mismatch"
  | "unknown_not_allowed"
  | "empty_value";

export interface ClarificationAnswerIssueResponse {
  readonly code: ClarificationAnswerIssueCode;
  readonly question_id: string;
  readonly field: BriefField | null;
}

export type ClarificationNextStep =
  "CLARIFICATION_REQUIRED" | "BRIEF_READY_FOR_APPROVAL" | "PAUSED_NEEDS_HUMAN";

export type ClarificationRoundAnswerStatus =
  | "APPLIED"
  | "ROUND_NOT_FOUND"
  | "ROUND_NOT_OPEN"
  | "ROUND_STALE"
  | "NO_ANSWERS"
  | "INVALID_ANSWERS"
  | "VERSION_UNCHANGED";

export interface ClarificationRoundAnswerResponse {
  readonly status: ClarificationRoundAnswerStatus;
  readonly round: ClarificationRoundResponse | null;
  readonly brief_version: ProjectBriefVersionResponse | null;
  readonly next_step: ClarificationNextStep | null;
  readonly issues: readonly ClarificationAnswerIssueResponse[];
  readonly invalid_question_ids: readonly string[];
}

export type BriefAssumptionSource = "OWNER_PROVIDED" | "MODEL_PROPOSED" | "DETERMINISTIC_RULE";

export type BriefAssumptionStatus = "PROPOSED" | "ACCEPTED" | "REJECTED";

export interface BriefAssumptionResponse {
  readonly id: string;
  readonly project_id: string;
  readonly brief_version_number: number;
  readonly field: BriefField;
  readonly statement: string;
  readonly source: BriefAssumptionSource;
  readonly status: BriefAssumptionStatus;
  readonly created_by_user_id: string;
  readonly created_at: string;
  readonly decided_by_user_id: string | null;
  readonly decided_at: string | null;
  readonly decision_reason: string | null;
}

export interface BriefAssumptionCreateInput {
  readonly field: BriefField;
  readonly statement: string;
}

export type BriefAssumptionCreationStatus =
  "CREATED" | "BRIEF_NOT_FOUND" | "FIELD_ALREADY_PROVIDED";

export interface BriefAssumptionCreationResponse {
  readonly status: BriefAssumptionCreationStatus;
  readonly assumption: BriefAssumptionResponse | null;
}

export type BriefAssumptionDecisionStatus =
  | "ACCEPTED"
  | "REJECTED"
  | "ASSUMPTION_NOT_FOUND"
  | "ASSUMPTION_NOT_PROPOSED"
  | "ASSUMPTION_STALE"
  | "FIELD_ALREADY_PROVIDED"
  | "VERSION_UNCHANGED";

export interface BriefAssumptionDecisionResponse {
  readonly status: BriefAssumptionDecisionStatus;
  readonly assumption: BriefAssumptionResponse | null;
  readonly brief_version: ProjectBriefVersionResponse | null;
}

export type HumanGateType = "PROJECT_BRIEF" | "AGENT_TEAM";

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

export type ProjectBriefGateDecisionAction = Exclude<HumanGateAction, "SUBMIT">;

export type HumanGateEventKind =
  | "SUBMIT"
  | "APPROVE"
  | "REJECT"
  | "REQUEST_REVISION"
  | "PAUSE"
  | "RESUME"
  | "CANCEL"
  | "ARTIFACT_SUPERSEDED";

export type HumanGateIssueCode =
  | "INVALID_TRANSITION"
  | "REASON_REQUIRED"
  | "REASON_TOO_LONG"
  | "ACTOR_NOT_OWNER"
  | "TIMESTAMP_NOT_AWARE"
  | "TIMESTAMP_OUT_OF_ORDER"
  | "ARTIFACT_SCOPE_MISMATCH";

export interface GateArtifactResponse {
  readonly project_id: string;
  readonly gate_type: HumanGateType;
  readonly artifact_id: string;
  readonly version: number;
  readonly content_hash: string;
}

export interface HumanGateResponse {
  readonly id: string;
  readonly project_id: string;
  readonly owner_user_id: string;
  readonly gate_type: HumanGateType;
  readonly artifact: GateArtifactResponse;
  readonly iteration: number;
  readonly max_iterations: number;
  readonly status: HumanGateStatus;
  readonly created_at: string;
  readonly updated_at: string;
  readonly event_sequence: number;
  readonly resume_status: HumanGateStatus | null;
}

export interface HumanGateEventResponse {
  readonly id: string;
  readonly gate_id: string;
  readonly sequence_number: number;
  readonly kind: HumanGateEventKind;
  readonly previous_status: HumanGateStatus;
  readonly resulting_status: HumanGateStatus;
  readonly artifact: GateArtifactResponse;
  readonly occurred_at: string;
  readonly actor_user_id: string | null;
  readonly reason: string | null;
}

export type ProjectBriefGateSubmissionStatus =
  | "SUBMITTED"
  | "ALREADY_PENDING"
  | "ALREADY_APPROVED"
  | "BRIEF_NOT_FOUND"
  | "BRIEF_INCOMPLETE"
  | "NEW_BRIEF_REQUIRED"
  | "GATE_BLOCKED"
  | "ITERATION_LIMIT_REACHED"
  | "TRANSITION_REJECTED";

export interface ProjectBriefGateSubmissionResponse {
  readonly status: ProjectBriefGateSubmissionStatus;
  readonly gate: HumanGateResponse | null;
  readonly events: readonly HumanGateEventResponse[];
  readonly missing_fields: readonly BriefField[];
  readonly issue: HumanGateIssueCode | null;
}

export type ProjectBriefGateDecisionStatus =
  "APPLIED" | "GATE_NOT_FOUND" | "BRIEF_NOT_FOUND" | "ARTIFACT_STALE" | "REJECTED";

export interface ProjectBriefGateDecisionResponse {
  readonly status: ProjectBriefGateDecisionStatus;
  readonly gate: HumanGateResponse | null;
  readonly event: HumanGateEventResponse | null;
  readonly issue: HumanGateIssueCode | null;
}

export interface ProjectWorkflowApi {
  startProjectClarificationRound(
    accessToken: string,
    projectId: string,
  ): Promise<ClarificationRoundStartResponse>;

  listProjectClarificationRounds(
    accessToken: string,
    projectId: string,
  ): Promise<readonly ClarificationRoundResponse[]>;

  getCurrentProjectClarificationRound(
    accessToken: string,
    projectId: string,
  ): Promise<ClarificationRoundResponse>;

  answerProjectClarificationRound(
    accessToken: string,
    projectId: string,
    roundId: string,
    answers: readonly ClarificationAnswerInput[],
  ): Promise<ClarificationRoundAnswerResponse>;

  listProjectBriefAssumptions(
    accessToken: string,
    projectId: string,
  ): Promise<readonly BriefAssumptionResponse[]>;

  createProjectBriefAssumption(
    accessToken: string,
    projectId: string,
    input: BriefAssumptionCreateInput,
  ): Promise<BriefAssumptionCreationResponse>;

  acceptProjectBriefAssumption(
    accessToken: string,
    projectId: string,
    assumptionId: string,
    reason?: string | null,
  ): Promise<BriefAssumptionDecisionResponse>;

  rejectProjectBriefAssumption(
    accessToken: string,
    projectId: string,
    assumptionId: string,
    reason: string,
  ): Promise<BriefAssumptionDecisionResponse>;

  submitProjectBriefGate(
    accessToken: string,
    projectId: string,
  ): Promise<ProjectBriefGateSubmissionResponse>;

  getCurrentProjectBriefGate(accessToken: string, projectId: string): Promise<HumanGateResponse>;

  listProjectBriefGateEvents(
    accessToken: string,
    projectId: string,
    gateId: string,
  ): Promise<readonly HumanGateEventResponse[]>;

  decideProjectBriefGate(
    accessToken: string,
    projectId: string,
    action: ProjectBriefGateDecisionAction,
    reason?: string | null,
  ): Promise<ProjectBriefGateDecisionResponse>;
}
