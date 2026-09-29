import { DOMWrapper, flushPromises, mount } from "@vue/test-utils";
import { h, Teleport } from "vue";
import { describe, expect, it } from "vitest";

import { createAppI18n } from "@/i18n";
import UiButton from "./UiButton.vue";
import UiSidePanel from "./UiSidePanel.vue";
import UiSurface from "./UiSurface.vue";
import { expectAccessible } from "@/test/axe";

function mountPanel(open = true, surface: "light" | "night" | undefined = undefined) {
  return mount(UiSidePanel, {
    props: surface ? { open, title: "Provenienza", surface } : { open, title: "Provenienza" },
    slots: { default: () => [h("p", "catena"), h(UiButton, () => "Azione")] },
    global: { plugins: [createAppI18n("it")] },
    attachTo: document.body,
  });
}

function inBody(selector: string): DOMWrapper<HTMLElement> {
  const element = document.body.querySelector<HTMLElement>(selector);
  if (element === null) {
    throw new Error(`Missing ${selector}`);
  }
  return new DOMWrapper(element);
}

describe("side panel", () => {
  it("renders a modal dialog with its title and closes from the button, the veil and Escape", async () => {
    const wrapper = mountPanel();
    const dialog = inBody("[role='dialog']");
    expect(dialog.attributes("aria-modal")).toBe("true");
    expect(document.getElementById(dialog.attributes("aria-labelledby") ?? "")?.textContent).toBe(
      "Provenienza",
    );
    expect(dialog.text()).toContain("catena");
    expect(inBody("[data-testid='side-panel-close']").attributes("aria-label")).toBe("Chiudi");
    await inBody("[data-testid='side-panel-close']").trigger("click");
    await inBody("[data-testid='side-panel-veil']").trigger("click");
    await dialog.trigger("keydown", { key: "Escape" });
    expect(wrapper.emitted("close")).toHaveLength(3);
    wrapper.unmount();
  });

  it("renders nothing while closed", () => {
    const wrapper = mountPanel(false);
    expect(document.body.querySelector("[data-testid='side-panel']")).toBeNull();
    wrapper.unmount();
  });

  it("stays light by default and becomes a dark panel on request, together with its content", () => {
    const light = mountPanel();
    expect(inBody("[role='dialog']").attributes("data-surface")).toBe("light");
    expect(inBody("[role='dialog']").classes()).toContain("bg-surface");
    expect(inBody("[role='dialog'] button:not([data-testid])").classes()).toContain("bg-action");
    light.unmount();
    const night = mountPanel(true, "night");
    expect(inBody("[role='dialog']").attributes("data-surface")).toBe("night");
    expect(inBody("[data-testid='side-panel']").attributes("data-surface")).toBe("night");
    expect(inBody("[role='dialog']").classes()).toContain("bg-night-panel");
    expect(inBody("[role='dialog'] button:not([data-testid])").classes()).toContain("bg-on-night");
    night.unmount();
  });

  it("has no axe violations while open", async () => {
    const wrapper = mountPanel(true);
    await expectAccessible(inBody("[data-testid='side-panel']").element);
    wrapper.unmount();
    const night = mountPanel(true, "night");
    await expectAccessible(inBody("[data-testid='side-panel']").element);
    night.unmount();
  });

  it("returns the focus to the element that opened it", async () => {
    const opener = document.createElement("button");
    document.body.appendChild(opener);
    opener.focus();
    const wrapper = mountPanel(false);
    await wrapper.setProps({ open: true });
    await flushPromises();
    expect(document.activeElement).toBe(inBody("[role='dialog']").element);
    await wrapper.setProps({ open: false });
    await flushPromises();
    expect(document.activeElement).toBe(opener);
    wrapper.unmount();
    opener.remove();
  });

  it("keeps the focus inside the panel while it is open", async () => {
    const wrapper = mountPanel(false);
    await wrapper.setProps({ open: true });
    await flushPromises();
    const dialog = inBody("[role='dialog']");
    const close = inBody("[data-testid='side-panel-close']");
    const action = inBody("[role='dialog'] button:not([data-testid])");
    await dialog.trigger("keydown", { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(action.element);
    await action.trigger("keydown", { key: "Tab" });
    expect(document.activeElement).toBe(close.element);
    await close.trigger("keydown", { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(action.element);
    wrapper.unmount();
  });

  it("covers the whole page even when it is opened inside a surface", async () => {
    const wrapper = mount(
      {
        render: () =>
          h(UiSurface, { "data-testid": "surface" }, () => [
            h("p", "Pagina"),
            h(UiSidePanel, { open: true, title: "Provenienza", surface: "night" }, () =>
              h("p", "catena"),
            ),
          ]),
      },
      { global: { plugins: [createAppI18n("it")] }, attachTo: document.body },
    );
    await flushPromises();
    const overlay = inBody("[data-testid='side-panel']");
    expect(overlay.element.parentElement).toBe(document.body);
    expect(wrapper.get("[data-testid='surface']").element.contains(overlay.element)).toBe(false);
    expect(overlay.classes()).toEqual(expect.arrayContaining(["fixed", "inset-0", "z-50"]));
    wrapper.unmount();
    expect(document.body.querySelector("[data-testid='side-panel']")).toBeNull();
  });

  it("stays in place when a parent has already moved it to the body", async () => {
    const wrapper = mount(
      {
        render: () =>
          h(Teleport, { to: "body" }, [
            h(UiSidePanel, { open: true, title: "Provenienza" }, () => h("p", "catena")),
          ]),
      },
      { global: { plugins: [createAppI18n("it")] }, attachTo: document.body },
    );
    await flushPromises();
    const panel = wrapper.findComponent(UiSidePanel);
    expect(panel.get("[role='dialog']").text()).toContain("catena");
    expect(inBody("[data-testid='side-panel']").element.parentElement?.dataset.testid).toBe(
      "side-panel-host",
    );
    wrapper.unmount();
  });
});
