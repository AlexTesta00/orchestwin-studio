export type UUID = string;

export type ArtifactKind =
  | "REQUIREMENTS_SPECIFICATION"
  | "AGENT_TEAM"
  | "USER_MODELING"
  | "DESIGN_PACKAGE"
  | "DECLARATIVE_PROTOTYPE";

export type ArtifactGraphStage = "CONTEXT" | "REQUIREMENTS" | "DESIGN";

export type ArtifactGraphNodeKind =
  | "PROJECT_BRIEF"
  | "AGENT_TEAM"
  | "USER_MODELING"
  | "USER_TWIN"
  | "REQUIREMENTS_SPECIFICATION"
  | "REQUIREMENT"
  | "USER_STORY"
  | "ACCEPTANCE_CRITERION"
  | "SCENARIO"
  | "PROJECT_RISK"
  | "DEFINITION_OF_DONE"
  | "DESIGN_PACKAGE"
  | "DESIGN_ALTERNATIVE"
  | "DESIGN_WORKFLOW"
  | "SYNTHETIC_DESIGN_CRITIQUE"
  | "DESIGN_CONCERN"
  | "DECLARATIVE_PROTOTYPE"
  | "PROTOTYPE_SCREEN";

export type ArtifactGraphLinkKind =
  | "CONTAINS"
  | "GROUNDED_IN"
  | "ACTS_AS"
  | "MOTIVATES"
  | "VERIFIED_BY"
  | "EXERCISES"
  | "AFFECTS"
  | "GOVERNS"
  | "TRACES_TO"
  | "REPRESENTS"
  | "CRITIQUES";

export interface VersionedArtifactReferencePayload {
  kind: ArtifactKind;
  artifact_id: UUID;
  version_number: number;
  content_hash: string;
}

export interface ArtifactGraphReferencePayload {
  kind: ArtifactGraphNodeKind;
  artifact_id: UUID;
  version_number: number | null;
  content_hash: string | null;
}

export interface ArtifactGraphNodePayload {
  reference: ArtifactGraphReferencePayload;
  stage: ArtifactGraphStage;
  display_code: string;
  title: string;
}

export interface ArtifactGraphLinkPayload {
  kind: ArtifactGraphLinkKind;
  source: ArtifactGraphReferencePayload;
  target: ArtifactGraphReferencePayload;
}

export interface CrossStageArtifactGraphPayload {
  schema_version: number;
  project_id: UUID;
  requirements_reference: VersionedArtifactReferencePayload;
  design_reference: VersionedArtifactReferencePayload | null;
  nodes: ArtifactGraphNodePayload[];
  links: ArtifactGraphLinkPayload[];
  stage_counts: Record<ArtifactGraphStage, number>;
  content_hash: string;
}
