import type { DesignRevisionPayload } from "./design";
import type { RequirementsRevisionPayload } from "./requirements";

export type ProposalSection = "REQUIREMENTS" | "DESIGN" | "TESTS";

export type ProposalStatus = "PROPOSED" | "APPLIED" | "SKIPPED";

export type ProposalListStatus = "waiting" | "all";

export interface ProposalSubjectsPayload {
  requirements: string[];
  screens: string[];
  criteria: string[];
}

export interface ProposalOriginPayload {
  commits: string[];
  files: string[];
  excerpt: string;
}

export interface AlignmentProposalPayload {
  id: string;
  run_id: string;
  code: string;
  section: ProposalSection;
  title: string;
  request: string;
  rationale: string;
  subjects: ProposalSubjectsPayload;
  origin: ProposalOriginPayload;
  status: ProposalStatus;
  created_at: string;
  decided_at: string | null;
  decision_note: string | null;
  applied_text: string | null;
  applied_diff_id: string | null;
}

export interface KnowledgeAlignmentRunPayload {
  id: string;
  project_id: string;
  from_commit: string | null;
  to_commit: string;
  commits: string[];
  locale: string;
  requirements_version_number: number;
  design_version_number: number;
  alternative_code: string | null;
  summary: string;
  created_at: string;
  cost_microusd: number;
  generation_ids: string[];
  proposals: AlignmentProposalPayload[];
}

export interface KnowledgeAlignmentRunSummaryPayload extends Omit<
  KnowledgeAlignmentRunPayload,
  "proposals"
> {
  waiting: number;
  proposals_count: number;
}

export interface KnowledgeAlignmentRunListPayload {
  items: KnowledgeAlignmentRunSummaryPayload[];
}

export interface KnowledgeAlignmentRunResponsePayload {
  run: KnowledgeAlignmentRunPayload;
}

export interface KnowledgeAlignmentRequest {
  locale?: string;
  from_commit: string | null;
  to_commit: string;
  commits: string[];
}

export interface AlignmentLatestRunPayload {
  id: string;
  from_commit: string | null;
  to_commit: string;
  created_at: string;
  requirements_version_number: number;
  design_version_number: number;
  alternative_code: string | null;
  summary: string;
}

export interface AlignmentProposalListPayload {
  items: AlignmentProposalPayload[];
  latest_run: AlignmentLatestRunPayload | null;
}

export interface ProposalApplyRequest {
  text: string | null;
  locale?: string;
}

export interface ProposalSkipRequest {
  reason: string | null;
}

export interface DesignChangeResultPayload {
  revision: DesignRevisionPayload;
  changes: string[];
}

export type ProposalRevisionPayload = RequirementsRevisionPayload | DesignChangeResultPayload;

export interface ProposalApplyPayload {
  proposal: AlignmentProposalPayload;
  revision: ProposalRevisionPayload | null;
}

export interface ProposalSkipPayload {
  proposal: AlignmentProposalPayload;
}
