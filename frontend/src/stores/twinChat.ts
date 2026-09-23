import { defineStore } from "pinia";

import { twinChatApi, TwinChatApiError, type TwinChatApi } from "../api/twinChat";
import type { TwinConversationPayload } from "../types/twinChat";

export type AuthorizedTwinChatRequest = <T>(
  operation: (accessToken: string) => Promise<T>,
) => Promise<T>;

interface TwinChatStoreState {
  conversations: Record<string, TwinConversationPayload | null>;
  busyTwins: string[];
  error: string | null;
}

function errorMessage(error: unknown): string {
  if (error instanceof TwinChatApiError) {
    return error.code ?? error.message;
  }
  return error instanceof Error ? error.message : "TWIN_CHAT_REQUEST_FAILED";
}

export const useTwinChatStore = defineStore("twinChat", {
  state: (): TwinChatStoreState => ({
    conversations: {},
    busyTwins: [],
    error: null,
  }),

  getters: {
    conversationOf: (state) => (twinId: string) => state.conversations[twinId] ?? null,
    isBusy: (state) => (twinId: string) => state.busyTwins.includes(twinId),
  },

  actions: {
    begin(twinId: string): void {
      if (!this.busyTwins.includes(twinId)) {
        this.busyTwins.push(twinId);
      }
      this.error = null;
    },

    finish(twinId: string): void {
      this.busyTwins = this.busyTwins.filter((item) => item !== twinId);
    },

    fail(error: unknown): never {
      this.error = errorMessage(error);
      throw error;
    },

    async load(
      projectId: string,
      twinId: string,
      authorize: AuthorizedTwinChatRequest,
      api: TwinChatApi = twinChatApi,
    ): Promise<TwinConversationPayload | null> {
      this.begin(twinId);
      try {
        const conversation = await authorize((token) => api.conversation(projectId, twinId, token));
        this.conversations = { ...this.conversations, [twinId]: conversation };
        return conversation;
      } catch (error) {
        return this.fail(error);
      } finally {
        this.finish(twinId);
      }
    },

    async ask(
      projectId: string,
      twinId: string,
      question: string,
      authorize: AuthorizedTwinChatRequest,
      api: TwinChatApi = twinChatApi,
    ): Promise<TwinConversationPayload> {
      this.begin(twinId);
      try {
        const expected = this.conversations[twinId]?.turns.length ?? 0;
        const conversation = await authorize((token) =>
          api.ask(projectId, twinId, { question, expected_turn_count: expected }, token),
        );
        this.conversations = { ...this.conversations, [twinId]: conversation };
        return conversation;
      } catch (error) {
        return this.fail(error);
      } finally {
        this.finish(twinId);
      }
    },
  },
});
