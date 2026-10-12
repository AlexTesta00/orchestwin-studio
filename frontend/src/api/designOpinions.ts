import { INVALID_API_RESPONSE, sendGeneration } from "./generationJobs";
import { absoluteBasePathOf, accessTokenOf, detailCode, isRecord, responseBody } from "./http";
import { ApiRequestError } from "./requestError";

import type { ChangeOpinionRun, DesignOpinionRequest } from "../types/designOpinions";

const DEFAULT_API_BASE_PATH = "/api/v1";
const JSON_MEDIA_TYPE = "application/json";

interface Answer {
  status: number;
  payload: unknown;
}

export interface DesignOpinionsApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export class DesignOpinionsApiError extends ApiRequestError {}

export interface DesignOpinionsApi {
  ask(
    projectId: string,
    body: DesignOpinionRequest,
    accessToken: string,
  ): Promise<ChangeOpinionRun>;
}

function isRun(value: unknown): value is ChangeOpinionRun {
  return (
    isRecord(value) &&
    typeof value.run_id === "string" &&
    typeof value.design_content_hash === "string" &&
    typeof value.request === "string" &&
    isRecord(value.target) &&
    Array.isArray(value.opinions)
  );
}

function unexpected({ status, payload }: Answer): DesignOpinionsApiError {
  return new DesignOpinionsApiError("The Design Opinions API returned an unexpected answer", {
    status,
    code: INVALID_API_RESPONSE,
    payload,
  });
}

export function createDesignOpinionsApi(options: DesignOpinionsApiOptions = {}): DesignOpinionsApi {
  const basePath = absoluteBasePathOf(options.basePath ?? DEFAULT_API_BASE_PATH, "Design Opinions");

  async function exchange(
    projectId: string,
    body: DesignOpinionRequest,
    accessToken: string,
  ): Promise<Answer> {
    const response = await sendGeneration(
      `${basePath}/projects/${encodeURIComponent(projectId)}/design/opinions`,
      {
        method: "POST",
        headers: {
          Accept: JSON_MEDIA_TYPE,
          Authorization: `Bearer ${accessTokenOf(accessToken, DesignOpinionsApiError)}`,
          "Content-Type": JSON_MEDIA_TYPE,
        },
        credentials: "include",
        body: JSON.stringify(body),
      },
      {
        fetchImpl: options.fetchImpl ?? globalThis.fetch.bind(globalThis),
        basePath,
        projectId,
      },
    );
    const payload = await responseBody(response);

    if (!response.ok) {
      throw new DesignOpinionsApiError("The design opinions request failed", {
        status: response.status,
        code: detailCode(payload),
        payload,
      });
    }

    return { status: response.status, payload };
  }

  return {
    async ask(projectId, body, accessToken) {
      const answer = await exchange(projectId, body, accessToken);

      if (!isRun(answer.payload)) {
        throw unexpected(answer);
      }

      return answer.payload;
    },
  };
}

export const designOpinionsApi = createDesignOpinionsApi();
