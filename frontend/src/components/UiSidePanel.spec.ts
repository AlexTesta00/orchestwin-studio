import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import { createAppI18n } from "@/i18n";
import UiSidePanel from "./UiSidePanel.vue";

function mountPanel(open = true) {
  return mount(UiSidePanel, {
    props: { open, title: "Provenienza" },
    slots: { default: "<p>catena</p>" },
    global: { plugins: [createAppI18n("it")] },
    attachTo: document.body,
  });
}

describe("side panel", () => {
  it("renders a modal dialog with its title and closes from the button, the veil and Escape", async () => {
    const wrapper = mountPanel();
    const dialog = wrapper.get("[role='dialog']");
    expect(dialog.attributes("aria-modal")).toBe("true");
    expect(document.getElementById(dialog.attributes("aria-labelledby") ?? "")?.textContent).toBe(
      "Provenienza",
    );
    expect(wrapper.text()).toContain("catena");
    await wrapper.get("[data-testid='side-panel-close']").trigger("click");
    await wrapper.get("[data-testid='side-panel-veil']").trigger("click");
    await dialog.trigger("keydown", { key: "Escape" });
    expect(wrapper.emitted("close")).toHaveLength(3);
    wrapper.unmount();
  });

  it("renders nothing while closed", () => {
    const wrapper = mountPanel(false);
    expect(wrapper.find("[data-testid='side-panel']").exists()).toBe(false);
    wrapper.unmount();
  });
});
