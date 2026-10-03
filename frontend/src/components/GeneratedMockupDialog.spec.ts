import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createAppI18n } from "@/i18n";
import { expectAccessible } from "@/test/axe";
import GeneratedMockupDialog, {
  type MockupDocument,
  type MockupObservation,
  type MockupPin,
  type MockupUnanchoredPin,
} from "./GeneratedMockupDialog.vue";
import GeneratedMockupFrame from "./GeneratedMockupFrame.vue";
import source from "./GeneratedMockupDialog.vue?raw";
import { whyContextKey } from "./whyContext";
import { whyDocument, whyNode } from "../test/whyFixtures";

function documentFor(entry: string): MockupDocument {
  return {
    html: `<!doctype html><html lang="it"><body><h1 class="mockup-marker">${entry}</h1><a href="#SCR-002">Avanti</a></body></html>`,
    content_hash: "a".repeat(64),
    source: "review",
    alternative_id: "alt-1",
    title: "Prestiti Biblio",
    entry_screen: entry,
    screens: [
      { code: "SCR-001", title: "Registro dei prestiti", state: "DEFAULT" },
      { code: "SCR-002", title: "Nuovo prestito", state: "DEFAULT" },
      { code: "SCR-003", title: "Prestito registrato", state: "SUCCESS" },
    ],
  };
}

const pins: MockupPin[] = [
  {
    number: 2,
    element_code: "ELM-014",
    screen_code: "SCR-001",
    twin_id: "twin-vb",
    finding_id: "UTF-002",
    severity: "major",
    label: "Ricerca",
  },
  {
    number: 1,
    element_code: "ELM-003",
    screen_code: "SCR-002",
    twin_id: "twin-cp",
    finding_id: "UTF-001",
    severity: "critical",
    label: "Data",
  },
];

const unanchored: MockupUnanchoredPin[] = [
  { number: 3, screen_code: "SCR-001", twin_id: "twin-lb", finding_id: "UTF-003" },
];

const observations: MockupObservation[] = [
  {
    number: 3,
    twin_name: "Lettori della biblioteca",
    severity: "moderate",
    text: "Non si capisce da quanti giorni il libro è in ritardo.",
    place: "Registro dei prestiti",
  },
  {
    number: 1,
    twin_name: "Coordinatrice dei prestiti",
    severity: "critical",
    text: "Manca la data del prestito.",
    place: "Nuovo prestito · Data",
  },
  {
    number: 2,
    twin_name: "Volontari al banco",
    severity: "major",
    text: "Non si può cercare un libro nella lista.",
    place: "Registro dei prestiti · Elenco",
  },
];

let wrapper: VueWrapper | null = null;

function open(props: Partial<InstanceType<typeof GeneratedMockupDialog>["$props"]> = {}) {
  wrapper = mount(GeneratedMockupDialog, {
    props: {
      title: "DES-002 · Registro con tabella",
      document: documentFor("SCR-001"),
      pins,
      unanchored,
      observations,
      ...props,
    },
    global: { plugins: [createAppI18n("it")] },
    attachTo: document.body,
  });
  return wrapper;
}

function query<T extends Element = HTMLElement>(selector: string): T {
  const element = document.body.querySelector<T>(selector);
  if (element === null) {
    throw new Error(`missing ${selector}`);
  }
  return element;
}

function all(selector: string): HTMLElement[] {
  return [...document.body.querySelectorAll<HTMLElement>(selector)];
}

function keydown(target: Element, key: string): void {
  target.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
}

afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
  document.body.innerHTML = "";
});

describe("generated mockup dialog", () => {
  it("opens as a modal window on top of the page, named by its title", () => {
    open();
    const overlay = query("[data-testid='mockup-dialog']");
    expect(overlay.parentElement).toBe(document.body);
    expect(overlay.dataset.surface).toBe("night");
    const dialog = query("[role='dialog']");
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(document.getElementById(dialog.getAttribute("aria-labelledby") ?? "")?.textContent).toBe(
      "DES-002 · Registro con tabella",
    );
  });

  it("shows the mockup only inside the sandboxed frame", () => {
    open();
    const frame = query<HTMLIFrameElement>("[data-testid='mockup-dialog'] iframe");
    expect(frame.getAttribute("sandbox")).toBe("");
    expect(frame.getAttribute("srcdoc")).toBe(
      documentFor("SCR-001").html.replace('href="#SCR-002"', 'href="about:srcdoc#SCR-002"'),
    );
    expect(frame.getAttribute("title")).toBe(
      "Mockup navigabile: DES-002 · Registro con tabella · Registro dei prestiti",
    );
    expect(document.querySelector(".mockup-marker")).toBeNull();
    expect(all("[data-testid='mockup-dialog'] iframe")).toHaveLength(1);
    expect(source).not.toMatch(/v-html|innerHTML|allow-/);
  });

  it("adds precise Studio element controls without changing generated HTML or sandbox permissions", async () => {
    const mockup = documentFor("SCR-001");
    const node = whyNode({
      key: "exact-element",
      kind: "PROTOTYPE_ELEMENT",
      code: "ELM-014",
      title: "Ricerca",
      declared_context: {
        perspectives: [],
        mockup: {
          alternative_id: mockup.alternative_id,
          prototype_id: "prototype",
          screen_code: "SCR-001",
          source: "LATEST",
          document_hashes: { "SCR-001": mockup.content_hash },
        },
      },
    });
    const api = { document: vi.fn().mockResolvedValue(whyDocument([node])), explain: vi.fn() };
    wrapper = mount(GeneratedMockupDialog, {
      props: { title: "Prestiti", document: mockup, locale: "it" },
      global: {
        plugins: [createAppI18n("it")],
        provide: {
          [whyContextKey as symbol]: {
            projectId: () => "project",
            api,
            authorize: <T>(request: (token: string) => Promise<T>) => request("token"),
          },
        },
      },
      attachTo: document.body,
    });
    const frame = query<HTMLIFrameElement>("iframe");
    const html = frame.getAttribute("srcdoc");
    const picker = query<HTMLDetailsElement>('[data-testid="mockup-why-elements"]');
    query('[data-focus-guard="start"]').focus();
    const walkthrough = query<HTMLDetailsElement>('[data-testid="mockup-scenario-walkthrough"]');
    expect(document.activeElement).toBe(walkthrough.querySelector("summary"));
    picker.open = true;
    picker.dispatchEvent(new Event("toggle"));
    await flushPromises();
    expect(query('[data-testid="mockup-why-element"]').textContent).toContain("Ricerca");
    expect(query('[data-testid="mockup-element-why"]').getAttribute("data-why-code")).toBe(
      node.key,
    );
    expect(frame.getAttribute("srcdoc")).toBe(html);
    expect(frame.getAttribute("sandbox")).toBe("");
    expect(wrapper.getComponent(GeneratedMockupFrame).props("html")).toBe(mockup.html);
    expect(api.explain).not.toHaveBeenCalled();
    query('[data-focus-guard="start"]').focus();
    expect(document.activeElement).toBe(walkthrough.querySelector("summary"));
  });

  it("closes with Escape, with its button and with a click outside the window", () => {
    const dialog = open();
    keydown(query("[role='dialog']"), "Escape");
    query("[data-testid='mockup-dialog-close']").click();
    query("[data-testid='mockup-dialog-veil']").click();
    expect(dialog.emitted("close")).toHaveLength(3);
    expect(query("[data-testid='mockup-dialog-close']").getAttribute("aria-label")).toBe(
      "Chiudi il mockup",
    );
  });

  it("takes the focus when it opens and gives it back to the element that opened it", async () => {
    const opener = document.createElement("button");
    opener.textContent = "Prova il mockup";
    document.body.appendChild(opener);
    opener.focus();
    open();
    await flushPromises();
    expect(document.activeElement).toBe(query("[role='dialog']"));
    wrapper?.unmount();
    wrapper = null;
    expect(document.activeElement).toBe(opener);
  });

  it("keeps the focus inside the window in both directions", async () => {
    open();
    await flushPromises();
    const inside = [
      ...query("[role='dialog']").querySelectorAll<HTMLElement>(
        "button, iframe, [tabindex]:not([tabindex='-1'])",
      ),
    ].filter((element) => element.tabIndex >= 0);
    query("[data-focus-guard='end']").focus();
    expect(document.activeElement).toBe(inside[0]);
    expect(document.activeElement).toBe(query("[data-testid='mockup-dialog-close']"));
    query("[data-focus-guard='start']").focus();
    expect(document.activeElement).toBe(inside.at(-1));
  });

  it("asks for another screen from the tabs and marks it while it opens", async () => {
    const dialog = open();
    const tabs = all("[data-testid='mockup-dialog-screen']");
    expect(tabs.map((tab) => tab.textContent?.trim())).toEqual([
      "Registro dei prestiti",
      "Nuovo prestito",
      "Prestito registrato",
    ]);
    expect(tabs.map((tab) => tab.getAttribute("aria-selected"))).toEqual([
      "true",
      "false",
      "false",
    ]);
    expect(query("[role='tablist']").getAttribute("aria-label")).toBe("Schermate del mockup");
    tabs[1]?.click();
    await flushPromises();
    expect(dialog.emitted("screen")).toEqual([["SCR-002"]]);
    expect(
      all("[data-testid='mockup-dialog-screen']").map((tab) => tab.getAttribute("aria-selected")),
    ).toEqual(["false", "true", "false"]);
    await dialog.setProps({ busy: true });
    expect(query("[data-testid='mockup-dialog-busy']").textContent).toContain("Apro la schermata…");
    expect(query("[role='tabpanel']").getAttribute("aria-busy")).toBe("true");
    await dialog.setProps({ busy: false, document: documentFor("SCR-002") });
    expect(document.body.querySelector("[data-testid='mockup-dialog-busy']")).toBeNull();
    expect(query<HTMLIFrameElement>("iframe").getAttribute("srcdoc")).toContain("SCR-002");
    const panel = query("[role='tabpanel']");
    expect(
      document.getElementById(panel.getAttribute("aria-labelledby") ?? "")?.textContent,
    ).toContain("Nuovo prestito");
  });

  it("goes back to the selected tab when the new screen does not arrive", async () => {
    const dialog = open();
    all("[data-testid='mockup-dialog-screen']")[2]?.click();
    await dialog.setProps({ busy: true });
    await dialog.setProps({ busy: false });
    expect(
      all("[data-testid='mockup-dialog-screen']").map((tab) => tab.getAttribute("aria-selected")),
    ).toEqual(["true", "false", "false"]);
  });

  it("starts the open screen again when its tab is chosen a second time", async () => {
    const dialog = open();
    const before = query("iframe");
    all("[data-testid='mockup-dialog-screen']")[0]?.click();
    await flushPromises();
    expect(dialog.emitted("screen")).toBeUndefined();
    const after = query("iframe");
    expect(after).not.toBe(before);
    expect(after.getAttribute("srcdoc")).toBe(before.getAttribute("srcdoc"));
  });

  it("moves between the tabs with the arrow keys, Home and End without opening them", async () => {
    const dialog = open();
    await flushPromises();
    const list = query("[role='tablist']");
    const tabs = () => all("[data-testid='mockup-dialog-screen']");
    expect(tabs().map((tab) => tab.tabIndex)).toEqual([0, -1, -1]);
    tabs()[0]?.focus();
    keydown(list, "ArrowRight");
    await flushPromises();
    expect(document.activeElement).toBe(tabs()[1]);
    expect(tabs().map((tab) => tab.tabIndex)).toEqual([-1, 0, -1]);
    keydown(list, "End");
    await flushPromises();
    expect(document.activeElement).toBe(tabs()[2]);
    keydown(list, "ArrowRight");
    await flushPromises();
    expect(document.activeElement).toBe(tabs()[0]);
    keydown(list, "ArrowLeft");
    await flushPromises();
    expect(document.activeElement).toBe(tabs()[2]);
    keydown(list, "Home");
    await flushPromises();
    expect(document.activeElement).toBe(tabs()[0]);
    expect(dialog.emitted("screen")).toBeUndefined();
  });

  it("lets the person choose the width of the mockup", async () => {
    const dialog = open();
    const group = query("[role='radiogroup']");
    expect(group.getAttribute("aria-label")).toBe("Larghezza del mockup");
    expect(dialog.findComponent(GeneratedMockupFrame).props("width")).toBe("desktop");
    query("[data-testid='mockup-dialog-width-phone']").click();
    await flushPromises();
    expect(dialog.findComponent(GeneratedMockupFrame).props("width")).toBe("phone");
    expect(query("[data-testid='generated-mockup-frame']").dataset.width).toBe("phone");
    query("[data-testid='mockup-dialog-width-tablet']").click();
    await flushPromises();
    expect(query("[data-testid='generated-mockup-frame']").dataset.width).toBe("tablet");
  });

  it("starts with the width of a phone on a narrow screen", () => {
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("max-width") }));
    const dialog = open();
    expect(dialog.findComponent(GeneratedMockupFrame).props("width")).toBe("phone");
  });

  it("lists the observations with the numbers of the pins, in order", () => {
    open();
    const list = query("[data-testid='mockup-dialog-observations']");
    expect(list.textContent).toContain("Osservazioni dei twin");
    expect(list.textContent).toContain("3 osservazioni");
    expect(list.textContent).toContain(
      "I numeri viola sul mockup sono le osservazioni dei twin: ipotesi da pesare, non prove.",
    );
    const items = all("[data-testid='mockup-dialog-observation']");
    expect(items.map((item) => item.dataset.number)).toEqual(["1", "2", "3"]);
    expect(items.map((item) => item.dataset.anchored)).toEqual(["true", "true", "false"]);
    expect(items[0]?.textContent).toContain("Critica");
    expect(items[0]?.textContent).toContain("Coordinatrice dei prestiti");
    expect(items[0]?.textContent).toContain("Manca la data del prestito.");
    expect(items[0]?.textContent).toContain("Dove: Nuovo prestito · Data");
    expect(items[0]?.textContent).toContain("Schermata «Nuovo prestito»");
    expect(items[1]?.textContent).toContain("Importante");
    expect(items[2]?.textContent).toContain(
      "Riguarda tutta la schermata: sul mockup non ha un punto preciso.",
    );
    expect(items[2]?.querySelector("[data-testid='mockup-dialog-number']")?.className).toContain(
      "border-violet-on-night",
    );
  });

  it("opens the screen of an observation that sits on another screen", () => {
    const dialog = open();
    const buttons = all("[data-testid='mockup-dialog-show-screen']");
    expect(buttons).toHaveLength(1);
    expect(buttons[0]?.textContent?.trim()).toBe("Mostra la schermata «Nuovo prestito»");
    buttons[0]?.click();
    expect(dialog.emitted("screen")).toEqual([["SCR-002"]]);
  });

  it("gives the whole width to the mockup when the twins have not reviewed it", () => {
    open({ pins: [], unanchored: [], observations: [] });
    expect(document.body.querySelector("[data-testid='mockup-dialog-observations']")).toBeNull();
    expect(query("[data-testid='mockup-dialog-stage']").className).toContain("flex-1");
  });

  it("waits for the document and says when there is none", async () => {
    const dialog = open({ document: null, busy: true });
    expect(query("[data-testid='mockup-dialog-stage']").textContent).toContain(
      "Apro la schermata…",
    );
    expect(document.body.querySelector("iframe")).toBeNull();
    expect(all("[data-testid='mockup-dialog-screen']")).toHaveLength(0);
    await dialog.setProps({ busy: false });
    expect(query("[data-testid='mockup-dialog-stage']").textContent).toContain(
      "Il mockup non è ancora disponibile.",
    );
  });

  it("keeps the focus on the chosen tab while its screen opens and when its frame is made again", async () => {
    const dialog = open();
    await flushPromises();
    query("[data-testid='mockup-dialog-width-phone']").click();
    await flushPromises();
    const tab = () => query("[data-screen='SCR-002']");
    tab().focus();
    tab().click();
    await flushPromises();
    expect(dialog.emitted("screen")).toEqual([["SCR-002"]]);
    await dialog.setProps({ busy: true, document: null });
    await flushPromises();
    expect(all("[data-testid='mockup-dialog-screen']")).toHaveLength(3);
    expect(document.activeElement).toBe(tab());
    await dialog.setProps({ busy: false, document: documentFor("SCR-002") });
    await flushPromises();
    expect(document.activeElement).toBe(tab());
    expect(tab().getAttribute("aria-selected")).toBe("true");
    const frame = query("iframe");
    tab().click();
    await flushPromises();
    expect(query("iframe")).not.toBe(frame);
    expect(document.activeElement).toBe(tab());
  });

  it("brings the focus back inside when it leaves the window", async () => {
    open();
    await flushPromises();
    const outside = document.createElement("button");
    outside.textContent = "Fuori";
    document.body.appendChild(outside);
    outside.focus();
    await flushPromises();
    expect(document.activeElement).toBe(query("[role='dialog']"));

    const show = query("[data-testid='mockup-dialog-show-screen']");
    expect(show.textContent?.trim()).toBe("Mostra la schermata «Nuovo prestito»");
    show.focus();
    show.click();
    await flushPromises();
    expect(show.isConnected).toBe(false);
    expect(document.activeElement).toBe(query("[data-screen='SCR-002']"));
  });

  it("closes with Escape wherever the focus is and stops listening once it is closed", async () => {
    const onClose = vi.fn();
    const dialog = open({ onClose });
    await flushPromises();
    const escape = () =>
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
    document.dispatchEvent(escape());
    expect(onClose).toHaveBeenCalledTimes(1);
    document.body.dispatchEvent(escape());
    expect(onClose).toHaveBeenCalledTimes(2);
    query("[data-screen='SCR-003']").dispatchEvent(escape());
    expect(onClose).toHaveBeenCalledTimes(3);
    dialog.unmount();
    wrapper = null;
    document.dispatchEvent(escape());
    expect(onClose).toHaveBeenCalledTimes(3);
  });

  it("wraps the tabs on more lines and cuts a long title, keeping the whole title in its name", () => {
    const long: MockupDocument = {
      ...documentFor("SCR-001"),
      screens: Array.from({ length: 6 }, (_item, index) => ({
        code: `SCR-00${index + 1}`,
        title: `Schermata ${index + 1} con un titolo davvero molto lungo da tagliare`,
        state: "DEFAULT",
      })),
    };
    open({ document: long, observations: [], pins: [], unanchored: [] });
    const list = query("[role='tablist']");
    expect(list.className).toContain("flex-wrap");
    expect(list.className).not.toContain("overflow-x-auto");
    const tabs = all("[data-testid='mockup-dialog-screen']");
    expect(tabs).toHaveLength(6);
    for (const [index, tab] of tabs.entries()) {
      const title = long.screens[index]?.title ?? "";
      expect(tab.getAttribute("title")).toBe(title);
      expect(tab.textContent?.trim()).toBe(title);
      expect(tab.className).toContain("max-w-[calc(28ch+1.75rem)]");
      expect(tab.className).not.toContain("whitespace-nowrap");
      expect(tab.querySelector("[data-testid='mockup-dialog-screen-title']")?.className).toContain(
        "truncate",
      );
    }
  });

  it("names screens and elements by their titles in the texts of the observations", () => {
    open({
      observations: [
        {
          number: 1,
          twin_name: "Coordinatrice dei prestiti",
          severity: "critical",
          text: "In SCR-002 manca ELM-003 e da SCR-009 non si torna indietro.",
          place: "SCR-002 Nuovo prestito · ELM-003 Data del prestito",
        },
      ],
    });
    const item = all("[data-testid='mockup-dialog-observation']")[0];
    expect(item?.textContent).toContain(
      "In «Nuovo prestito» manca «Data del prestito» e da SCR-009 non si torna indietro.",
    );
    expect(item?.textContent).toContain("Dove: Nuovo prestito · Data del prestito");
    expect(item?.textContent).not.toContain("ELM-003");
  });

  it("speaks English when the page is in English", () => {
    open({ locale: "en" });
    expect(query("[data-testid='mockup-dialog-close']").getAttribute("aria-label")).toBe(
      "Close the mockup",
    );
    expect(query("[data-testid='mockup-dialog-observations']").textContent).toContain(
      "What the twins noticed",
    );
    expect(all("[data-testid='mockup-dialog-observation']")[0]?.textContent).toContain("Critical");
  });

  it("has no axe violations with and without observations", async () => {
    open();
    await expectAccessible(query("[data-testid='mockup-dialog']"), { iframes: false });
    wrapper?.unmount();
    open({ observations: [], document: null, busy: true });
    await expectAccessible(query("[data-testid='mockup-dialog']"), { iframes: false });
  });
});
