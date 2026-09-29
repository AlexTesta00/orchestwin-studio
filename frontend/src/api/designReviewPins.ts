import { ApiRequestError } from "./requestError";

import type { MockupDocumentPayload, ReviewPinsPayload } from "../types/designMockups";

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
  ): Promise<MockupDocumentPayload>;
}

function normalizedBasePath(value: string): string {
  const normalized = value.trim().replace(/\/+$/, "");

  if (normalized.length === 0) {
    throw new Error("Design Review Pins API base path must not be empty");
  }

  return normalized;
}

function requiredAccessToken(value: string): string {
  const normalized = value.trim();

  if (normalized.length === 0) {
    throw new DesignReviewPinsApiError("Authentication is required", {
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
    throw new DesignReviewPinsApiError("The Design Review Pins API returned invalid JSON", {
      status: response.status,
      code: "INVALID_API_RESPONSE",
      payload: text,
    });
  }
}

function evaluationPath(basePath: string, projectId: string, runId: string): string {
  return `${basePath}/projects/${encodeURIComponent(projectId)}/design/evaluations/${encodeURIComponent(runId)}`;
}

export function createDesignReviewPinsApi(
  options: DesignReviewPinsApiOptions = {},
): DesignReviewPinsApi {
  const basePath = normalizedBasePath(options.basePath ?? DEFAULT_API_BASE_PATH);

  async function request<T>(path: string, accessTokenValue: string): Promise<T> {
    const accessToken = requiredAccessToken(accessTokenValue);
    const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
    const response = await fetchImpl(path, {
      method: "GET",
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${accessToken}`,
      },
      credentials: "include",
    });
    const payload = await responsePayload(response);

    if (!response.ok) {
      const code = errorCode(payload);

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

    document(projectId, runId, entryScreen, accessToken) {
      const path = `${evaluationPath(basePath, projectId, runId)}/document`;
      const query =
        entryScreen === null ? "" : `?${new URLSearchParams({ entry_screen: entryScreen })}`;

      return request(`${path}${query}`, accessToken);
    },
  };
}

export const designReviewPinsApi = createDesignReviewPinsApi();
