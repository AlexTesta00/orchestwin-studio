import { ApiRequestError } from "./requestError";

import type {
  DesignIterationPayload,
  GenerationJobPayload,
  IterationJobRequest,
} from "../types/designMockups";

const DEFAULT_API_BASE_PATH = "/api/v1";

type HttpMethod = "GET" | "POST";

interface RequestOptions {
  method: HttpMethod;
  accessToken: string;
  body?: unknown;
}

export interface DesignIterationsApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export class DesignIterationsApiError extends ApiRequestError {}

export interface DesignChangeTarget {
  screen_code: string;
  element_code?: string;
  label: string;
  html: string;
}

export type IterationJobBody = IterationJobRequest & {
  target?: DesignChangeTarget;
  critique_source_id?: string;
};

export type DesignIterationItem = DesignIterationPayload & {
  critique_source_id?: string | null;
};

export interface DesignIterationItemsPayload {
  items: DesignIterationItem[];
}

export interface DesignIterationsApi {
  startJob(
    projectId: string,
    request: IterationJobBody,
    accessToken: string,
  ): Promise<GenerationJobPayload>;
  job(projectId: string, jobId: string, accessToken: string): Promise<GenerationJobPayload>;
  list(projectId: string, accessToken: string): Promise<DesignIterationItemsPayload>;
}

function normalizedBasePath(value: string): string {
  const normalized = value.trim().replace(/\/+$/, "");

  if (normalized.length === 0) {
    throw new Error("Design Iterations API base path must not be empty");
  }

  return normalized;
}

function requiredAccessToken(value: string): string {
  const normalized = value.trim();

  if (normalized.length === 0) {
    throw new DesignIterationsApiError("Authentication is required", {
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
    throw new DesignIterationsApiError("The Design Iterations API returned invalid JSON", {
      status: response.status,
      code: "INVALID_API_RESPONSE",
      payload: text,
    });
  }
}

function iterationsPath(basePath: string, projectId: string): string {
  return `${basePath}/projects/${encodeURIComponent(projectId)}/design/iterations`;
}

export function createDesignIterationsApi(
  options: DesignIterationsApiOptions = {},
): DesignIterationsApi {
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

      throw new DesignIterationsApiError(
        code ?? `Design Iterations API request failed with status ${response.status}`,
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
    return iterationsPath(basePath, projectId);
  }

  return {
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

    list(projectId, accessToken) {
      return request(projectPath(projectId), {
        method: "GET",
        accessToken,
      });
    },
  };
}

export const designIterationsApi = createDesignIterationsApi();
