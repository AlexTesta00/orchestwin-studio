import { accessTokenOf, basePathOf, detailCode, responseBody } from "./http";
import { ApiRequestError } from "./requestError";

import type { GenerationBudgetPayload, ModelUsagePayload } from "../types/designMockups";

const DEFAULT_API_BASE_PATH = "/api/v1";

export interface ModelUsageApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export class ModelUsageApiError extends ApiRequestError {}

export interface ModelUsageApi {
  usage(projectId: string, accessToken: string): Promise<ModelUsagePayload>;
  budget(accessToken: string): Promise<GenerationBudgetPayload>;
}

function usagePath(basePath: string, projectId: string): string {
  return `${basePath}/projects/${encodeURIComponent(projectId)}/model-usage`;
}

export function createModelUsageApi(options: ModelUsageApiOptions = {}): ModelUsageApi {
  const basePath = basePathOf(options.basePath ?? DEFAULT_API_BASE_PATH, "Model Usage");

  async function request<T>(path: string, accessTokenValue: string): Promise<T> {
    const accessToken = accessTokenOf(accessTokenValue, ModelUsageApiError);
    const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
    const response = await fetchImpl(path, {
      method: "GET",
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${accessToken}`,
      },
      credentials: "include",
    });
    const payload = await responseBody(response, ModelUsageApiError, "Model Usage");

    if (!response.ok) {
      const code = detailCode(payload);

      throw new ModelUsageApiError(
        code ?? `Model Usage API request failed with status ${response.status}`,
        {
          status: response.status,
          code,
          payload,
        },
      );
    }

    return payload as T;
  }

  return {
    usage(projectId, accessToken) {
      return request(usagePath(basePath, projectId), accessToken);
    },

    budget(accessToken) {
      return request(`${basePath}/model-runtime/budget`, accessToken);
    },
  };
}

export const modelUsageApi = createModelUsageApi();
