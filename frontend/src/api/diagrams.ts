import { accessTokenOf, basePathOf, detailCode, isRecord, responseBody } from "./http";
import { ApiRequestError } from "./requestError";

import type { DiagramLocale, ProjectDiagramsPayload } from "../types/diagrams";

const DEFAULT_API_BASE_PATH = "/api/v1";

export interface DiagramsApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export class DiagramsApiError extends ApiRequestError {}

export interface DiagramsApi {
  current(
    projectId: string,
    locale: DiagramLocale,
    accessToken: string,
  ): Promise<ProjectDiagramsPayload>;
}

function diagramsPath(basePath: string, projectId: string, locale: DiagramLocale): string {
  const query = new URLSearchParams({ locale });

  return `${basePath}/projects/${encodeURIComponent(projectId)}/diagrams?${query.toString()}`;
}

export function createDiagramsApi(options: DiagramsApiOptions = {}): DiagramsApi {
  const basePath = basePathOf(options.basePath ?? DEFAULT_API_BASE_PATH, "Diagrams");
  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);

  return {
    async current(projectId, locale, accessToken) {
      const response = await fetchImpl(diagramsPath(basePath, projectId, locale), {
        method: "GET",
        credentials: "include",
        headers: {
          Accept: "application/json",
          Authorization: `Bearer ${accessTokenOf(accessToken, DiagramsApiError)}`,
        },
      });
      const payload = await responseBody(response);

      if (!response.ok) {
        throw new DiagramsApiError("The diagrams request failed", {
          status: response.status,
          code: detailCode(payload),
          payload,
        });
      }

      if (!isRecord(payload)) {
        throw new DiagramsApiError("The Diagrams API returned invalid JSON", {
          status: response.status,
          code: "INVALID_API_RESPONSE",
          payload,
        });
      }

      return payload as unknown as ProjectDiagramsPayload;
    },
  };
}

export const diagramsApi = createDiagramsApi();
