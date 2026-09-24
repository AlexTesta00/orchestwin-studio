import { ApiRequestError } from "./requestError";
import type {
  WebImplementationLanguage,
  WebProjectLayout,
  WebRepairProposalPayload,
  WebSourceRevisionPayload,
} from "../types/webExecution";
import type { ExecutionTarget } from "../types/execution";

export type SourcePlatform = "web";
export type GeneratedSource = WebSourceRevisionPayload;
export type GeneratedRepair = WebRepairProposalPayload;

export interface SourceGenerationInput {
  target: ExecutionTarget;
  architecture_version_id: string;
  architecture_content_hash: string;
  frontend_language?: WebImplementationLanguage | null;
  backend_language?: WebImplementationLanguage | null;
  layout?: WebProjectLayout;
}

export interface RepairGenerationInput {
  base_revision_content_hash: string;
  failure_signature_digest: string;
}

export interface SourceGenerationApi {
  source(
    projectId: string,
    platform: SourcePlatform,
    input: SourceGenerationInput,
    token: string,
  ): Promise<GeneratedSource>;
  repair(
    projectId: string,
    platform: SourcePlatform,
    executionId: string,
    input: RepairGenerationInput,
    token: string,
  ): Promise<GeneratedRepair>;
}

export class SourceGenerationApiError extends ApiRequestError {}

export function createSourceGenerationApi(
  options: { basePath?: string; fetchImpl?: typeof fetch } = {},
): SourceGenerationApi {
  const base = (options.basePath ?? "/api/v1").trim().replace(/\/+$/, "");
  if (!base.startsWith("/") || base.startsWith("//") || base === "") {
    throw new Error("Source generation API requires an absolute application path");
  }
  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
  async function post<T>(path: string, input: unknown, token: string): Promise<T> {
    if (!token.trim())
      throw new SourceGenerationApiError("Authentication required", {
        status: 0,
        code: "ACCESS_TOKEN_REQUIRED",
        payload: null,
      });
    const response = await fetchImpl(base + path, {
      method: "POST",
      credentials: "include",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        Authorization: `Bearer ${token.trim()}`,
      },
      body: JSON.stringify(input),
    });
    const payload: unknown = await response.json().catch(() => null);
    const body = payload as { detail?: { code?: string }; snapshot?: T } | null;
    if (!response.ok || !body?.snapshot) {
      throw new SourceGenerationApiError("Source generation request failed", {
        status: response.status,
        code: typeof body?.detail?.code === "string" ? body.detail.code : null,
        payload,
      });
    }
    return body.snapshot;
  }
  return {
    source: (project, platform, input, token) =>
      post(`/projects/${encodeURIComponent(project)}/source-generations/${platform}`, input, token),
    repair: (project, platform, execution, input, token) =>
      post(
        `/projects/${encodeURIComponent(project)}/repair-generations/${platform}/${encodeURIComponent(execution)}`,
        input,
        token,
      ),
  };
}

export const sourceGenerationApi = createSourceGenerationApi();
