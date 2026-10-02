import type { ProjectStage } from "../api/contracts";

export type SectionState =
  "NOT_STARTED" | "IN_PROGRESS" | "FINE" | "UPDATE_AVAILABLE" | "TO_UPDATE";

export type SectionReason =
  | "BRIEF_CHANGED"
  | "PERSPECTIVES_CHANGED"
  | "ARCHETYPES_CHANGED"
  | "USER_TWINS_CHANGED"
  | "REQUIREMENTS_CHANGED"
  | "FOLDER_BEHIND"
  | "TWINS_LEARNED"
  | "REQUIREMENTS_NOT_COVERED"
  | "EVALUATION_MISSING";

export type SectionBlock =
  | "REQUIREMENT_NO_LONGER_AVAILABLE"
  | "TWIN_SET_CHANGED"
  | "TWIN_NO_LONGER_AVAILABLE"
  | "REVISION_PENDING"
  | "UPSTREAM_NOT_READY"
  | "PREPARE_AGAIN"
  | "PREPARE_TWINS";

export type AlignableSectionKey = "TEAM" | "USER_TWINS" | "REQUIREMENTS" | "DESIGN";

export interface ProjectSectionPayload {
  key: ProjectStage;
  state: SectionState;
  version_number: number | null;
  reasons: SectionReason[];
  blocked: SectionBlock | null;
  codes: string[];
  affected_codes?: {
    scenarios: string[];
    needs: string[];
    requirements: string[];
  };
}

export interface SectionsAlignmentSummaryPayload {
  available: boolean;
  sections: AlignableSectionKey[];
  uncovered_codes: string[];
}

export interface ProjectSectionsPayload {
  first_pass_complete: boolean;
  sections: ProjectSectionPayload[];
  alignment: SectionsAlignmentSummaryPayload;
}

export type SectionsAlignmentStatus = "ALIGNED" | "PARTIAL" | "NOTHING_TO_ALIGN";

export type SectionAlignmentOutcome = "ALIGNED" | "BLOCKED" | "SKIPPED";

export interface SectionAlignmentResultPayload {
  key: AlignableSectionKey;
  outcome: SectionAlignmentOutcome;
  issue: string | null;
  version_number: number | null;
  codes: string[];
}

export interface SectionsAlignmentPayload {
  status: SectionsAlignmentStatus;
  results: SectionAlignmentResultPayload[];
  sections: ProjectSectionsPayload;
}
