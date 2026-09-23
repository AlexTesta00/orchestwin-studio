import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TwinChatApi } from "@/api/twinChat";
import { createAppI18n } from "@/i18n";
import { expectAccessible } from "@/test/axe";
import type { TwinConversationPayload } from "@/types/twinChat";
import type { UserTwinVersionPayload } from "@/types/userModeling";
import TwinChatPanel from "./TwinChatPanel.vue";

const twin = {
  id: "version-1",
  project_id: "project-1",
  twin_id: "twin-1",
  version_number: 2,
  based_on_version_number: 1,
  content_hash: "a".repeat(64),
  created_by_user_id: "owner-1",
  created_at: "2026-09-22T10:00:00Z",
  profile: { name: "Marta Rinaldi", observations: [] },
} as unknown as UserTwinVersionPayload;

function conversation(turns: TwinConversationPayload["turns"]): TwinConversationPayload {
  return {
    id: "conversation-1",
    project_id: "project-1",
    twin_id: "twin-1",
    twin_version_number: 2,
    twin_content_hash: "a".repeat(64),
    twin_name: "Marta Rinaldi",
    created_at: "2026-09-22T10:00:00Z",
    turns,
  };
}

const answered = conversation([
  {
    id: "turn-1",
    ordinal: 1,
    question: "Quanto tempo hai per registrare un ospite?",
    reply: "Pochissimo: lo faccio mentre l'ospite è davanti a me.\nServe un solo campo.",
    insights: [
      {
        kind: "NEED",
        text: "Registrazione in meno di dieci secondi.",
        confidence: 0.7,
        grounded_on: ["user_twin.recurring_tasks", "user_twin.context_of_use"],
      },
    ],
    model_generation_id: "generation-1",
    content_hash: "b".repeat(64),
    created_at: "2026-09-22T10:01:00Z",
    epistemic_status: "HYPOTHESIS",
    human_validation: "REQUIRED",
  },
]);

function fakeApi(current: TwinConversationPayload | null): TwinChatApi {
  return {
    conversation: vi.fn().mockResolvedValue(current),
    ask: vi.fn().mockResolvedValue(answered),
  };
}

function mountPanel(api: TwinChatApi) {
  return mount(TwinChatPanel, {
    props: {
      projectId: "project-1",
      twin,
      api,
      authorize: <T>(operation: (token: string) => Promise<T>) => operation("token"),
    },
    global: { plugins: [createAppI18n("it")] },
  });
}

describe("twin chat panel", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("asks a question and shows the answer as a labelled hypothesis with its insights", async () => {
    const api = fakeApi(null);
    const wrapper = mountPanel(api);
    await flushPromises();

    expect(wrapper.get("[data-testid='twin-chat-empty']").text()).toContain("Marta Rinaldi");
    expect(wrapper.text()).toContain("Proposta dell'AI, non validata");

    await wrapper.get("form").trigger("submit");
    expect(wrapper.get("[role='alert']").text()).toBe("Scrivi una domanda prima di inviare.");
    expect(api.ask).not.toHaveBeenCalled();

    await wrapper
      .get("[data-testid='twin-chat-question']")
      .setValue("Quanto tempo hai per registrare un ospite?");
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(vi.mocked(api.ask).mock.calls[0]?.slice(0, 3)).toEqual([
      "project-1",
      "twin-1",
      { question: "Quanto tempo hai per registrare un ospite?", expected_turn_count: 0 },
    ]);
    const turn = wrapper.get("[data-testid='twin-chat-turn']");
    expect(turn.text()).toContain("Quanto tempo hai per registrare un ospite?");
    expect(turn.text()).toContain("Serve un solo campo.");
    expect(turn.findAll("[data-testid='twin-chat-insight']")).toHaveLength(1);
    expect(turn.text()).toContain("Bisogno");
    expect(turn.text()).toContain("70%");
    expect(turn.text()).toContain("recurring_tasks, context_of_use");
    expect(wrapper.find("[data-testid='twin-chat-empty']").exists()).toBe(false);
    expect(
      (wrapper.get("[data-testid='twin-chat-question']").element as HTMLTextAreaElement).value,
    ).toBe("");
  });

  it("reloads an existing conversation and flags an older profile version", async () => {
    const api = fakeApi({ ...answered, twin_version_number: 1 });
    const wrapper = mountPanel(api);
    await flushPromises();

    expect(api.conversation).toHaveBeenCalledWith("project-1", "twin-1", "token");
    expect(wrapper.findAll("[data-testid='twin-chat-turn']")).toHaveLength(1);
    expect(wrapper.get("[data-testid='twin-chat-stale']").text()).toContain("versione 1");
  });

  it("shows the request error without losing the question", async () => {
    const api = fakeApi(null);
    vi.mocked(api.ask).mockRejectedValue(new Error("TWIN_MODEL_UNAVAILABLE"));
    const wrapper = mountPanel(api);
    await flushPromises();

    await wrapper.get("[data-testid='twin-chat-question']").setValue("Cosa ti frustra?");
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(wrapper.get("[role='alert']").text()).toBe("TWIN_MODEL_UNAVAILABLE");
    expect(
      (wrapper.get("[data-testid='twin-chat-question']").element as HTMLTextAreaElement).value,
    ).toBe("Cosa ti frustra?");
  });

  it("has no axe violations", async () => {
    const wrapper = mountPanel(fakeApi(answered));
    await flushPromises();
    await expectAccessible(wrapper.element);
  });
});
