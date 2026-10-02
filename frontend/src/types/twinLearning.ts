export type LearningSource = "TWIN_CRITIQUE" | "OWNER";

export type TwinUpdateStatus = "PROPOSED" | "APPROVED" | "REJECTED" | "EMPTY";

export interface LearningSubjectPayload {
  requirement: string | null;
  screen: string | null;
}

export interface LearnedObservationPayload {
  code: string;
  statement: string;
  basis: string | null;
  source: LearningSource;
  about: LearningSubjectPayload;
  contradicts_profile: string | null;
  added_in_version: number;
  approved_at: string;
  update_id: string | null;
}

export interface RetiredObservationPayload {
  code: string;
  statement: string;
  retired_in_version: number;
  retired_at: string;
  reason: string | null;
}

export interface TwinLearningEntryPayload {
  twin_id: string;
  twin_name: string;
  profile_version_number: number;
  development_version_number: number;
  label: string;
  observations: LearnedObservationPayload[];
  retired: RetiredObservationPayload[];
}

export interface TwinUpdateBasePayload {
  profile_version_number: number;
  development_version_number: number;
}

export interface ProposedObservationPayload {
  index: number;
  statement: string;
  basis: string;
  about: LearningSubjectPayload;
  contradicts_profile: string | null;
  evidence?: EvidenceChangePayload;
}

export interface TwinUpdateMaterialPayload {
  changes: number;
  tests: number;
}

export interface TwinUpdateDecisionPayload {
  decided_at: string;
  kept: number[];
  reason: string | null;
}

export interface TwinUpdatePayload {
  id: string;
  twin_id: string;
  twin_name: string;
  created_at: string;
  locale: string;
  status: TwinUpdateStatus;
  base: TwinUpdateBasePayload;
  comment: string;
  observations: ProposedObservationPayload[];
  material: TwinUpdateMaterialPayload;
  decision: TwinUpdateDecisionPayload | null;
  cost_microusd: number;
  evidence?: TwinUpdateEvidencePayload;
}

export interface LearningTwinPayload extends TwinLearningEntryPayload {
  pending_update: TwinUpdatePayload | null;
  new_material: TwinUpdateMaterialPayload;
}

export interface TwinLearningPayload {
  project_id: string;
  update_available: boolean;
  twins: LearningTwinPayload[];
}
import type { EvidenceChangePayload, TwinUpdateEvidencePayload } from "./researchEvidence";
