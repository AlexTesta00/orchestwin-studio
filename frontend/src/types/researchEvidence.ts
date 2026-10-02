import type { EvidenceSourceKind, ObservationValuePayload, UserTwinField } from "./userModeling";
import type { TwinUpdatePayload } from "./twinLearning";

export interface ResearchEvidencePayload {
  id: string;
  code: string;
  version: number;
  title: string;
  source_kind: EvidenceSourceKind;
  source_ref: string;
  context: string;
  method: string;
  collected_at: string | null;
  limitations: string;
  empirical: boolean;
  content_hash: string;
  character_count: number;
  byte_count: number;
  created_at: string;
  status: "ACTIVE" | "RETIRED";
  retired_at: string | null;
  retired_reason: string | null;
  text_available: boolean;
  text?: string;
  citations?: ApprovedEvidenceCitationPayload[];
}

export interface ResearchEvidenceListPayload {
  project_id: string;
  evidence: ResearchEvidencePayload[];
  citations?: ApprovedEvidenceCitationPayload[];
}

export interface ResearchEvidenceInput {
  title: string;
  source_kind: EvidenceSourceKind;
  source_ref: string;
  context: string;
  method: string;
  collected_at: string | null;
  limitations: string;
  empirical: boolean;
  text: string;
  acknowledged: true;
}

export interface EvidenceCitationPayload {
  source_id: string;
  source_version: number;
  content_hash: string;
  quote: string;
  start: number;
  end: number;
  start_line: number;
  end_line: number;
}

export interface EvidenceChangePayload {
  effect: "SUPPORTS" | "CONTRADICTS" | "ADDS";
  field: UserTwinField;
  value: ObservationValuePayload;
  citation: EvidenceCitationPayload;
}

export interface ApprovedEvidenceCitationPayload {
  twin_id: string;
  twin_version: number;
  field: UserTwinField;
  effect: EvidenceChangePayload["effect"];
  citation: EvidenceCitationPayload;
  status: "ACTIVE" | "RETIRED";
}

export interface TwinUpdateEvidencePayload {
  source_id: string;
  source_version: number;
  content_hash: string;
  rejected_changes: number;
}

export interface EvidenceMutationPayload {
  status: string;
  evidence: ResearchEvidencePayload;
  affected_twins?: string[];
  review_required?: boolean;
}

export interface EvidenceUpdateResultPayload {
  status: string;
  update: TwinUpdatePayload;
}

export interface EvidenceUpdateDecisionInput {
  decision: "APPROVE" | "REJECT";
  kept: { index: number; statement?: string }[];
  reason?: string;
}
