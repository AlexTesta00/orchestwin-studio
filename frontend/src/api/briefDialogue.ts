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

function normalizedBasePath(value: string): string {
  const normalized = value.trim().replace(/\/+$/u, "");
  if (normalized.length === 0 || !normalized.startsWith("/") || normalized.startsWith("//")) {
    throw new Error("Brief dialogue API base path must be an absolute application path");
  }
  return normalized;
}

function requiredAccessToken(value: string): string {
  const normalized = value.trim();
  if (normalized.length === 0) {
    throw new BriefDialogueApiError("Authentication is required", {
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

export function createBriefDialogueApi(options: BriefDialogueApiOptions = {}): BriefDialogueApi {
  const basePath = normalizedBasePath(options.basePath ?? DEFAULT_API_BASE_PATH);
  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);

  function dialoguePath(projectId: string): string {
    return `${basePath}/projects/${encodeURIComponent(projectId)}/brief-dialogue`;
  }

  async function request(path: string, accessToken: string, body?: unknown): Promise<unknown> {
    const headers = new Headers();
    headers.set("Accept", "application/json");
    headers.set("Authorization", `Bearer ${requiredAccessToken(accessToken)}`);
    const init: RequestInit = { credentials: "include", headers };
    if (body !== undefined) {
      headers.set("Content-Type", "application/json");
      init.method = "POST";
      init.body = JSON.stringify(body);
    }
    const response = await fetchImpl(path, init);
    const payload = await responsePayload(response);
    if (!response.ok) {
      throw new BriefDialogueApiError("The brief dialogue request failed", {
        status: response.status,
        code: errorCode(payload),
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
