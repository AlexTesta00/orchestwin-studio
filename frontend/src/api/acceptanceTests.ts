import { accessTokenOf, basePathOf, detailCode, isRecord, responseBody } from "./http";
import { ApiRequestError } from "./requestError";

import type { AcceptanceTestsOverviewPayload } from "../types/acceptanceTests";

const DEFAULT_API_BASE_PATH = "/api/v1";

export interface AcceptanceTestsApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export class AcceptanceTestsApiError extends ApiRequestError {}

export interface AcceptanceTestsApi {
  overview(projectId: string, accessToken: string): Promise<AcceptanceTestsOverviewPayload>;
}

function isLatestReview(value: unknown): boolean {
  return (
    value === undefined ||
    value === null ||
    (isRecord(value) &&
      typeof value.run_id === "string" &&
      typeof value.finished_at === "string" &&
      Array.isArray(value.critiques))
  );
}

function isOverview(payload: unknown): payload is Record<string, unknown> {
  return (
    isRecord(payload) &&
    (payload.latest_run === null || isRecord(payload.latest_run)) &&
    (payload.latest_run_stale === undefined || typeof payload.latest_run_stale === "boolean") &&
    isLatestReview(payload.latest_review)
  );
}

function overviewPath(basePath: string, projectId: string): string {
  return `${basePath}/projects/${encodeURIComponent(projectId)}/acceptance-tests`;
}

export function createAcceptanceTestsApi(
  options: AcceptanceTestsApiOptions = {},
): AcceptanceTestsApi {
  const basePath = basePathOf(options.basePath ?? DEFAULT_API_BASE_PATH, "Acceptance Tests");
  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);

  return {
    async overview(projectId, accessToken) {
      const response = await fetchImpl(overviewPath(basePath, projectId), {
        method: "GET",
        credentials: "include",
        headers: {
          Accept: "application/json",
          Authorization: `Bearer ${accessTokenOf(accessToken, AcceptanceTestsApiError)}`,
        },
      });
      const payload = await responseBody(response);

      if (!response.ok) {
        throw new AcceptanceTestsApiError("The acceptance tests request failed", {
          status: response.status,
          code: detailCode(payload),
          payload,
        });
      }

      if (!isOverview(payload)) {
        throw new AcceptanceTestsApiError("The Acceptance Tests API returned invalid JSON", {
          status: response.status,
          code: "INVALID_API_RESPONSE",
          payload,
        });
      }

      return payload as unknown as AcceptanceTestsOverviewPayload;
    },
  };
}

export const acceptanceTestsApi = createAcceptanceTestsApi();
