import { ApiError, resolveApiBaseUrl } from "./client";
import type { DeclarativePrototypePayload } from "../types/design";

interface ArtifactReference {
  artifact_id: string;
  version_number: number;
  content_hash: string;
}

export interface SourceDesignReferencePayload {
  source: {
    revision_id: string;
    version_number: number;
    content_hash: string;
    origin: string;
  };
  architecture: ArtifactReference;
  design: ArtifactReference;
  prototype: DeclarativePrototypePayload | null;
  current_design: ArtifactReference | null;
  design_status: "CURRENT" | "STALE" | "UNAVAILABLE";
  visual_conformance: "NOT_ASSESSED";
  structure_contract: "VERIFIED" | "NOT_ASSESSED";
  owner_mockup: {
    generation_id: string;
    design_version_id: string;
    design_content_hash: string;
    prototype_id: string;
    prototype_content_hash: string;
    package_content_hash: string;
    prototype: DeclarativePrototypePayload;
  } | null;
}

export interface SourceDesignApi {
  reference(
    projectId: string,
    revisionId: string,
    accessToken: string,
  ): Promise<SourceDesignReferencePayload>;
}

export function createSourceDesignApi(fetchImpl?: typeof fetch): SourceDesignApi {
  return {
    async reference(projectId, revisionId, accessToken) {
      const response = await (fetchImpl ?? globalThis.fetch)(
        `${resolveApiBaseUrl()}/projects/${encodeURIComponent(projectId)}/web-source-revisions/${encodeURIComponent(revisionId)}/design-reference`,
        {
          credentials: "include",
          headers: { Accept: "application/json", Authorization: `Bearer ${accessToken}` },
        },
      );
      if (!response.ok) throw new ApiError(response.status, "SOURCE_DESIGN_REFERENCE_UNAVAILABLE");
      return (await response.json()) as SourceDesignReferencePayload;
    },
  };
}

export const sourceDesignApi = createSourceDesignApi();
