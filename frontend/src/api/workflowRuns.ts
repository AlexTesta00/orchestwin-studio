import type {
  CreateWorkflowRunInput,
  WorkflowCheckpointPayload,
  WorkflowEventPayload,
  WorkflowLifecycleAction,
  WorkflowLifecycleInput,
  WorkflowRunPayload,
} from "../types/workflowRuns";

const DEFAULT_API_BASE_PATH = "/api/v1";

export interface WorkflowRunsApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

interface SnapshotResponse<T> {
  snapshot: T;
}

interface SnapshotListResponse<T> {
  items: T[];
}

interface CommandResponse<T> {
  status: string;
  snapshot: T;
  message: string;
}

export interface WorkflowRunsApi {
  createRun(
    projectId: string,
    input: CreateWorkflowRunInput,
    accessToken: string,
  ): Promise<WorkflowRunPayload>;
  runs(projectId: string, accessToken: string): Promise<WorkflowRunPayload[]>;
  run(runId: string, accessToken: string): Promise<WorkflowRunPayload>;
  checkpoints(runId: string, accessToken: string): Promise<WorkflowCheckpointPayload[]>;
  applyLifecycle(
    runId: string,
    action: WorkflowLifecycleAction,
    input: WorkflowLifecycleInput,
    accessToken: string,
  ): Promise<WorkflowRunPayload>;
  replayEvents(
    runId: string,
    afterSequence: number,
    accessToken: string,
  ): Promise<WorkflowEventPayload[]>;
}

export class WorkflowRunsApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly payload: unknown;

  constructor(message: string, options: { status: number; code: string | null; payload: unknown }) {
    super(message);
    this.name = "WorkflowRunsApiError";
    this.status = options.status;
    this.code = options.code;
    this.payload = options.payload;
  }
}

function normalizedBasePath(value: string): string {
  const normalized = value.trim().replace(/\/+$/, "");
  if (normalized.length === 0 || !normalized.startsWith("/") || normalized.startsWith("//")) {
    throw new Error("Workflow API base path must be an absolute application path");
  }
  return normalized;
}

function requiredAccessToken(value: string): string {
  const normalized = value.trim();
  if (normalized.length === 0) {
    throw new WorkflowRunsApiError("Authentication is required", {
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
  if (typeof payload.detail.code === "string") {
    return payload.detail.code;
  }
  return typeof payload.detail.status === "string" ? payload.detail.status : null;
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

function parseSseEvents(text: string): WorkflowEventPayload[] {
  return text
    .split(/\r?\n\r?\n/u)
    .map((block) => block.trim())
    .filter((block) => block.length > 0)
    .map((block) => {
      const dataLines = block
        .split(/\r?\n/u)
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart());
      if (dataLines.length === 0) {
        throw new WorkflowRunsApiError("Workflow event stream contained no data", {
          status: 0,
          code: "WORKFLOW_EVENT_STREAM_INVALID",
          payload: block,
        });
      }
      const parsed: unknown = JSON.parse(dataLines.join("\n"));
      if (!isRecord(parsed) || typeof parsed.sequence_number !== "number") {
        throw new WorkflowRunsApiError("Workflow event stream contained an invalid event", {
          status: 0,
          code: "WORKFLOW_EVENT_STREAM_INVALID",
          payload: parsed,
        });
      }
      return parsed as unknown as WorkflowEventPayload;
    });
}

export function createWorkflowRunsApi(options: WorkflowRunsApiOptions = {}): WorkflowRunsApi {
  const basePath = normalizedBasePath(options.basePath ?? DEFAULT_API_BASE_PATH);
  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);

  async function request<T>(path: string, accessToken: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    headers.set("Authorization", `Bearer ${requiredAccessToken(accessToken)}`);
    if (init.body !== undefined) {
      headers.set("Content-Type", "application/json");
    }
    const response = await fetchImpl(path, {
      ...init,
      credentials: "include",
      headers,
    });
    const payload = await responsePayload(response);
    if (!response.ok) {
      throw new WorkflowRunsApiError("The workflow request failed", {
        status: response.status,
        code: errorCode(payload),
        payload,
      });
    }
    return payload as T;
  }

  return {
    async createRun(projectId, input, accessToken) {
      const response = await request<CommandResponse<WorkflowRunPayload>>(
        `${basePath}/projects/${encodeURIComponent(projectId)}/runs`,
        accessToken,
        { method: "POST", body: JSON.stringify(input) },
      );
      return response.snapshot;
    },

    async runs(projectId, accessToken) {
      const response = await request<SnapshotListResponse<WorkflowRunPayload>>(
        `${basePath}/projects/${encodeURIComponent(projectId)}/runs`,
        accessToken,
      );
      return response.items;
    },

    async run(runId, accessToken) {
      const response = await request<SnapshotResponse<WorkflowRunPayload>>(
        `${basePath}/runs/${encodeURIComponent(runId)}`,
        accessToken,
      );
      return response.snapshot;
    },

    async checkpoints(runId, accessToken) {
      const response = await request<SnapshotListResponse<WorkflowCheckpointPayload>>(
        `${basePath}/runs/${encodeURIComponent(runId)}/checkpoints`,
        accessToken,
      );
      return response.items;
    },

    async applyLifecycle(runId, action, input, accessToken) {
      const response = await request<CommandResponse<WorkflowRunPayload>>(
        `${basePath}/runs/${encodeURIComponent(runId)}/${action}`,
        accessToken,
        { method: "POST", body: JSON.stringify(input) },
      );
      return response.snapshot;
    },

    async replayEvents(runId, afterSequence, accessToken) {
      if (!Number.isSafeInteger(afterSequence) || afterSequence < 0) {
        throw new WorkflowRunsApiError("The workflow event cursor is invalid", {
          status: 0,
          code: "WORKFLOW_EVENT_CURSOR_INVALID",
          payload: afterSequence,
        });
      }
      const headers = new Headers();
      headers.set("Accept", "text/event-stream");
      headers.set("Authorization", `Bearer ${requiredAccessToken(accessToken)}`);
      const response = await fetchImpl(
        `${basePath}/runs/${encodeURIComponent(runId)}/events?after_sequence=${afterSequence}`,
        { credentials: "include", headers },
      );
      const text = await response.text();
      if (!response.ok) {
        let payload: unknown = text;
        try {
          payload = JSON.parse(text) as unknown;
        } catch {
          // Preserve non-JSON error payloads for inspection.
        }
        throw new WorkflowRunsApiError("The workflow event replay failed", {
          status: response.status,
          code: errorCode(payload),
          payload,
        });
      }
      return parseSseEvents(text);
    },
  };
}

export const workflowRunsApi = createWorkflowRunsApi();
