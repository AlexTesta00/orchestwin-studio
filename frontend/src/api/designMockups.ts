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

function normalizedBasePath(value: string): string {
  const normalized = value.trim().replace(/\/+$/, "");

  if (normalized.length === 0) {
    throw new Error("Design Mockups API base path must not be empty");
  }

  return normalized;
}

function requiredAccessToken(value: string): string {
  const normalized = value.trim();

  if (normalized.length === 0) {
    throw new DesignMockupsApiError("Authentication is required", {
      status: 0,
      code: "ACCESS_TOKEN_REQUIRED",
      payload: null,
    });
  }

  return normalized;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function errorCode(payload: unknown): string | null {
  if (!isRecord(payload) || !isRecord(payload.detail)) {
    return null;
  }

  return typeof payload.detail.code === "string" ? payload.detail.code : null;
}

async function responsePayload(response: Response): Promise<unknown> {
  const text = await response.text();

  if (text.trim().length === 0) {
    return null;
  }

  try {
    return JSON.parse(text) as unknown;
  } catch {
    throw new DesignMockupsApiError("The Design Mockups API returned invalid JSON", {
      status: response.status,
      code: "INVALID_API_RESPONSE",
      payload: text,
    });
  }
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
  const basePath = normalizedBasePath(options.basePath ?? DEFAULT_API_BASE_PATH);

  async function request<T>(path: string, optionsValue: RequestOptions): Promise<T> {
    const accessToken = requiredAccessToken(optionsValue.accessToken);
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
    const payload = await responsePayload(response);

    if (!response.ok) {
      const code = errorCode(payload);

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
