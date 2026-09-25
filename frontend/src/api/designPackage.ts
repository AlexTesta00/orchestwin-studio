import { ApiRequestError } from "./requestError";

const DEFAULT_API_BASE_PATH = "/api/v1";

export interface DesignPackageApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export class DesignPackageApiError extends ApiRequestError {}

export interface DesignPackageDownload {
  blob: Blob;
  fileName: string;
  contentHash: string | null;
}

export interface DesignPackageApi {
  download(projectId: string, accessToken: string): Promise<DesignPackageDownload>;
}

function normalizedBasePath(value: string): string {
  const normalized = value.trim().replace(/\/+$/, "");

  if (normalized.length === 0) {
    throw new Error("Design Package API base path must not be empty");
  }

  return normalized;
}

function requiredAccessToken(value: string): string {
  const normalized = value.trim();

  if (normalized.length === 0) {
    throw new DesignPackageApiError("Authentication is required", {
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

export function designPackageFileName(projectId: string): string {
  return `orchestwin-${projectId}-design-package.zip`;
}

function fileNameFromDisposition(header: string | null, fallback: string): string {
  const match = /filename="([^"]+)"/.exec(header ?? "");
  return match?.[1] ?? fallback;
}

export function designPackagePath(basePath: string, projectId: string): string {
  return `${basePath}/projects/${encodeURIComponent(projectId)}/design-package`;
}

export function createDesignPackageApi(options: DesignPackageApiOptions = {}): DesignPackageApi {
  const basePath = normalizedBasePath(options.basePath ?? DEFAULT_API_BASE_PATH);
  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);

  return {
    async download(projectId, accessToken) {
      const response = await fetchImpl(designPackagePath(basePath, projectId), {
        method: "GET",
        credentials: "include",
        headers: {
          Accept: "application/zip",
          Authorization: `Bearer ${requiredAccessToken(accessToken)}`,
        },
      });

      if (!response.ok) {
        const payload = await responsePayload(response);
        throw new DesignPackageApiError("The design package request failed", {
          status: response.status,
          code: errorCode(payload),
          payload,
        });
      }

      return {
        blob: await response.blob(),
        fileName: fileNameFromDisposition(
          response.headers.get("content-disposition"),
          designPackageFileName(projectId),
        ),
        contentHash: response.headers.get("x-content-sha256"),
      };
    },
  };
}

export const designPackageApi = createDesignPackageApi();
