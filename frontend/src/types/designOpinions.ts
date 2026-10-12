import type { DesignChangeTarget } from "../api/designIterations";
import type { ColorMode, IsoDateTime, UUID } from "./design";

export type ChangeOpinionVerdict = "HELPS" | "SLOWS" | "BLOCKS";

export interface DesignOpinionRequest {
  design_version_id: UUID;
  design_content_hash: string;
  request: string;
  target: DesignChangeTarget;
  locale: string;
}

export interface ChangeOpinion {
  twin_id: UUID;
  twin_version: number;
  twin_name: string;
  verdict: ChangeOpinionVerdict;
  why: string;
  what_to_do: string;
  try_this: string | null;
  profile_keys: string[];
  confidence: number;
  generation_id: UUID;
}

export interface ChangeOpinionContrast {
  mode: ColorMode;
  text_threshold: number;
  large_text_threshold: number;
  control_border_threshold: number;
}

export interface ChangeOpinionRun {
  run_id: UUID;
  design_version_id: UUID;
  design_content_hash: string;
  design_version_number: number;
  request: string;
  target: DesignChangeTarget;
  locale: string;
  requested_at: IsoDateTime;
  opinions: ChangeOpinion[];
  contrast: ChangeOpinionContrast;
  cost_microusd: number | null;
}
