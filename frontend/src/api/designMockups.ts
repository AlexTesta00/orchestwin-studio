import { accessTokenOf, basePathOf, detailCode, responseBody } from "./http";
import { ApiRequestError } from "./requestError";

import type {
  DesignMockupCapabilitiesPayload,
  GenerationJobPayload,
  MockupDocumentPayload,
  MockupDocumentQuery,
  MockupJobRequest,
  MockupResultPayload,
} from "../types/designMockups";

const DEFAULT_API_BASE_PATH = "/api/v1";

type HttpMethod = "GET" | "POST";

interface RequestOptions {
  method: HttpMethod;
  accessToken: string;
  body?: unknown;
}

export interface DesignMockupsApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export class DesignMockupsApiError extends ApiRequestError {}

export interface DesignMockupsApi {
  capabilities(projectId: string, accessToken: string): Promise<DesignMockupCapabilitiesPayload>;
  startJob(
    projectId: string,
    request: MockupJobRequest,
    accessToken: string,
  ): Promise<GenerationJobPayload>;
  job(projectId: string, jobId: string, accessToken: string): Promise<GenerationJobPayload>;
  latest(
    projectId: string,
    alternativeId: string,
    accessToken: string,
  ): Promise<MockupResultPayload | null>;
  document(
    projectId: string,
    query: MockupDocumentQuery,
    accessToken: string,
  ): Promise<MockupDocumentPayload>;
}

function mockupsPath(basePath: string, projectId: string): string {
  return `${basePath}/projects/${encodeURIComponent(projectId)}/design/mockups`;
}

function withQuery(path: string, query: Record<string, string | undefined>): string {
  const parameters = new URLSearchParams();

  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined) {
      parameters.set(key, value);
    }
  }

  return `${path}?${parameters.toString()}`;
}

export function createDesignMockupsApi(options: DesignMockupsApiOptions = {}): DesignMockupsApi {
  const basePath = basePathOf(options.basePath ?? DEFAULT_API_BASE_PATH, "Design Mockups");

  async function request<T>(path: string, optionsValue: RequestOptions): Promise<T> {
    const accessToken = accessTokenOf(optionsValue.accessToken, DesignMockupsApiError);
    const headers: Record<string, string> = {
      Accept: "application/json",
      Authorization: `Bearer ${accessToken}`,
    };
    const init: RequestInit = {
      method: optionsValue.method,
      headers,
      credentials: "include",
    };

    if (optionsValue.body !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(optionsValue.body);
    }

    const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
    const response = await fetchImpl(path, init);
    const payload = await responseBody(response, DesignMockupsApiError, "Design Mockups");

    if (!response.ok) {
      const code = detailCode(payload);

      throw new DesignMockupsApiError(
        code ?? `Design Mockups API request failed with status ${response.status}`,
        {
          status: response.status,
          code,
          payload,
        },
      );
    }

    return payload as T;
  }

  function projectPath(projectId: string): string {
    return mockupsPath(basePath, projectId);
  }

  return {
    capabilities(projectId, accessToken) {
      return request(`${projectPath(projectId)}/capabilities`, {
        method: "GET",
        accessToken,
      });
    },

    startJob(projectId, requestValue, accessToken) {
      return request(`${projectPath(projectId)}/jobs`, {
        method: "POST",
        accessToken,
        body: requestValue,
      });
    },

    job(projectId, jobId, accessToken) {
      return request(`${projectPath(projectId)}/jobs/${encodeURIComponent(jobId)}`, {
        method: "GET",
        accessToken,
      });
    },

    latest(projectId, alternativeId, accessToken) {
      return request(withQuery(projectPath(projectId), { alternative_id: alternativeId }), {
        method: "GET",
        accessToken,
      });
    },

    document(projectId, query, accessToken) {
      return request(
        withQuery(`${projectPath(projectId)}/document`, {
          alternative_id: query.alternative_id,
          source: query.source,
          entry_screen: query.entry_screen,
        }),
        {
          method: "GET",
          accessToken,
        },
      );
    },
  };
}

export const designMockupsApi = createDesignMockupsApi();
