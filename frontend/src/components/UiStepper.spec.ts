import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import { createAppI18n } from "@/i18n";
import UiEvidenceDrawer from "./UiEvidenceDrawer.vue";
import UiFindingsCard from "./UiFindingsCard.vue";
import UiLongRunning from "./UiLongRunning.vue";
import UiStepper from "./UiStepper.vue";
import { expectAccessible } from "@/test/axe";

function plugins(locale: "en" | "it" = "it") {
  return { global: { plugins: [createAppI18n(locale)] } };
}

const steps = [
  { key: "brief", label: "Brief", status: "approved" as const },
  { key: "team", label: "Squadra", status: "current" as const, decision: 1, max: 4 },
  { key: "twins", label: "User Twin", status: "pending" as const },
];

describe("stepper", () => {
  it("marks the current step, keeps future steps unclickable and reports decisions", async () => {
    const wrapper = mount(UiStepper, { props: { steps, active: "team" }, ...plugins() });
    const buttons = wrapper.findAll("button");
    expect(buttons[0]?.text()).toContain("Approvato");
    expect(buttons[1]?.attributes("aria-current")).toBe("step");
    expect(buttons[1]?.text()).toContain("Decisione 1 di 4");
    expect(buttons[1]?.classes()).toContain("bg-surface-3");
    expect(buttons[2]?.attributes("disabled")).toBeDefined();
    expect(buttons[2]?.text()).toContain("in attesa");
    await buttons[0]?.trigger("click");
    expect(wrapper.emitted("select")).toEqual([["brief"]]);
  });
});

describe("long-running state", () => {
  it("announces progress politely and lets the person cancel", async () => {
    const wrapper = mount(UiLongRunning, {
      props: {
        title: "L'AI sta preparando la proposta",
        expected: "di solito 10-40 secondi",
        elapsed: 12.4,
        progress: 40,
        cancellable: true,
      },
      ...plugins(),
    });
    expect(wrapper.get("[data-testid='long-running']").attributes("aria-live")).toBe("polite");
    expect(wrapper.get("[role='progressbar']").attributes("aria-valuenow")).toBe("40");
    expect(wrapper.text()).toContain("12 s trascorsi");
    await wrapper.get("[data-testid='cancel']").trigger("click");
    expect(wrapper.emitted("cancel")).toHaveLength(1);
  });
});

describe("evidence drawer", () => {
  it("stays closed by default and exposes the entries when opened", async () => {
    const wrapper = mount(UiEvidenceDrawer, {
      props: { entries: [{ key: "sha256", value: "abc123" }] },
      ...plugins(),
    });
    const toggle = wrapper.get("[data-testid='evidence-toggle']");
    expect(toggle.attributes("aria-expanded")).toBe("false");
    expect(wrapper.find("dl").exists()).toBe(false);
    await toggle.trigger("click");
    expect(toggle.attributes("aria-expanded")).toBe("true");
    expect(toggle.text()).toBe("Nascondi i dettagli");
    expect(wrapper.get("dd").text()).toBe("abc123");
  });
});

describe("findings card", () => {
  it("explains a failed check in three plain rows with the rule in mono", () => {
    const wrapper = mount(UiFindingsCard, {
      props: {
        rule: "AXE_COLOR_CONTRAST",
        title: "Testo poco leggibile",
        what: "Il pulsante ha contrasto 2.1:1.",
        where: "Schermata di conferma",
        change: "Scurisce il colore del pulsante.",
      },
      slots: { action: "<button>Ripara</button>" },
      ...plugins(),
    });
    expect(wrapper.get("[data-testid='finding-rule']").text()).toBe("AXE_COLOR_CONTRAST");
    expect(wrapper.text()).toContain("Controllo non superato");
    expect(wrapper.findAll("dt").map((node) => node.text())).toEqual([
      "Cosa è successo",
      "Dove",
      "Cosa cambia la riparazione",
    ]);
    expect(wrapper.find("button").text()).toBe("Ripara");
  });

  it("has no axe violations across the primitives", async () => {
    const wrappers = [
      mount(UiStepper, { props: { steps, active: "team" }, ...plugins() }),
      mount(UiLongRunning, {
        props: {
          title: "Attesa",
          expected: "circa 30 secondi",
          elapsed: 3,
          progress: 20,
          cancellable: true,
        },
        ...plugins(),
      }),
      mount(UiEvidenceDrawer, {
        props: { entries: [{ key: "sha256", value: "abc" }] },
        ...plugins(),
      }),
      mount(UiFindingsCard, {
        props: { rule: "AXE_COLOR_CONTRAST", title: "T", what: "w", where: "d", change: "c" },
        ...plugins(),
      }),
    ];
    for (const wrapper of wrappers) {
      await expectAccessible(wrapper.element);
    }
  });
});
