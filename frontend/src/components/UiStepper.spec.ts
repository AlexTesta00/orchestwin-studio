import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import { createAppI18n } from "@/i18n";
import { expectAccessible } from "@/test/axe";
import UiStepper from "./UiStepper.vue";

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

describe("primitive accessibility", () => {
  it("has no axe violations across the primitives", async () => {
    const wrappers = [mount(UiStepper, { props: { steps, active: "team" }, ...plugins() })];
    for (const wrapper of wrappers) {
      await expectAccessible(wrapper.element);
    }
  });
});
