import { ApiRequestError } from "./requestError";

import type { GenerationBudgetPayload, ModelUsagePayload } from "../types/designMockups";

const DEFAULT_API_BASE_PATH = "/api/v1";

export interface ModelUsageApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export class ModelUsageApiError extends ApiRequestError {}

export interface ModelUsageApi {
  usage(projectId: string, accessToken: string): Promise<ModelUsagePayload>;
  budget(accessToken: string): Promise<GenerationBudgetPayload>;
}

function normalizedBasePath(value: string): string {
  const normalized = value.trim().replace(/\/+$/, "");

  if (normalized.length === 0) {
    throw new Error("Model Usage API base path must not be empty");
  }

  return normalized;
}

function requiredAccessToken(value: string): string {
  const normalized = value.trim();

  if (normalized.length === 0) {
    throw new ModelUsageApiError("Authentication is required", {
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
    throw new ModelUsageApiError("The Model Usage API returned invalid JSON", {
      status: response.status,
      code: "INVALID_API_RESPONSE",
      payload: text,
    });
  }
}

function usagePath(basePath: string, projectId: string): string {
  return `${basePath}/projects/${encodeURIComponent(projectId)}/model-usage`;
}

export function createModelUsageApi(options: ModelUsageApiOptions = {}): ModelUsageApi {
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

      throw new ModelUsageApiError(
        code ?? `Model Usage API request failed with status ${response.status}`,
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
    usage(projectId, accessToken) {
      return request(usagePath(basePath, projectId), accessToken);
    },

    budget(accessToken) {
      return request(`${basePath}/model-runtime/budget`, accessToken);
    },
  };
}

export const modelUsageApi = createModelUsageApi();
