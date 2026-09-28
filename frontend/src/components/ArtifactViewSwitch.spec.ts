import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import ArtifactViewSwitch from "./ArtifactViewSwitch.vue";
import { expectAccessible } from "@/test/axe";

function mounted(modelValue: "text" | "table" | "diagram" = "text", locale: "en" | "it" = "it") {
  return mount(ArtifactViewSwitch, {
    props: { modelValue, locale, panelId: "panel" },
    attachTo: document.body,
  });
}

describe("ArtifactViewSwitch", () => {
  it("offers text, table and diagram and marks the current view", () => {
    const wrapper = mounted("table");
    const tabs = wrapper.findAll('[role="tab"]');

    expect(wrapper.get('[role="tablist"]').attributes("aria-label")).toBe(
      "Come guardare questo contenuto",
    );
    expect(tabs.map((tab) => tab.text())).toEqual(["Testo", "Tabella", "Diagramma"]);
    expect(tabs.map((tab) => tab.attributes("aria-selected"))).toEqual(["false", "true", "false"]);
    expect(tabs.map((tab) => tab.attributes("tabindex"))).toEqual(["-1", "0", "-1"]);
    expect(tabs.every((tab) => tab.attributes("aria-controls") === "panel")).toBe(true);
    expect(tabs[2]!.attributes("title")).toBe("Guarda come sono collegate le parti");
    wrapper.unmount();
  });

  it("emits the chosen view and stays silent on the current one", async () => {
    const wrapper = mounted("text");

    await wrapper.get('[data-testid="artifact-view-diagram"]').trigger("click");
    await wrapper.get('[data-testid="artifact-view-text"]').trigger("click");

    expect(wrapper.emitted("update:modelValue")).toEqual([["diagram"]]);
    wrapper.unmount();
  });

  it("moves with the arrow, home and end keys and wraps around", async () => {
    const wrapper = mounted("text");
    const text = wrapper.get('[data-testid="artifact-view-text"]');

    await text.trigger("keydown", { key: "ArrowRight" });
    await text.trigger("keydown", { key: "ArrowLeft" });
    await text.trigger("keydown", { key: "End" });
    await wrapper.get('[data-testid="artifact-view-diagram"]').trigger("keydown", { key: "Home" });
    await text.trigger("keydown", { key: "Enter" });

    expect(wrapper.emitted("update:modelValue")).toEqual([["table"], ["diagram"], ["diagram"]]);
    expect(document.activeElement?.getAttribute("data-view")).toBe("text");
    wrapper.unmount();
  });

  it("uses the given label, speaks English and has no axe violations", async () => {
    const wrapper = mount(ArtifactViewSwitch, {
      props: { modelValue: "diagram", label: "Views of the requirements" },
      attachTo: document.body,
    });

    expect(wrapper.get('[role="tablist"]').attributes("aria-label")).toBe(
      "Views of the requirements",
    );
    expect(wrapper.findAll('[role="tab"]').map((tab) => tab.text())).toEqual([
      "Text",
      "Table",
      "Diagram",
    ]);
    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });
});
