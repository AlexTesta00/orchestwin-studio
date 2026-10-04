import type { ObservationValuePayload, ReadableClaimStatus } from "./userModeling";
import type { DirectionAxes } from "./design";
import type { EvidenceCitationPayload } from "./researchEvidence";
import type { HumanValidationOutcome, OperationalHypothesis } from "./humanValidation";
import type { ProvidedPrototype, WorkflowDecision, WorkflowInputsPayload } from "./workflowInputs";

export interface WhyReference {
  artifact_id: string;
  version_number: number | null;
  content_hash: string | null;
}

export interface WhyGap {
  code: string;
  node_key: string;
  related_code: string | null;
  stage: string | null;
}

export interface WhyPerspective {
  key?: string;
  label?: string;
  title?: string;
  applied?: boolean;
  team_reference?: WhyReference;
}

export interface WhyNode {
  key: string;
  code: string;
  kind: string;
  title: string;
  display_status: ReadableClaimStatus;
  reference: WhyReference;
  current: boolean;
  rationale: {
    text: string;
    origin: "MODEL" | "OWNER" | "SYSTEM" | "UNKNOWN";
    version_number: number | null;
    content_hash: string | null;
  } | null;
  citations: {
    citation: EvidenceCitationPayload;
    status: "ACTIVE" | "RETIRED";
    effect?: string;
    session_kind?: "HUMAN_SESSION" | "SYNTHETIC_EXERCISE";
    field?: string;
    twin_version?: number;
    source?: {
      title?: string;
      code?: string;
      status?: "ACTIVE" | "RETIRED";
      text_available?: boolean;
      method?: string;
      limitations?: string;
      context?: string;
    };
  }[];
  validation_required: boolean;
  gaps: WhyGap[];
  declared_context: {
    perspectives: WhyPerspective[];
    scenario?: { goal?: string; steps?: string[]; expected_outcome?: string };
    hypothesis?: OperationalHypothesis;
    outcome?: HumanValidationOutcome;
    workflow_decision?: WorkflowDecision;
    provided_prototype?: ProvidedPrototype;
    origin?: "OWNER_INPUT";
    limits?: string[];
    effective_status?: "ACTIVE" | "RETIRED";
    observation_value?: ObservationValuePayload;
    base_reference?: WhyReference;
    audit_reference?: { generation_id: string; content_hash: string; request_content_hash: string };
    mockup?: {
      alternative_id: string;
      prototype_id: string;
      screen_code: string;
      source: string;
      document_hashes: Record<string, string>;
    };
    direction?: {
      name: string;
      concept: string;
      axes: DirectionAxes;
      candidates: number;
      origin: "MODEL";
      selected_by: "STUDIO";
    };
  };
}

export interface WhyLink {
  source: string;
  target: string;
  kind: string;
}

export interface WhyDocument {
  kind: "orchestwin.why";
  schema_version: 1;
  project_id: string;
  nodes: WhyNode[];
  links: WhyLink[];
  omitted_sections: unknown[];
  workflow_records?: WorkflowInputsPayload;
}

export interface WhyAnswer {
  kind: "orchestwin.why-answer";
  schema_version: 1;
  project_id: string;
  target: WhyNode;
  summary: {
    upstream_count: number;
    downstream_count: number;
    complete_to_twin: boolean;
    complete_to_evidence: boolean;
    all_paths_complete: boolean;
    stop_reasons: string[];
  };
  upstream: WhyNode[];
  downstream: WhyNode[];
  links: WhyLink[];
  gaps: WhyGap[];
  human_validation: WhyNode[];
  declared_context: { perspectives: WhyPerspective[] };
  limits: string[];
}
