import { ApiRequestError } from "./requestError";

import type {
  AlignmentPayload,
  ChangeReviewListPayload,
  CodeChangeListPayload,
  CodeTaskListPayload,
  CodeTaskListStatus,
} from "../types/codeChanges";

const DEFAULT_API_BASE_PATH = "/api/v1";

export interface CodeChangesApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export class CodeChangesApiError extends ApiRequestError {}

export interface CodeChangesApi {
  alignment(projectId: string, accessToken: string): Promise<AlignmentPayload>;
  changes(
    projectId: string,
    accessToken: string,
    pending?: boolean,
  ): Promise<CodeChangeListPayload>;
  reviews(projectId: string, commit: string, accessToken: string): Promise<ChangeReviewListPayload>;
  tasks(
    projectId: string,
    accessToken: string,
    status?: CodeTaskListStatus,
  ): Promise<CodeTaskListPayload>;
}

function normalizedBasePath(value: string): string {
  const normalized = value.trim().replace(/\/+$/, "");

  if (normalized.length === 0) {
    throw new Error("Code Changes API base path must not be empty");
  }

  return normalized;
}

function requiredAccessToken(value: string): string {
  const normalized = value.trim();

  if (normalized.length === 0) {
    throw new CodeChangesApiError("Authentication is required", {
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

function projectPath(basePath: string, projectId: string): string {
  return `${basePath}/projects/${encodeURIComponent(projectId)}`;
}

function alignmentPath(basePath: string, projectId: string): string {
  return `${projectPath(basePath, projectId)}/alignment`;
}

function changesPath(basePath: string, projectId: string, pending: boolean): string {
  const path = `${projectPath(basePath, projectId)}/code-changes`;

  if (!pending) {
    return path;
  }

  const query = new URLSearchParams({ pending: "true" });

  return `${path}?${query.toString()}`;
}

function reviewsPath(basePath: string, projectId: string, commit: string): string {
  return `${projectPath(basePath, projectId)}/code-changes/${encodeURIComponent(commit)}/reviews`;
}

function tasksPath(basePath: string, projectId: string, status: CodeTaskListStatus): string {
  const query = new URLSearchParams({ status });

  return `${projectPath(basePath, projectId)}/code-tasks?${query.toString()}`;
}

export function createCodeChangesApi(options: CodeChangesApiOptions = {}): CodeChangesApi {
  const basePath = normalizedBasePath(options.basePath ?? DEFAULT_API_BASE_PATH);
  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);

  async function read(
    path: string,
    accessToken: string,
    list: boolean,
  ): Promise<Record<string, unknown>> {
    const response = await fetchImpl(path, {
      method: "GET",
      credentials: "include",
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${requiredAccessToken(accessToken)}`,
      },
    });
    const payload = await responsePayload(response);

    if (!response.ok) {
      throw new CodeChangesApiError("The code change request failed", {
        status: response.status,
        code: errorCode(payload),
        payload,
      });
    }

    if (!isRecord(payload) || (list && !Array.isArray(payload.items))) {
      throw new CodeChangesApiError("The Code Changes API returned invalid JSON", {
        status: response.status,
        code: "INVALID_API_RESPONSE",
        payload,
      });
    }

    return payload;
  }

  return {
    async alignment(projectId, accessToken) {
      const payload = await read(alignmentPath(basePath, projectId), accessToken, false);

      return payload as unknown as AlignmentPayload;
    },

    async changes(projectId, accessToken, pending = false) {
      const payload = await read(changesPath(basePath, projectId, pending), accessToken, true);

      return payload as unknown as CodeChangeListPayload;
    },

    async reviews(projectId, commit, accessToken) {
      const payload = await read(reviewsPath(basePath, projectId, commit), accessToken, true);

      return payload as unknown as ChangeReviewListPayload;
    },

    async tasks(projectId, accessToken, status = "open") {
      const payload = await read(tasksPath(basePath, projectId, status), accessToken, true);

      return payload as unknown as CodeTaskListPayload;
    },
  };
}

export const codeChangesApi = createCodeChangesApi();
