import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BriefDialogueApiError, type BriefDialogueApi } from "../api/briefDialogue";
import type { BriefDialogueResponse, BriefDialogueTurnPayload } from "../types/briefDialogue";
import { useBriefDialogueStore } from "./briefDialogue";

const authorize = <T>(operation: (token: string) => Promise<T>) => operation("token");

function turn(ordinal: number, answered: boolean): BriefDialogueTurnPayload {
  return {
    id: `turn-${ordinal}`,
    dialogue_id: "dialogue-1",
    ordinal,
    field: ordinal === 1 ? "problem" : null,
    answer_type: "TEXT",
    question: `Domanda ${ordinal}?`,
    model_generation_id: `generation-${ordinal}`,
    asked_at: "2026-09-25T10:00:00Z",
    answer: answered ? { kind: "TEXT", text: `Risposta ${ordinal}`, items: null } : null,
    answered_at: answered ? "2026-09-25T10:01:00Z" : null,
  };
}

function response(
  status: BriefDialogueResponse["status"],
  turns: BriefDialogueTurnPayload[],
  dialogueStatus: BriefDialogueResponse["snapshot"]["status"] = "OPEN",
): BriefDialogueResponse {
  return {
    status,
    snapshot: {
      id: "dialogue-1",
      project_id: "project-1",
      source_brief_version_number: 1,
      statement: "Una lista ospiti.",
      status: dialogueStatus,
      created_at: "2026-09-25T10:00:00Z",
      question_limit: 20,
      essential_fields: [
        "description",
        "problem",
        "goals",
        "target_users",
        "functional_requirements",
      ],
      asked_fields: ["problem"],
      turns,
      resulting_brief_version_number: null,
      synthesis_generation_id: null,
      completed_at: null,
    },
    progress: {
      questions_asked: turns.length,
      question_limit: 20,
      open_fields: ["goals"],
      open_essential_fields: ["goals"],
    },
    brief_version: null,
    assumptions: [],
  };
}

function fakeApi(): BriefDialogueApi {
  return {
    current: vi.fn().mockResolvedValue(response("BRIEF_DIALOGUE_CURRENT", [turn(1, false)])),
    start: vi.fn().mockResolvedValue(response("BRIEF_DIALOGUE_STARTED", [turn(1, false)])),
    answer: vi
      .fn()
      .mockResolvedValue(response("BRIEF_QUESTION_ASKED", [turn(1, true), turn(2, false)])),
    nextQuestion: vi
      .fn()
      .mockResolvedValue(response("BRIEF_QUESTION_ASKED", [turn(1, true), turn(2, false)])),
    synthesize: vi
      .fn()
      .mockResolvedValue(response("BRIEF_SYNTHESIZED", [turn(1, true)], "SYNTHESIZED")),
    close: vi.fn().mockResolvedValue(response("BRIEF_DIALOGUE_CLOSED", [turn(1, true)], "CLOSED")),
  };
}

describe("brief dialogue store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("tracks the pending question and sends the current turn count", async () => {
    const api = fakeApi();
    const store = useBriefDialogueStore();

    await store.load("project-1", authorize, api);
    expect(store.loaded).toBe(true);
    expect(store.isActive).toBe(true);
    expect(store.pendingTurn?.ordinal).toBe(1);
    expect(store.answeredTurns).toHaveLength(0);

    await store.answer("project-1", { kind: "TEXT", text: "Ok" }, authorize, api);
    expect(vi.mocked(api.answer).mock.calls[0]?.[1]).toEqual({
      kind: "TEXT",
      text: "Ok",
      expected_turn_count: 1,
    });
    expect(store.pendingTurn?.ordinal).toBe(2);
    expect(store.answeredTurns).toHaveLength(1);
    expect(store.lastOutcome).toBe("BRIEF_QUESTION_ASKED");

    await store.synthesize("project-1", authorize, api);
    expect(vi.mocked(api.synthesize).mock.calls[0]?.[1]).toBe(2);
    expect(store.isActive).toBe(false);
    expect(store.dialogue?.status).toBe("SYNTHESIZED");
  });

  it("resets when the project changes and treats a missing dialogue as empty", async () => {
    const api = fakeApi();
    vi.mocked(api.current).mockResolvedValueOnce(null);
    const store = useBriefDialogueStore();

    await store.load("project-1", authorize, api);
    expect(store.dialogue).toBeNull();
    expect(store.isActive).toBe(false);

    await store.start("project-2", "Nuova idea.", authorize, api);
    expect(store.projectId).toBe("project-2");
    expect(store.pendingTurn?.ordinal).toBe(1);
  });

  it("records the failure code and flags an unconfigured model", async () => {
    const api = fakeApi();
    vi.mocked(api.start).mockRejectedValueOnce(
      new BriefDialogueApiError("failed", {
        status: 503,
        code: "BRIEF_DIALOGUE_MODEL_NOT_CONFIGURED",
        payload: null,
      }),
    );
    vi.mocked(api.close).mockRejectedValueOnce(new Error("network down"));
    const store = useBriefDialogueStore();

    await expect(store.start("project-1", "Idea.", authorize, api)).rejects.toBeInstanceOf(
      BriefDialogueApiError,
    );
    expect(store.modelUnavailable).toBe(true);
    expect(store.error).toBe("BRIEF_DIALOGUE_MODEL_NOT_CONFIGURED");
    expect(store.busy).toBe(false);

    await expect(store.close("project-1", authorize, api)).rejects.toThrow("network down");
    expect(store.error).toBe("network down");
  });
});
