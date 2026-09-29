export type DiagramStage = "requirements" | "design";

export type DiagramKind =
  | "USE_CASES"
  | "REQUIREMENTS"
  | "REQUIREMENTS_TRACEABILITY"
  | "WORKFLOWS"
  | "SCREEN_MAP"
  | "DESIGN_TRACEABILITY";

export type DiagramLocale = "en" | "it";

export interface DiagramSourceVersionPayload {
  version_id: string;
  version_number: number;
  content_hash: string;
}

export interface DiagramPayload {
  key: string;
  stage: DiagramStage;
  kind: DiagramKind;
  subject: string | null;
  title: string;
  description: string;
  path: string;
  source: string;
}

export interface ProjectDiagramsPayload {
  project_id: string;
  locale: DiagramLocale;
  mermaid_version: string;
  system_name: string;
  requirements: DiagramSourceVersionPayload;
  design: DiagramSourceVersionPayload | null;
  diagrams: DiagramPayload[];
}
