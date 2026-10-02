import { ApiRequestError } from "./requestError";

import type { TwinLearningPayload } from "../types/twinLearning";

const DEFAULT_API_BASE_PATH = "/api/v1";
const ABSENT_STATUSES: ReadonlySet<number> = new Set([404, 405]);

export interface TwinLearningApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export class TwinLearningApiError extends ApiRequestError {}

export interface TwinLearningApi {
  overview(projectId: string, accessToken: string): Promise<TwinLearningPayload | null>;
}

function normalizedBasePath(value: string): string {
  const normalized = value.trim().replace(/\/+$/, "");

  if (normalized.length === 0) {
    throw new Error("Twin Learning API base path must not be empty");
  }

  return normalized;
}

function requiredAccessToken(value: string): string {
  const normalized = value.trim();

  if (normalized.length === 0) {
    throw new TwinLearningApiError("Authentication is required", {
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

function isObservation(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.code === "string" &&
    typeof value.statement === "string" &&
    typeof value.source === "string" &&
    typeof value.approved_at === "string" &&
    isRecord(value.about)
  );
}

function isMaterial(value: unknown): boolean {
  return isRecord(value) && typeof value.changes === "number" && typeof value.tests === "number";
}

function isLearningTwin(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.twin_id === "string" &&
    typeof value.twin_name === "string" &&
    typeof value.label === "string" &&
    Array.isArray(value.observations) &&
    value.observations.every(isObservation) &&
    Array.isArray(value.retired) &&
    (value.pending_update === null || isRecord(value.pending_update)) &&
    isMaterial(value.new_material)
  );
}

function isOverview(payload: unknown): payload is Record<string, unknown> {
  return (
    isRecord(payload) &&
    typeof payload.update_available === "boolean" &&
    Array.isArray(payload.twins) &&
    payload.twins.every(isLearningTwin)
  );
}

function overviewPath(basePath: string, projectId: string): string {
  return `${basePath}/projects/${encodeURIComponent(projectId)}/twin-learning`;
}

export function createTwinLearningApi(options: TwinLearningApiOptions = {}): TwinLearningApi {
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

      if (ABSENT_STATUSES.has(response.status)) {
        return null;
      }

      if (!response.ok) {
        throw new TwinLearningApiError("The twin learning request failed", {
          status: response.status,
          code: errorCode(payload),
          payload,
        });
      }

      if (!isOverview(payload)) {
        throw new TwinLearningApiError("The Twin Learning API returned invalid JSON", {
          status: response.status,
          code: "INVALID_API_RESPONSE",
          payload,
        });
      }

      return payload as unknown as TwinLearningPayload;
    },
  };
}

export const twinLearningApi = createTwinLearningApi();
