import { ApiRequestError } from "./requestError";

import type { ProjectImportOriginPayload, ProjectImportPayload } from "../types/projectImports";

const DEFAULT_API_BASE_PATH = "/api/v1";
const IMPORT_NOT_FOUND = "PROJECT_IMPORT_NOT_FOUND";

export interface ProjectImportsApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export class ProjectImportsApiError extends ApiRequestError {
  readonly location: string | null;

  constructor(
    message: string,
    options: { status: number; code: string | null; payload: unknown; location?: string | null },
  ) {
    super(message, options);
    this.location = options.location ?? null;
  }
}

export interface ProjectImportsApi {
  importArchive(
    file: Blob,
    fileName: string,
    displayName: string | null,
    accessToken: string,
  ): Promise<ProjectImportPayload>;
  origin(projectId: string, accessToken: string): Promise<ProjectImportOriginPayload | null>;
}

function normalizedBasePath(value: string): string {
  const normalized = value.trim().replace(/\/+$/, "");

  if (normalized.length === 0) {
    throw new Error("Project Imports API base path must not be empty");
  }

  return normalized;
}

function requiredAccessToken(value: string): string {
  const normalized = value.trim();

  if (normalized.length === 0) {
    throw new ProjectImportsApiError("Authentication is required", {
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

function errorDetail(payload: unknown, key: "code" | "location"): string | null {
  if (!isRecord(payload) || !isRecord(payload.detail)) {
    return null;
  }

  const value = payload.detail[key];
  return typeof value === "string" ? value : null;
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

function importsPath(basePath: string): string {
  return `${basePath}/project-imports`;
}

function originPath(basePath: string, projectId: string): string {
  return `${basePath}/projects/${encodeURIComponent(projectId)}/import`;
}

function archiveForm(file: Blob, fileName: string, displayName: string | null): FormData {
  const form = new FormData();
  form.append("archive", file, fileName);

  if (displayName !== null) {
    form.append("display_name", displayName);
  }

  return form;
}

export function createProjectImportsApi(options: ProjectImportsApiOptions = {}): ProjectImportsApi {
  const basePath = normalizedBasePath(options.basePath ?? DEFAULT_API_BASE_PATH);
  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);

  async function request(
    path: string,
    method: "GET" | "POST",
    accessToken: string,
    body?: FormData,
  ): Promise<{ response: Response; payload: unknown }> {
    const init: RequestInit = {
      method,
      credentials: "include",
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${requiredAccessToken(accessToken)}`,
      },
    };

    if (body !== undefined) {
      init.body = body;
    }

    const response = await fetchImpl(path, init);
    return { response, payload: await responsePayload(response) };
  }

  function failure(response: Response, payload: unknown): ProjectImportsApiError {
    return new ProjectImportsApiError("The project import request failed", {
      status: response.status,
      code: errorDetail(payload, "code"),
      payload,
      location: errorDetail(payload, "location"),
    });
  }

  function jsonPayload<T>(response: Response, payload: unknown): T {
    if (!isRecord(payload)) {
      throw new ProjectImportsApiError("The Project Imports API returned invalid JSON", {
        status: response.status,
        code: "INVALID_API_RESPONSE",
        payload,
      });
    }

    return payload as unknown as T;
  }

  return {
    async importArchive(file, fileName, displayName, accessToken) {
      const { response, payload } = await request(
        importsPath(basePath),
        "POST",
        accessToken,
        archiveForm(file, fileName, displayName),
      );

      if (!response.ok) {
        throw failure(response, payload);
      }

      return jsonPayload<ProjectImportPayload>(response, payload);
    },

    async origin(projectId, accessToken) {
      const { response, payload } = await request(
        originPath(basePath, projectId),
        "GET",
        accessToken,
      );

      if (response.status === 404 && errorDetail(payload, "code") === IMPORT_NOT_FOUND) {
        return null;
      }

      if (!response.ok) {
        throw failure(response, payload);
      }

      return jsonPayload<ProjectImportOriginPayload>(response, payload);
    },
  };
}

export const projectImportsApi = createProjectImportsApi();
