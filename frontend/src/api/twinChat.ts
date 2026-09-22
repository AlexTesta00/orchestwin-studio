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

function normalizedBasePath(value: string): string {
  const normalized = value.trim().replace(/\/+$/u, "");
  if (normalized.length === 0 || !normalized.startsWith("/") || normalized.startsWith("//")) {
    throw new Error("Twin chat API base path must be an absolute application path");
  }
  return normalized;
}

function requiredAccessToken(value: string): string {
  const normalized = value.trim();
  if (normalized.length === 0) {
    throw new TwinChatApiError("Authentication is required", {
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

export function createTwinChatApi(options: TwinChatApiOptions = {}): TwinChatApi {
  const basePath = normalizedBasePath(options.basePath ?? DEFAULT_API_BASE_PATH);
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
    headers.set("Authorization", `Bearer ${requiredAccessToken(accessToken)}`);
    if (init.body !== undefined) {
      headers.set("Content-Type", "application/json");
    }
    const response = await fetchImpl(path, { ...init, credentials: "include", headers });
    const payload = await responsePayload(response);
    if (!response.ok) {
      throw new TwinChatApiError("The twin chat request failed", {
        status: response.status,
        code: errorCode(payload),
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
