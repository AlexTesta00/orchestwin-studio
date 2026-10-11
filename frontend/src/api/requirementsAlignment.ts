import { accessTokenOf, basePathOf, detailCode, isRecord, responseBody } from "./http";
import { ApiRequestError } from "./requestError";

import type {
  RequirementsAlignmentPayload,
  RequirementsRealignmentPayload,
} from "../types/requirementsAlignment";

const DEFAULT_API_BASE_PATH = "/api/v1";

export interface RequirementsAlignmentApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export class RequirementsAlignmentApiError extends ApiRequestError {}

export interface RequirementsAlignmentApi {
  status(projectId: string, accessToken: string): Promise<RequirementsAlignmentPayload>;
  realign(projectId: string, accessToken: string): Promise<RequirementsRealignmentPayload>;
}

function alignmentPath(basePath: string, projectId: string): string {
  return `${basePath}/projects/${encodeURIComponent(projectId)}/requirements/twin-alignment`;
}

export function createRequirementsAlignmentApi(
  options: RequirementsAlignmentApiOptions = {},
): RequirementsAlignmentApi {
  const basePath = basePathOf(options.basePath ?? DEFAULT_API_BASE_PATH, "Requirements Alignment");
  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);

  async function request<T>(
    projectId: string,
    method: "GET" | "POST",
    accessToken: string,
  ): Promise<T> {
    const response = await fetchImpl(alignmentPath(basePath, projectId), {
      method,
      credentials: "include",
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${accessTokenOf(accessToken, RequirementsAlignmentApiError)}`,
      },
    });
    const payload = await responseBody(response);

    if (!response.ok) {
      throw new RequirementsAlignmentApiError("The requirements alignment request failed", {
        status: response.status,
        code: detailCode(payload),
        payload,
      });
    }

    if (!isRecord(payload)) {
      throw new RequirementsAlignmentApiError(
        "The Requirements Alignment API returned invalid JSON",
        {
          status: response.status,
          code: "INVALID_API_RESPONSE",
          payload,
        },
      );
    }

    return payload as unknown as T;
  }

  return {
    status(projectId, accessToken) {
      return request<RequirementsAlignmentPayload>(projectId, "GET", accessToken);
    },

    realign(projectId, accessToken) {
      return request<RequirementsRealignmentPayload>(projectId, "POST", accessToken);
    },
  };
}

export const requirementsAlignmentApi = createRequirementsAlignmentApi();
