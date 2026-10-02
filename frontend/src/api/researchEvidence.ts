import { sendGeneration } from "./generationJobs";
import { ApiRequestError } from "./requestError";
import type {
  EvidenceMutationPayload,
  EvidenceUpdateDecisionInput,
  EvidenceUpdateResultPayload,
  ResearchEvidenceInput,
  ResearchEvidenceListPayload,
  ResearchEvidencePayload,
} from "../types/researchEvidence";

export class ResearchEvidenceApiError extends ApiRequestError {}

export interface ResearchEvidenceApi {
  list(projectId: string, token: string): Promise<ResearchEvidenceListPayload>;
  show(
    projectId: string,
    id: string,
    version: number,
    text: boolean,
    token: string,
  ): Promise<ResearchEvidencePayload>;
  add(
    projectId: string,
    input: ResearchEvidenceInput,
    token: string,
  ): Promise<EvidenceMutationPayload>;
  revise(
    projectId: string,
    id: string,
    input: ResearchEvidenceInput,
    token: string,
  ): Promise<EvidenceMutationPayload>;
  retire(
    projectId: string,
    id: string,
    reason: string,
    token: string,
  ): Promise<EvidenceMutationPayload>;
  deleteText(projectId: string, id: string, token: string): Promise<EvidenceMutationPayload>;
  propose(
    projectId: string,
    twinId: string,
    evidence: ResearchEvidencePayload,
    locale: string,
    token: string,
  ): Promise<EvidenceUpdateResultPayload>;
  decide(
    projectId: string,
    updateId: string,
    input: EvidenceUpdateDecisionInput,
    token: string,
  ): Promise<EvidenceUpdateResultPayload>;
}

export function createResearchEvidenceApi(
  options: { basePath?: string; fetchImpl?: typeof fetch } = {},
): ResearchEvidenceApi {
  const basePath = (options.basePath ?? "/api/v1").trim().replace(/\/+$/, "");
  if (basePath.length === 0) throw new Error("Evidence API base path must not be empty");
  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
  const projectPath = (id: string) => `${basePath}/projects/${encodeURIComponent(id)}`;
  const evidencePath = (project: string, id: string) =>
    `${projectPath(project)}/evidence/${encodeURIComponent(id)}`;

  async function request<T>(
    path: string,
    token: string,
    method = "GET",
    body?: unknown,
    generationProject?: string,
  ): Promise<T> {
    if (token.trim().length === 0) {
      throw new ResearchEvidenceApiError("Authentication is required", {
        status: 0,
        code: "ACCESS_TOKEN_REQUIRED",
        payload: null,
      });
    }
    const init: RequestInit = {
      method,
      credentials: "include",
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${token.trim()}`,
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    };
    const response =
      generationProject === undefined
        ? await fetchImpl(path, init)
        : await sendGeneration(path, init, { fetchImpl, basePath, projectId: generationProject });
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      throw new ResearchEvidenceApiError("Evidence API returned invalid JSON", {
        status: response.status,
        code: "INVALID_API_RESPONSE",
        payload: null,
      });
    }
    if (!response.ok) {
      const detail =
        typeof payload === "object" && payload !== null && "detail" in payload
          ? payload.detail
          : null;
      const code =
        typeof detail === "object" &&
        detail !== null &&
        "code" in detail &&
        typeof detail.code === "string"
          ? detail.code
          : null;
      throw new ResearchEvidenceApiError("The evidence request failed", {
        status: response.status,
        code,
        payload: null,
      });
    }
    return payload as T;
  }

  return {
    list: (project, token) => request(`${projectPath(project)}/evidence?all=true`, token),
    show: (project, id, version, text, token) =>
      request(`${evidencePath(project, id)}?version=${version}&text=${text}`, token),
    add: (project, input, token) =>
      request(`${projectPath(project)}/evidence`, token, "POST", input),
    revise: (project, id, input, token) =>
      request(`${evidencePath(project, id)}/versions`, token, "POST", input),
    retire: (project, id, reason, token) =>
      request(`${evidencePath(project, id)}/retire`, token, "POST", { reason }),
    deleteText: (project, id, token) =>
      request(`${evidencePath(project, id)}/text`, token, "DELETE", { acknowledged: true }),
    propose: (project, twin, evidence, locale, token) =>
      request(
        `${projectPath(project)}/user-twins/${encodeURIComponent(twin)}/updates`,
        token,
        "POST",
        { locale, evidence_id: evidence.id, evidence_version: evidence.version },
        project,
      ),
    decide: (project, update, input, token) =>
      request(
        `${projectPath(project)}/twin-updates/${encodeURIComponent(update)}/decision`,
        token,
        "POST",
        input,
      ),
  };
}

export const researchEvidenceApi = createResearchEvidenceApi();
