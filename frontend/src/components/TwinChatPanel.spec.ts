import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TwinChatApiError, type TwinChatApi } from "@/api/twinChat";
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

    expect(wrapper.get("[data-testid='twin-chat-empty']").text()).toBe(
      "Nessuna domanda ancora. Chiedi come lavora, che cosa rende difficile il suo lavoro o che cosa si aspetta dall'applicazione.",
    );
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
    expect(turn.text()).toContain("attività ricorrenti e contesto d'uso");
    expect(turn.text()).not.toMatch(/recurring_tasks|context_of_use/);
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

    const alert = wrapper.get("[role='alert']");
    expect(alert.get("p").text()).toBe("Il twin non ha potuto rispondere. Riprova tra poco.");
    expect(alert.get("code").text()).toBe("TWIN_MODEL_UNAVAILABLE");
    expect(
      (wrapper.get("[data-testid='twin-chat-question']").element as HTMLTextAreaElement).value,
    ).toBe("Cosa ti frustra?");
  });

  it("explains a known refusal in plain words without the code", async () => {
    const api = fakeApi(null);
    vi.mocked(api.ask).mockRejectedValue(
      new TwinChatApiError("The twin chat request failed", {
        status: 503,
        code: "TWIN_CHAT_MODEL_NOT_CONFIGURED",
        payload: null,
      }),
    );
    const wrapper = mountPanel(api);
    await flushPromises();

    await wrapper.get("[data-testid='twin-chat-question']").setValue("Come lavori?");
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    const alert = wrapper.get("[data-testid='twin-chat-error']");
    expect(alert.text()).toBe(
      "Il modello che dà voce ai twin non è collegato. Chiedi a chi gestisce lo Studio di collegarlo.",
    );
    expect(alert.find("code").exists()).toBe(false);
  });

  it("offers questions to start with and sends the chosen one", async () => {
    const api = fakeApi(null);
    const wrapper = mountPanel(api);
    await flushPromises();

    const suggestions = wrapper.findAll("[data-testid='twin-chat-suggestion']");
    expect(suggestions.map((item) => item.text())).toEqual([
      "Come lavori di solito?",
      "Che cosa ti fa perdere tempo oggi?",
      "Che cosa ti aspetti da questa applicazione?",
    ]);

    await suggestions[1]!.trigger("click");
    await flushPromises();

    expect(vi.mocked(api.ask).mock.calls[0]?.[2]).toEqual({
      question: "Che cosa ti fa perdere tempo oggi?",
      expected_turn_count: 0,
    });
  });

  it("sends the question with the enter key and keeps shift and enter for a new line", async () => {
    const api = fakeApi(null);
    const wrapper = mountPanel(api);
    await flushPromises();
    const field = wrapper.get("[data-testid='twin-chat-question']");

    await field.setValue("Prima riga");
    await field.trigger("keydown", { key: "Enter", shiftKey: true });
    expect(api.ask).not.toHaveBeenCalled();

    await field.trigger("keydown", { key: "Enter" });
    await flushPromises();

    expect(vi.mocked(api.ask).mock.calls[0]?.[2]).toEqual({
      question: "Prima riga",
      expected_turn_count: 0,
    });
  });

  it("shows the questions of the owner and the answers of the twin as a conversation", async () => {
    const wrapper = mountPanel(fakeApi(answered));
    await flushPromises();

    const turn = wrapper.get("[data-testid='twin-chat-turn']");
    const bubbles = turn.findAll("p");
    expect(bubbles[0]!.classes()).toContain("self-end");
    const reply = turn.get("[data-claim-status='hypothesis']");
    expect(reply.classes()).toContain("self-start");
    expect(reply.text()).toContain("Serve un solo campo.");
    expect(wrapper.get("[data-testid='twin-identity']").text()).toContain("Marta Rinaldi");
    expect(wrapper.get("[data-testid='twin-identity']").text()).toContain(
      "Risposte simulate · ipotesi",
    );
  });

  it("names the fields of the twin behind each insight in plain words, in both languages", async () => {
    const grounded = conversation([
      {
        ...answered.turns[0]!,
        insights: [
          {
            kind: "FRUSTRATION",
            text: "Il testo piccolo mi rallenta.",
            confidence: 0.6,
            grounded_on: [
              "user_twin.accessibility_needs",
              "user_twin.technical_literacy",
              "user_twin.pain_points",
              "user_twin.night_shifts",
            ],
          },
        ],
      },
    ]);
    const italian = mountPanel(fakeApi(grounded));
    await flushPromises();
    const insight = () => italian.get("[data-testid='twin-chat-insight']").text();
    expect(insight()).toContain(
      "esigenze di accessibilità, competenza tecnica, pain point e night shifts",
    );
    expect(insight()).not.toMatch(/accessibility_needs|technical_literacy|pain_points|_/);

    const english = mount(TwinChatPanel, {
      props: {
        projectId: "project-1",
        twin,
        api: fakeApi(grounded),
        authorize: <T>(operation: (token: string) => Promise<T>) => operation("token"),
      },
      global: { plugins: [createAppI18n("en")] },
    });
    await flushPromises();
    expect(english.get("[data-testid='twin-chat-insight']").text()).toContain(
      "accessibility needs, technical literacy, pain points, and night shifts",
    );
  });

  it("has no axe violations", async () => {
    const wrapper = mountPanel(fakeApi(answered));
    await flushPromises();
    await expectAccessible(wrapper.element);
  });
});
