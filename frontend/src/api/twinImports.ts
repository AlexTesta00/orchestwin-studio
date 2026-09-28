import { ApiRequestError } from "./requestError";

import type {
  TwinImportPayload,
  TwinImportRequest,
  TwinImportSourcePayload,
  TwinImportSourcesPayload,
} from "../types/twinImports";

const DEFAULT_API_BASE_PATH = "/api/v1";

export interface TwinImportsApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export class TwinImportsApiError extends ApiRequestError {}

export interface TwinImportsApi {
  sources(projectId: string, accessToken: string): Promise<TwinImportSourcesPayload>;
  source(
    projectId: string,
    sourceProjectId: string,
    accessToken: string,
  ): Promise<TwinImportSourcePayload>;
  importFromProject(
    projectId: string,
    sourceProjectId: string,
    twinId: string,
    accessToken: string,
  ): Promise<TwinImportPayload>;
  importDocument(
    projectId: string,
    document: unknown,
    accessToken: string,
  ): Promise<TwinImportPayload>;
}

function normalizedBasePath(value: string): string {
  const normalized = value.trim().replace(/\/+$/, "");

  if (normalized.length === 0) {
    throw new Error("Twin Imports API base path must not be empty");
  }

  return normalized;
}

function requiredAccessToken(value: string): string {
  const normalized = value.trim();

  if (normalized.length === 0) {
    throw new TwinImportsApiError("Authentication is required", {
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

function importsPath(basePath: string, projectId: string): string {
  return `${basePath}/projects/${encodeURIComponent(projectId)}/user-modeling/twin-imports`;
}

function sourcesPath(basePath: string, projectId: string): string {
  return `${importsPath(basePath, projectId)}/sources`;
}

function sourcePath(basePath: string, projectId: string, sourceProjectId: string): string {
  return `${sourcesPath(basePath, projectId)}/${encodeURIComponent(sourceProjectId)}`;
}

export function createTwinImportsApi(options: TwinImportsApiOptions = {}): TwinImportsApi {
  const basePath = normalizedBasePath(options.basePath ?? DEFAULT_API_BASE_PATH);
  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);

  async function request<T>(
    path: string,
    accessToken: string,
    body?: TwinImportRequest,
  ): Promise<T> {
    const headers: Record<string, string> = {
      Accept: "application/json",
      Authorization: `Bearer ${requiredAccessToken(accessToken)}`,
    };
    const init: RequestInit = { method: "GET", credentials: "include", headers };

    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      init.method = "POST";
      init.body = JSON.stringify(body);
    }

    const response = await fetchImpl(path, init);
    const payload = await responsePayload(response);

    if (!response.ok) {
      throw new TwinImportsApiError("The twin import request failed", {
        status: response.status,
        code: errorCode(payload),
        payload,
      });
    }

    if (!isRecord(payload)) {
      throw new TwinImportsApiError("The Twin Imports API returned invalid JSON", {
        status: response.status,
        code: "INVALID_API_RESPONSE",
        payload,
      });
    }

    return payload as unknown as T;
  }

  return {
    async sources(projectId, accessToken) {
      return request<TwinImportSourcesPayload>(sourcesPath(basePath, projectId), accessToken);
    },

    async source(projectId, sourceProjectId, accessToken) {
      return request<TwinImportSourcePayload>(
        sourcePath(basePath, projectId, sourceProjectId),
        accessToken,
      );
    },

    async importFromProject(projectId, sourceProjectId, twinId, accessToken) {
      return request<TwinImportPayload>(importsPath(basePath, projectId), accessToken, {
        source_project_id: sourceProjectId,
        twin_id: twinId,
      });
    },

    async importDocument(projectId, document, accessToken) {
      return request<TwinImportPayload>(importsPath(basePath, projectId), accessToken, {
        document,
      });
    },
  };
}

export const twinImportsApi = createTwinImportsApi();
