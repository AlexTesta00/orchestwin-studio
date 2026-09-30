import type { DesignPackagePayload, IsoDateTime, PrototypeScreenState, UUID } from "./design";
import type { SyntheticFindingSeverity } from "./designLoop";

export interface GeneratedScreenPayload {
  code: string;
  title: string;
  state: PrototypeScreenState;
  markup: string;
}

export interface GeneratedMockupPayload {
  contract_version: number;
  design_alternative_id: UUID;
  title: string;
  styles: string;
  screens: GeneratedScreenPayload[];
}

export interface BoundGeneratedMockupPayload {
  mockup: GeneratedMockupPayload;
  requirement_ids_by_code: Record<string, UUID>;
}

export interface DesignMockupCapabilitiesPayload {
  generated_mockups: boolean;
  iterations: boolean;
  model: string | null;
  static_check?: boolean;
}

export type GenerationJobKind = "MOCKUP" | "ITERATION" | "REQUEST";
export type GenerationJobStatus = "RUNNING" | "SUCCEEDED" | "REJECTED" | "FAILED";
export type GenerationJobStage = "GENERATING" | "VALIDATING" | "RETRYING";
export type GenerationOperation =
  | "MOCKUP"
  | "ITERATION"
  | "PERSONA_PROPOSAL"
  | "USER_TWIN_GENERATION"
  | "REQUIREMENTS_PROPOSAL"
  | "REQUIREMENTS_CHANGE"
  | "DESIGN_PROPOSAL"
  | "DESIGN_REGENERATION"
  | "DESIGN_EVALUATION"
  | "DISCUSSION_START"
  | "DISCUSSION_ROUND"
  | "CODE_CHANGE_REVIEW"
  | "TEST_PLAN"
  | "TEST_REVIEW";

export interface GenerationJobResponsePayload {
  status_code: number;
  body: unknown;
}

export interface MockupIssuePayload {
  code: string;
  screen_code: string | null;
  detail: string;
}

export interface GenerationFailurePayload {
  code: string;
  reasons: MockupIssuePayload[];
}

export interface MockupResultPayload {
  status: "MOCKUP_GENERATED";
  generation_id: UUID;
  design_version_id: UUID;
  design_content_hash: string;
  package: DesignPackagePayload;
  approach: string | null;
  changes: string[];
  warnings: MockupIssuePayload[];
  cost_microusd: number | null;
}

export interface GenerationJobPayload {
  job_id: UUID;
  kind: GenerationJobKind;
  operation?: GenerationOperation;
  status: GenerationJobStatus;
  stage: GenerationJobStage | null;
  attempt: number;
  started_at: IsoDateTime;
  finished_at: IsoDateTime | null;
  alternative_id: UUID | null;
  result: MockupResultPayload | null;
  failure: GenerationFailurePayload | null;
  response?: GenerationJobResponsePayload | null;
}

export interface MockupJobRequest {
  design_version_id: UUID;
  design_content_hash: string;
  alternative_id: UUID;
}

export type MockupDocumentSource = "applied" | "latest";

export interface MockupDocumentQuery {
  alternative_id: UUID;
  source: MockupDocumentSource;
  entry_screen?: string;
}

export interface MockupDocumentScreenPayload {
  code: string;
  title: string;
  state: PrototypeScreenState;
}

export interface MockupDocumentPayload {
  html: string;
  content_hash: string;
  source: MockupDocumentSource | "review";
  alternative_id: UUID;
  title: string;
  entry_screen: string;
  screens: MockupDocumentScreenPayload[];
}

export interface IterationJobRequest {
  design_version_id: UUID;
  design_content_hash: string;
  request: string;
  assertions: string[];
}

export type DesignIterationStatus = "PROPOSED" | "APPLIED" | "REJECTED" | "FAILED";

export interface DesignIterationPayload {
  generation_id: UUID;
  requested_at: IsoDateTime;
  request: string;
  assertions: string[];
  changes: string[];
  status: DesignIterationStatus;
  base_design_version_number: number;
  applied_design_version_number: number | null;
  cost_microusd: number | null;
}

export interface DesignIterationListPayload {
  items: DesignIterationPayload[];
}

export interface ReviewPinPayload {
  number: number;
  element_code: string;
  screen_code: string;
  twin_id: UUID;
  finding_id: string;
  severity: SyntheticFindingSeverity;
  label: string;
}

export interface UnanchoredReviewPinPayload {
  number: number;
  screen_code: string;
  twin_id: UUID;
  finding_id: string;
}

export interface ReviewPinsPayload {
  design_version_id: UUID;
  pins: ReviewPinPayload[];
  unanchored: UnanchoredReviewPinPayload[];
}

export type ModelProviderKind =
  "ANTHROPIC_HOSTED" | "OPENAI_COMPATIBLE_HOSTED" | "OPENAI_COMPATIBLE_LOCAL";

export interface ModelUsageItemPayload {
  generation_id: UUID;
  recorded_at: IsoDateTime;
  task: string;
  purpose: string | null;
  provider_kind: ModelProviderKind;
  model: string;
  status: string;
  failure_code: string | null;
  input_tokens: number;
  output_tokens: number;
  reasoning_tokens?: number | undefined;
  cache_read_input_tokens: number;
  cache_write_input_tokens: number;
  cost_microusd: number | null;
  latency_milliseconds: number | null;
}

export interface ModelUsageTotalsPayload {
  generations: number;
  input_tokens: number;
  output_tokens: number;
  reasoning_tokens?: number | undefined;
  cost_microusd: number;
}

export interface ModelUsagePayload {
  items: ModelUsageItemPayload[];
  totals: ModelUsageTotalsPayload;
}

export interface GenerationBudgetPayload {
  currency: "USD";
  per_generation_microusd: number;
  per_project_microusd: number;
  total_microusd: number;
  spent_total_microusd: number;
  remaining_total_microusd: number;
  period_start: string | null;
}
