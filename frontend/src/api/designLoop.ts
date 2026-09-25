import { ApiRequestError } from "./requestError";

import type { DesignGenerationPayload } from "../types/design";
import type {
  DesignEvaluationComparisonPayload,
  DesignEvaluationRequest,
  DesignEvaluationRunPayload,
  InsightApplicationPayload,
  InsightApplicationRequest,
} from "../types/designLoop";

const DEFAULT_API_BASE_PATH = "/api/v1";

export interface DesignLoopApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export interface DesignLoopApi {
  evaluate(
    projectId: string,
    body: DesignEvaluationRequest,
    accessToken: string,
  ): Promise<DesignEvaluationRunPayload>;
  runs(projectId: string, accessToken: string): Promise<DesignEvaluationRunPayload[]>;
  comparison(
    projectId: string,
    accessToken: string,
  ): Promise<DesignEvaluationComparisonPayload | null>;
  regenerate(projectId: string, accessToken: string): Promise<DesignGenerationPayload>;
  applyInsight(
    projectId: string,
    body: InsightApplicationRequest,
    accessToken: string,
  ): Promise<InsightApplicationPayload>;
  applications(projectId: string, accessToken: string): Promise<InsightApplicationPayload[]>;
}

export class DesignLoopApiError extends ApiRequestError {}

function normalizedBasePath(value: string): string {
  const normalized = value.trim().replace(/\/+$/u, "");
  if (normalized.length === 0 || !normalized.startsWith("/") || normalized.startsWith("//")) {
    throw new Error("Design loop API base path must be an absolute application path");
  }
  return normalized;
}

function requiredAccessToken(value: string): string {
  const normalized = value.trim();
  if (normalized.length === 0) {
    throw new DesignLoopApiError("Authentication is required", {
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

export function createDesignLoopApi(options: DesignLoopApiOptions = {}): DesignLoopApi {
  const basePath = normalizedBasePath(options.basePath ?? DEFAULT_API_BASE_PATH);
  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);

  function projectPath(projectId: string): string {
    return `${basePath}/projects/${encodeURIComponent(projectId)}`;
  }

  async function request(
    path: string,
    accessToken: string,
    method: "GET" | "POST",
    body?: unknown,
  ): Promise<unknown> {
    const headers = new Headers();
    headers.set("Accept", "application/json");
    headers.set("Authorization", `Bearer ${requiredAccessToken(accessToken)}`);
    const init: RequestInit = { credentials: "include", headers, method };
    if (body !== undefined) {
      headers.set("Content-Type", "application/json");
      init.body = JSON.stringify(body);
    }
    const response = await fetchImpl(path, init);
    const payload = await responsePayload(response);
    if (!response.ok) {
      throw new DesignLoopApiError("The design loop request failed", {
        status: response.status,
        code: errorCode(payload),
        payload,
      });
    }
    return payload;
  }

  return {
    async evaluate(projectId, body, accessToken) {
      return (await request(
        `${projectPath(projectId)}/design/evaluations`,
        accessToken,
        "POST",
        body,
      )) as DesignEvaluationRunPayload;
    },

    async runs(projectId, accessToken) {
      return (await request(
        `${projectPath(projectId)}/design/evaluations`,
        accessToken,
        "GET",
      )) as DesignEvaluationRunPayload[];
    },

    async comparison(projectId, accessToken) {
      try {
        return (await request(
          `${projectPath(projectId)}/design/evaluations/comparison`,
          accessToken,
          "GET",
        )) as DesignEvaluationComparisonPayload;
      } catch (error) {
        if (error instanceof DesignLoopApiError && error.status === 404) {
          return null;
        }
        throw error;
      }
    },

    async regenerate(projectId, accessToken) {
      return (await request(
        `${projectPath(projectId)}/design/regenerations`,
        accessToken,
        "POST",
        {},
      )) as DesignGenerationPayload;
    },

    async applyInsight(projectId, body, accessToken) {
      return (await request(
        `${projectPath(projectId)}/insight-applications`,
        accessToken,
        "POST",
        body,
      )) as InsightApplicationPayload;
    },

    async applications(projectId, accessToken) {
      return (await request(
        `${projectPath(projectId)}/insight-applications`,
        accessToken,
        "GET",
      )) as InsightApplicationPayload[];
    },
  };
}

export const designLoopApi = createDesignLoopApi();
