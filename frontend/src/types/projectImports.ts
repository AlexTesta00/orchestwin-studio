export interface ImportedProjectPayload {
  id: string;
  display_name: string;
  mode: string;
  created_at: string;
}

export interface FolderOriginPayload {
  project_id: string;
  project_name: string;
  package_version: number;
  package_content_hash: string;
  schema_version: number;
}

export interface ImportedStagePayload {
  version_id: string;
  version_number: number;
  content_hash: string;
}

export interface ImportedTwinPayload {
  twin_id: string;
  name: string;
}

export interface ProjectImportPayload {
  project: ImportedProjectPayload;
  origin: FolderOriginPayload;
  stages: Record<string, ImportedStagePayload>;
  twins: ImportedTwinPayload[];
  imported_at: string;
  approval_required: string[];
  why_verified?: boolean;
  import_limits?: string[];
}

export interface ProjectImportOriginPayload {
  origin: FolderOriginPayload;
  stages: Record<string, ImportedStagePayload>;
  imported_at: string;
  archive_hash: string;
}
