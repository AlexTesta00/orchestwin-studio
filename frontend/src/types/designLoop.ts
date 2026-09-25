import type { DesignGenerationPayload, UUID } from "./design";

export type SyntheticFindingSeverity = "critical" | "major" | "moderate" | "minor" | "observation";
export type SyntheticFindingCriterion =
  | "usefulness"
  | "comprehensibility"
  | "actionability"
  | "cognitive_load"
  | "trust"
  | "accessibility"
  | "task_alignment";
export type InsightSourceKind = "TWIN_CHAT_INSIGHT" | "DESIGN_CRITIQUE" | "SYNTHETIC_FINDING";
export type InsightTarget = "BRIEF" | "REQUIREMENTS" | "DESIGN";
export type InsightBriefField =
  | "goals"
  | "target_users"
  | "technical_constraints"
  | "functional_requirements"
  | "non_functional_requirements"
  | "risks"
  | "stakeholders"
  | "definition_of_done";

export interface SyntheticFindingPayload {
  finding_id: string;
  twin_id: UUID;
  twin_version: number;
  artifact_id: UUID;
  artifact_version: number;
  location: string;
  summary: string;
  rationale: string;
  criterion: SyntheticFindingCriterion;
  severity: SyntheticFindingSeverity;
  epistemic_status: string;
  evidence_refs: string[];
  confidence: number;
  confidence_semantics: string;
  recommended_action: string;
  requires_human_validation: boolean;
  model_config_ref: string;
  prompt_version_ref: string;
  is_simulated_feedback: boolean;
  content_hash: string;
}

export interface TwinEvaluationResponsePayload {
  evaluation_run_id: UUID;
  artifact_bundle_id: UUID;
  artifact_bundle_hash: string;
  twin_id: UUID;
  twin_version: number;
  evaluator: {
    evaluator_id: string;
    evaluator_version: string;
    model_config_ref: string;
    prompt_version_ref: string;
  };
  findings: SyntheticFindingPayload[];
  summary: string;
  evidence_gaps: string[];
  is_simulated_feedback: boolean;
  completed_at: string;
  content_hash: string;
  disclaimer: string;
}

export interface DesignEvaluationRunPayload {
  schema_version: number;
  id: UUID;
  project_id: UUID;
  owner_user_id: UUID;
  design_version_id: UUID;
  design_version_number: number;
  design_content_hash: string;
  alternative_id: UUID;
  alternative_code: string;
  bundle: Record<string, unknown>;
  responses: TwinEvaluationResponsePayload[];
  started_at: string;
  completed_at: string;
  content_hash: string;
}

export interface DesignEvaluationComparisonPayload {
  base_run_id: UUID;
  head_run_id: UUID;
  resolved: SyntheticFindingPayload[];
  persisting: { before: SyntheticFindingPayload; after: SyntheticFindingPayload }[];
  introduced: SyntheticFindingPayload[];
  counts: {
    base: number;
    head: number;
    resolved: number;
    persisting: number;
    introduced: number;
  };
}

export interface DesignEvaluationRequest {
  design_version_id: UUID;
  design_content_hash: string;
  locale?: string;
}

export interface InsightApplicationRequest {
  source_kind: InsightSourceKind;
  source_id: string;
  source_twin_id?: UUID | null;
  text: string;
  target: InsightTarget;
  brief_field?: InsightBriefField | null;
  mitigation?: string | null;
  requirement_kind?: "FUNCTIONAL" | "NON_FUNCTIONAL" | "CONSTRAINT" | null;
}

export interface InsightApplicationPayload {
  id: UUID;
  project_id: UUID;
  owner_user_id: UUID;
  source_kind: InsightSourceKind;
  source_id: string;
  source_twin_id: UUID | null;
  text: string;
  target: InsightTarget;
  target_field: string | null;
  target_version_id: UUID;
  target_version_number: number;
  target_code: string | null;
  created_at: string;
  content_hash: string;
}

export interface InsightSource {
  kind: InsightSourceKind;
  id: string;
  twinId?: UUID | null;
  text: string;
  mitigation?: string | null;
}

export type DesignRegenerationPayload = DesignGenerationPayload;
