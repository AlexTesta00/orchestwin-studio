export interface RequirementsAlignmentPayload {
  aligned: boolean;
  issue: string | null;
  requirements_version_number: number | null;
  snapshot_version_number: number | null;
  twins_approved: boolean;
}

export interface RequirementsRealignmentPayload {
  version_id: string;
  version_number: number;
  based_on_version_number: number | null;
  content_hash: string;
  user_modeling_version_number: number;
  twin_count: number;
  gate_approval_required: boolean;
}
