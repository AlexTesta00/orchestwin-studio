export type ChangedFileKind = "ADDED" | "MODIFIED" | "DELETED" | "RENAMED";

export type AlignmentStatus =
  "ALIGNED" | "CODE_DRIFT" | "DESIGN_OUTDATED" | "REQUIREMENTS_OUTDATED";

export type ChangeDecisionKind =
  "ALIGNED" | "DESIGN_CHANGE" | "REQUIREMENTS_CHANGE" | "CODE_TASKS" | "DISMISSED";

export type CritiqueVerdict = "FINE" | "CONCERN" | "DRIFT";

export type FindingSeverity = "LOW" | "MEDIUM" | "HIGH";

export type CodeTaskStatus = "OPEN" | "DONE";

export interface ChangedFilePayload {
  path: string;
  kind: ChangedFileKind;
  added: number;
  removed: number;
}

export interface ChangeReviewSummaryPayload {
  run_id: string;
  reviewed_at: string;
  verdict: AlignmentStatus;
  summary: string;
}

export interface ChangeDecisionPayload {
  kind: ChangeDecisionKind;
  decided_at: string;
  note: string | null;
}

export interface CodeChangePayload {
  commit: string;
  parent: string | null;
  committed_at: string;
  author: string | null;
  message: string;
  files: ChangedFilePayload[];
  recorded_at: string;
  review: ChangeReviewSummaryPayload | null;
  decision: ChangeDecisionPayload | null;
}

export interface CodeChangeListPayload {
  items: CodeChangePayload[];
}

export interface VersionReferencePayload {
  version_id: string;
  version_number: number;
  content_hash: string;
}

export interface DesignVersionReferencePayload extends VersionReferencePayload {
  alternative_code: string | null;
}

export interface DevelopmentReferencePayload {
  requirements: VersionReferencePayload | null;
  design: DesignVersionReferencePayload | null;
}

export interface AlignedPointPayload {
  commit: string;
  decided_at: string;
  requirements_version_number: number | null;
  design_version_number: number | null;
}

export interface CodeSubjectsPayload {
  requirements: string[];
  screens: string[];
}

export interface CodeTaskPayload {
  code: string;
  text: string;
  about: CodeSubjectsPayload;
  from_commit: string;
  created_at: string;
  status: CodeTaskStatus;
}

export interface AlignmentPayload {
  project_id: string;
  reference: DevelopmentReferencePayload;
  aligned: AlignedPointPayload | null;
  pending_changes: number;
  latest_change: CodeChangePayload | null;
  tasks: CodeTaskPayload[];
  review_available: boolean;
}

export interface FindingSubjectPayload {
  requirement: string | null;
  screen: string | null;
  file: string | null;
}

export interface CritiqueFindingPayload {
  severity: FindingSeverity;
  text: string;
  about: FindingSubjectPayload;
  action: string | null;
}

export interface ChangeCritiquePayload {
  twin_id: string;
  twin_name: string;
  verdict: CritiqueVerdict;
  summary: string;
  findings: CritiqueFindingPayload[];
}

export interface AlignmentVerdictPayload {
  status: AlignmentStatus;
  summary: string;
  affected: CodeSubjectsPayload;
  design_request: string | null;
  requirements_request: string | null;
  code_tasks: string[];
}

export interface RunReferencePayload {
  requirements_version_number: number;
  design_version_number: number;
  alternative_code: string | null;
}

export interface ChangeReviewRunPayload {
  id: string;
  commit: string;
  reviewed_at: string;
  locale: string;
  reference: RunReferencePayload;
  critiques: ChangeCritiquePayload[];
  alignment: AlignmentVerdictPayload;
  cost_microusd: number;
}

export interface ChangeReviewListPayload {
  items: ChangeReviewRunPayload[];
}
