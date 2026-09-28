import { ApiRequestError } from "./requestError";

import type {
  RequirementsAlignmentPayload,
  RequirementsRealignmentPayload,
} from "../types/requirementsAlignment";

const DEFAULT_API_BASE_PATH = "/api/v1";

export interface RequirementsAlignmentApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export class RequirementsAlignmentApiError extends ApiRequestError {}

export interface RequirementsAlignmentApi {
  status(projectId: string, accessToken: string): Promise<RequirementsAlignmentPayload>;
  realign(projectId: string, accessToken: string): Promise<RequirementsRealignmentPayload>;
}

function normalizedBasePath(value: string): string {
  const normalized = value.trim().replace(/\/+$/, "");

  if (normalized.length === 0) {
    throw new Error("Requirements Alignment API base path must not be empty");
  }

  return normalized;
}

function requiredAccessToken(value: string): string {
  const normalized = value.trim();

  if (normalized.length === 0) {
    throw new RequirementsAlignmentApiError("Authentication is required", {
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

function alignmentPath(basePath: string, projectId: string): string {
  return `${basePath}/projects/${encodeURIComponent(projectId)}/requirements/twin-alignment`;
}

export function createRequirementsAlignmentApi(
  options: RequirementsAlignmentApiOptions = {},
): RequirementsAlignmentApi {
  const basePath = normalizedBasePath(options.basePath ?? DEFAULT_API_BASE_PATH);
  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);

  async function request<T>(
    projectId: string,
    method: "GET" | "POST",
    accessToken: string,
  ): Promise<T> {
    const response = await fetchImpl(alignmentPath(basePath, projectId), {
      method,
      credentials: "include",
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${requiredAccessToken(accessToken)}`,
      },
    });
    const payload = await responsePayload(response);

    if (!response.ok) {
      throw new RequirementsAlignmentApiError("The requirements alignment request failed", {
        status: response.status,
        code: errorCode(payload),
        payload,
      });
    }

    if (!isRecord(payload)) {
      throw new RequirementsAlignmentApiError(
        "The Requirements Alignment API returned invalid JSON",
        {
          status: response.status,
          code: "INVALID_API_RESPONSE",
          payload,
        },
      );
    }

    return payload as unknown as T;
  }

  return {
    status(projectId, accessToken) {
      return request<RequirementsAlignmentPayload>(projectId, "GET", accessToken);
    },

    realign(projectId, accessToken) {
      return request<RequirementsRealignmentPayload>(projectId, "POST", accessToken);
    },
  };
}

export const requirementsAlignmentApi = createRequirementsAlignmentApi();
