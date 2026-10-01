import { createPinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import type { ModelRuntimeComponent, ModelRuntimeReadiness } from "@/api/modelRuntime";
import { expectAccessible } from "@/test/axe";
import ModelRuntimeStatus from "./ModelRuntimeStatus.vue";

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
    expect(wrapper.get("h2").text()).toBe("AI assistants");
    expect(wrapper.get("[role='status']").text()).toContain("Real AI assistants are not connected");
    expect(wrapper.text()).toContain("Real AI assistants are not connected");
    await wrapper.get("button").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("assistants are connected and ready");
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
      "The AI assistants cannot be reached right now. Try again shortly.",
    );
    expect(wrapper.find('[data-testid="model-runtime-claude-code"]').exists()).toBe(false);
  });

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
