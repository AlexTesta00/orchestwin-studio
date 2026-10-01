import { createPinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import type { ModelRuntimeComponent, ModelRuntimeReadiness } from "@/api/modelRuntime";
import { expectAccessible } from "@/test/axe";
import ModelRuntimeStatus from "./ModelRuntimeStatus.vue";

const OLD_STEP_NAMES =
  /passo Squadra|Team step|passo Requisiti|Requirements step|passo Pacchetto|Package step|\bPacchetto\b/;

const TEAM_WORDS =
  /\b(?:squadr[ae]|teams?|agent[ei]|agents?|assistent[ei]|assistants?|specialist[ai]|specialists?|ruol[oi]|roles?|membr[oi]|members?)\b/i;

const CLAUDE_CODE_READY = {
  ready: true,
  kind: "CLAUDE_CODE_CLI",
  executable: "/opt/claude/bin/claude",
  version: "2.1.286",
  logged_in: true,
  subscription: "max",
  models: {},
};

function withClaudeCode(component: ModelRuntimeComponent): ModelRuntimeReadiness {
  return {
    mode: "REAL_REQUIRED",
    ready: component.ready,
    components: { "provider:claude-code": component, database: { ready: true } },
  };
}

function mountStatus(query: (token: string) => Promise<ModelRuntimeReadiness>) {
  return mount(ModelRuntimeStatus, {
    props: {
      query,
      authorize: <T>(operation: (token: string) => Promise<T>) => operation("token"),
    },
    global: { plugins: [createPinia()] },
  });
}

describe("model runtime status", () => {
  it("shows development mode and refreshes from a fresh readiness response", async () => {
    const query = vi
      .fn()
      .mockResolvedValueOnce({ mode: "DEVELOPMENT_FIXTURES", ready: false })
      .mockResolvedValueOnce({ mode: "REAL_REQUIRED", ready: true });
    const wrapper = mount(ModelRuntimeStatus, {
      props: {
        query,
        authorize: <T>(operation: (token: string) => Promise<T>) => operation("token"),
      },
      global: { plugins: [createPinia()] },
    });
    await flushPromises();
    expect(wrapper.get("h2").text()).toBe("AI model");
    expect(wrapper.get("[role='status']").text()).toContain("The real AI model is not connected");
    expect(wrapper.text()).toContain("The real AI model is not connected");
    await wrapper.get("button").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("The AI model is connected and ready");
    expect(query).toHaveBeenCalledTimes(2);
  });

  it.each([
    [
      "ready on the subscription",
      CLAUDE_CODE_READY,
      "Claude Code 2.1.286, max subscription",
      "Claude Code 2.1.286, abbonamento max",
      [],
    ],
    [
      "ready on the subscription, without the plan",
      { ...CLAUDE_CODE_READY, subscription: null },
      "Claude Code 2.1.286, on the Claude subscription",
      "Claude Code 2.1.286, con l'abbonamento di Claude",
      [],
    ],
    [
      "ready on the subscription, without the version",
      { ...CLAUDE_CODE_READY, version: null, subscription: "team" },
      "Claude Code, team subscription",
      "Claude Code, abbonamento team",
      [],
    ],
    [
      "ready on the subscription, without the version and the plan",
      { ...CLAUDE_CODE_READY, version: null, subscription: null },
      "Claude Code, on the Claude subscription",
      "Claude Code, con l'abbonamento di Claude",
      [],
    ],
    [
      "not found",
      {
        ready: false,
        kind: "CLAUDE_CODE_CLI",
        code: "CLAUDE_CODE_NOT_FOUND",
        executable: null,
        version: null,
        logged_in: null,
        subscription: null,
        models: {},
      },
      "The Studio cannot find Claude Code: install it on the computer where the Studio runs, then check again.",
      "Lo Studio non trova Claude Code: installalo sul computer dove gira lo Studio, poi verifica di nuovo.",
      [],
    ],
    [
      "not logged in",
      {
        ...CLAUDE_CODE_READY,
        ready: false,
        code: "CLAUDE_CODE_NOT_LOGGED_IN",
        logged_in: false,
        subscription: null,
      },
      "Claude Code is not logged in: run claude once in a terminal and log in with your Claude account.",
      "Claude Code non è collegato a un account: esegui claude una volta in un terminale e accedi con il tuo account Claude.",
      ["claude"],
    ],
    [
      "not logged in, reported without the other keys",
      { ready: false, code: "CLAUDE_CODE_NOT_LOGGED_IN" },
      "Claude Code is not logged in: run claude once in a terminal and log in with your Claude account.",
      "Claude Code non è collegato a un account: esegui claude una volta in un terminale e accedi con il tuo account Claude.",
      ["claude"],
    ],
    [
      "logged in without a subscription",
      {
        ...CLAUDE_CODE_READY,
        ready: false,
        code: "CLAUDE_CODE_NOT_ON_SUBSCRIPTION",
        subscription: null,
      },
      "Claude Code is logged in to an account without a Claude subscription: log in with the account of your subscription.",
      "Claude Code è collegato a un account senza abbonamento di Claude: accedi con l'account del tuo abbonamento.",
      [],
    ],
  ])(
    "says in plain words that Claude Code is %s",
    async (_label, component, english, italian, commands) => {
      const wrapper = mountStatus(vi.fn().mockResolvedValue(withClaudeCode(component)));
      await flushPromises();
      const line = () => wrapper.get('[data-testid="model-runtime-claude-code"]');
      expect(wrapper.findAll('[data-testid="model-runtime-claude-code"]')).toHaveLength(1);
      expect(line().text()).toBe(english);
      expect(
        line()
          .findAll("code")
          .map((item) => item.text()),
      ).toEqual(commands);
      expect(wrapper.get("[role='status']").text()).toContain(english);
      await expectAccessible(wrapper.element);
      await wrapper.setProps({ locale: "it" });
      expect(line().text()).toBe(italian);
      expect(
        line()
          .findAll("code")
          .map((item) => item.text()),
      ).toEqual(commands);
    },
  );

  it("says nothing about Claude Code when the providers are paid through an API key", async () => {
    const wrapper = mountStatus(
      vi.fn().mockResolvedValue({
        mode: "REAL_REQUIRED",
        ready: false,
        components: {
          "provider:anthropic": { ready: true, kind: "ANTHROPIC_HOSTED" },
          database: { ready: false, code: "MODEL_DATABASE_SCHEMA_UNAVAILABLE" },
        },
      }),
    );
    await flushPromises();
    expect(wrapper.get("[role='status']").text()).toBe(
      "The AI model cannot be reached right now. Try again shortly.",
    );
    expect(wrapper.find('[data-testid="model-runtime-claude-code"]').exists()).toBe(false);
  });

  it.each([
    [
      "it",
      "Modello AI",
      [
        "Questo ambiente usa simulazioni di sviluppo. Il modello AI reale non è collegato.",
        "Il modello AI è collegato e pronto a ricevere richieste.",
        "Il modello AI non è al momento raggiungibile. Riprova tra poco.",
        "Non è stato possibile verificare la disponibilità del modello.",
      ],
    ],
    [
      "en",
      "AI model",
      [
        "This environment uses development simulations. The real AI model is not connected.",
        "The AI model is connected and ready for requests.",
        "The AI model cannot be reached right now. Try again shortly.",
        "Could not check model availability.",
      ],
    ],
  ] as const)(
    "speaks of the model, of no team and of no step by its old name in %s",
    async (locale, title, sentences) => {
      const query = vi
        .fn()
        .mockResolvedValueOnce({ mode: "DEVELOPMENT_FIXTURES", ready: false })
        .mockResolvedValueOnce({ mode: "REAL_REQUIRED", ready: true })
        .mockResolvedValueOnce({ mode: "REAL_REQUIRED", ready: false })
        .mockRejectedValueOnce(new Error("offline"));
      const wrapper = mount(ModelRuntimeStatus, {
        props: {
          locale,
          query,
          authorize: <T>(operation: (token: string) => Promise<T>) => operation("token"),
        },
        global: { plugins: [createPinia()] },
      });
      await flushPromises();
      const seen = [wrapper.get("[role='status']").text()];
      for (let attempt = 0; attempt < 3; attempt += 1) {
        await wrapper.get("button").trigger("click");
        await flushPromises();
        seen.push(wrapper.get("[role='status']").text());
      }
      expect(wrapper.get("h2").text()).toBe(title);
      expect(seen).toEqual(sentences);
      for (const sentence of [title, ...seen]) {
        expect(sentence).not.toMatch(OLD_STEP_NAMES);
        expect(sentence).not.toMatch(TEAM_WORDS);
      }
    },
  );

  it("hides the line about Claude Code while it checks again", async () => {
    const query = vi
      .fn()
      .mockResolvedValueOnce(withClaudeCode(CLAUDE_CODE_READY))
      .mockReturnValueOnce(new Promise<ModelRuntimeReadiness>(() => undefined));
    const wrapper = mountStatus(query);
    await flushPromises();
    expect(wrapper.find('[data-testid="model-runtime-claude-code"]').exists()).toBe(true);
    await wrapper.get("button").trigger("click");
    expect(wrapper.get("[role='status']").text()).toBe("Checking…");
    expect(wrapper.find('[data-testid="model-runtime-claude-code"]').exists()).toBe(false);
  });
});
