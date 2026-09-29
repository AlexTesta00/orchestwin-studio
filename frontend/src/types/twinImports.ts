export interface ImportableTwinPayload {
  twin_id: string;
  name: string;
  version_number: number;
  content_hash: string;
  validation_status: string;
  summary: string | null;
  issue: string | null;
}

export interface TwinImportSourcePayload {
  project_id: string;
  project_name: string;
  snapshot_version_number: number;
  approved_at: string;
  twins: ImportableTwinPayload[];
}

export interface TwinImportCandidatePayload {
  project_id: string;
  project_name: string;
  snapshot_version_number: number;
  approved_at: string;
  twin_names: string[];
}

export interface TwinImportSourcesPayload {
  sources: TwinImportCandidatePayload[];
}

export interface ImportedTwinPayload {
  twin_id: string;
  version_id: string;
  version_number: number;
  name: string;
  content_hash: string;
  validation_status: string;
}

export interface ImportedPersonaPayload {
  persona_id: string;
  version_id: string;
  version_number: number;
  name: string;
}

export interface ImportedSnapshotPayload {
  version_id: string;
  version_number: number;
  content_hash: string;
  twin_count: number;
}

export interface TwinOriginPayload {
  project_id: string;
  project_name: string;
  twin_id: string;
  twin_version_number: number;
  twin_content_hash: string;
  persona_id: string;
  persona_version_number: number;
  persona_content_hash: string;
}

export interface TwinImportPayload {
  status: "TWIN_IMPORTED";
  twin: ImportedTwinPayload;
  persona: ImportedPersonaPayload;
  snapshot: ImportedSnapshotPayload;
  origin: TwinOriginPayload;
  gate_approval_required: boolean;
}

export interface TwinImportFromProjectRequest {
  source_project_id: string;
  twin_id: string;
}

export interface TwinImportDocumentRequest {
  document: unknown;
}

export type TwinImportRequest = TwinImportFromProjectRequest | TwinImportDocumentRequest;
