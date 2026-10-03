import type { EvidenceCitationPayload } from "./researchEvidence";
import type { WhyGap, WhyNode, WhyReference } from "./why";

export type ValidationState = "TO_VERIFY" | "CONFIRMED" | "REFUTED" | "UNCERTAIN" | "CONTESTED";
export type ValidationSessionKind = "HUMAN_SESSION" | "SYNTHETIC_EXERCISE";
export type ValidationCoverage = "COMPLETE" | "PARTIAL";
export type ValidationOutcomeValue = "CONFIRMED" | "REFUTED" | "UNCERTAIN";

export interface ValidationGap {
  code: string;
  node_key?: string;
  reference?: string;
}

export interface ValidationCandidate {
  key: string;
  code: string;
  kind: string;
  title: string;
  reference: WhyReference;
  origin: WhyNode;
  twin_references: WhyNode[];
  scenario_candidates: WhyNode[];
  design_references: WhyNode[];
  gaps: (WhyGap | ValidationGap)[];
  limits: string[];
}

export interface OperationalHypothesis {
  id: string;
  code: string;
  version_number: number;
  based_on_version_number: number | null;
  project_id: string;
  owner_user_id: string;
  origin_key: string;
  origin_reference: WhyReference;
  origin_kind: string;
  twin_key: string;
  twin_reference: WhyReference;
  scenario_key: string;
  scenario_reference: WhyReference;
  design_key: string;
  design_reference: WhyReference;
  alternative_id: string | null;
  anchor_keys: string[];
  mockup_references: {
    key: string;
    reference: WhyReference;
    mockup: NonNullable<WhyNode["declared_context"]["mockup"]>;
  }[];
  question: string | null;
  task: string | null;
  observe: string[];
  limitations: string;
  created_at: string;
  content_hash: string;
  state?: ValidationState;
  current?: boolean;
  active_outcome_ids?: string[];
  outcomes?: HumanValidationOutcome[];
  partial_evidence?: boolean;
  conflicting_outcomes?: boolean;
  gaps?: ValidationGap[];
}

export interface HumanValidationOutcome {
  id: string;
  code: string;
  project_id: string;
  owner_user_id: string;
  hypothesis_id: string;
  hypothesis_version_number: number;
  hypothesis_content_hash: string;
  session_ref: string;
  session_kind: ValidationSessionKind;
  outcome: ValidationOutcomeValue;
  coverage: ValidationCoverage;
  limitations: string;
  evidence_id: string;
  evidence_version: number;
  evidence_content_hash: string;
  citation: EvidenceCitationPayload;
  recorded_at: string;
  content_hash: string;
  effective_status?: "ACTIVE" | "RETIRED" | "SOURCE_UNAVAILABLE";
  source_text_available?: boolean | null;
  gaps?: ValidationGap[];
}

export interface HumanValidationOverview {
  kind: "orchestwin.human-validation";
  schema_version: 1;
  project_id: string;
  candidates: ValidationCandidate[];
  candidate_count: number;
  hypotheses: OperationalHypothesis[];
  outcomes: HumanValidationOutcome[];
  summary: {
    hypotheses: number;
    to_verify: number;
    confirmed: number;
    refuted: number;
    uncertain: number;
    contested: number;
    retired_outcomes: number;
  };
  empirical_summary: { human_session_outcomes: number; synthetic_exercise_outcomes: number };
  omitted_sections: unknown[];
  limits: string[];
}

export interface HypothesisInput {
  candidate_key: string;
  twin_key: string;
  scenario_key: string;
  design_key: string;
  alternative_id?: string;
  anchor_keys?: string[];
  question?: string | null;
  task?: string | null;
  observe: string[];
  limitations: string;
}

export interface HypothesisRevisionInput extends HypothesisInput {
  based_on_version_number: number;
  based_on_content_hash: string;
}

export interface ValidationOutcomeInput {
  hypothesis_id: string;
  hypothesis_version_number: number;
  hypothesis_content_hash: string;
  session_ref: string;
  session_kind: ValidationSessionKind;
  outcome: ValidationOutcomeValue;
  coverage: ValidationCoverage;
  limitations: string;
  evidence_id: string;
  evidence_version: number;
  quote: string;
  line: number;
}

export interface ScenarioWalkthrough {
  kind: "orchestwin.scenario-walkthrough";
  schema_version: 1;
  project_id: string;
  scenario: WhyNode;
  twin_references: WhyNode[];
  task: string | null;
  steps: {
    number: number;
    text: string;
    anchors: WhyNode[];
    observe: string[];
    gaps: ValidationGap[];
  }[];
  reference: WhyReference;
  design_references: WhyNode[];
  anchor_candidates: WhyNode[];
  expected_outcome?: string | null;
  gaps: ValidationGap[];
  limits: string[];
}

export interface EvidenceFocus {
  id: string;
  version: number;
}
