import type { IsoDateTime, UUID } from "./design";
import type { SyntheticFindingCriterion, SyntheticFindingSeverity } from "./designLoop";

export type DesignCritiqueSourceKind = "IMAGE" | "WEB_PAGE";
export type DesignCritiqueMediaType = "image/png" | "image/jpeg";
export type DesignCritiqueVerdict = "WORKS" | "SLOWS" | "BLOCKS";

export interface DesignCritiqueShotPayload {
  code: string;
  media_type: DesignCritiqueMediaType;
  byte_size: number;
  sha256: string;
  width: number;
  height: number;
  viewport_width: number | null;
}

export interface DesignCritiquePageElementPayload {
  index: number;
  role: string;
  name: string;
  value?: string | null;
  state?: string | null;
  options?: string[] | null;
}

export interface DesignCritiquePagePayload {
  url: string;
  title: string;
  text: string;
  hidden_text: string;
  elements: DesignCritiquePageElementPayload[];
}

export interface DesignCritiqueSourcePayload {
  id: UUID;
  project_id: UUID;
  kind: DesignCritiqueSourceKind;
  title: string;
  url: string | null;
  page: DesignCritiquePagePayload | null;
  shots: DesignCritiqueShotPayload[];
  created_at: IsoDateTime;
  content_hash: string;
}

export interface DesignCritiqueFindingPayload {
  finding_id: string;
  twin_id: UUID;
  location: string;
  anchor_key: string;
  summary: string;
  rationale: string;
  criterion: SyntheticFindingCriterion;
  severity: SyntheticFindingSeverity;
  recommended_action: string;
  confidence: number;
}

export interface DesignCritiqueResponsePayload {
  twin_id: UUID;
  twin_version: number;
  summary: string;
  evidence_gaps: string[];
  findings: DesignCritiqueFindingPayload[];
}

export interface DesignCritiqueTwinPayload {
  twin_id: UUID;
  version_number: number;
  name: string;
}

export interface DesignCritiqueVerdictPayload {
  twin_id: UUID;
  anchor_key: string;
  verdict: DesignCritiqueVerdict;
}

export interface DesignCritiqueRunPayload {
  id: UUID;
  project_id: UUID;
  source: DesignCritiqueSourcePayload;
  twins: DesignCritiqueTwinPayload[];
  responses: DesignCritiqueResponsePayload[];
  verdicts: DesignCritiqueVerdictPayload[];
  started_at: IsoDateTime;
  completed_at: IsoDateTime;
  duration_seconds: number;
  cost_microusd: number;
  content_hash: string;
}

export interface DesignCritiqueResultPayload {
  status: "DESIGN_CRITIQUE_RECORDED";
  run: DesignCritiqueRunPayload;
}

export interface DesignCritiqueRequest {
  source_id: UUID;
  locale: string;
}
