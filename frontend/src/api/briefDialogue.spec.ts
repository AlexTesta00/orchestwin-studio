import { describe, expect, it, vi } from "vitest";

import { BriefDialogueApiError, createBriefDialogueApi } from "./briefDialogue";

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const response = {
  status: "BRIEF_DIALOGUE_CURRENT",
  snapshot: {
    id: "dialogue-1",
    project_id: "project-1",
    source_brief_version_number: 1,
    statement: "Una lista ospiti.",
    status: "OPEN",
    created_at: "2026-09-25T10:00:00Z",
    question_limit: 20,
    essential_fields: [
      "description",
      "problem",
      "goals",
      "target_users",
      "functional_requirements",
    ],
    asked_fields: [],
    turns: [],
    resulting_brief_version_number: null,
    synthesis_generation_id: null,
    completed_at: null,
  },
  progress: {
    questions_asked: 0,
    question_limit: 20,
    open_fields: ["name"],
    open_essential_fields: ["problem"],
  },
  brief_version: null,
  assumptions: [],
};

describe("brief dialogue API", () => {
  it("reads the current dialogue and treats a missing one as empty", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(response))
      .mockResolvedValueOnce(jsonResponse({ detail: { code: "BRIEF_DIALOGUE_NOT_FOUND" } }, 404));
    const api = createBriefDialogueApi({ fetchImpl });

    expect(await api.current("project-1", "token")).toEqual(response);
    expect(await api.current("project-1", "token")).toBeNull();
    const firstCall = fetchImpl.mock.calls[0];
    expect(String(firstCall?.[0])).toBe("/api/v1/projects/project-1/brief-dialogue");
    expect(firstCall?.[1]?.method).toBeUndefined();
    expect(new Headers(firstCall?.[1]?.headers).get("Authorization")).toBe("Bearer token");
  });

  it("posts each command to its route with the expected turn count", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockImplementation(async () => jsonResponse(response));
    const api = createBriefDialogueApi({ fetchImpl, basePath: "/api/v1/" });

    await api.start("project-1", "Una lista ospiti.", "token");
    await api.answer("project-1", { expected_turn_count: 1, kind: "TEXT", text: "Ok" }, "token");
    await api.nextQuestion("project-1", 2, "token");
    await api.synthesize("project-1", 3, "token");
    await api.close("project-1", 4, "token");

    const calls = fetchImpl.mock.calls.map((call) => [
      String(call[0]),
      call[1]?.method,
      JSON.parse(String(call[1]?.body)),
    ]);
    expect(calls).toEqual([
      ["/api/v1/projects/project-1/brief-dialogue", "POST", { statement: "Una lista ospiti." }],
      [
        "/api/v1/projects/project-1/brief-dialogue/answers",
        "POST",
        { expected_turn_count: 1, kind: "TEXT", text: "Ok" },
      ],
      ["/api/v1/projects/project-1/brief-dialogue/questions", "POST", { expected_turn_count: 2 }],
      ["/api/v1/projects/project-1/brief-dialogue/synthesis", "POST", { expected_turn_count: 3 }],
      ["/api/v1/projects/project-1/brief-dialogue/close", "POST", { expected_turn_count: 4 }],
    ]);
  });

  it("maps failures to typed errors", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ detail: { code: "BRIEF_DIALOGUE_CHANGED" } }, 409))
      .mockResolvedValueOnce(new Response("", { status: 503 }));
    const api = createBriefDialogueApi({ fetchImpl });

    await expect(api.synthesize("project-1", 1, "token")).rejects.toMatchObject({
      code: "BRIEF_DIALOGUE_CHANGED",
      status: 409,
    });
    await expect(api.close("project-1", 1, "token")).rejects.toMatchObject({
      code: null,
      status: 503,
    });
    await expect(api.current("project-1", " ")).rejects.toBeInstanceOf(BriefDialogueApiError);
    expect(() => createBriefDialogueApi({ basePath: "api" })).toThrow();
  });
});
