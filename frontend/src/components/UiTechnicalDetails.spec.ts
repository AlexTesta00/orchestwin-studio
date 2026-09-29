import { mount } from "@vue/test-utils";
import { h } from "vue";
import { describe, expect, it } from "vitest";

import { createAppI18n } from "@/i18n";
import { expectAccessible } from "@/test/axe";
import UiSurface from "./UiSurface.vue";
import UiTechnicalDetails from "./UiTechnicalDetails.vue";

const rows = [
  { label: "Hash del contenuto", value: "9eb3799e49ea1867" },
  { label: "Provenienza", value: "Dialogo del 28 set 2026" },
];

function mountDetails(locale: "en" | "it" = "it") {
  return mount(UiTechnicalDetails, {
    props: { summary: "Versione 2 · in attesa della tua decisione", rows },
    slots: { default: "<p data-testid='extra'>Assistenti simulati</p>" },
    global: { plugins: [createAppI18n(locale)] },
  });
}

describe("technical details", () => {
  it("starts closed behind a real button that says what it hides", () => {
    const wrapper = mountDetails();
    const toggle = wrapper.get("button");
    expect(toggle.attributes("type")).toBe("button");
    expect(toggle.attributes("aria-expanded")).toBe("false");
    expect(toggle.attributes("aria-controls")).toBeUndefined();
    expect(toggle.text()).toContain("Versione 2 · in attesa della tua decisione");
    expect(toggle.text()).toContain("Dettagli tecnici");
    expect(wrapper.find("[data-testid='step-technical-details-content']").exists()).toBe(false);
    expect(wrapper.find("[data-testid='extra']").exists()).toBe(false);
  });

  it("opens the rows and the slot, and closes again", async () => {
    const wrapper = mountDetails("en");
    const toggle = wrapper.get("button");
    await toggle.trigger("click");
    expect(toggle.attributes("aria-expanded")).toBe("true");
    const content = wrapper.get("[data-testid='step-technical-details-content']");
    expect(toggle.attributes("aria-controls")).toBe(content.attributes("id"));
    expect(toggle.text()).toContain("Hide technical details");
    expect(wrapper.findAll("dt").map((node) => node.text())).toEqual([
      "Hash del contenuto",
      "Provenienza",
    ]);
    expect(wrapper.findAll("dd").map((node) => node.text())).toEqual([
      "9eb3799e49ea1867",
      "Dialogo del 28 set 2026",
    ]);
    expect(wrapper.get("[data-testid='extra']").text()).toBe("Assistenti simulati");
    await toggle.trigger("click");
    expect(toggle.attributes("aria-expanded")).toBe("false");
    expect(wrapper.find("[data-testid='step-technical-details-content']").exists()).toBe(false);
  });

  it("renders only the slot when there are no rows", async () => {
    const wrapper = mount(UiTechnicalDetails, {
      props: { summary: "Versione 1" },
      slots: { default: "<p>solo testo</p>" },
      global: { plugins: [createAppI18n("it")] },
    });
    await wrapper.get("button").trigger("click");
    expect(wrapper.find("dl").exists()).toBe(false);
    expect(wrapper.text()).toContain("solo testo");
  });

  it("uses the colours for dark surfaces inside a dark surface", async () => {
    const wrapper = mount(UiSurface, {
      slots: { default: () => h(UiTechnicalDetails, { summary: "Versione 2", rows }) },
      global: { plugins: [createAppI18n("it")] },
    });
    expect(wrapper.get("[data-testid='step-technical-details']").classes()).toContain(
      "border-night-line",
    );
    expect(wrapper.get("button").classes()).toContain("text-on-night-3");
    await wrapper.get("button").trigger("click");
    expect(wrapper.get("[data-testid='step-technical-details-content']").classes()).toContain(
      "bg-night-raised",
    );
  });

  it("has no axe violations closed and open", async () => {
    const wrapper = mountDetails();
    await expectAccessible(wrapper.element);
    await wrapper.get("button").trigger("click");
    await expectAccessible(wrapper.element);
  });
});
