import type {
  ApplyWebRepairProposalInput,
  CreateWebRepairProposalInput,
  CreateWebSourceRevisionInput,
  StartWebExecutionInput,
  WebBrowserEvidencePayload,
  WebCommandResponse,
  WebExecutionAttemptPayload,
  WebExecutionReportPayload,
  WebRepairProposalPayload,
  WebSnapshotListResponse,
  WebSnapshotResponse,
  WebSourceRevisionPayload,
} from "../types/webExecution";

const DEFAULT_API_BASE_PATH = "/api/v1";

export interface WebExecutionApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export interface WebExecutionApi {
  createSourceRevision(
    projectId: string,
    input: CreateWebSourceRevisionInput,
    accessToken: string,
  ): Promise<WebSourceRevisionPayload>;
  sourceRevisions(projectId: string, accessToken: string): Promise<WebSourceRevisionPayload[]>;
  sourceRevision(
    projectId: string,
    revisionId: string,
    accessToken: string,
  ): Promise<WebSourceRevisionPayload>;
  startExecution(
    projectId: string,
    input: StartWebExecutionInput,
    accessToken: string,
  ): Promise<WebExecutionAttemptPayload>;
  executions(projectId: string, accessToken: string): Promise<WebExecutionAttemptPayload[]>;
  execution(executionId: string, accessToken: string): Promise<WebExecutionAttemptPayload>;
  executionReport(executionId: string, accessToken: string): Promise<WebExecutionReportPayload>;
  browserEvidence(executionId: string, accessToken: string): Promise<WebBrowserEvidencePayload>;
  repairProposals(executionId: string, accessToken: string): Promise<WebRepairProposalPayload[]>;
  createRepairProposal(
    executionId: string,
    input: CreateWebRepairProposalInput,
    accessToken: string,
  ): Promise<WebRepairProposalPayload>;
  applyRepairProposal(
    executionId: string,
    proposalId: string,
    input: ApplyWebRepairProposalInput,
    accessToken: string,
  ): Promise<WebSourceRevisionPayload>;
}

export class WebExecutionApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly payload: unknown;

  constructor(message: string, options: { status: number; code: string | null; payload: unknown }) {
    super(message);
    this.name = "WebExecutionApiError";
    this.status = options.status;
    this.code = options.code;
    this.payload = options.payload;
  }
}

function normalizedBasePath(value: string): string {
  const normalized = value.trim().replace(/\/+$/, "");
  if (normalized.length === 0 || !normalized.startsWith("/") || normalized.startsWith("//")) {
    throw new Error("Web execution API base path must be an absolute application path");
  }
  return normalized;
}

function requiredAccessToken(value: string): string {
  const normalized = value.trim();
  if (normalized.length === 0) {
    throw new WebExecutionApiError("Authentication is required", {
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

export function createWebExecutionApi(options: WebExecutionApiOptions = {}): WebExecutionApi {
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
      throw new WebExecutionApiError("The Web execution request failed", {
        status: response.status,
        code: errorCode(payload),
        payload,
      });
    }
    return payload as T;
  }

  return {
    async createSourceRevision(projectId, input, accessToken) {
      const response = await request<WebCommandResponse<WebSourceRevisionPayload>>(
        `${projectPath(basePath, projectId)}/web-source-revisions`,
        accessToken,
        { method: "POST", body: JSON.stringify(input) },
      );
      return response.snapshot;
    },

    async sourceRevisions(projectId, accessToken) {
      const response = await request<WebSnapshotListResponse<WebSourceRevisionPayload>>(
        `${projectPath(basePath, projectId)}/web-source-revisions`,
        accessToken,
      );
      return response.items;
    },

    async sourceRevision(projectId, revisionId, accessToken) {
      const response = await request<WebSnapshotResponse<WebSourceRevisionPayload>>(
        `${projectPath(basePath, projectId)}/web-source-revisions/${encodeURIComponent(revisionId)}`,
        accessToken,
      );
      return response.snapshot;
    },

    async startExecution(projectId, input, accessToken) {
      const response = await request<WebCommandResponse<WebExecutionAttemptPayload>>(
        `${projectPath(basePath, projectId)}/web-executions`,
        accessToken,
        { method: "POST", body: JSON.stringify(input) },
      );
      return response.snapshot;
    },

    async executions(projectId, accessToken) {
      const response = await request<WebSnapshotListResponse<WebExecutionAttemptPayload>>(
        `${projectPath(basePath, projectId)}/web-executions`,
        accessToken,
      );
      return response.items;
    },

    async execution(executionId, accessToken) {
      const response = await request<WebSnapshotResponse<WebExecutionAttemptPayload>>(
        `${basePath}/web-executions/${encodeURIComponent(executionId)}`,
        accessToken,
      );
      return response.snapshot;
    },

    async executionReport(executionId, accessToken) {
      const response = await request<WebSnapshotResponse<WebExecutionReportPayload>>(
        `${basePath}/web-executions/${encodeURIComponent(executionId)}/report`,
        accessToken,
      );
      return response.snapshot;
    },

    async browserEvidence(executionId, accessToken) {
      const response = await request<WebSnapshotResponse<WebBrowserEvidencePayload>>(
        `${basePath}/web-executions/${encodeURIComponent(executionId)}/browser-evidence`,
        accessToken,
      );
      return response.snapshot;
    },

    async repairProposals(executionId, accessToken) {
      const response = await request<WebSnapshotListResponse<WebRepairProposalPayload>>(
        `${basePath}/web-executions/${encodeURIComponent(executionId)}/repair-proposals`,
        accessToken,
      );
      return response.items;
    },

    async createRepairProposal(executionId, input, accessToken) {
      const response = await request<WebCommandResponse<WebRepairProposalPayload>>(
        `${basePath}/web-executions/${encodeURIComponent(executionId)}/repair-proposals`,
        accessToken,
        { method: "POST", body: JSON.stringify(input) },
      );
      return response.snapshot;
    },

    async applyRepairProposal(executionId, proposalId, input, accessToken) {
      const response = await request<WebCommandResponse<WebSourceRevisionPayload>>(
        `${basePath}/web-executions/${encodeURIComponent(executionId)}/repair-proposals/${encodeURIComponent(proposalId)}/apply`,
        accessToken,
        { method: "POST", body: JSON.stringify(input) },
      );
      return response.snapshot;
    },
  };
}

export const webExecutionApi = createWebExecutionApi();
