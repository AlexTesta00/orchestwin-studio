import { describe, expect, it, vi } from "vitest";

import { createTwinChatApi, TwinChatApiError } from "./twinChat";

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const conversation = {
  id: "conversation-1",
  project_id: "project-1",
  twin_id: "twin-1",
  twin_version_number: 1,
  twin_content_hash: "a".repeat(64),
  twin_name: "Marta",
  created_at: "2026-09-22T10:00:00Z",
  turns: [],
};

describe("twin chat API", () => {
  it("reads the conversation and treats a missing one as empty", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ snapshot: conversation }))
      .mockResolvedValueOnce(
        jsonResponse({ detail: { code: "TWIN_CONVERSATION_NOT_FOUND" } }, 404),
      );
    const api = createTwinChatApi({ fetchImpl });

    expect(await api.conversation("project-1", "twin-1", "token")).toEqual(conversation);
    expect(await api.conversation("project-1", "twin-1", "token")).toBeNull();
    const firstCall = fetchImpl.mock.calls[0];
    expect(String(firstCall?.[0])).toBe(
      "/api/v1/projects/project-1/user-twins/twin-1/conversation",
    );
    expect(new Headers(firstCall?.[1]?.headers).get("Authorization")).toBe("Bearer token");
  });

  it("posts the question with the expected turn count and maps failures", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ status: "TWIN_TURN_RECORDED", snapshot: conversation }))
      .mockResolvedValueOnce(jsonResponse({ detail: { code: "TWIN_CONVERSATION_CHANGED" } }, 409));
    const api = createTwinChatApi({ fetchImpl });

    await api.ask("project-1", "twin-1", { question: "Ciao?", expected_turn_count: 0 }, "token");
    const call = fetchImpl.mock.calls[0];
    expect(String(call?.[0])).toBe(
      "/api/v1/projects/project-1/user-twins/twin-1/conversation/turns",
    );
    expect(call?.[1]?.method).toBe("POST");
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({
      question: "Ciao?",
      expected_turn_count: 0,
    });

    await expect(
      api.ask("project-1", "twin-1", { question: "Ciao?", expected_turn_count: 0 }, "token"),
    ).rejects.toMatchObject({ code: "TWIN_CONVERSATION_CHANGED", status: 409 });
    await expect(api.conversation("project-1", "twin-1", " ")).rejects.toBeInstanceOf(
      TwinChatApiError,
    );
  });
});
