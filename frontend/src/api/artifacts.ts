import { accessTokenOf, basePathOf, detailCode, isRecord, responseBody } from "./http";
import { ApiRequestError } from "./requestError";

import type { CrossStageArtifactGraphPayload } from "../types/artifacts";

const DEFAULT_API_BASE_PATH = "/api/v1";

export interface ArtifactGraphApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export class ArtifactGraphApiError extends ApiRequestError {}

export interface ArtifactGraphApi {
  current(projectId: string, accessToken: string): Promise<CrossStageArtifactGraphPayload>;
  exportCurrent(projectId: string, accessToken: string): Promise<Blob>;
}

function graphPath(basePath: string, projectId: string): string {
  return `${basePath}/projects/${encodeURIComponent(projectId)}/artifacts/graph`;
}

export function createArtifactGraphApi(options: ArtifactGraphApiOptions = {}): ArtifactGraphApi {
  const basePath = basePathOf(options.basePath ?? DEFAULT_API_BASE_PATH, "Artifact Graph");
  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);

  async function authenticatedFetch(
    path: string,
    accessToken: string,
    accept: string,
  ): Promise<Response> {
    const response = await fetchImpl(path, {
      method: "GET",
      credentials: "include",
      headers: {
        Accept: accept,
        Authorization: `Bearer ${accessTokenOf(accessToken, ArtifactGraphApiError)}`,
      },
    });

    if (!response.ok) {
      const payload = await responseBody(response);
      throw new ArtifactGraphApiError("The Artifact Graph request failed", {
        status: response.status,
        code: detailCode(payload),
        payload,
      });
    }

    return response;
  }

  return {
    async current(projectId, accessToken) {
      const response = await authenticatedFetch(
        graphPath(basePath, projectId),
        accessToken,
        "application/json",
      );
      const payload = await responseBody(response);

      if (!isRecord(payload)) {
        throw new ArtifactGraphApiError("The Artifact Graph API returned invalid JSON", {
          status: response.status,
          code: "INVALID_API_RESPONSE",
          payload,
        });
      }

      return payload as unknown as CrossStageArtifactGraphPayload;
    },

    async exportCurrent(projectId, accessToken) {
      const response = await authenticatedFetch(
        `${graphPath(basePath, projectId)}/export`,
        accessToken,
        "application/json",
      );

      return response.blob();
    },
  };
}

export const artifactGraphApi = createArtifactGraphApi();
