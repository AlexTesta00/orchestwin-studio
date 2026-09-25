import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BriefDialogueApiError, type BriefDialogueApi } from "@/api/briefDialogue";
import type { BriefField, ProjectBriefVersionResponse } from "@/api/contracts";
import { createAppI18n } from "@/i18n";
import { expectAccessible } from "@/test/axe";
import type { BriefDialogueResponse, BriefDialogueTurnPayload } from "@/types/briefDialogue";
import ProjectBriefDialogue from "./ProjectBriefDialogue.vue";

const BRIEF = {
  id: "brief-2",
  project_id: "project-1",
  version_number: 2,
  content_hash: "b".repeat(64),
  created_at: "2026-09-25T10:05:00Z",
  brief: { description: "Una lista ospiti per il workshop." },
} as ProjectBriefVersionResponse;

function turn(
  ordinal: number,
  field: BriefDialogueTurnPayload["field"],
  answer: BriefDialogueTurnPayload["answer"],
): BriefDialogueTurnPayload {
  return {
    id: `turn-${ordinal}`,
    dialogue_id: "dialogue-1",
    ordinal,
    field,
    answer_type: field === "goals" ? "ITEM_LIST" : "TEXT",
    question: field === null ? "Cosa intendi con volontari?" : `Domanda su ${field}?`,
    model_generation_id: `generation-${ordinal}`,
    asked_at: "2026-09-25T10:00:00Z",
    answer,
    answered_at: answer === null ? null : "2026-09-25T10:01:00Z",
  };
}

function response(
  status: BriefDialogueResponse["status"],
  turns: BriefDialogueTurnPayload[],
  options: {
    dialogueStatus?: BriefDialogueResponse["snapshot"]["status"];
    essentialOpen?: BriefField[];
    briefVersion?: ProjectBriefVersionResponse | null;
  } = {},
): BriefDialogueResponse {
  return {
    status,
    snapshot: {
      id: "dialogue-1",
      project_id: "project-1",
      source_brief_version_number: 1,
      statement: "Una lista ospiti per il workshop.",
      status: options.dialogueStatus ?? "OPEN",
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
      turns,
      resulting_brief_version_number: options.briefVersion?.version_number ?? null,
      synthesis_generation_id: null,
      completed_at: null,
    },
    progress: {
      questions_asked: turns.length,
      question_limit: 20,
      open_fields: options.essentialOpen ?? ["goals"],
      open_essential_fields: options.essentialOpen ?? ["goals"],
    },
    brief_version: options.briefVersion ?? null,
    assumptions: [],
  };
}

function fakeApi(current: BriefDialogueResponse | null): BriefDialogueApi {
  return {
    current: vi.fn().mockResolvedValue(current),
    start: vi
      .fn()
      .mockResolvedValue(response("BRIEF_DIALOGUE_STARTED", [turn(1, "problem", null)])),
    answer: vi.fn(),
    nextQuestion: vi
      .fn()
      .mockResolvedValue(
        response("BRIEF_QUESTION_ASKED", [
          turn(1, "problem", { kind: "TEXT", text: "Si perdono i nomi.", items: null }),
          turn(2, "goals", null),
        ]),
      ),
    synthesize: vi
      .fn()
      .mockResolvedValue(
        response(
          "BRIEF_SYNTHESIZED",
          [turn(1, "problem", { kind: "TEXT", text: "Si perdono i nomi.", items: null })],
          { dialogueStatus: "SYNTHESIZED", essentialOpen: [], briefVersion: BRIEF },
        ),
      ),
    close: vi
      .fn()
      .mockResolvedValue(
        response(
          "BRIEF_DIALOGUE_CLOSED",
          [turn(1, "problem", { kind: "TEXT", text: "Si perdono i nomi.", items: null })],
          { dialogueStatus: "CLOSED" },
        ),
      ),
  };
}

function mountDialogue(
  api: BriefDialogueApi,
  currentBrief: ProjectBriefVersionResponse | null = null,
) {
  return mount(ProjectBriefDialogue, {
    props: {
      projectId: "project-1",
      currentBrief,
      api,
      authorize: <T>(operation: (token: string) => Promise<T>) => operation("token"),
    },
    global: { plugins: [createAppI18n("it")] },
  });
}

describe("project brief dialogue", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("starts from the statement, asks one question at a time and composes the brief", async () => {
    const api = fakeApi(null);
    vi.mocked(api.answer)
      .mockResolvedValueOnce(
        response("BRIEF_QUESTION_ASKED", [
          turn(1, "problem", { kind: "TEXT", text: "Si perdono i nomi.", items: null }),
          turn(2, "goals", null),
        ]),
      )
      .mockResolvedValueOnce(
        response("BRIEF_QUESTION_ASKED", [
          turn(1, "problem", { kind: "TEXT", text: "Si perdono i nomi.", items: null }),
          turn(2, "goals", { kind: "ITEM_LIST", text: null, items: ["Aggiungere", "Vedere"] }),
          turn(3, null, null),
        ]),
      )
      .mockResolvedValueOnce(
        response(
          "BRIEF_DIALOGUE_READY",
          [
            turn(1, "problem", { kind: "TEXT", text: "Si perdono i nomi.", items: null }),
            turn(2, "goals", { kind: "ITEM_LIST", text: null, items: ["Aggiungere", "Vedere"] }),
            turn(3, null, { kind: "UNKNOWN", text: null, items: null }),
          ],
          { dialogueStatus: "READY", essentialOpen: [] },
        ),
      );
    const wrapper = mountDialogue(api);
    await flushPromises();

    expect(wrapper.emitted("active")?.[0]).toEqual([false]);
    await wrapper.get("[data-testid='brief-dialogue-entry'] form").trigger("submit");
    expect(wrapper.get("[role='alert']").text()).toBe("Scrivi almeno una frase sulla tua idea.");
    expect(api.start).not.toHaveBeenCalled();

    await wrapper
      .get("[data-testid='brief-dialogue-statement']")
      .setValue("Una lista ospiti per il workshop.");
    await wrapper.get("[data-testid='brief-dialogue-entry'] form").trigger("submit");
    await flushPromises();

    expect(vi.mocked(api.start).mock.calls[0]?.slice(0, 2)).toEqual([
      "project-1",
      "Una lista ospiti per il workshop.",
    ]);
    expect(wrapper.emitted("active")?.[1]).toEqual([true]);
    const question = wrapper.get("[data-testid='brief-dialogue-question']");
    expect(question.text()).toContain("Quale problema vuoi risolvere?");
    expect(question.text()).toContain("Domanda su problem?");
    expect(wrapper.get("[data-testid='brief-dialogue-progress']").text()).toContain(
      "Domanda 1 di 20",
    );

    await question.get("form").trigger("submit");
    expect(wrapper.get("[role='alert']").text()).toContain("Non lo so");
    expect(api.answer).not.toHaveBeenCalled();

    await wrapper.get("[data-testid='brief-dialogue-answer']").setValue(" Si perdono i nomi. ");
    await question.get("form").trigger("submit");
    await flushPromises();
    expect(vi.mocked(api.answer).mock.calls[0]?.[1]).toEqual({
      kind: "TEXT",
      text: "Si perdono i nomi.",
      expected_turn_count: 1,
    });
    expect(wrapper.findAll("[data-testid='brief-dialogue-turn']")).toHaveLength(1);
    expect(wrapper.get("[data-testid='brief-dialogue-question']").text()).toContain("Obiettivi");

    await wrapper.get("[data-testid='brief-dialogue-answer']").setValue("Aggiungere\n\nVedere\n");
    await wrapper.get("[data-testid='brief-dialogue-question'] form").trigger("submit");
    await flushPromises();
    expect(vi.mocked(api.answer).mock.calls[1]?.[1]).toEqual({
      kind: "ITEM_LIST",
      items: ["Aggiungere", "Vedere"],
      expected_turn_count: 2,
    });
    expect(wrapper.get("[data-testid='brief-dialogue-question']").text()).toContain(
      "Approfondimento",
    );
    expect(wrapper.text()).toContain("Aggiungere · Vedere");

    await wrapper.get("[data-testid='brief-dialogue-unknown']").trigger("click");
    await flushPromises();
    expect(vi.mocked(api.answer).mock.calls[2]?.[1]).toEqual({
      kind: "UNKNOWN",
      expected_turn_count: 3,
    });
    expect(vi.mocked(api.synthesize).mock.calls[0]?.slice(0, 2)).toEqual(["project-1", 3]);
    expect(wrapper.emitted("synthesized")?.[0]).toEqual([BRIEF]);
    expect(wrapper.emitted("active")?.at(-1)).toEqual([false]);
    expect(wrapper.get("[data-testid='brief-dialogue-synthesized']").text()).toContain(
      "Il brief è pronto",
    );
    await wrapper.get("[data-testid='brief-dialogue-open-form']").trigger("click");
    expect(wrapper.emitted("open-form")).toHaveLength(1);
  });

  it("resumes an interrupted dialogue and lets the owner compose early or close", async () => {
    const api = fakeApi(
      response("BRIEF_DIALOGUE_CURRENT", [
        turn(1, "problem", { kind: "TEXT", text: "Si perdono i nomi.", items: null }),
      ]),
    );
    const wrapper = mountDialogue(api, BRIEF);
    await flushPromises();

    expect(wrapper.emitted("active")?.[0]).toEqual([true]);
    expect(wrapper.get("[data-testid='brief-dialogue-resume']").text()).toContain(
      "Le tue risposte sono salvate",
    );
    await wrapper.get("[data-testid='brief-dialogue-continue']").trigger("click");
    await flushPromises();
    expect(vi.mocked(api.nextQuestion).mock.calls[0]?.slice(0, 2)).toEqual(["project-1", 1]);
    expect(wrapper.get("[data-testid='brief-dialogue-question']").text()).toContain("Obiettivi");

    await wrapper.get("[data-testid='brief-dialogue-compose']").trigger("click");
    await flushPromises();
    expect(vi.mocked(api.synthesize).mock.calls[0]?.slice(0, 2)).toEqual(["project-1", 2]);
    expect(wrapper.emitted("synthesized")).toHaveLength(1);

    const reopened = mountDialogue(
      fakeApi(response("BRIEF_DIALOGUE_CURRENT", [turn(1, "problem", null)])),
    );
    await flushPromises();
    await reopened.get("[data-testid='brief-dialogue-close']").trigger("click");
    await flushPromises();
    expect(reopened.emitted("active")?.at(-1)).toEqual([false]);
    expect(reopened.get("[data-testid='brief-dialogue-start']").text()).toBe("Inizia il dialogo");
  });

  it("falls back to the form when the model is not configured", async () => {
    const api = fakeApi(null);
    vi.mocked(api.start).mockRejectedValue(
      new BriefDialogueApiError("failed", {
        status: 503,
        code: "BRIEF_DIALOGUE_MODEL_NOT_CONFIGURED",
        payload: null,
      }),
    );
    const wrapper = mountDialogue(api, BRIEF);
    await flushPromises();

    expect(
      (wrapper.get("[data-testid='brief-dialogue-statement']").element as HTMLTextAreaElement)
        .value,
    ).toBe("Una lista ospiti per il workshop.");
    expect(wrapper.get("[data-testid='brief-dialogue-start']").text()).toBe("Riapri il dialogo");
    await wrapper.get("[data-testid='brief-dialogue-entry'] form").trigger("submit");
    await flushPromises();

    expect(wrapper.emitted("unavailable")).toHaveLength(1);
    expect(wrapper.get("[data-testid='brief-dialogue-unavailable']").text()).toContain(
      "puoi compilare il modulo",
    );
    expect(wrapper.find("[data-testid='brief-dialogue-error']").exists()).toBe(false);
  });

  it("shows a translated error and keeps the answer after a failed turn", async () => {
    const api = fakeApi(response("BRIEF_DIALOGUE_CURRENT", [turn(1, "problem", null)]));
    vi.mocked(api.answer).mockRejectedValue(
      new BriefDialogueApiError("failed", {
        status: 503,
        code: "PROVIDER_UNAVAILABLE",
        payload: null,
      }),
    );
    const wrapper = mountDialogue(api);
    await flushPromises();

    await wrapper.get("[data-testid='brief-dialogue-answer']").setValue("Si perdono i nomi.");
    await wrapper.get("[data-testid='brief-dialogue-question'] form").trigger("submit");
    await flushPromises();

    expect(wrapper.get("[data-testid='brief-dialogue-error']").text()).toBe(
      "Il modello non risponde: riprova tra poco.",
    );
    expect(
      (wrapper.get("[data-testid='brief-dialogue-answer']").element as HTMLTextAreaElement).value,
    ).toBe("Si perdono i nomi.");
  });

  it("has no axe violations", async () => {
    const wrapper = mountDialogue(
      fakeApi(
        response("BRIEF_DIALOGUE_CURRENT", [
          turn(1, "problem", { kind: "TEXT", text: "Si perdono i nomi.", items: null }),
          turn(2, "goals", null),
        ]),
      ),
    );
    await flushPromises();
    await expectAccessible(wrapper.element);
  });
});
