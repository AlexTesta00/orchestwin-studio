import { accessTokenOf, basePathOf, detailCode, isRecord } from "./http";
import { ApiRequestError } from "./requestError";
import type { WhyAnswer, WhyDocument } from "../types/why";

export class WhyApiError extends ApiRequestError {}

export interface WhyApi {
  explain(projectId: string, code: string, token: string): Promise<WhyAnswer>;
  document(projectId: string, token: string): Promise<WhyDocument>;
}

export function createWhyApi(
  options: { basePath?: string; fetchImpl?: typeof fetch } = {},
): WhyApi {
  const base = basePathOf(options.basePath ?? "/api/v1", "Why");
  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
  const path = (project: string) => `${base}/projects/${encodeURIComponent(project)}/artifacts/why`;

  async function request<T>(url: string, token: string, kind: string): Promise<T> {
    const accessToken = accessTokenOf(token, WhyApiError);
    const response = await fetchImpl(url, {
      method: "GET",
      credentials: "include",
      headers: { Accept: "application/json", Authorization: `Bearer ${accessToken}` },
    });
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (!response.ok) {
      const code = detailCode(payload);
      throw new WhyApiError("The Why request failed", { status: response.status, code, payload });
    }
    if (!isRecord(payload) || payload.kind !== kind || payload.schema_version !== 1) {
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
