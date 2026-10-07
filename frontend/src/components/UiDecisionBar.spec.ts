import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import { createAppI18n } from "@/i18n";
import { expectAccessible } from "@/test/axe";
import UiDecisionBar from "./UiDecisionBar.vue";
import styles from "../styles/tailwind.css?raw";

type BarProps = InstanceType<typeof UiDecisionBar>["$props"];

function mountBar(props: Partial<BarProps> = {}, locale: "en" | "it" = "it") {
  return mount(UiDecisionBar, {
    props: {
      description: "Approvando, il designer prepara due alternative.",
      primaryLabel: "Approva i requisiti",
      ...props,
    },
    global: { plugins: [createAppI18n(locale)] },
    attachTo: document.body,
  });
}

function focusOrder(wrapper: ReturnType<typeof mountBar>): (string | undefined)[] {
  const root = wrapper.element as HTMLElement;
  return Array.from(root.querySelectorAll<HTMLElement>("button, textarea")).map(
    (node) => node.dataset.testid,
  );
}

describe("decision bar", () => {
  it("names the decision as a region and offers the two actions in the natural order", async () => {
    const wrapper = mountBar();
    const region = wrapper.get("section");
    const title = document.getElementById(region.attributes("aria-labelledby") ?? "");
    expect(title?.textContent).toBe("La decisione è tua");
    expect(wrapper.text()).toContain("Approvando, il designer prepara due alternative.");
    expect(wrapper.get("[data-testid='decision-secondary']").text()).toBe("Chiedi modifiche");
    expect(wrapper.get("[data-testid='decision-primary']").text()).toBe("Approva i requisiti");
    expect(focusOrder(wrapper)).toEqual(["decision-secondary", "decision-primary"]);
    await wrapper.get("[data-testid='decision-primary']").trigger("click");
    expect(wrapper.emitted("primary")).toHaveLength(1);
    wrapper.unmount();
  });

  it("stays in the flow of the page, sticking to the bottom of the view, so it never hides the end of the step", () => {
    const wrapper = mountBar();
    const classes = wrapper.get("section").classes();
    expect(classes).toEqual(expect.arrayContaining(["sticky", "bottom-4", "mt-10"]));
    expect(classes).not.toContain("fixed");
    expect(wrapper.get("section").attributes("data-surface")).toBe("night");
    wrapper.unmount();
  });

  it("marks its root so the page scrolls a focused control above the bar", () => {
    const wrapper = mountBar();
    const root = wrapper.element as HTMLElement;
    expect(root.getAttribute("data-ui-decision-bar")).toBe("");
    expect(wrapper.classes()).toEqual(expect.arrayContaining(["sticky", "bottom-4"]));
    const base = styles.slice(styles.indexOf("@layer base")).replace(/\s+/g, " ");
    expect(base).toContain("html:has([data-ui-decision-bar]) { scroll-padding-bottom: 9rem; }");
    wrapper.unmount();
  });

  it("accepts its own title and secondary label", () => {
    const wrapper = mountBar({ title: "Decide you", secondaryLabel: "Change it" }, "en");
    expect(wrapper.text()).toContain("Decide you");
    expect(wrapper.get("[data-testid='decision-secondary']").text()).toBe("Change it");
    wrapper.unmount();
  });

  it("opens a labelled note, refuses an empty request and sends the written one", async () => {
    const wrapper = mountBar();
    await wrapper.get("[data-testid='decision-secondary']").trigger("click");
    await flushPromises();
    expect(wrapper.emitted("secondary")).toHaveLength(1);
    const note = wrapper.get("textarea");
    expect(document.activeElement).toBe(note.element);
    const label = wrapper.get(`label[for="${note.attributes("id")}"]`);
    expect(label.text()).toBe("Che cosa vuoi cambiare?");
    expect(focusOrder(wrapper)).toEqual(["decision-note", "decision-cancel", "decision-send"]);
    const send = wrapper.get("[data-testid='decision-send']");
    expect(send.attributes("disabled")).toBeDefined();
    await note.setValue("   ");
    expect(send.attributes("disabled")).toBeDefined();
    await send.trigger("click");
    expect(wrapper.emitted("request")).toBeUndefined();
    await note.setValue("  Aggiungi la ricerca per titolo.  ");
    expect(send.attributes("disabled")).toBeUndefined();
    await send.trigger("click");
    await flushPromises();
    expect(wrapper.emitted("request")).toEqual([["Aggiungi la ricerca per titolo."]]);
    await wrapper.vm.completeRequest();
    await flushPromises();
    expect(wrapper.find("textarea").exists()).toBe(false);
    expect(document.activeElement).toBe(wrapper.get("[data-testid='decision-secondary']").element);
    await wrapper.get("[data-testid='decision-secondary']").trigger("click");
    expect((wrapper.get("textarea").element as HTMLTextAreaElement).value).toBe("");
    wrapper.unmount();
  });

  it("keeps the note and its text while the parent works and after a failed request", async () => {
    const wrapper = mountBar();
    await wrapper.get("[data-testid='decision-secondary']").trigger("click");
    await wrapper.get("textarea").setValue("Aggiungi la ricerca per titolo.");
    await wrapper.get("[data-testid='decision-send']").trigger("click");
    expect(wrapper.emitted("request")).toEqual([["Aggiungi la ricerca per titolo."]]);
    await wrapper.setProps({ busy: true });
    const note = wrapper.get("textarea");
    expect((note.element as HTMLTextAreaElement).value).toBe("Aggiungi la ricerca per titolo.");
    expect(note.attributes("disabled")).toBeDefined();
    expect(wrapper.get("[data-testid='decision-send']").attributes("disabled")).toBeDefined();
    expect(wrapper.get("[data-testid='decision-cancel']").attributes("disabled")).toBeDefined();
    await wrapper.get("[data-testid='decision-send']").trigger("click");
    expect(wrapper.emitted("request")).toHaveLength(1);
    await wrapper.setProps({ busy: false });
    await flushPromises();
    expect((wrapper.get("textarea").element as HTMLTextAreaElement).value).toBe(
      "Aggiungi la ricerca per titolo.",
    );
    expect(document.activeElement).toBe(wrapper.get("textarea").element);
    await wrapper.get("[data-testid='decision-send']").trigger("click");
    expect(wrapper.emitted("request")).toEqual([
      ["Aggiungi la ricerca per titolo."],
      ["Aggiungi la ricerca per titolo."],
    ]);
    await wrapper.setProps({ busy: true });
    await wrapper.vm.completeRequest();
    await wrapper.setProps({ busy: false });
    await flushPromises();
    expect(wrapper.find("textarea").exists()).toBe(false);
    expect(document.activeElement).toBe(wrapper.get("[data-testid='decision-secondary']").element);
    wrapper.unmount();
  });

  it("hides the secondary action and the note when the step has no request to make", async () => {
    const wrapper = mountBar({ secondaryLabel: null });
    expect(wrapper.find("[data-testid='decision-secondary']").exists()).toBe(false);
    expect(wrapper.find("textarea").exists()).toBe(false);
    expect(focusOrder(wrapper)).toEqual(["decision-primary"]);
    await wrapper.get("[data-testid='decision-primary']").trigger("click");
    expect(wrapper.emitted("primary")).toHaveLength(1);
    await wrapper.setProps({ secondaryLabel: undefined });
    expect(wrapper.get("[data-testid='decision-secondary']").text()).toBe("Chiedi modifiche");
    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });

  it("closes an open note when the request stops making sense and moves the focus to the decision", async () => {
    const wrapper = mountBar();
    await wrapper.get("[data-testid='decision-secondary']").trigger("click");
    await wrapper.get("textarea").setValue("Una nota");
    await wrapper.setProps({ secondaryLabel: null });
    await flushPromises();
    expect(wrapper.find("textarea").exists()).toBe(false);
    expect(document.activeElement).toBe(wrapper.get("[data-testid='decision-primary']").element);
    await wrapper.setProps({ secondaryLabel: "Chiedi modifiche" });
    await wrapper.get("[data-testid='decision-secondary']").trigger("click");
    expect((wrapper.get("textarea").element as HTMLTextAreaElement).value).toBe("");
    wrapper.unmount();
  });

  it("uses the placeholder of the step for the note and the shared one otherwise", async () => {
    const wrapper = mountBar({ requestPlaceholder: "La richiesta resta registrata." });
    await wrapper.get("[data-testid='decision-secondary']").trigger("click");
    expect(wrapper.get("textarea").attributes("placeholder")).toBe(
      "La richiesta resta registrata.",
    );
    wrapper.unmount();
    const shared = mountBar();
    await shared.get("[data-testid='decision-secondary']").trigger("click");
    expect(shared.get("textarea").attributes("placeholder")).toBe("Scrivi che cosa vuoi cambiare…");
    shared.unmount();
  });

  it("ignores a confirmation when no request is open", async () => {
    const wrapper = mountBar();
    const outside = document.createElement("button");
    document.body.appendChild(outside);
    outside.focus();
    await wrapper.vm.completeRequest();
    await flushPromises();
    expect(document.activeElement).toBe(outside);
    expect(wrapper.find("textarea").exists()).toBe(false);
    outside.remove();
    wrapper.unmount();
  });

  it("closes the note without sending from the cancel button and from Escape", async () => {
    const wrapper = mountBar();
    await wrapper.get("[data-testid='decision-secondary']").trigger("click");
    await wrapper.get("textarea").setValue("Una nota");
    await wrapper.get("[data-testid='decision-cancel']").trigger("click");
    await flushPromises();
    expect(wrapper.find("textarea").exists()).toBe(false);
    expect(document.activeElement).toBe(wrapper.get("[data-testid='decision-secondary']").element);
    await wrapper.get("[data-testid='decision-secondary']").trigger("click");
    await wrapper.get("textarea").trigger("keydown", { key: "Escape" });
    await flushPromises();
    expect(wrapper.find("textarea").exists()).toBe(false);
    expect(wrapper.emitted("request")).toBeUndefined();
    wrapper.unmount();
  });

  it("blocks the approval when disabled and every action while busy", async () => {
    const wrapper = mountBar({ disabled: true });
    expect(wrapper.get("[data-testid='decision-primary']").attributes("disabled")).toBeDefined();
    expect(
      wrapper.get("[data-testid='decision-secondary']").attributes("disabled"),
    ).toBeUndefined();
    await wrapper.setProps({ disabled: false, busy: true });
    expect(wrapper.get("section").attributes("aria-busy")).toBe("true");
    expect(wrapper.get("[role='status']").text()).toBe("Operazione in corso…");
    expect(wrapper.get("[data-testid='decision-primary']").attributes("disabled")).toBeDefined();
    expect(wrapper.get("[data-testid='decision-secondary']").attributes("disabled")).toBeDefined();
    await wrapper.setProps({ busy: false });
    expect(wrapper.get("section").attributes("aria-busy")).toBeUndefined();
    expect(wrapper.get("[role='status']").text()).toBe("");
    wrapper.unmount();
  });

  it("uses the pills of the dark design", () => {
    const wrapper = mountBar();
    expect(wrapper.get("[data-testid='decision-primary']").classes()).toEqual(
      expect.arrayContaining(["rounded-pill", "bg-on-night", "text-ink"]),
    );
    expect(wrapper.get("[data-testid='decision-secondary']").classes()).toContain(
      "border-on-night/32",
    );
    wrapper.unmount();
  });

  it("has no axe violations in both states", async () => {
    const wrapper = mountBar();
    await expectAccessible(wrapper.element);
    await wrapper.get("[data-testid='decision-secondary']").trigger("click");
    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });
});
