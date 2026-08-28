import type {
  ApplyJvmRepairProposalInput,
  CreateJvmRepairProposalInput,
  CreateJvmSourceRevisionInput,
  JvmExecutionAttemptPayload,
  JvmExecutionReportPayload,
  JvmProfilePayload,
  JvmRepairProposalPayload,
  JvmSourceRevisionPayload,
  StartJvmExecutionInput,
} from "../types/jvmExecution";

const DEFAULT_API_BASE_PATH = "/api/v1";

export interface JvmExecutionApiOptions {
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

export interface JvmExecutionApi {
  profiles(accessToken: string): Promise<JvmProfilePayload[]>;
  createSourceRevision(
    projectId: string,
    input: CreateJvmSourceRevisionInput,
    accessToken: string,
  ): Promise<JvmSourceRevisionPayload>;
  sourceRevisions(projectId: string, accessToken: string): Promise<JvmSourceRevisionPayload[]>;
  sourceRevision(
    projectId: string,
    revisionId: string,
    accessToken: string,
  ): Promise<JvmSourceRevisionPayload>;
  startExecution(
    projectId: string,
    input: StartJvmExecutionInput,
    accessToken: string,
  ): Promise<JvmExecutionAttemptPayload>;
  executions(projectId: string, accessToken: string): Promise<JvmExecutionAttemptPayload[]>;
  execution(executionId: string, accessToken: string): Promise<JvmExecutionAttemptPayload>;
  executionReport(executionId: string, accessToken: string): Promise<JvmExecutionReportPayload>;
  repairProposals(executionId: string, accessToken: string): Promise<JvmRepairProposalPayload[]>;
  createRepairProposal(
    executionId: string,
    input: CreateJvmRepairProposalInput,
    accessToken: string,
  ): Promise<JvmRepairProposalPayload>;
  applyRepairProposal(
    executionId: string,
    proposalId: string,
    input: ApplyJvmRepairProposalInput,
    accessToken: string,
  ): Promise<JvmSourceRevisionPayload>;
}

export class JvmExecutionApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly payload: unknown;

  constructor(message: string, options: { status: number; code: string | null; payload: unknown }) {
    super(message);
    this.name = "JvmExecutionApiError";
    this.status = options.status;
    this.code = options.code;
    this.payload = options.payload;
  }
}

function normalizedBasePath(value: string): string {
  const normalized = value.trim().replace(/\/+$/, "");
  if (normalized.length === 0 || !normalized.startsWith("/") || normalized.startsWith("//")) {
    throw new Error("JVM execution API base path must be an absolute application path");
  }
  return normalized;
}

function requiredAccessToken(value: string): string {
  const normalized = value.trim();
  if (normalized.length === 0) {
    throw new JvmExecutionApiError("Authentication is required", {
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

function projectPath(basePath: string, projectId: string): string {
  return `${basePath}/projects/${encodeURIComponent(projectId)}`;
}

export function createJvmExecutionApi(options: JvmExecutionApiOptions = {}): JvmExecutionApi {
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
      throw new JvmExecutionApiError("The JVM execution request failed", {
        status: response.status,
        code: errorCode(payload),
        payload,
      });
    }
    return payload as T;
  }

  return {
    async profiles(accessToken) {
      const response = await request<SnapshotListResponse<JvmProfilePayload>>(
        `${basePath}/jvm-execution-profiles`,
        accessToken,
      );
      return response.items;
    },

    async createSourceRevision(projectId, input, accessToken) {
      const response = await request<CommandResponse<JvmSourceRevisionPayload>>(
        `${projectPath(basePath, projectId)}/jvm-source-revisions`,
        accessToken,
        { method: "POST", body: JSON.stringify(input) },
      );
      return response.snapshot;
    },

    async sourceRevisions(projectId, accessToken) {
      const response = await request<SnapshotListResponse<JvmSourceRevisionPayload>>(
        `${projectPath(basePath, projectId)}/jvm-source-revisions`,
        accessToken,
      );
      return response.items;
    },

    async sourceRevision(projectId, revisionId, accessToken) {
      const response = await request<SnapshotResponse<JvmSourceRevisionPayload>>(
        `${projectPath(basePath, projectId)}/jvm-source-revisions/${encodeURIComponent(revisionId)}`,
        accessToken,
      );
      return response.snapshot;
    },

    async startExecution(projectId, input, accessToken) {
      const response = await request<CommandResponse<JvmExecutionAttemptPayload>>(
        `${projectPath(basePath, projectId)}/jvm-executions`,
        accessToken,
        { method: "POST", body: JSON.stringify(input) },
      );
      return response.snapshot;
    },

    async executions(projectId, accessToken) {
      const response = await request<SnapshotListResponse<JvmExecutionAttemptPayload>>(
        `${projectPath(basePath, projectId)}/jvm-executions`,
        accessToken,
      );
      return response.items;
    },

    async execution(executionId, accessToken) {
      const response = await request<SnapshotResponse<JvmExecutionAttemptPayload>>(
        `${basePath}/jvm-executions/${encodeURIComponent(executionId)}`,
        accessToken,
      );
      return response.snapshot;
    },

    async executionReport(executionId, accessToken) {
      const response = await request<SnapshotResponse<JvmExecutionReportPayload>>(
        `${basePath}/jvm-executions/${encodeURIComponent(executionId)}/report`,
        accessToken,
      );
      return response.snapshot;
    },

    async repairProposals(executionId, accessToken) {
      const response = await request<SnapshotListResponse<JvmRepairProposalPayload>>(
        `${basePath}/jvm-executions/${encodeURIComponent(executionId)}/repair-proposals`,
        accessToken,
      );
      return response.items;
    },

    async createRepairProposal(executionId, input, accessToken) {
      const response = await request<CommandResponse<JvmRepairProposalPayload>>(
        `${basePath}/jvm-executions/${encodeURIComponent(executionId)}/repair-proposals`,
        accessToken,
        { method: "POST", body: JSON.stringify(input) },
      );
      return response.snapshot;
    },

    async applyRepairProposal(executionId, proposalId, input, accessToken) {
      const response = await request<CommandResponse<JvmSourceRevisionPayload>>(
        `${basePath}/jvm-executions/${encodeURIComponent(executionId)}/repair-proposals/${encodeURIComponent(proposalId)}/apply`,
        accessToken,
        { method: "POST", body: JSON.stringify(input) },
      );
      return response.snapshot;
    },
  };
}

export const jvmExecutionApi = createJvmExecutionApi();
