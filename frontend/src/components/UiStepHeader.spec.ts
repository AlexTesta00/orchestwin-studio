import { mount } from "@vue/test-utils";
import { h } from "vue";
import { describe, expect, it } from "vitest";

import { createAppI18n } from "@/i18n";
import { expectAccessible } from "@/test/axe";
import UiStepHeader from "./UiStepHeader.vue";
import UiSurface from "./UiSurface.vue";

function plugins(locale: "en" | "it" = "it") {
  return { global: { plugins: [createAppI18n(locale)] } };
}

const base = {
  step: 5,
  total: 6,
  title: "Design",
  description: "Due alternative, già provate dai twin.",
};

describe("step header", () => {
  it("shows the position, the state of the step, the large title and the description", () => {
    const wrapper = mount(UiStepHeader, { props: { ...base, status: "current" }, ...plugins() });
    expect(wrapper.text()).toContain("Passo 5 di 6");
    expect(wrapper.get("[data-testid='step-status']").text()).toBe("Tocca a te");
    const title = wrapper.get("h1");
    expect(title.text()).toBe("Design");
    expect(title.classes()).toEqual(
      expect.arrayContaining(["font-display", "uppercase", "font-extralight"]),
    );
    expect(wrapper.get("p").text()).toBe("Due alternative, già provate dai twin.");
  });

  it("names every state of the step in words, with a dot where the design has one", () => {
    const approved = mount(UiStepHeader, { props: { ...base, status: "approved" }, ...plugins() });
    const chip = approved.get("[data-testid='step-status']");
    expect(chip.text()).toBe("Approvato da te");
    expect(chip.attributes("data-status")).toBe("approved");
    expect(chip.get("span[aria-hidden]").classes()).toContain("bg-action");
    const pending = mount(UiStepHeader, {
      props: { ...base, status: "pending" },
      ...plugins("en"),
    });
    expect(pending.get("[data-testid='step-status']").text()).toBe("Waiting");
    const rejected = mount(UiStepHeader, {
      props: { ...base, status: "rejected" },
      ...plugins("en"),
    });
    expect(rejected.get("[data-testid='step-status']").text()).toBe("Needs another look");
    const current = mount(UiStepHeader, { props: { ...base, status: "current" }, ...plugins() });
    expect(current.find("[data-testid='step-status'] span[aria-hidden]").exists()).toBe(false);
  });

  it("leaves out the chip and the description when they are not given, and can be a second level title", () => {
    const wrapper = mount(UiStepHeader, {
      props: { step: 1, total: 6, title: "Brief", as: "h2" },
      slots: { default: "<p data-testid='extra'>nota</p>" },
      ...plugins(),
    });
    expect(wrapper.find("[data-testid='step-status']").exists()).toBe(false);
    expect(wrapper.find("h1").exists()).toBe(false);
    expect(wrapper.get("h2").text()).toBe("Brief");
    expect(wrapper.findAll("p").map((node) => node.text())).toEqual(["nota"]);
  });

  it("uses the colours for dark surfaces inside a dark surface", () => {
    const wrapper = mount(UiSurface, {
      slots: { default: () => h(UiStepHeader, { ...base, status: "current" }) },
      ...plugins(),
    });
    expect(wrapper.get("[data-testid='step-status']").classes()).toEqual(
      expect.arrayContaining(["bg-on-night", "text-ink"]),
    );
    expect(wrapper.get("p").classes()).toContain("text-on-night-3");
  });

  it("has no axe violations", async () => {
    const wrapper = mount(UiStepHeader, { props: { ...base, status: "approved" }, ...plugins() });
    await expectAccessible(wrapper.element);
  });
});
