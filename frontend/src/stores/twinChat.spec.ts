import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TwinChatApi } from "../api/twinChat";
import type { TwinConversationPayload } from "../types/twinChat";
import { useTwinChatStore } from "./twinChat";

const authorize = <T>(operation: (token: string) => Promise<T>) => operation("token");

function conversation(turnCount: number): TwinConversationPayload {
  return {
    id: "conversation-1",
    project_id: "project-1",
    twin_id: "twin-1",
    twin_version_number: 1,
    twin_content_hash: "a".repeat(64),
    twin_name: "Marta",
    created_at: "2026-09-22T10:00:00Z",
    turns: Array.from({ length: turnCount }, (_, index) => ({
      id: `turn-${index + 1}`,
      ordinal: index + 1,
      question: `Domanda ${index + 1}`,
      reply: `Risposta ${index + 1}`,
      insights: [],
      model_generation_id: `generation-${index + 1}`,
      content_hash: "b".repeat(64),
      created_at: "2026-09-22T10:01:00Z",
      epistemic_status: "HYPOTHESIS" as const,
      human_validation: "REQUIRED" as const,
    })),
  };
}

describe("twin chat store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("keeps one conversation per twin and sends the expected turn count", async () => {
    const api: TwinChatApi = {
      conversation: vi.fn().mockResolvedValue(conversation(1)),
      ask: vi.fn().mockResolvedValue(conversation(2)),
    };
    const store = useTwinChatStore();

    expect(await store.load("project-1", "twin-1", authorize, api)).toEqual(conversation(1));
    expect(store.conversationOf("twin-1")?.turns).toHaveLength(1);
    expect(store.conversationOf("twin-2")).toBeNull();

    await store.ask("project-1", "twin-1", "E poi?", authorize, api);
    expect(vi.mocked(api.ask).mock.calls[0]?.[2]).toEqual({
      question: "E poi?",
      expected_turn_count: 1,
    });
    expect(store.conversationOf("twin-1")?.turns).toHaveLength(2);
    expect(store.isBusy("twin-1")).toBe(false);
    expect(store.error).toBeNull();
  });

  it("records the failure code and releases the busy state", async () => {
    const api: TwinChatApi = {
      conversation: vi.fn().mockResolvedValue(null),
      ask: vi.fn().mockRejectedValue(new Error("TWIN_CHAT_MODEL_NOT_CONFIGURED")),
    };
    const store = useTwinChatStore();

    await store.load("project-1", "twin-1", authorize, api);
    await expect(store.ask("project-1", "twin-1", "Ciao?", authorize, api)).rejects.toThrow(
      "TWIN_CHAT_MODEL_NOT_CONFIGURED",
    );
    expect(store.error).toBe("TWIN_CHAT_MODEL_NOT_CONFIGURED");
    expect(store.isBusy("twin-1")).toBe(false);
    expect(vi.mocked(api.ask).mock.calls[0]?.[2]).toEqual({
      question: "Ciao?",
      expected_turn_count: 0,
    });
  });
});
