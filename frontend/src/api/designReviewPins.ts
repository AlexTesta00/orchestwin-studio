import { accessTokenOf, basePathOf, detailCode, responseBody } from "./http";
import { ApiRequestError } from "./requestError";

import type {
  MockupDocumentPayload,
  MockupDocumentZones,
  ReviewPinsPayload,
} from "../types/designMockups";

const DEFAULT_API_BASE_PATH = "/api/v1";

export interface DesignReviewPinsApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export class DesignReviewPinsApiError extends ApiRequestError {}

export interface DesignReviewPinsApi {
  pins(projectId: string, runId: string, accessToken: string): Promise<ReviewPinsPayload>;
  document(
    projectId: string,
    runId: string,
    entryScreen: string | null,
    accessToken: string,
    options?: MockupDocumentZones,
  ): Promise<MockupDocumentPayload>;
}

function evaluationPath(basePath: string, projectId: string, runId: string): string {
  return `${basePath}/projects/${encodeURIComponent(projectId)}/design/evaluations/${encodeURIComponent(runId)}`;
}

export function createDesignReviewPinsApi(
  options: DesignReviewPinsApiOptions = {},
): DesignReviewPinsApi {
  const basePath = basePathOf(options.basePath ?? DEFAULT_API_BASE_PATH, "Design Review Pins");

  async function request<T>(path: string, accessTokenValue: string): Promise<T> {
    const accessToken = accessTokenOf(accessTokenValue, DesignReviewPinsApiError);
    const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
    const response = await fetchImpl(path, {
      method: "GET",
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${accessToken}`,
      },
      credentials: "include",
    });
    const payload = await responseBody(response, DesignReviewPinsApiError, "Design Review Pins");

    if (!response.ok) {
      const code = detailCode(payload);

      throw new DesignReviewPinsApiError(
        code ?? `Design Review Pins API request failed with status ${response.status}`,
        {
          status: response.status,
          code,
          payload,
        },
      );
    }

    return payload as T;
  }

  return {
    pins(projectId, runId, accessToken) {
      return request(`${evaluationPath(basePath, projectId, runId)}/pins`, accessToken);
    },

    document(projectId, runId, entryScreen, accessToken, options = {}) {
      const path = `${evaluationPath(basePath, projectId, runId)}/document`;
      const query = new URLSearchParams({
        ...(entryScreen === null ? {} : { entry_screen: entryScreen }),
        ...(options.zones === true ? { zones: "true" } : {}),
      }).toString();

      return request(query === "" ? path : `${path}?${query}`, accessToken);
    },
  };
}

export const designReviewPinsApi = createDesignReviewPinsApi();
