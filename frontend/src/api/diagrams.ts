import { ApiRequestError } from "./requestError";

import type { DiagramLocale, ProjectDiagramsPayload } from "../types/diagrams";

const DEFAULT_API_BASE_PATH = "/api/v1";

export interface DiagramsApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export class DiagramsApiError extends ApiRequestError {}

export interface DiagramsApi {
  current(
    projectId: string,
    locale: DiagramLocale,
    accessToken: string,
  ): Promise<ProjectDiagramsPayload>;
}

function normalizedBasePath(value: string): string {
  const normalized = value.trim().replace(/\/+$/, "");

  if (normalized.length === 0) {
    throw new Error("Diagrams API base path must not be empty");
  }

  return normalized;
}

function requiredAccessToken(value: string): string {
  const normalized = value.trim();

  if (normalized.length === 0) {
    throw new DiagramsApiError("Authentication is required", {
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

function diagramsPath(basePath: string, projectId: string, locale: DiagramLocale): string {
  const query = new URLSearchParams({ locale });

  return `${basePath}/projects/${encodeURIComponent(projectId)}/diagrams?${query.toString()}`;
}

export function createDiagramsApi(options: DiagramsApiOptions = {}): DiagramsApi {
  const basePath = normalizedBasePath(options.basePath ?? DEFAULT_API_BASE_PATH);
  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);

  return {
    async current(projectId, locale, accessToken) {
      const response = await fetchImpl(diagramsPath(basePath, projectId, locale), {
        method: "GET",
        credentials: "include",
        headers: {
          Accept: "application/json",
          Authorization: `Bearer ${requiredAccessToken(accessToken)}`,
        },
      });
      const payload = await responsePayload(response);

      if (!response.ok) {
        throw new DiagramsApiError("The diagrams request failed", {
          status: response.status,
          code: errorCode(payload),
          payload,
        });
      }

      if (!isRecord(payload)) {
        throw new DiagramsApiError("The Diagrams API returned invalid JSON", {
          status: response.status,
          code: "INVALID_API_RESPONSE",
          payload,
        });
      }

      return payload as unknown as ProjectDiagramsPayload;
    },
  };
}

export const diagramsApi = createDiagramsApi();
