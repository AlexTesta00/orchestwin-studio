import { accessTokenOf, basePathOf, detailCode, isRecord, responseBody } from "./http";
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

function restorePath(basePath: string, projectId: string): string {
  return `${basePath}/projects/${encodeURIComponent(projectId)}/design/revisions/restore`;
}

export function createDesignRestoreApi(options: DesignRestoreApiOptions = {}): DesignRestoreApi {
  const basePath = basePathOf(options.basePath ?? DEFAULT_API_BASE_PATH, "Design Restore");

  return {
    async restore(projectId, request, accessToken) {
      const fetchImpl = options.fetchImpl ?? globalThis.fetch;
      const response = await fetchImpl(restorePath(basePath, projectId), {
        method: "POST",
        credentials: "include",
        headers: {
          Accept: "application/json",
          Authorization: `Bearer ${accessTokenOf(accessToken, DesignRestoreApiError)}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          version_number: request.version_number,
          locale: request.locale,
        }),
      });
      const payload = await responseBody(response);

      if (!response.ok) {
        throw new DesignRestoreApiError("The design restore request failed", {
          status: response.status,
          code: detailCode(payload),
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
