import type {
  CreateFinalExportInput,
  DecideFinalApprovalInput,
  EvaluationAggregationPayload,
  FinalApprovalPayload,
  FinalExportDownloadPayload,
  FinalExportPayload,
  FinalReviewPayload,
  SubmitFinalReviewInput,
  SyntheticEvaluationRunPayload,
  SyntheticFindingPayload,
} from "../types/finalization";

const DEFAULT_API_BASE_PATH = "/api/v1";

export interface FinalizationApiOptions {
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

export interface FinalizationApi {
  evaluationRun(id: string, accessToken: string): Promise<SyntheticEvaluationRunPayload>;
  findings(id: string, accessToken: string): Promise<SyntheticFindingPayload[]>;
  aggregation(id: string, accessToken: string): Promise<EvaluationAggregationPayload>;
  finalReviews(projectId: string, accessToken: string): Promise<FinalReviewPayload[]>;
  submitFinalReview(
    reviewId: string,
    input: SubmitFinalReviewInput,
    accessToken: string,
  ): Promise<FinalApprovalPayload>;
  decideFinalApproval(
    gateId: string,
    input: DecideFinalApprovalInput,
    accessToken: string,
  ): Promise<FinalApprovalPayload>;
  createExport(
    projectId: string,
    input: CreateFinalExportInput,
    accessToken: string,
  ): Promise<FinalExportPayload>;
  exportBundle(exportId: string, accessToken: string): Promise<FinalExportPayload>;
  downloadExport(exportId: string, accessToken: string): Promise<FinalExportDownloadPayload>;
}

export class FinalizationApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly payload: unknown;

  constructor(message: string, options: { status: number; code: string | null; payload: unknown }) {
    super(message);
    this.name = "FinalizationApiError";
    this.status = options.status;
    this.code = options.code;
    this.payload = options.payload;
  }
}

function normalizedBasePath(value: string): string {
  const normalized = value.trim().replace(/\/+$/u, "");
  if (normalized.length === 0 || !normalized.startsWith("/") || normalized.startsWith("//")) {
    throw new Error("Finalization API base path must be an absolute application path");
  }
  return normalized;
}

function requiredAccessToken(value: string): string {
  const normalized = value.trim();
  if (normalized.length === 0) {
    throw new FinalizationApiError("Authentication is required", {
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

function filenameFromDisposition(value: string | null): string {
  const match = /filename="([^"\\/\r\n]+\.zip)"/u.exec(value ?? "");
  return match?.[1] ?? "orchestwin-final-export.zip";
}

export function createFinalizationApi(options: FinalizationApiOptions = {}): FinalizationApi {
  const basePath = normalizedBasePath(options.basePath ?? DEFAULT_API_BASE_PATH);
  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);

  async function request<T>(path: string, accessToken: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    headers.set("Authorization", `Bearer ${requiredAccessToken(accessToken)}`);
    if (init.body !== undefined) {
      headers.set("Content-Type", "application/json");
    }
    const response = await fetchImpl(path, { ...init, credentials: "include", headers });
    const payload = await responsePayload(response);
    if (!response.ok) {
      throw new FinalizationApiError("The finalization request failed", {
        status: response.status,
        code: errorCode(payload),
        payload,
      });
    }
    return payload as T;
  }

  return {
    async evaluationRun(id, accessToken) {
      const response = await request<SnapshotResponse<SyntheticEvaluationRunPayload>>(
        `${basePath}/evaluation-runs/${encodeURIComponent(id)}`,
        accessToken,
      );
      return response.snapshot;
    },

    async findings(id, accessToken) {
      const response = await request<SnapshotListResponse<SyntheticFindingPayload>>(
        `${basePath}/evaluation-runs/${encodeURIComponent(id)}/findings`,
        accessToken,
      );
      return response.items;
    },

    async aggregation(id, accessToken) {
      const response = await request<SnapshotResponse<EvaluationAggregationPayload>>(
        `${basePath}/evaluation-runs/${encodeURIComponent(id)}/aggregation`,
        accessToken,
      );
      return response.snapshot;
    },

    async finalReviews(projectId, accessToken) {
      const response = await request<SnapshotListResponse<FinalReviewPayload>>(
        `${basePath}/projects/${encodeURIComponent(projectId)}/final-reviews`,
        accessToken,
      );
      return response.items;
    },

    async submitFinalReview(reviewId, input, accessToken) {
      const response = await request<CommandResponse<FinalApprovalPayload>>(
        `${basePath}/final-reviews/${encodeURIComponent(reviewId)}/submit`,
        accessToken,
        { method: "POST", body: JSON.stringify(input) },
      );
      return response.snapshot;
    },

    async decideFinalApproval(gateId, input, accessToken) {
      const response = await request<CommandResponse<FinalApprovalPayload>>(
        `${basePath}/final-approval-requests/${encodeURIComponent(gateId)}/decisions`,
        accessToken,
        { method: "POST", body: JSON.stringify(input) },
      );
      return response.snapshot;
    },

    async createExport(projectId, input, accessToken) {
      const response = await request<CommandResponse<FinalExportPayload>>(
        `${basePath}/projects/${encodeURIComponent(projectId)}/exports`,
        accessToken,
        { method: "POST", body: JSON.stringify(input) },
      );
      return response.snapshot;
    },

    async exportBundle(exportId, accessToken) {
      const response = await request<SnapshotResponse<FinalExportPayload>>(
        `${basePath}/exports/${encodeURIComponent(exportId)}`,
        accessToken,
      );
      return response.snapshot;
    },

    async downloadExport(exportId, accessToken) {
      const headers = new Headers({
        Accept: "application/zip",
        Authorization: `Bearer ${requiredAccessToken(accessToken)}`,
      });
      const response = await fetchImpl(
        `${basePath}/exports/${encodeURIComponent(exportId)}/download`,
        {
          credentials: "include",
          headers,
        },
      );
      if (!response.ok) {
        const payload = await responsePayload(response);
        throw new FinalizationApiError("The final export download failed", {
          status: response.status,
          code: errorCode(payload),
          payload,
        });
      }
      return {
        blob: await response.blob(),
        filename: filenameFromDisposition(response.headers.get("Content-Disposition")),
        etag: response.headers.get("ETag"),
      };
    },
  };
}

export const finalizationApi = createFinalizationApi();
