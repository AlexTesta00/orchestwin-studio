export type KnowledgeStage = "brief" | "team" | "twins" | "requirements" | "design";

export interface PackageStagePayload {
  stage: KnowledgeStage;
  label: string;
  version_number: number;
  content_hash: string;
}

export interface PackageTwinPayload {
  twin_id: string;
  name: string;
  slug: string;
  version_number: number;
  document: string;
}

export interface PackageFeedbackPayload {
  reviews: number;
  findings: number;
  decisions: number;
  discussions: number;
  insights: number;
}

export interface KnowledgePackageVersionPayload {
  id: string;
  project_id: string;
  project_name: string;
  version_number: number;
  schema_version: number;
  content_hash: string;
  archive_hash: string;
  file_name: string;
  file_count: number;
  archive_size: number;
  created_at: string;
  stages: PackageStagePayload[];
  twins: PackageTwinPayload[];
  feedback: PackageFeedbackPayload;
  diagram_count: number;
  table_count: number;
  entries: string[];
}

export interface KnowledgePackagePublicationPayload {
  reused: boolean;
  version: KnowledgePackageVersionPayload;
}

export interface KnowledgePackageHistoryPayload {
  project_id: string;
  versions: KnowledgePackageVersionPayload[];
}

export interface KnowledgePackageDownload {
  blob: Blob;
  fileName: string;
  archiveHash: string | null;
}
