import { ApiRequestError } from "./requestError";

import type {
  KnowledgePackageDownload,
  KnowledgePackageHistoryPayload,
  KnowledgePackagePublicationPayload,
} from "../types/knowledgePackages";

const DEFAULT_API_BASE_PATH = "/api/v1";

export interface KnowledgePackagesApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export class KnowledgePackagesApiError extends ApiRequestError {}

export interface KnowledgePackagesApi {
  publish(projectId: string, accessToken: string): Promise<KnowledgePackagePublicationPayload>;
  history(
    projectId: string,
    accessToken: string,
    limit?: number,
  ): Promise<KnowledgePackageHistoryPayload>;
  download(
    projectId: string,
    versionNumber: number,
    accessToken: string,
  ): Promise<KnowledgePackageDownload>;
}

function normalizedBasePath(value: string): string {
  const normalized = value.trim().replace(/\/+$/, "");

  if (normalized.length === 0) {
    throw new Error("Knowledge Packages API base path must not be empty");
  }

  return normalized;
}

function requiredAccessToken(value: string): string {
  const normalized = value.trim();

  if (normalized.length === 0) {
    throw new KnowledgePackagesApiError("Authentication is required", {
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

export function knowledgePackageFileName(projectId: string, versionNumber: number): string {
  return `orchestwin-${projectId}-knowledge-v${versionNumber}.zip`;
}

function fileNameFromDisposition(header: string | null, fallback: string): string {
  const match = /filename="([^"]+)"/.exec(header ?? "");
  return match?.[1] ?? fallback;
}

function packagesPath(basePath: string, projectId: string): string {
  return `${basePath}/projects/${encodeURIComponent(projectId)}/knowledge-packages`;
}

function historyPath(basePath: string, projectId: string, limit: number | undefined): string {
  const path = packagesPath(basePath, projectId);

  if (limit === undefined) {
    return path;
  }

  const query = new URLSearchParams({ limit: String(limit) });

  return `${path}?${query.toString()}`;
}

function archivePath(basePath: string, projectId: string, versionNumber: number): string {
  return `${packagesPath(basePath, projectId)}/${encodeURIComponent(versionNumber)}/archive`;
}

export function createKnowledgePackagesApi(
  options: KnowledgePackagesApiOptions = {},
): KnowledgePackagesApi {
  const basePath = normalizedBasePath(options.basePath ?? DEFAULT_API_BASE_PATH);
  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);

  async function authenticatedFetch(
    path: string,
    method: "GET" | "POST",
    accept: string,
    accessToken: string,
  ): Promise<Response> {
    const response = await fetchImpl(path, {
      method,
      credentials: "include",
      headers: {
        Accept: accept,
        Authorization: `Bearer ${requiredAccessToken(accessToken)}`,
      },
    });

    if (!response.ok) {
      const payload = await responsePayload(response);
      throw new KnowledgePackagesApiError("The knowledge package request failed", {
        status: response.status,
        code: errorCode(payload),
        payload,
      });
    }

    return response;
  }

  async function jsonPayload<T>(response: Response): Promise<T> {
    const payload = await responsePayload(response);

    if (!isRecord(payload)) {
      throw new KnowledgePackagesApiError("The Knowledge Packages API returned invalid JSON", {
        status: response.status,
        code: "INVALID_API_RESPONSE",
        payload,
      });
    }

    return payload as unknown as T;
  }

  return {
    async publish(projectId, accessToken) {
      const response = await authenticatedFetch(
        packagesPath(basePath, projectId),
        "POST",
        "application/json",
        accessToken,
      );

      return jsonPayload<KnowledgePackagePublicationPayload>(response);
    },

    async history(projectId, accessToken, limit) {
      const response = await authenticatedFetch(
        historyPath(basePath, projectId, limit),
        "GET",
        "application/json",
        accessToken,
      );

      return jsonPayload<KnowledgePackageHistoryPayload>(response);
    },

    async download(projectId, versionNumber, accessToken) {
      const response = await authenticatedFetch(
        archivePath(basePath, projectId, versionNumber),
        "GET",
        "application/zip",
        accessToken,
      );

      return {
        blob: await response.blob(),
        fileName: fileNameFromDisposition(
          response.headers.get("content-disposition"),
          knowledgePackageFileName(projectId, versionNumber),
        ),
        archiveHash: response.headers.get("x-content-sha256"),
      };
    },
  };
}

export const knowledgePackagesApi = createKnowledgePackagesApi();
