import { sendGeneration } from "./generationJobs";
import { ApiRequestError } from "./requestError";

import type {
  AlignmentProposalListPayload,
  KnowledgeAlignmentRunListPayload,
  ProposalApplyPayload,
  ProposalApplyRequest,
  ProposalListStatus,
  ProposalSkipPayload,
  ProposalSkipRequest,
} from "../types/knowledgeAlignment";

const DEFAULT_API_BASE_PATH = "/api/v1";

type HttpMethod = "GET" | "POST";

interface RequestOptions {
  method: HttpMethod;
  accessToken: string;
  body?: ProposalApplyRequest | ProposalSkipRequest;
  generationProjectId?: string;
}

export interface KnowledgeAlignmentApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export class KnowledgeAlignmentApiError extends ApiRequestError {}

export interface KnowledgeAlignmentApi {
  proposals(
    projectId: string,
    status: ProposalListStatus,
    accessToken: string,
  ): Promise<AlignmentProposalListPayload>;
  apply(
    projectId: string,
    code: string,
    text: string | null,
    accessToken: string,
  ): Promise<ProposalApplyPayload>;
  skip(
    projectId: string,
    code: string,
    reason: string | null,
    accessToken: string,
  ): Promise<ProposalSkipPayload>;
  runs(projectId: string, accessToken: string): Promise<KnowledgeAlignmentRunListPayload>;
}

function normalizedBasePath(value: string): string {
  const normalized = value.trim().replace(/\/+$/, "");

  if (normalized.length === 0) {
    throw new Error("Knowledge Alignment API base path must not be empty");
  }

  return normalized;
}

function requiredAccessToken(value: string): string {
  const normalized = value.trim();

  if (normalized.length === 0) {
    throw new KnowledgeAlignmentApiError("Authentication is required", {
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

  const reason = payload.detail.proposal_issue;

  if (typeof reason === "string" && reason.length > 0) {
    return reason;
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

function invalidResponse(status: number, payload: unknown): KnowledgeAlignmentApiError {
  return new KnowledgeAlignmentApiError("The Knowledge Alignment API returned invalid JSON", {
    status,
    code: "INVALID_API_RESPONSE",
    payload,
  });
}

function alignmentPath(basePath: string, projectId: string): string {
  return `${basePath}/projects/${encodeURIComponent(projectId)}/alignment`;
}

function proposalsPath(basePath: string, projectId: string, status: ProposalListStatus): string {
  const query = new URLSearchParams({ status });

  return `${alignmentPath(basePath, projectId)}/proposals?${query.toString()}`;
}

function decisionPath(
  basePath: string,
  projectId: string,
  code: string,
  decision: "apply" | "skip",
): string {
  return `${alignmentPath(basePath, projectId)}/proposals/${encodeURIComponent(code)}/${decision}`;
}

function runsPath(basePath: string, projectId: string): string {
  return `${alignmentPath(basePath, projectId)}/runs`;
}

export function createKnowledgeAlignmentApi(
  options: KnowledgeAlignmentApiOptions = {},
): KnowledgeAlignmentApi {
  const basePath = normalizedBasePath(options.basePath ?? DEFAULT_API_BASE_PATH);
  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);

  async function request(
    path: string,
    optionsValue: RequestOptions,
  ): Promise<Record<string, unknown>> {
    const headers: Record<string, string> = {
      Accept: "application/json",
      Authorization: `Bearer ${requiredAccessToken(optionsValue.accessToken)}`,
    };
    const init: RequestInit = {
      method: optionsValue.method,
      headers,
      credentials: "include",
    };

    if (optionsValue.body !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(optionsValue.body);
    }

    const response =
      optionsValue.generationProjectId === undefined
        ? await fetchImpl(path, init)
        : await sendGeneration(path, init, {
            fetchImpl,
            basePath,
            projectId: optionsValue.generationProjectId,
          });
    const payload = await responsePayload(response);

    if (!response.ok) {
      const code = errorCode(payload);

      throw new KnowledgeAlignmentApiError(
        code ?? `Knowledge Alignment API request failed with status ${response.status}`,
        { status: response.status, code, payload },
      );
    }

    if (!isRecord(payload)) {
      throw invalidResponse(response.status, payload);
    }

    return payload;
  }

  async function list(path: string, accessToken: string): Promise<Record<string, unknown>> {
    const payload = await request(path, { method: "GET", accessToken });

    if (!Array.isArray(payload.items)) {
      throw invalidResponse(200, payload);
    }

    return payload;
  }

  async function decide(
    path: string,
    accessToken: string,
    body: ProposalApplyRequest | ProposalSkipRequest,
    generationProjectId?: string,
  ): Promise<Record<string, unknown>> {
    const payload = await request(path, {
      method: "POST",
      accessToken,
      body,
      ...(generationProjectId === undefined ? {} : { generationProjectId }),
    });

    if (!isRecord(payload.proposal)) {
      throw invalidResponse(200, payload);
    }

    return payload;
  }

  return {
    async proposals(projectId, status, accessToken) {
      const payload = await list(proposalsPath(basePath, projectId, status), accessToken);

      return payload as unknown as AlignmentProposalListPayload;
    },

    async apply(projectId, code, text, accessToken) {
      const payload = await decide(
        decisionPath(basePath, projectId, code, "apply"),
        accessToken,
        { text },
        projectId,
      );

      return payload as unknown as ProposalApplyPayload;
    },

    async skip(projectId, code, reason, accessToken) {
      const payload = await decide(decisionPath(basePath, projectId, code, "skip"), accessToken, {
        reason,
      });

      return payload as unknown as ProposalSkipPayload;
    },

    async runs(projectId, accessToken) {
      const payload = await list(runsPath(basePath, projectId), accessToken);

      return payload as unknown as KnowledgeAlignmentRunListPayload;
    },
  };
}

export const knowledgeAlignmentApi = createKnowledgeAlignmentApi();
