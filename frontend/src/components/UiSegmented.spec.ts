import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent, h, ref, type PropType } from "vue";
import { describe, expect, it } from "vitest";

import { expectAccessible } from "@/test/axe";
import UiSegmented from "./UiSegmented.vue";
import UiSurface from "./UiSurface.vue";

type View = "text" | "table" | "diagram";

const options = [
  { value: "text" as const, label: "Testo", testId: "view-text" },
  { value: "table" as const, label: "Tabella", testId: "view-table" },
  { value: "diagram" as const, label: "Diagramma", testId: "view-diagram" },
];

const Harness = defineComponent({
  props: { kind: { type: String as PropType<"tabs" | "radio">, default: "tabs" } },
  setup(props) {
    const view = ref<View>("text");
    return () => [
      h(UiSegmented<View>, {
        modelValue: view.value,
        "onUpdate:modelValue": (value: View) => {
          view.value = value;
        },
        options,
        label: "Vista dei requisiti",
        kind: props.kind,
        panelId: "requirements-panel",
      }),
      h("p", { id: "requirements-panel", "data-view": view.value }, view.value),
    ];
  },
});

function segments(wrapper: ReturnType<typeof mount>) {
  return wrapper.findAll("[data-segment]");
}

describe("segmented control", () => {
  it("behaves as a tab list that controls a panel", () => {
    const wrapper = mount(Harness);
    const list = wrapper.get("[role='tablist']");
    expect(list.attributes("aria-label")).toBe("Vista dei requisiti");
    const tabs = segments(wrapper);
    expect(tabs.map((tab) => tab.attributes("role"))).toEqual(["tab", "tab", "tab"]);
    expect(tabs.map((tab) => tab.attributes("aria-selected"))).toEqual(["true", "false", "false"]);
    expect(tabs.map((tab) => tab.attributes("tabindex"))).toEqual(["0", "-1", "-1"]);
    expect(tabs[0]?.attributes("aria-controls")).toBe("requirements-panel");
    expect(tabs.map((tab) => tab.attributes("data-testid"))).toEqual([
      "view-text",
      "view-table",
      "view-diagram",
    ]);
  });

  it("changes the value with a click and keeps the selected one as it is", async () => {
    const wrapper = mount(UiSegmented<View>, {
      props: { modelValue: "text", options, label: "Vista" },
    });
    await segments(wrapper)[0]?.trigger("click");
    expect(wrapper.emitted("update:modelValue")).toBeUndefined();
    await segments(wrapper)[2]?.trigger("click");
    expect(wrapper.emitted("update:modelValue")).toEqual([["diagram"]]);
  });

  it("moves with the arrow keys, Home and End, selecting and focusing the next option", async () => {
    const wrapper = mount(Harness, { attachTo: document.body });
    await segments(wrapper)[0]?.trigger("keydown", { key: "ArrowRight" });
    await flushPromises();
    expect(wrapper.get("[data-view]").text()).toBe("table");
    expect(document.activeElement).toBe(segments(wrapper)[1]?.element);
    expect(segments(wrapper).map((tab) => tab.attributes("tabindex"))).toEqual(["-1", "0", "-1"]);
    await segments(wrapper)[1]?.trigger("keydown", { key: "End" });
    expect(wrapper.get("[data-view]").text()).toBe("diagram");
    await segments(wrapper)[2]?.trigger("keydown", { key: "ArrowRight" });
    expect(wrapper.get("[data-view]").text()).toBe("text");
    await segments(wrapper)[0]?.trigger("keydown", { key: "ArrowLeft" });
    expect(wrapper.get("[data-view]").text()).toBe("diagram");
    await segments(wrapper)[2]?.trigger("keydown", { key: "Home" });
    expect(wrapper.get("[data-view]").text()).toBe("text");
    await segments(wrapper)[0]?.trigger("keydown", { key: "ArrowDown" });
    expect(wrapper.get("[data-view]").text()).toBe("text");
    wrapper.unmount();
  });

  it("behaves as a radio group when asked to, also with the vertical arrows", async () => {
    const wrapper = mount(Harness, { props: { kind: "radio" }, attachTo: document.body });
    expect(wrapper.find("[role='tablist']").exists()).toBe(false);
    expect(wrapper.get("[role='radiogroup']").attributes("aria-label")).toBe("Vista dei requisiti");
    const radios = segments(wrapper);
    expect(radios.map((radio) => radio.attributes("aria-checked"))).toEqual([
      "true",
      "false",
      "false",
    ]);
    expect(radios[0]?.attributes("aria-selected")).toBeUndefined();
    expect(radios[0]?.attributes("aria-controls")).toBeUndefined();
    await radios[0]?.trigger("keydown", { key: "ArrowDown" });
    expect(wrapper.get("[data-view]").text()).toBe("table");
    await segments(wrapper)[1]?.trigger("keydown", { key: "ArrowUp" });
    expect(wrapper.get("[data-view]").text()).toBe("text");
    wrapper.unmount();
  });

  it("keeps the control reachable when no option matches and exposes the id of each tab", () => {
    const wrapper = mount(UiSegmented<string>, {
      props: { modelValue: "none", options: [...options], label: "Vista" },
    });
    expect(segments(wrapper).map((tab) => tab.attributes("tabindex"))).toEqual(["0", "-1", "-1"]);
    expect(wrapper.vm.tabId("table")).toBe(segments(wrapper)[1]?.attributes("id"));
    expect(wrapper.vm.tabId("missing")).toBeUndefined();
  });

  it("uses a light pill for the selected option on a dark surface and an ink one on a light page", () => {
    const light = mount(UiSegmented<View>, {
      props: { modelValue: "table", options, label: "Vista" },
    });
    expect(segments(light)[1]?.classes()).toEqual(expect.arrayContaining(["bg-ink", "text-white"]));
    expect(segments(light)[1]?.classes()).toContain("min-h-11");
    const night = mount(UiSurface, {
      slots: {
        default: () => h(UiSegmented<View>, { modelValue: "table", options, label: "Vista" }),
      },
    });
    expect(segments(night)[1]?.classes()).toEqual(
      expect.arrayContaining(["bg-on-night", "text-ink"]),
    );
    expect(segments(night)[0]?.classes()).toContain("text-on-night");
  });

  it("has no axe violations as tabs and as radios", async () => {
    await expectAccessible(mount(Harness).element);
    await expectAccessible(mount(Harness, { props: { kind: "radio" } }).element);
  });
});
