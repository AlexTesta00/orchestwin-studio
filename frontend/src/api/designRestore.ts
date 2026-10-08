import { ApiRequestError } from "./requestError";

import type { DesignRevisionPayload } from "../types/design";

const DEFAULT_API_BASE_PATH = "/api/v1";

export interface DesignRestoreRequest {
  version_number: number;
  locale: string;
}

export interface DesignRestorePayload {
  reason: "RESTORED";
  restored_version_number: number;
  note: string;
  revision: DesignRevisionPayload;
}

export interface DesignRestoreApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export class DesignRestoreApiError extends ApiRequestError {}

export interface DesignRestoreApi {
  restore(
    projectId: string,
    request: DesignRestoreRequest,
    accessToken: string,
  ): Promise<DesignRestorePayload>;
}

function normalizedBasePath(value: string): string {
  const normalized = value.trim().replace(/\/+$/, "");

  if (normalized.length === 0) {
    throw new Error("Design Restore API base path must not be empty");
  }

  return normalized;
}

function requiredAccessToken(value: string): string {
  const normalized = value.trim();

  if (normalized.length === 0) {
    throw new DesignRestoreApiError("Authentication is required", {
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

function isRestore(payload: unknown): payload is DesignRestorePayload {
  return (
    isRecord(payload) &&
    payload.reason === "RESTORED" &&
    typeof payload.restored_version_number === "number" &&
    typeof payload.note === "string" &&
    isRecord(payload.revision) &&
    isRecord(payload.revision.version) &&
    typeof payload.revision.version.version_number === "number"
  );
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

function restorePath(basePath: string, projectId: string): string {
  return `${basePath}/projects/${encodeURIComponent(projectId)}/design/revisions/restore`;
}

export function createDesignRestoreApi(options: DesignRestoreApiOptions = {}): DesignRestoreApi {
  const basePath = normalizedBasePath(options.basePath ?? DEFAULT_API_BASE_PATH);

  return {
    async restore(projectId, request, accessToken) {
      const fetchImpl = options.fetchImpl ?? globalThis.fetch;
      const response = await fetchImpl(restorePath(basePath, projectId), {
        method: "POST",
        credentials: "include",
        headers: {
          Accept: "application/json",
          Authorization: `Bearer ${requiredAccessToken(accessToken)}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          version_number: request.version_number,
          locale: request.locale,
        }),
      });
      const payload = await responsePayload(response);

      if (!response.ok) {
        throw new DesignRestoreApiError("The design restore request failed", {
          status: response.status,
          code: errorCode(payload),
          payload,
        });
      }

      if (!isRestore(payload)) {
        throw new DesignRestoreApiError("The Design Restore API returned an unexpected answer", {
          status: response.status,
          code: "INVALID_API_RESPONSE",
          payload,
        });
      }

      return payload;
    },
  };
}

export const designRestoreApi = createDesignRestoreApi();
