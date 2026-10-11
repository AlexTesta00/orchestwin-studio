export type IterationJobStatus = "RUNNING" | "SUCCEEDED" | "REJECTED" | "FAILED";
export type IterationJobStage = "GENERATING" | "VALIDATING" | "RETRYING";
export type IterationStatus = "PROPOSED" | "APPLIED" | "REJECTED" | "FAILED";
export type IterationSide = "before" | "after";

export interface IterationReason {
  code: string;
  screen_code?: string | null | undefined;
  detail?: string | undefined;
}

export interface IterationFailure {
  code: string;
  reasons: readonly IterationReason[];
}

export interface IterationResult {
  status: string;
  generation_id: string;
  design_version_id: string;
  design_content_hash: string;
  package?: unknown;
  approach: string | null;
  changes: readonly string[];
  warnings: readonly IterationReason[];
  cost_microusd: number | null;
}

export interface IterationJob {
  job_id: string;
  kind: string;
  status: IterationJobStatus;
  stage: IterationJobStage | null;
  attempt: number;
  started_at: string;
  finished_at: string | null;
  alternative_id: string | null;
  result: IterationResult | null;
  failure: IterationFailure | null;
}

export interface IterationItem {
  generation_id: string;
  requested_at: string;
  request: string;
  assertions: readonly string[];
  changes: readonly string[];
  status: IterationStatus;
  base_design_version_number: number | null;
  applied_design_version_number: number | null;
  cost_microusd: number | null;
}
