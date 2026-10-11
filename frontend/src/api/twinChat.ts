import { absoluteBasePathOf, accessTokenOf, detailCode, responseBody } from "./http";
import { ApiRequestError } from "./requestError";

import type { AskTwinInput, TwinConversationPayload } from "../types/twinChat";

const DEFAULT_API_BASE_PATH = "/api/v1";

export interface TwinChatApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

interface SnapshotResponse<T> {
  snapshot: T;
}

export interface TwinChatApi {
  conversation(
    projectId: string,
    twinId: string,
    accessToken: string,
  ): Promise<TwinConversationPayload | null>;
  ask(
    projectId: string,
    twinId: string,
    input: AskTwinInput,
    accessToken: string,
  ): Promise<TwinConversationPayload>;
}

export class TwinChatApiError extends ApiRequestError {}

export function createTwinChatApi(options: TwinChatApiOptions = {}): TwinChatApi {
  const basePath = absoluteBasePathOf(options.basePath ?? DEFAULT_API_BASE_PATH, "Twin chat");
  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);

  function conversationPath(projectId: string, twinId: string): string {
    return (
      `${basePath}/projects/${encodeURIComponent(projectId)}` +
      `/user-twins/${encodeURIComponent(twinId)}/conversation`
    );
  }

  async function request<T>(path: string, accessToken: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    headers.set("Authorization", `Bearer ${accessTokenOf(accessToken, TwinChatApiError)}`);
    if (init.body !== undefined) {
      headers.set("Content-Type", "application/json");
    }
    const response = await fetchImpl(path, { ...init, credentials: "include", headers });
    const payload = await responseBody(response);
    if (!response.ok) {
      throw new TwinChatApiError("The twin chat request failed", {
        status: response.status,
        code: detailCode(payload),
        payload,
      });
    }
    return payload as T;
  }

  return {
    async conversation(projectId, twinId, accessToken) {
      try {
        const response = await request<SnapshotResponse<TwinConversationPayload>>(
          conversationPath(projectId, twinId),
          accessToken,
        );
        return response.snapshot;
      } catch (error) {
        if (error instanceof TwinChatApiError && error.status === 404) {
          return null;
        }
        throw error;
      }
    },

    async ask(projectId, twinId, input, accessToken) {
      const response = await request<SnapshotResponse<TwinConversationPayload>>(
        `${conversationPath(projectId, twinId)}/turns`,
        accessToken,
        { method: "POST", body: JSON.stringify(input) },
      );
      return response.snapshot;
    },
  };
}

export const twinChatApi = createTwinChatApi();
