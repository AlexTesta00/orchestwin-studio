import { ApiRequestError } from "./requestError";
import type { WhyAnswer, WhyDocument } from "../types/why";

export class WhyApiError extends ApiRequestError {}

export interface WhyApi {
  explain(projectId: string, code: string, token: string): Promise<WhyAnswer>;
  document(projectId: string, token: string): Promise<WhyDocument>;
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function createWhyApi(
  options: { basePath?: string; fetchImpl?: typeof fetch } = {},
): WhyApi {
  const base = (options.basePath ?? "/api/v1").trim().replace(/\/+$/, "");
  if (base.length === 0) throw new Error("Why API base path must not be empty");
  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
  const path = (project: string) => `${base}/projects/${encodeURIComponent(project)}/artifacts/why`;

  async function request<T>(url: string, token: string, kind: string): Promise<T> {
    if (token.trim().length === 0) {
      throw new WhyApiError("Authentication is required", {
        status: 0,
        code: "ACCESS_TOKEN_REQUIRED",
        payload: null,
      });
    }
    const response = await fetchImpl(url, {
      method: "GET",
      credentials: "include",
      headers: { Accept: "application/json", Authorization: `Bearer ${token.trim()}` },
    });
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (!response.ok) {
      const code =
        record(payload) && record(payload.detail) && typeof payload.detail.code === "string"
          ? payload.detail.code
          : null;
      throw new WhyApiError("The Why request failed", { status: response.status, code, payload });
    }
    if (!record(payload) || payload.kind !== kind || payload.schema_version !== 1) {
      throw new WhyApiError("Why API returned an invalid response", {
        status: response.status,
        code: "INVALID_API_RESPONSE",
        payload: null,
      });
    }
    return payload as T;
  }

  return {
    explain: (project, code, token) =>
      request(`${path(project)}?code=${encodeURIComponent(code)}`, token, "orchestwin.why-answer"),
    document: (project, token) => request(`${path(project)}/document`, token, "orchestwin.why"),
  };
}

export const whyApi = createWhyApi();
