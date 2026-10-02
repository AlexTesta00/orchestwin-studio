import { ApiRequestError } from "./requestError";

import type { AcceptanceTestsOverviewPayload } from "../types/acceptanceTests";

const DEFAULT_API_BASE_PATH = "/api/v1";

export interface AcceptanceTestsApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export class AcceptanceTestsApiError extends ApiRequestError {}

export interface AcceptanceTestsApi {
  overview(projectId: string, accessToken: string): Promise<AcceptanceTestsOverviewPayload>;
}

function normalizedBasePath(value: string): string {
  const normalized = value.trim().replace(/\/+$/, "");

  if (normalized.length === 0) {
    throw new Error("Acceptance Tests API base path must not be empty");
  }

  return normalized;
}

function requiredAccessToken(value: string): string {
  const normalized = value.trim();

  if (normalized.length === 0) {
    throw new AcceptanceTestsApiError("Authentication is required", {
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
    return text;
  }
}

function isLatestReview(value: unknown): boolean {
  return (
    value === undefined ||
    value === null ||
    (isRecord(value) &&
      typeof value.run_id === "string" &&
      typeof value.finished_at === "string" &&
      Array.isArray(value.critiques))
  );
}

function isOverview(payload: unknown): payload is Record<string, unknown> {
  return (
    isRecord(payload) &&
    (payload.latest_run === null || isRecord(payload.latest_run)) &&
    (payload.latest_run_stale === undefined || typeof payload.latest_run_stale === "boolean") &&
    isLatestReview(payload.latest_review)
  );
}

function overviewPath(basePath: string, projectId: string): string {
  return `${basePath}/projects/${encodeURIComponent(projectId)}/acceptance-tests`;
}

export function createAcceptanceTestsApi(
  options: AcceptanceTestsApiOptions = {},
): AcceptanceTestsApi {
  const basePath = normalizedBasePath(options.basePath ?? DEFAULT_API_BASE_PATH);
  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);

  return {
    async overview(projectId, accessToken) {
      const response = await fetchImpl(overviewPath(basePath, projectId), {
        method: "GET",
        credentials: "include",
        headers: {
          Accept: "application/json",
          Authorization: `Bearer ${requiredAccessToken(accessToken)}`,
        },
      });
      const payload = await responsePayload(response);

      if (!response.ok) {
        throw new AcceptanceTestsApiError("The acceptance tests request failed", {
          status: response.status,
          code: errorCode(payload),
          payload,
        });
      }

      if (!isOverview(payload)) {
        throw new AcceptanceTestsApiError("The Acceptance Tests API returned invalid JSON", {
          status: response.status,
          code: "INVALID_API_RESPONSE",
          payload,
        });
      }

      return payload as unknown as AcceptanceTestsOverviewPayload;
    },
  };
}

export const acceptanceTestsApi = createAcceptanceTestsApi();
