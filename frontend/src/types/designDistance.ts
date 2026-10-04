import type { DirectionAxis, UUID } from "./design";

export type DesignDistanceVerdict = "FAR" | "CLOSE" | "UNKNOWN";

export type DirectionAdherenceStatus = "FOLLOWED" | "NOT_FOLLOWED" | "NOT_CHECKED";

export type StyleDifference =
  | "RADIUS"
  | "BORDER"
  | "BOXING"
  | "SHADOW"
  | "TYPE_SCALE"
  | "TITLE_SCALE"
  | "UPPERCASE"
  | "COLOUR_FIELDS"
  | "TINTS"
  | "GRADIENT"
  | "CONTAINER"
  | "COLUMNS"
  | "SPACING"
  | "MONOSPACE";

export type StructureDifference =
  "OUTLINE" | "TAGS" | "TABLE" | "CARDS" | "SIDE_COLUMN" | "NAVIGATION" | "FORMS";

export interface DeclaredDistancePayload {
  score: number | null;
  axes_different: number | null;
  axes: DirectionAxis[];
  choices_different: number | null;
  choices_total: number;
  primary_colour_distance: number | null;
}

export interface MeasuredDistancePayload<Difference extends string> {
  available: boolean;
  score: number | null;
  differences: Difference[];
}

export interface DesignDistancePairPayload {
  first: string;
  second: string;
  declared: DeclaredDistancePayload;
  styles: MeasuredDistancePayload<StyleDifference>;
  structure: MeasuredDistancePayload<StructureDifference>;
  verdict: DesignDistanceVerdict;
}

export interface DirectionAdherencePayload {
  available: boolean;
  axes: Partial<Record<DirectionAxis, DirectionAdherenceStatus>>;
}

export interface DesignDistanceAlternativePayload {
  code: string;
  direction: string | null;
  adherence: DirectionAdherencePayload;
}

export interface DesignDistanceReportPayload {
  distance_version: number;
  design_version_id: UUID;
  design_content_hash: string;
  pairs: DesignDistancePairPayload[];
  alternatives: DesignDistanceAlternativePayload[];
}
