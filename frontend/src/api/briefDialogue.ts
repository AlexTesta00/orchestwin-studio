import { absoluteBasePathOf, accessTokenOf, detailCode, responseBody } from "./http";
import { ApiRequestError } from "./requestError";

import type { BriefDialogueResponse, DialogueAnswerInput } from "../types/briefDialogue";

const DEFAULT_API_BASE_PATH = "/api/v1";

export interface BriefDialogueApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export interface BriefDialogueApi {
  current(projectId: string, accessToken: string): Promise<BriefDialogueResponse | null>;
  start(projectId: string, statement: string, accessToken: string): Promise<BriefDialogueResponse>;
  answer(
    projectId: string,
    input: DialogueAnswerInput,
    accessToken: string,
  ): Promise<BriefDialogueResponse>;
  nextQuestion(
    projectId: string,
    expectedTurnCount: number,
    accessToken: string,
  ): Promise<BriefDialogueResponse>;
  synthesize(
    projectId: string,
    expectedTurnCount: number,
    accessToken: string,
  ): Promise<BriefDialogueResponse>;
  close(
    projectId: string,
    expectedTurnCount: number,
    accessToken: string,
  ): Promise<BriefDialogueResponse>;
}

export class BriefDialogueApiError extends ApiRequestError {}

export function createBriefDialogueApi(options: BriefDialogueApiOptions = {}): BriefDialogueApi {
  const basePath = absoluteBasePathOf(options.basePath ?? DEFAULT_API_BASE_PATH, "Brief dialogue");
  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);

  function dialoguePath(projectId: string): string {
    return `${basePath}/projects/${encodeURIComponent(projectId)}/brief-dialogue`;
  }

  async function request(path: string, accessToken: string, body?: unknown): Promise<unknown> {
    const headers = new Headers();
    headers.set("Accept", "application/json");
    headers.set("Authorization", `Bearer ${accessTokenOf(accessToken, BriefDialogueApiError)}`);
    const init: RequestInit = { credentials: "include", headers };
    if (body !== undefined) {
      headers.set("Content-Type", "application/json");
      init.method = "POST";
      init.body = JSON.stringify(body);
    }
    const response = await fetchImpl(path, init);
    const payload = await responseBody(response);
    if (!response.ok) {
      throw new BriefDialogueApiError("The brief dialogue request failed", {
        status: response.status,
        code: detailCode(payload),
        payload,
      });
    }
    return payload;
  }

  return {
    async current(projectId, accessToken) {
      try {
        return (await request(dialoguePath(projectId), accessToken)) as BriefDialogueResponse;
      } catch (error) {
        if (error instanceof BriefDialogueApiError && error.status === 404) {
          return null;
        }
        throw error;
      }
    },

    async start(projectId, statement, accessToken) {
      return (await request(dialoguePath(projectId), accessToken, {
        statement,
      })) as BriefDialogueResponse;
    },

    async answer(projectId, input, accessToken) {
      return (await request(
        `${dialoguePath(projectId)}/answers`,
        accessToken,
        input,
      )) as BriefDialogueResponse;
    },

    async nextQuestion(projectId, expectedTurnCount, accessToken) {
      return (await request(`${dialoguePath(projectId)}/questions`, accessToken, {
        expected_turn_count: expectedTurnCount,
      })) as BriefDialogueResponse;
    },

    async synthesize(projectId, expectedTurnCount, accessToken) {
      return (await request(`${dialoguePath(projectId)}/synthesis`, accessToken, {
        expected_turn_count: expectedTurnCount,
      })) as BriefDialogueResponse;
    },

    async close(projectId, expectedTurnCount, accessToken) {
      return (await request(`${dialoguePath(projectId)}/close`, accessToken, {
        expected_turn_count: expectedTurnCount,
      })) as BriefDialogueResponse;
    },
  };
}

export const briefDialogueApi = createBriefDialogueApi();
