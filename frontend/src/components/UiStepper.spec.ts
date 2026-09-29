import { mount } from "@vue/test-utils";
import { h } from "vue";
import { describe, expect, it } from "vitest";

import { createAppI18n } from "@/i18n";
import { expectAccessible } from "@/test/axe";
import UiStepper from "./UiStepper.vue";
import UiSurface from "./UiSurface.vue";

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
    expect(buttons[1]?.attributes("data-active")).toBe("true");
    expect(buttons[0]?.attributes("data-active")).toBeUndefined();
    expect(buttons[2]?.attributes("disabled")).toBeDefined();
    expect(buttons[2]?.text()).toContain("In attesa");
    await buttons[0]?.trigger("click");
    expect(wrapper.emitted("select")).toEqual([["brief"]]);
  });

  it("shows the large step numbers as decoration and keeps the stage attributes", () => {
    const wrapper = mount(UiStepper, {
      props: {
        steps: [
          { key: "a", label: "Brief", status: "approved" as const, index: 0 },
          { key: "b", label: "Squadra", status: "current" as const, index: 1 },
          { key: "c", label: "Twin", status: "pending" as const, index: 2 },
        ],
        active: "a",
      },
      ...plugins(),
    });
    const numbers = wrapper.findAll("[data-step-number]");
    expect(numbers.map((number) => number.text())).toEqual(["01", "02", "03"]);
    expect(numbers[0]?.classes()).toContain("font-display");
    expect(numbers[0]?.element.parentElement?.getAttribute("aria-hidden")).toBe("true");
    expect(numbers[0]?.classes()).toContain("text-ink");
    expect(numbers[1]?.classes()).toContain("text-ink/25");
    expect(wrapper.findAll("[data-stage]").map((node) => node.attributes("data-stage"))).toEqual([
      "0",
      "1",
    ]);
    expect(wrapper.get("[data-testid='stepper']").attributes("aria-label")).toBe("Passi");
  });

  it("lets a step replace its status line with a note", () => {
    const wrapper = mount(UiStepper, {
      props: {
        steps: [{ key: "package", label: "Pacchetto", status: "current" as const, note: "Pronto" }],
        active: "package",
      },
      ...plugins("en"),
    });
    expect(wrapper.get("button").text()).toContain("Pronto");
    expect(wrapper.get("button").text()).not.toContain("Your turn");
  });

  it("uses the colours of the dark timeline inside a dark surface", () => {
    const wrapper = mount(UiSurface, {
      props: { tone: "night" },
      slots: { default: () => h(UiStepper, { steps, active: "team" }) },
      ...plugins(),
    });
    expect(wrapper.get("[data-testid='stepper']").attributes("data-surface-context")).toBe("night");
    const numbers = wrapper.findAll("[data-step-number]");
    expect(numbers[0]?.classes()).toContain("text-petrol-on-night");
    expect(numbers[1]?.classes()).toContain("text-on-night");
    expect(numbers[2]?.classes()).toContain("text-on-night/32");
    expect(wrapper.get("ol").classes()).toContain("border-on-night/14");
  });
});

describe("primitive accessibility", () => {
  it("has no axe violations across the primitives", async () => {
    const wrappers = [
      mount(UiStepper, { props: { steps, active: "team" }, ...plugins() }),
      mount(UiSurface, {
        props: { tone: "night" },
        slots: { default: () => h(UiStepper, { steps, active: "brief" }) },
        ...plugins(),
      }),
    ];
    for (const wrapper of wrappers) {
      await expectAccessible(wrapper.element);
    }
  });
});
