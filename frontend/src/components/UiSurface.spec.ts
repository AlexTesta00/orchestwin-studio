import { mount } from "@vue/test-utils";
import { defineComponent, h, type PropType } from "vue";
import { describe, expect, it } from "vitest";

import { createAppI18n } from "@/i18n";
import { expectAccessible } from "@/test/axe";
import UiButton from "./UiButton.vue";
import UiSurface, { useSurface } from "./UiSurface.vue";

const Probe = defineComponent({
  props: { surface: { type: String as PropType<"night" | "light">, default: undefined } },
  setup(props) {
    const context = useSurface(() => props.surface);
    return () => h("span", { "data-probe": context.value }, context.value);
  },
});

describe("surface", () => {
  it("draws the dark rounded container with the text colours for dark surfaces", () => {
    const wrapper = mount(UiSurface, { slots: { default: "<p>contenuto</p>" } });
    expect(wrapper.element.tagName).toBe("DIV");
    expect(wrapper.attributes("data-surface")).toBe("night");
    expect(wrapper.classes()).toEqual(
      expect.arrayContaining(["bg-night", "text-on-night", "rounded-stage", "isolate", "px-6"]),
    );
    expect(wrapper.text()).toBe("contenuto");
  });

  it("offers the panel and light tones, every radius and an unpadded variant", () => {
    const panel = mount(UiSurface, { props: { tone: "panel", radius: "sheet", as: "section" } });
    expect(panel.element.tagName).toBe("SECTION");
    expect(panel.classes()).toEqual(
      expect.arrayContaining(["bg-night-panel", "text-on-night", "rounded-sheet", "p-6"]),
    );
    const light = mount(UiSurface, { props: { tone: "light", radius: "tile", padded: false } });
    expect(light.attributes("data-surface")).toBe("light");
    expect(light.classes()).toEqual(
      expect.arrayContaining(["bg-surface", "text-ink", "border-line", "rounded-tile"]),
    );
    expect(light.classes()).not.toContain("p-5");
    const field = mount(UiSurface, { props: { radius: "field" } });
    expect(field.classes()).toEqual(expect.arrayContaining(["rounded-field", "px-3.5"]));
  });

  it("tells the components inside which surface they sit on", () => {
    const wrapper = mount(
      {
        render: () => [
          h(Probe, { "data-testid": "outside" }),
          h(UiSurface, { tone: "night" }, () => [
            h(Probe),
            h(UiSurface, { tone: "light", "data-testid": "inner" }, () => h(Probe)),
            h(Probe, { surface: "light" }),
          ]),
          h(UiSurface, { tone: "panel" }, () => h(Probe)),
        ],
      },
      { global: { plugins: [createAppI18n("it")] } },
    );
    expect(wrapper.findAll("[data-probe]").map((node) => node.text())).toEqual([
      "light",
      "night",
      "light",
      "light",
      "night",
    ]);
  });

  it("makes the main action a light pill inside the dark surface", () => {
    const wrapper = mount(UiSurface, {
      slots: { default: () => h(UiButton, () => "Entra nello Studio") },
    });
    expect(wrapper.get("button").classes()).toEqual(
      expect.arrayContaining(["rounded-pill", "bg-on-night", "text-ink"]),
    );
  });

  it("has no axe violations", async () => {
    const wrapper = mount(UiSurface, {
      props: { as: "section" },
      attrs: { "aria-label": "Progetti" },
      slots: {
        default: () => [h("h2", "I tuoi progetti"), h(UiButton, () => "Nuovo progetto")],
      },
    });
    await expectAccessible(wrapper.element);
  });
});
