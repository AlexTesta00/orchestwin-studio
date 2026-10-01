import { ApiRequestError } from "./requestError";

const DEFAULT_API_BASE_PATH = "/api/v1";

export interface DesignAlignmentPayload {
  aligned: boolean;
  issue: string | null;
  design_version_number: number | null;
  grounded_requirements_version_number: number | null;
  requirements_version_number: number | null;
  missing_codes: string[];
  uncovered_codes: string[];
}

export interface DesignRealignmentPayload {
  version_id: string;
  version_number: number;
  based_on_version_number: number | null;
  content_hash: string;
  requirements_version_number: number;
  gate_approval_required: boolean;
  uncovered_codes: string[];
}

export interface DesignAlignmentApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export class DesignAlignmentApiError extends ApiRequestError {}

export interface DesignAlignmentApi {
  status(projectId: string, accessToken: string): Promise<DesignAlignmentPayload>;
  realign(projectId: string, accessToken: string): Promise<DesignRealignmentPayload>;
}

function normalizedBasePath(value: string): string {
  const normalized = value.trim().replace(/\/+$/, "");

  if (normalized.length === 0) {
    throw new Error("Design Alignment API base path must not be empty");
  }

  return normalized;
}

function requiredAccessToken(value: string): string {
  const normalized = value.trim();

  if (normalized.length === 0) {
    throw new DesignAlignmentApiError("Authentication is required", {
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
  return `${basePath}/projects/${encodeURIComponent(projectId)}/design/requirements-alignment`;
}

export function createDesignAlignmentApi(
  options: DesignAlignmentApiOptions = {},
): DesignAlignmentApi {
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
      throw new DesignAlignmentApiError("The design alignment request failed", {
        status: response.status,
        code: errorCode(payload),
        payload,
      });
    }

    if (!isRecord(payload)) {
      throw new DesignAlignmentApiError("The Design Alignment API returned invalid JSON", {
        status: response.status,
        code: "INVALID_API_RESPONSE",
        payload,
      });
    }

    return payload as unknown as T;
  }

  return {
    status(projectId, accessToken) {
      return request<DesignAlignmentPayload>(projectId, "GET", accessToken);
    },

    realign(projectId, accessToken) {
      return request<DesignRealignmentPayload>(projectId, "POST", accessToken);
    },
  };
}

export const designAlignmentApi = createDesignAlignmentApi();
