import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";

import { createAppI18n } from "@/i18n";
import { expectAccessible } from "@/test/axe";
import {
  BASE_DESIGN_PACKAGE,
  DESIGN_ALTERNATIVE_ID,
  DESIGN_PROJECT_ID,
  PROPOSED_DESIGN_DIFF,
  UNSELECTED_DESIGN_VERSION,
} from "@/test/designFixtures";
import { DesignApiError, type DesignApi } from "../api/design";
import { DesignIterationsApiError, type DesignIterationsApi } from "../api/designIterations";
import { DesignLoopApiError, type DesignLoopApi } from "../api/designLoop";
import { useDesignStore } from "../stores/design";
import { useDesignIterationsStore } from "../stores/designIterations";
import { useDesignLoopStore } from "../stores/designLoop";
import { POLL_INTERVAL_MILLISECONDS, type AuthorizedMockupRequest } from "../stores/designMockups";
import type {
  DesignPackageDiffPayload,
  DesignPackageVersionPayload,
  DesignRevisionPayload,
} from "../types/design";
import type {
  DesignEvaluationRunPayload,
  SyntheticFindingPayload,
  SyntheticFindingSeverity,
} from "../types/designLoop";
import type { GenerationJobPayload, MockupResultPayload } from "../types/designMockups";
import MockupInspector, {
  changeTarget,
  describeElement,
  elementText,
  markedElements,
  requirementsOf,
  screenElements,
  visibleScreen,
} from "./MockupInspector.vue";
import source from "./MockupInspector.vue?raw";

const MOCKUP = [
  "<!doctype html><html lang='it'><head><title>Prestiti</title></head><body class='ot-mockup'>",
  "<section class='ot-screen' id='SCR-001' aria-label='Registro' data-entry>",
  "<main data-req='REQ-001, REQ-004'>",
  "<h1 data-elm='ELM-001'>Registro dei prestiti</h1>",
  "<a href='about:srcdoc#SCR-002' class='btn' data-elm='ELM-002'>Nuovo <b>prestito</b></a>",
  "<label for='cerca'>Cerca un libro</label><input id='cerca' data-elm='ELM-003' placeholder='Titolo'>",
  "<table><tbody><tr data-elm='ELM-004' data-req='REQ-002 REQ-003'>",
  "<td>Rossi<span class='ot-pin' aria-label='Osservazione 2'>2</span></td><td>12 giorni</td>",
  "</tr></tbody></table>",
  "</main></section>",
  "<section class='ot-screen' id='SCR-002' aria-label='Nuovo prestito'>",
  "<h1 data-elm='ELM-005'>Nuovo prestito</h1>",
  "<button type='button' data-elm='ELM-006' data-req='REQ-005'>Prenota</button>",
  "</section></body></html>",
].join("");

const SCREENS = [
  { code: "SCR-001", title: "Registro dei prestiti" },
  { code: "SCR-002", title: "Nuovo prestito" },
];

const HASH = "2".repeat(64);

const VERSION: DesignPackageVersionPayload = {
  ...UNSELECTED_DESIGN_VERSION,
  id: "00000000-0000-4000-8000-222222222222",
  content_hash: HASH,
  package: {
    ...BASE_DESIGN_PACKAGE,
    owner_selected_alternative_id: DESIGN_ALTERNATIVE_ID,
    generated_mockup: {
      mockup: {
        contract_version: 1,
        design_alternative_id: DESIGN_ALTERNATIVE_ID,
        title: "Prestiti",
        styles: ".desk{display:grid}",
        screens: [{ code: "SCR-001", title: "Registro", state: "DEFAULT", markup: "<h1>R</h1>" }],
      },
      requirement_ids_by_code: {},
    },
    owner_assertions: [],
  },
};

const authorize: AuthorizedMockupRequest = (operation) => operation("token");

function proposal(): MockupResultPayload {
  return {
    status: "MOCKUP_GENERATED",
    generation_id: "iteration-1",
    design_version_id: VERSION.id,
    design_content_hash: HASH,
    package: VERSION.package,
    approach: null,
    changes: ["Il collegamento «Nuovo prestito» è più evidente"],
    warnings: [],
    cost_microusd: null,
  };
}

function job(
  status: GenerationJobPayload["status"],
  overrides: Partial<GenerationJobPayload> = {},
): GenerationJobPayload {
  return {
    job_id: "iteration-job-1",
    kind: "ITERATION",
    status,
    stage: status === "RUNNING" ? "GENERATING" : null,
    attempt: 1,
    started_at: "2026-10-08T09:00:00+00:00",
    finished_at: null,
    alternative_id: DESIGN_ALTERNATIVE_ID,
    result: null,
    failure: null,
    ...overrides,
  };
}

function fakeApi(started: GenerationJobPayload = job("RUNNING")) {
  return {
    startJob: vi.fn<DesignIterationsApi["startJob"]>(async () => started),
    job: vi.fn<DesignIterationsApi["job"]>(async () => started),
    list: vi.fn<DesignIterationsApi["list"]>(async () => ({ items: [] })),
  };
}

function parsed(html: string): Document {
  return new DOMParser().parseFromString(html, "text/html");
}

function load(frame: HTMLIFrameElement, html: string): Document {
  const page = frame.contentDocument;
  if (page === null) {
    throw new Error("missing frame document");
  }
  page.replaceChild(page.importNode(parsed(html).documentElement, true), page.documentElement);
  return page;
}

function frameWith(html: string): HTMLIFrameElement {
  const frame = document.createElement("iframe");
  document.body.appendChild(frame);
  load(frame, html);
  return frame;
}

function inFrame<T extends Element = HTMLElement>(frame: HTMLIFrameElement, selector: string): T {
  const element = frame.contentDocument?.querySelector<T>(selector) ?? null;
  if (element === null) {
    throw new Error(`missing ${selector} in the frame`);
  }
  return element;
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

function text(selector: string): string {
  return (query(selector).textContent ?? "").replace(/\s+/g, " ").trim();
}

function windowOf(target: Node): Window & typeof globalThis {
  const view = (target.ownerDocument ?? (target as Document)).defaultView;
  if (view === null) {
    throw new Error("missing window");
  }
  return view;
}

function pointer(target: Element, type: string, bubbles = true): boolean {
  return target.dispatchEvent(
    new (windowOf(target).MouseEvent)(type, { bubbles, cancelable: true }),
  );
}

function scrolled(frame: HTMLIFrameElement): void {
  const page = frame.contentDocument;
  if (page !== null) {
    page.dispatchEvent(new (windowOf(page).Event)("scroll"));
  }
}

function press(target: Element, key: string): KeyboardEvent {
  const event = new (windowOf(target).KeyboardEvent)("keydown", {
    key,
    bubbles: true,
    cancelable: true,
  });
  target.dispatchEvent(event);
  return event;
}

function placed(element: Element, left: number, top: number, width: number, height: number): void {
  vi.spyOn(element, "getBoundingClientRect").mockReturnValue({
    left,
    top,
    width,
    height,
    right: left + width,
    bottom: top + height,
    x: left,
    y: top,
    toJSON: () => ({}),
  } as DOMRect);
}

let wrapper: VueWrapper | null = null;

function inspector(
  frame: HTMLIFrameElement | null,
  props: Partial<InstanceType<typeof MockupInspector>["$props"]> = {},
) {
  wrapper = mount(MockupInspector, {
    props: {
      frame,
      loads: 1,
      screen: "SCR-001",
      locale: "it",
      screens: SCREENS,
      authorize,
      ...props,
    },
    global: { plugins: [createAppI18n(props.locale ?? "it")] },
    attachTo: document.body,
  });
  return wrapper;
}

async function choose(code: string): Promise<void> {
  query(`[data-testid='mockup-element'][data-code='${code}']`).click();
  await flushPromises();
}

beforeEach(() => {
  sessionStorage.clear();
  setActivePinia(createPinia());
});

afterEach(() => {
  useDesignIterationsStore().reset();
  wrapper?.unmount();
  wrapper = null;
  document.body.innerHTML = "";
  vi.useRealTimers();
  sessionStorage.clear();
});

describe("reading the elements of a mockup", () => {
  it("takes the elements of the screen in view, else of the entry screen, else of the first", () => {
    const page = parsed(MOCKUP);
    expect(visibleScreen(page)?.id).toBe("SCR-001");
    expect(screenElements(page).screen).toBe("SCR-001");
    expect(screenElements(page).elements.map((item) => item.getAttribute("data-elm"))).toEqual([
      "ELM-001",
      "ELM-002",
      "ELM-003",
      "ELM-004",
    ]);

    placed(page.getElementById("SCR-002") as Element, 0, 0, 1280, 800);
    expect(screenElements(page).screen).toBe("SCR-002");
    expect(screenElements(page).elements.map((item) => item.getAttribute("data-elm"))).toEqual([
      "ELM-005",
      "ELM-006",
    ]);

    const plain = parsed(MOCKUP.replace(" data-entry", ""));
    expect(visibleScreen(plain)?.id).toBe("SCR-001");
    const loose = parsed("<p data-elm='ELM-009'>Testo</p><p data-elm='ELM-009'>Doppio</p>");
    expect(screenElements(loose)).toEqual({
      screen: null,
      elements: [loose.querySelector("[data-elm]")],
    });
  });

  it("describes an element with its code, its tag, its visible text and its requirements", () => {
    const page = parsed(MOCKUP);
    const element = (code: string) => page.querySelector(`[data-elm='${code}']`) as Element;

    expect(describeElement(element("ELM-002"))).toEqual({
      code: "ELM-002",
      tag: "a",
      text: "Nuovo prestito",
      screen: "SCR-001",
      requirements: ["REQ-001", "REQ-004"],
    });
    expect(describeElement(element("ELM-003")).text).toBe("Cerca un libro");
    expect(describeElement(element("ELM-004")).text).toBe("Rossi 12 giorni");
    expect(requirementsOf(element("ELM-004"))).toEqual(["REQ-002", "REQ-003"]);
    expect(describeElement(element("ELM-006"))).toMatchObject({
      tag: "button",
      screen: "SCR-002",
      requirements: ["REQ-005"],
    });

    const named = parsed(
      "<input data-elm='ELM-010' aria-label='Data del prestito'><button data-elm='ELM-011'></button>" +
        `<p data-elm='ELM-012'>${"parola ".repeat(40)}</p><select data-elm='ELM-013'><option>Uno</option><option selected>Due</option></select>`,
    );
    const marked = (code: string) => named.querySelector(`[data-elm='${code}']`) as Element;
    expect(elementText(marked("ELM-010"))).toBe("Data del prestito");
    expect(elementText(marked("ELM-011"))).toBe("");
    expect([...elementText(marked("ELM-012"))].length).toBeLessThanOrEqual(120);
    expect(elementText(marked("ELM-012"))).toMatch(/^parola parola/);
    expect(elementText(marked("ELM-013"))).toBe("Due");
  });

  it("builds the target of a change with the markup of the element as the model must read it", () => {
    const page = parsed(MOCKUP);

    expect(changeTarget(page.querySelector("[data-elm='ELM-002']") as Element, null)).toEqual({
      screen_code: "SCR-001",
      element_code: "ELM-002",
      label: "Nuovo prestito",
      html: '<a href="#SCR-002" class="btn" data-elm="ELM-002">Nuovo <b>prestito</b></a>',
    });
    const row = changeTarget(page.querySelector("[data-elm='ELM-004']") as Element, null);
    expect(row?.html).not.toContain("ot-pin");
    expect(row?.html).toContain("<td>Rossi</td><td>12 giorni</td>");
    expect(page.querySelector(".ot-pin")).not.toBeNull();

    const loose = parsed(
      `<p data-elm='ELM-020'>${"è".repeat(3000)}</p><button data-elm='ELM-021'></button>`,
    );
    const long = changeTarget(loose.querySelector("p") as Element, "SCR-003");
    expect(long?.screen_code).toBe("SCR-003");
    expect([...(long?.html ?? "")].length).toBe(2048);
    expect([...(long?.label ?? "")].length).toBe(120);
    expect(changeTarget(loose.querySelector("button") as Element, "SCR-003")?.label).toBe(
      "ELM-021",
    );
    expect(changeTarget(loose.querySelector("button") as Element, null)).toBeNull();
  });

  it("knows whether a mockup has elements to point at", () => {
    expect(markedElements(MOCKUP)).toBe(true);
    expect(markedElements("<!doctype html><html><body><h1>Vecchio</h1></body></html>")).toBe(false);
  });
});

describe("mockup inspector", () => {
  it("waits for the document of the frame and says when the screen has nothing to point at", async () => {
    const view = inspector(null);
    expect(text("[data-testid='mockup-elements-reading']")).toBe(
      "Leggo gli elementi della schermata…",
    );
    const frame = frameWith("<!doctype html><html><body><h1>Vecchio</h1></body></html>");
    await view.setProps({ frame });
    expect(text("[data-testid='mockup-elements-empty']")).toBe(
      "In questa schermata non ci sono elementi indicabili.",
    );
    expect(document.body.querySelector("[data-testid='mockup-elements']")).toBeNull();
    expect(document.body.querySelector("[data-testid='mockup-inspect-hint']")).toBeNull();
  });

  it("lists the elements of the visible screen and chooses them with the arrows and Enter", async () => {
    inspector(frameWith(MOCKUP));
    await flushPromises();
    const list = query("[data-testid='mockup-elements']");
    const options = () => all("[data-testid='mockup-element']");

    expect(list.getAttribute("role")).toBe("listbox");
    expect(document.getElementById(list.getAttribute("aria-labelledby") ?? "")?.textContent).toBe(
      "Elementi indicabili",
    );
    expect(options().map((option) => option.getAttribute("role"))).toEqual([
      "option",
      "option",
      "option",
      "option",
    ]);
    expect(options().map((option) => option.getAttribute("aria-label"))).toEqual([
      "ELM-001, h1, Registro dei prestiti",
      "ELM-002, a, Nuovo prestito",
      "ELM-003, input, Cerca un libro",
      "ELM-004, tr, Rossi 12 giorni",
    ]);
    expect(options()[3]?.textContent).toContain("Rossi 12 giorni");
    expect(options().map((option) => option.tabIndex)).toEqual([0, -1, -1, -1]);
    expect(text("[data-testid='mockup-inspect-hint']")).toContain("con le frecce e Invio");

    options()[0]?.focus();
    press(list, "ArrowDown");
    await flushPromises();
    expect(document.activeElement).toBe(options()[1]);
    expect(options().map((option) => option.tabIndex)).toEqual([-1, 0, -1, -1]);
    expect(options().every((option) => option.getAttribute("aria-selected") === "false")).toBe(
      true,
    );

    expect(press(list, "Enter").defaultPrevented).toBe(true);
    await flushPromises();
    expect(options()[1]?.getAttribute("aria-selected")).toBe("true");
    expect(text("[data-testid='mockup-selection-code']")).toBe("ELM-002");
    expect(text("[data-testid='mockup-inspect-announcement']")).toBe(
      "Hai scelto ELM-002: Nuovo prestito",
    );

    press(list, "End");
    await flushPromises();
    expect(document.activeElement).toBe(options()[3]);
    press(list, " ");
    await flushPromises();
    expect(text("[data-testid='mockup-selection-code']")).toBe("ELM-004");
    press(list, "ArrowDown");
    await flushPromises();
    expect(document.activeElement).toBe(options()[3]);
    press(list, "Home");
    await flushPromises();
    expect(document.activeElement).toBe(options()[0]);

    expect(press(list, "Escape").defaultPrevented).toBe(true);
    await flushPromises();
    expect(document.body.querySelector("[data-testid='mockup-selection']")).toBeNull();
    expect(text("[data-testid='mockup-inspect-announcement']")).toBe("Nessun elemento scelto.");
    expect(press(list, "Escape").defaultPrevented).toBe(false);
  });

  it("highlights the nearest marked element under the mouse and chooses it with a click", async () => {
    const frame = frameWith(MOCKUP);
    const link = inFrame(frame, "[data-elm='ELM-002']");
    const title = inFrame(frame, "[data-elm='ELM-001']");
    placed(link, 40, 80, 120, 32);
    placed(title, 24, 16, 600, 48);
    const view = inspector(frame);
    await flushPromises();
    const last = () => view.emitted("highlight")?.at(-1)?.[0];

    pointer(inFrame(frame, "[data-elm='ELM-002'] b"), "mousemove");
    await flushPromises();
    expect(last()).toEqual({
      hover: { code: "ELM-002", left: 40, top: 80, width: 120, height: 32 },
      selected: null,
    });

    expect(pointer(inFrame(frame, "[data-elm='ELM-002'] b"), "click")).toBe(false);
    await flushPromises();
    expect(last()).toEqual({
      hover: null,
      selected: { code: "ELM-002", left: 40, top: 80, width: 120, height: 32 },
    });
    expect(text("[data-testid='mockup-selection-code']")).toBe("ELM-002");
    expect(
      query("[data-testid='mockup-element'][data-code='ELM-002']").getAttribute("aria-selected"),
    ).toBe("true");

    pointer(title, "mousemove");
    await flushPromises();
    expect(last()).toEqual({
      hover: { code: "ELM-001", left: 24, top: 16, width: 600, height: 48 },
      selected: { code: "ELM-002", left: 40, top: 80, width: 120, height: 32 },
    });
    pointer(inFrame(frame, "html"), "mouseleave", false);
    await flushPromises();
    expect(last()).toMatchObject({ hover: null });

    expect(pointer(title, "click")).toBe(true);
    await flushPromises();
    expect(text("[data-testid='mockup-selection-code']")).toBe("ELM-001");
    pointer(inFrame(frame, "main"), "click");
    await flushPromises();
    expect(text("[data-testid='mockup-selection-code']")).toBe("ELM-001");

    expect(press(inFrame(frame, "body"), "Escape").defaultPrevented).toBe(true);
    await flushPromises();
    expect(document.body.querySelector("[data-testid='mockup-selection']")).toBeNull();
    expect(last()).toEqual({ hover: null, selected: null });
  });

  it("follows the scroll of the document and stops listening to it once it is closed", async () => {
    const frame = frameWith(MOCKUP);
    const link = inFrame(frame, "[data-elm='ELM-002']");
    placed(link, 40, 80, 120, 32);
    const view = inspector(frame);
    await choose("ELM-002");
    placed(link, 40, 20, 120, 32);

    scrolled(frame);
    expect(view.emitted("highlight")?.at(-1)?.[0]).toMatchObject({ selected: { top: 20 } });
    expect(pointer(link, "click")).toBe(false);

    view.unmount();
    wrapper = null;
    expect(pointer(link, "click")).toBe(true);
    expect(press(link, "Escape").defaultPrevented).toBe(false);
  });

  it("shows the chosen element with its screen, its text and its requirements one per line", async () => {
    inspector(frameWith(MOCKUP));
    await flushPromises();
    await choose("ELM-004");

    const panel = query("[data-testid='mockup-selection']");
    expect(document.getElementById(panel.getAttribute("aria-labelledby") ?? "")?.textContent).toBe(
      "Elemento scelto",
    );
    expect(text("[data-testid='mockup-selection-code']")).toBe("ELM-004");
    expect(text("[data-testid='mockup-selection-screen']")).toBe("SCR-001 · Registro dei prestiti");
    expect(text("[data-testid='mockup-selection-text']")).toBe("Rossi 12 giorni");
    expect(
      all("[data-testid='mockup-requirement']").map((item) => item.textContent?.trim()),
    ).toEqual(["REQ-002", "REQ-003"]);
    await choose("ELM-001");
    expect(
      all("[data-testid='mockup-requirement']").map((item) => item.textContent?.trim()),
    ).toEqual(["REQ-001", "REQ-004"]);

    const field = query<HTMLTextAreaElement>("[data-testid='mockup-request']");
    expect(document.querySelector(`label[for='${field.id}']`)?.textContent).toBe(
      "Che cosa cambio?",
    );
    expect(field.maxLength).toBe(1000);
    expect(
      document.getElementById(field.getAttribute("aria-describedby") ?? "")?.textContent?.trim(),
    ).toBe("0 di 1000 caratteri");
    const apply = query("[data-testid='mockup-apply']");
    expect(apply.textContent?.trim()).toBe("Applica la modifica");
    expect(apply.getAttribute("aria-disabled")).toBe("true");
    field.value = "Più grande 😀";
    field.dispatchEvent(new Event("input"));
    await flushPromises();
    expect(text("[data-testid='mockup-request-count']")).toBe("12 di 1000 caratteri");
    expect(apply.getAttribute("aria-disabled")).toBeNull();

    const review = query<HTMLInputElement>("[data-testid='mockup-review']");
    expect(review.checked).toBe(true);
    expect(review.closest("label")?.textContent?.trim()).toBe("Chiedi subito il parere dei twin");
    expect(
      document.getElementById(apply.getAttribute("aria-describedby") ?? "")?.textContent?.trim(),
    ).toBe("Di solito servono da 5 a 10 minuti, più il parere dei twin.");
    review.click();
    await flushPromises();
    expect(text("[data-testid='mockup-estimate']")).toBe("Di solito servono da 5 a 10 minuti.");

    field.focus();
    expect(press(field, "Escape").defaultPrevented).toBe(true);
    await flushPromises();
    expect(document.body.querySelector("[data-testid='mockup-selection']")).toBeNull();
    expect(document.activeElement).toBe(
      query("[data-testid='mockup-element'][data-code='ELM-001']"),
    );
    await choose("ELM-001");
    expect(query<HTMLTextAreaElement>("[data-testid='mockup-request']").value).toBe(
      "Più grande 😀",
    );
  });

  it("asks for the change of the chosen element with the action of the Design step and its target", async () => {
    const api = fakeApi(job("SUCCEEDED", { result: proposal() }));
    useDesignIterationsStore().activate(DESIGN_PROJECT_ID, VERSION);
    const frame = frameWith(MOCKUP);
    const view = inspector(frame, { api });
    await choose("ELM-002");
    const field = query<HTMLTextAreaElement>("[data-testid='mockup-request']");
    field.value = "Rendi il collegamento più evidente";
    field.dispatchEvent(new Event("input"));
    await flushPromises();

    query("[data-testid='mockup-apply']").click();
    await flushPromises();

    expect(api.startJob).toHaveBeenCalledExactlyOnceWith(
      DESIGN_PROJECT_ID,
      {
        design_version_id: VERSION.id,
        design_content_hash: HASH,
        request: "Rendi il collegamento più evidente",
        assertions: [],
        target: {
          screen_code: "SCR-001",
          element_code: "ELM-002",
          label: "Nuovo prestito",
          html: '<a href="#SCR-002" class="btn" data-elm="ELM-002">Nuovo <b>prestito</b></a>',
        },
      },
      "token",
    );
    expect(view.emitted("version")).toEqual([["SCR-001"]]);
    expect(text("[data-testid='mockup-change-status']")).toBe(
      "Ecco la nuova versione. Confrontala con quella attuale e decidi se applicarla.",
    );
    expect(query<HTMLTextAreaElement>("[data-testid='mockup-request']").value).toBe("");
    expect(query("[data-testid='mockup-apply']").getAttribute("aria-disabled")).toBe("true");
    expect(document.body.querySelector("[data-testid='mockup-change-pending']")).toBeNull();

    load(frame, "<!doctype html><html><head></head><body></body></html>");
    await view.setProps({ loads: 2 });
    expect(document.body.querySelector("[data-testid='mockup-selection']")).toBeNull();
    load(frame, MOCKUP.replace("Nuovo <b>prestito</b>", "Nuovo prestito subito"));
    await view.setProps({ loads: 3 });
    expect(text("[data-testid='mockup-selection-code']")).toBe("ELM-002");
    expect(text("[data-testid='mockup-selection-text']")).toBe("Nuovo prestito subito");
    load(frame, MOCKUP.replace("data-elm='ELM-002'", ""));
    await view.setProps({ loads: 4 });
    expect(document.body.querySelector("[data-testid='mockup-selection']")).toBeNull();
  });

  it("shows the designer at work and the failure of the drawing as the Design step does", async () => {
    vi.useFakeTimers();
    const api = fakeApi(job("RUNNING"));
    api.job.mockResolvedValue(
      job("REJECTED", { failure: { code: "MOCKUP_QUALITY_REJECTED", reasons: [] } }),
    );
    useDesignIterationsStore().activate(DESIGN_PROJECT_ID, VERSION);
    const view = inspector(frameWith(MOCKUP), { api });
    query("[data-testid='mockup-element'][data-code='ELM-003']").click();
    await nextTick();
    const field = query<HTMLTextAreaElement>("[data-testid='mockup-request']");
    field.value = "Allarga il campo";
    field.dispatchEvent(new Event("input"));
    await nextTick();

    query("[data-testid='mockup-apply']").click();
    await vi.advanceTimersByTimeAsync(0);
    await nextTick();

    const status = query("[data-testid='mockup-change-status']");
    expect(status.getAttribute("role")).toBe("status");
    expect(status.textContent).toContain("Il designer sta disegnando le schermate.");
    expect(status.textContent).toContain(
      "Sto disegnando la nuova versione con le tue indicazioni.",
    );
    expect(query("[data-testid='mockup-apply']").getAttribute("aria-disabled")).toBe("true");
    query("[data-testid='mockup-apply']").click();
    await vi.advanceTimersByTimeAsync(0);
    expect(api.startJob).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MILLISECONDS);
    await nextTick();

    const failure = query("[data-testid='mockup-change-status']");
    expect(failure.getAttribute("role")).toBe("alert");
    expect(failure.textContent).toContain("La nuova versione va rifatta");
    expect(failure.textContent).toContain(
      "Lo Studio ha scartato la risposta perché non superava i controlli di qualità.",
    );
    expect(view.emitted("version")).toBeUndefined();
  });

  it("says why the change did not start and when another version waits for a decision", async () => {
    const api = fakeApi();
    api.startJob.mockRejectedValueOnce(
      new DesignIterationsApiError("TOO_MANY_GENERATIONS", {
        status: 429,
        code: "TOO_MANY_GENERATIONS",
        payload: null,
      }),
    );
    const store = useDesignIterationsStore();
    store.activate(DESIGN_PROJECT_ID, VERSION);
    const view = inspector(frameWith(MOCKUP), { api });
    await choose("ELM-001");
    const field = query<HTMLTextAreaElement>("[data-testid='mockup-request']");
    field.value = "Titolo più corto";
    field.dispatchEvent(new Event("input"));
    await flushPromises();

    query("[data-testid='mockup-apply']").click();
    await flushPromises();

    const refusal = query("[data-testid='mockup-change-status']");
    expect(refusal.getAttribute("role")).toBe("alert");
    expect(refusal.textContent).toContain("La richiesta non è partita");
    expect(refusal.textContent).toContain(
      "Ci sono già troppi disegni in corso. Aspetta che uno finisca e riprova.",
    );
    expect(field.value).toBe("Titolo più corto");
    view.unmount();
    wrapper = null;

    await store.start({ request: "Altro" }, authorize, {
      api: fakeApi(job("SUCCEEDED", { result: proposal() })),
    });
    inspector(frameWith(MOCKUP), { api });
    await choose("ELM-001");
    const again = query<HTMLTextAreaElement>("[data-testid='mockup-request']");
    again.value = "Titolo più corto";
    again.dispatchEvent(new Event("input"));
    await flushPromises();
    const apply = query("[data-testid='mockup-apply']");
    expect(text("[data-testid='mockup-change-pending']")).toBe(
      "Una nuova versione aspetta già la tua decisione: applicala o scartala prima di chiedere altre modifiche.",
    );
    expect(apply.getAttribute("aria-disabled")).toBe("true");
    expect(apply.getAttribute("aria-describedby")?.split(" ")).toHaveLength(2);
    apply.click();
    await flushPromises();
    expect(api.startJob).toHaveBeenCalledTimes(1);
  });

  it("reads the mockup without changing it and without any request before the change is applied", async () => {
    const fetchImpl = vi.fn();
    vi.stubGlobal("fetch", fetchImpl);
    const api = fakeApi();
    const frame = frameWith(MOCKUP);
    const before = frame.contentDocument?.documentElement.outerHTML;
    inspector(frame, { api });
    await flushPromises();

    pointer(inFrame(frame, "h1"), "mousemove");
    pointer(inFrame(frame, "[data-elm='ELM-002']"), "click");
    press(query("[data-testid='mockup-elements']"), "ArrowDown");
    await flushPromises();

    expect(frame.contentDocument?.documentElement.outerHTML).toBe(before);
    expect(frame.contentDocument?.querySelector("script")).toBeNull();
    expect(fetchImpl).not.toHaveBeenCalled();
    expect(api.startJob).not.toHaveBeenCalled();
    expect(source).not.toMatch(/innerHTML|v-html|createElement|appendChild|insertAdjacent/);
  });

  it("speaks English when the page is in English", async () => {
    inspector(frameWith(MOCKUP), { locale: "en" });
    await flushPromises();
    expect(text("h3")).toBe("Elements you can point at");
    expect(text("[data-testid='mockup-inspect-hint']")).toBe(
      "Move over the mockup and click an element, or choose it from the list with the arrow keys and Enter.",
    );
    await choose("ELM-003");
    expect(text("[data-testid='mockup-selection'] h4")).toBe("Chosen element");
    expect(document.querySelector("label[for]")?.textContent).toBe("What should I change?");
    expect(text("[data-testid='mockup-estimate']")).toBe(
      "It usually takes 5 to 10 minutes, plus the opinion of the twins.",
    );
    expect(query("[data-testid='mockup-review']").closest("label")?.textContent?.trim()).toBe(
      "Ask the twins for their opinion right away",
    );
    expect(text("[data-testid='mockup-apply']")).toBe("Apply the change");
    expect(
      all("[data-testid='mockup-requirement']").map((item) => item.textContent?.trim()),
    ).toEqual(["REQ-001", "REQ-004"]);
    expect(text("[data-testid='mockup-inspect-announcement']")).toBe(
      "You chose ELM-003: Cerca un libro",
    );
  });

  it("has no axe violations while it lists and while an element is chosen", async () => {
    inspector(frameWith(MOCKUP));
    await flushPromises();
    await expectAccessible(query("[data-testid='mockup-inspector']"), { iframes: false });
    await choose("ELM-002");
    await expectAccessible(query("[data-testid='mockup-inspector']"), { iframes: false });
  });
});

const NEXT_HASH = "3".repeat(64);
const SCOPED_PROMPT = "s24-design-twin-review-v3+s43-changed-element-v1";
const TWIN = BASE_DESIGN_PACKAGE.grounding.user_twin_references[0]!;
const POINTED = { screen_code: "SCR-001", element_code: "ELM-002" };

const NEXT: DesignPackageVersionPayload = {
  ...VERSION,
  id: "00000000-0000-4000-8000-333333333333",
  version_number: 2,
  based_on_version_number: 1,
  content_hash: NEXT_HASH,
};

function revisionDiff(status: DesignPackageDiffPayload["status"]): DesignPackageDiffPayload {
  return {
    ...PROPOSED_DESIGN_DIFF,
    id: "diff-43",
    base_version_id: VERSION.id,
    base_content_hash: HASH,
    proposed_package: VERSION.package,
    status,
    applied_version_id: status === "APPROVED" ? NEXT.id : null,
  };
}

function revision(version: DesignPackageVersionPayload | null): DesignRevisionPayload {
  return {
    status: version === null ? "CREATED" : "APPLIED",
    diff: revisionDiff(version === null ? "PROPOSED" : "APPROVED"),
    version,
    issue: null,
    domain_issue: null,
    diff_persistence_status: null,
    version_persistence_status: null,
  };
}

function fakeDesignApi() {
  return {
    proposeRevision: vi.fn<DesignApi["proposeRevision"]>(async () => revision(null)),
    decideRevision: vi.fn<DesignApi["decideRevision"]>(async () => revision(NEXT)),
    readiness: vi.fn<DesignApi["readiness"]>(async () => ({
      status: "DESIGN_APPROVAL_REQUIRED",
      version: NEXT,
      gate: null,
      has_package: true,
      package_ready_for_gate: true,
      approved_current_package: false,
    })),
    history: vi.fn<DesignApi["history"]>(async () => [VERSION, NEXT]),
    revisionHistory: vi.fn<DesignApi["revisionHistory"]>(async () => [revisionDiff("APPROVED")]),
  };
}

function twinFinding(
  number: number,
  severity: SyntheticFindingSeverity,
  element: string | null,
  summary: string,
  action: string,
): SyntheticFindingPayload & { element_code?: string } {
  const finding: SyntheticFindingPayload = {
    finding_id: `UTF-00${number}`,
    twin_id: TWIN.twin_id,
    twin_version: 1,
    artifact_id: VERSION.id,
    artifact_version: 2,
    location:
      element === null ? "SCR-001 Registro" : `SCR-001 Registro · ${element} Nuovo prestito`,
    summary,
    rationale: "Al banco cerco subito il prossimo prestito.",
    criterion: "actionability",
    severity,
    epistemic_status: "MODEL_INFERRED",
    evidence_refs: [],
    confidence: 0.7,
    confidence_semantics: "MODEL_SELF_ASSESSMENT_UNLESS_CALIBRATED",
    recommended_action: action,
    requires_human_validation: true,
    model_config_ref: "c".repeat(64),
    prompt_version_ref: SCOPED_PROMPT,
    is_simulated_feedback: true,
    content_hash: String(number).repeat(64),
  };
  return element === null ? finding : { ...finding, element_code: element };
}

const FINDINGS = [
  twinFinding(
    1,
    "observation",
    "ELM-002",
    "La modifica mi aiuta: ELM-002 ora si vede subito.",
    "Prova con un blu più scuro per ELM-002.",
  ),
  twinFinding(
    2,
    "critical",
    "ELM-002",
    "Sul telefono il collegamento è troppo vicino al titolo.",
    "Allontana il collegamento dal titolo.",
  ),
  twinFinding(3, "minor", "ELM-001", "Il titolo è lungo.", "Accorcia il titolo."),
  twinFinding(4, "moderate", null, "Manca un filtro per i ritardi.", "Aggiungi un filtro."),
];

function reviewRun(
  version: DesignPackageVersionPayload,
  findings: SyntheticFindingPayload[] = FINDINGS,
): DesignEvaluationRunPayload {
  const id = `run-${version.version_number}`;
  return {
    schema_version: 1,
    id,
    project_id: DESIGN_PROJECT_ID,
    owner_user_id: "owner-1",
    design_version_id: version.id,
    design_version_number: version.version_number,
    design_content_hash: version.content_hash,
    alternative_id: DESIGN_ALTERNATIVE_ID,
    alternative_code: "DES-001",
    bundle: {},
    responses: [
      {
        evaluation_run_id: id,
        artifact_bundle_id: "bundle-1",
        artifact_bundle_hash: "b".repeat(64),
        twin_id: TWIN.twin_id,
        twin_version: 1,
        evaluator: {
          evaluator_id: "proposer-design-twin-review",
          evaluator_version: "1.0.0",
          model_config_ref: "c".repeat(64),
          prompt_version_ref: SCOPED_PROMPT,
        },
        findings,
        summary: "La modifica mi aiuta.",
        evidence_gaps: [],
        is_simulated_feedback: true,
        completed_at: "2026-10-08T10:02:00+00:00",
        content_hash: "d".repeat(64),
        disclaimer: "Simulated feedback.",
      },
    ],
    started_at: "2026-10-08T10:00:00+00:00",
    completed_at: "2026-10-08T10:02:00+00:00",
    content_hash: "e".repeat(64),
  };
}

function fakeLoopApi(run: DesignEvaluationRunPayload = reviewRun(NEXT)) {
  return {
    evaluate: vi.fn<DesignLoopApi["evaluate"]>(async () => run),
    comparison: vi.fn<DesignLoopApi["comparison"]>(async () => null),
  };
}

function current(version: DesignPackageVersionPayload): void {
  useDesignIterationsStore().activate(DESIGN_PROJECT_ID, version);
  const design = useDesignStore();
  design.activateProject(DESIGN_PROJECT_ID);
  design.applyVersion(version);
  useDesignLoopStore().reset(DESIGN_PROJECT_ID);
}

async function proposed(props: Partial<InstanceType<typeof MockupInspector>["$props"]> = {}) {
  const iterationsApi = fakeApi(job("SUCCEEDED", { result: proposal() }));
  const designApi = fakeDesignApi();
  const loopApi = fakeLoopApi();
  current(VERSION);
  const view = inspector(frameWith(MOCKUP), {
    api: iterationsApi,
    designApi: designApi as unknown as DesignApi,
    loopApi: loopApi as unknown as DesignLoopApi,
    ...props,
  });
  await choose("ELM-002");
  const field = query<HTMLTextAreaElement>("[data-testid='mockup-request']");
  field.value = "Rendi il collegamento più evidente";
  field.dispatchEvent(new Event("input"));
  await flushPromises();
  query("[data-testid='mockup-apply']").click();
  await flushPromises();
  return { view, iterationsApi, designApi, loopApi };
}

function texts(selector: string): string[] {
  return all(selector).map((item) => (item.textContent ?? "").replace(/\s+/g, " ").trim());
}

describe("the twins on the changed element", () => {
  it("applies the waiting version with the action of the page and asks the twins about the element", async () => {
    const { view, iterationsApi, designApi, loopApi } = await proposed();
    const apply = query("[data-testid='mockup-apply-version']");
    expect(apply.textContent?.trim()).toBe("Applica la nuova versione");
    expect(apply.hasAttribute("aria-disabled")).toBe(false);
    expect(
      document.getElementById(apply.getAttribute("aria-describedby") ?? "")?.textContent?.trim(),
    ).toBe("Dopo l'applicazione i twin guardano ELM-002: di solito serve un paio di minuti.");
    expect(designApi.proposeRevision).not.toHaveBeenCalled();
    expect(loopApi.evaluate).not.toHaveBeenCalled();

    apply.click();
    await flushPromises();

    expect(designApi.proposeRevision).toHaveBeenCalledExactlyOnceWith(
      DESIGN_PROJECT_ID,
      { package: VERSION.package },
      "token",
    );
    expect(designApi.decideRevision).toHaveBeenCalledExactlyOnceWith(
      DESIGN_PROJECT_ID,
      "diff-43",
      { decision: "APPROVE", reason: null },
      "token",
    );
    expect(view.emitted("applied")).toEqual([[NEXT.id]]);
    expect(useDesignIterationsStore().state).toBe("idle");
    expect(useDesignStore().current?.id).toBe(NEXT.id);
    expect(loopApi.evaluate).toHaveBeenCalledExactlyOnceWith(
      DESIGN_PROJECT_ID,
      {
        design_version_id: NEXT.id,
        design_content_hash: NEXT_HASH,
        mode: "TWIN_REVIEW",
        locale: "it-IT",
        scope: POINTED,
      },
      "token",
    );
    expect(useDesignLoopStore().runs.map((run) => run.id)).toEqual(["run-2"]);
    expect(iterationsApi.startJob).toHaveBeenCalledTimes(1);
    expect(document.body.querySelector("[data-testid='mockup-apply-version']")).toBeNull();
    expect(text("[data-testid='mockup-change-status']")).toBe(
      "Hai applicato la nuova versione: ora è quella attuale.",
    );
    expect(text("[data-testid='mockup-review-status']")).toBe(
      "I twin hanno detto la loro su ELM-002: le loro note sono accanto all'elemento.",
    );
    expect(text("[data-testid='mockup-inspect-announcement']")).toBe(
      "I twin hanno detto la loro su ELM-002: le loro note sono accanto all'elemento.",
    );

    const notes = query("[data-testid='mockup-twin-notes']");
    expect(document.getElementById(notes.getAttribute("aria-labelledby") ?? "")?.textContent).toBe(
      "Che cosa ne dicono i twin",
    );
    expect(notes.textContent).toContain("Sono ipotesi dei twin da pesare, non prove.");
    expect(all("[data-testid='mockup-twin-note']").map((note) => note.dataset.verdict)).toEqual([
      "helps",
      "blocks",
    ]);
    expect(texts("[data-testid='mockup-twin-note-twin']")).toEqual([
      "Receptionist Twin",
      "Receptionist Twin",
    ]);
    expect(texts("[data-testid='mockup-twin-note-verdict']")).toEqual(["Aiuta", "Blocca"]);
    expect(texts("[data-testid='mockup-twin-note-summary']")).toEqual([
      "La modifica mi aiuta: «Nuovo prestito» ora si vede subito.",
      "Sul telefono il collegamento è troppo vicino al titolo.",
    ]);
    expect(texts("[data-testid='mockup-twin-note-action']")).toEqual([
      "Cosa fare: Prova con un blu più scuro per «Nuovo prestito».",
      "Cosa fare: Allontana il collegamento dal titolo.",
    ]);

    const tries = all("[data-testid='mockup-try-suggestion']");
    expect(tries.map((item) => item.textContent?.trim())).toEqual(["Prova questo", "Prova questo"]);
    expect(
      document.getElementById(tries[1]?.getAttribute("aria-describedby") ?? "")?.textContent,
    ).toContain("Allontana il collegamento dal titolo.");
    tries[0]?.click();
    await flushPromises();
    const field = query<HTMLTextAreaElement>("[data-testid='mockup-request']");
    expect(field.value).toBe("Prova con un blu più scuro per «Nuovo prestito».");
    expect(document.activeElement).toBe(field);
    expect(text("[data-testid='mockup-inspect-announcement']")).toBe(
      "Ho scritto il suggerimento in «Che cosa cambio?»: controllalo e premi «Applica la modifica».",
    );
    expect(query("[data-testid='mockup-apply']").hasAttribute("aria-disabled")).toBe(false);
    expect(iterationsApi.startJob).toHaveBeenCalledTimes(1);
    expect(loopApi.evaluate).toHaveBeenCalledTimes(1);

    await choose("ELM-001");
    expect(texts("[data-testid='mockup-twin-note-verdict']")).toEqual(["Rallenta"]);
    expect(texts("[data-testid='mockup-twin-note-summary']")).toEqual(["Il titolo è lungo."]);
    await choose("ELM-003");
    expect(document.body.querySelector("[data-testid='mockup-twin-notes']")).toBeNull();
  });

  it("says that the twins are looking at the element while their review runs", async () => {
    let finish!: (run: DesignEvaluationRunPayload) => void;
    const { loopApi } = await proposed();
    loopApi.evaluate.mockImplementationOnce(
      () =>
        new Promise<DesignEvaluationRunPayload>((resolve) => {
          finish = resolve;
        }),
    );
    query("[data-testid='mockup-apply-version']").click();
    await flushPromises();

    const status = query("[data-testid='mockup-review-status']");
    expect(status.getAttribute("role")).toBe("status");
    expect(status.getAttribute("aria-live")).toBe("polite");
    expect(status.textContent).toContain("I twin stanno guardando l'elemento…");
    expect(status.textContent).toContain(
      "Di solito serve un paio di minuti: intanto puoi continuare a guardare il mockup.",
    );
    expect(document.body.querySelector("[data-testid='mockup-twin-notes']")).toBeNull();
    expect(useDesignLoopStore().busy).toBe("evaluate");

    finish(reviewRun(NEXT));
    await flushPromises();
    expect(all("[data-testid='mockup-twin-note']")).toHaveLength(2);
    expect(useDesignLoopStore().busy).toBeNull();
  });

  it("applies the version without the twins when the box is off and asks them with a gesture apart", async () => {
    const { designApi, loopApi } = await proposed();
    query<HTMLInputElement>("[data-testid='mockup-review']").click();
    await flushPromises();
    expect(text("[data-testid='mockup-version-note']")).toBe(
      "Applicarla non avvia nessuna generazione: la versione proposta diventa quella attuale.",
    );
    expect(text("[data-testid='mockup-ask-twins']")).toBe(
      "Chiedi il parere dei twin su questo elemento",
    );
    expect(query("[data-testid='mockup-ask-twins']").getAttribute("aria-disabled")).toBe("true");
    query("[data-testid='mockup-ask-twins']").click();
    await flushPromises();
    expect(loopApi.evaluate).not.toHaveBeenCalled();

    query("[data-testid='mockup-apply-version']").click();
    await flushPromises();
    expect(designApi.decideRevision).toHaveBeenCalledTimes(1);
    expect(loopApi.evaluate).not.toHaveBeenCalled();
    expect(document.body.querySelector("[data-testid='mockup-review-status']")).toBeNull();
    const ask = query("[data-testid='mockup-ask-twins']");
    expect(ask.hasAttribute("aria-disabled")).toBe(false);
    expect(
      document.getElementById(ask.getAttribute("aria-describedby") ?? "")?.textContent?.trim(),
    ).toBe("Di solito serve un paio di minuti.");

    ask.click();
    await flushPromises();
    expect(loopApi.evaluate).toHaveBeenCalledExactlyOnceWith(
      DESIGN_PROJECT_ID,
      {
        design_version_id: NEXT.id,
        design_content_hash: NEXT_HASH,
        mode: "TWIN_REVIEW",
        locale: "it-IT",
        scope: POINTED,
      },
      "token",
    );
    expect(all("[data-testid='mockup-twin-note']")).toHaveLength(2);
  });

  it("keeps the version waiting when it is not applied and lets the owner ask the twins again", async () => {
    const { view, designApi, loopApi } = await proposed();
    designApi.decideRevision.mockRejectedValueOnce(
      new DesignApiError("refused", { status: 409, code: "DIFF_ALREADY_DECIDED", payload: null }),
    );
    query("[data-testid='mockup-apply-version']").click();
    await flushPromises();

    const failure = query("[data-testid='mockup-change-status']");
    expect(failure.getAttribute("role")).toBe("alert");
    expect(failure.textContent).toContain("La nuova versione non è stata applicata");
    expect(failure.textContent).toContain(
      "La nuova versione è registrata ma non è ancora stata applicata. Premi di nuovo «Applica la nuova versione».",
    );
    expect(view.emitted("applied")).toBeUndefined();
    expect(loopApi.evaluate).not.toHaveBeenCalled();
    expect(useDesignIterationsStore().state).toBe("ready");

    loopApi.evaluate.mockRejectedValueOnce(
      new DesignLoopApiError("failed", {
        status: 503,
        code: "DESIGN_REVIEWER_NOT_CONFIGURED",
        payload: null,
      }),
    );
    query("[data-testid='mockup-apply-version']").click();
    await flushPromises();
    expect(designApi.proposeRevision).toHaveBeenCalledTimes(1);
    expect(designApi.decideRevision).toHaveBeenCalledTimes(2);
    expect(view.emitted("applied")).toEqual([[NEXT.id]]);
    const review = query("[data-testid='mockup-review-status']");
    expect(review.getAttribute("role")).toBe("alert");
    expect(review.textContent).toContain("Il parere dei twin non è arrivato");
    expect(review.textContent).toContain(
      "Il modello che interpreta i twin non è collegato, quindi i twin non possono dare il loro parere.",
    );

    query("[data-testid='mockup-ask-twins']").click();
    await flushPromises();
    expect(loopApi.evaluate).toHaveBeenCalledTimes(2);
    expect(all("[data-testid='mockup-twin-note']")).toHaveLength(2);
    expect(document.body.querySelector("[data-testid='mockup-ask-twins']")).toBeNull();
  });

  it("does not apply the version while another change waits for a decision on the page", async () => {
    const { designApi, loopApi } = await proposed();
    useDesignStore().applyDiff({
      ...revisionDiff("PROPOSED"),
      id: "diff-other",
      proposed_package: { ...VERSION.package, owner_assertions: ["Il titolo resta corto"] },
    });
    query("[data-testid='mockup-apply-version']").click();
    await flushPromises();
    const refusal = query("[data-testid='mockup-change-status']");
    expect(refusal.textContent).toContain("La nuova versione non è stata applicata");
    expect(refusal.textContent).toContain(
      "Un'altra modifica aspetta la tua decisione nella pagina del passo Design: applicala o scartala prima.",
    );
    expect(designApi.proposeRevision).not.toHaveBeenCalled();
    expect(designApi.decideRevision).not.toHaveBeenCalled();
    expect(loopApi.evaluate).not.toHaveBeenCalled();
  });

  it("shows the notes already recorded for the chosen element of the current version without asking", async () => {
    const loopApi = fakeLoopApi();
    current(VERSION);
    const elsewhere = twinFinding(5, "critical", "ELM-003", "Il campo è stretto.", "Allargalo.");
    useDesignLoopStore().runs = [reviewRun(NEXT, [elsewhere]), reviewRun(VERSION)];
    inspector(frameWith(MOCKUP), { loopApi: loopApi as unknown as DesignLoopApi });
    await choose("ELM-001");
    expect(texts("[data-testid='mockup-twin-note-summary']")).toEqual(["Il titolo è lungo."]);
    expect(texts("[data-testid='mockup-twin-note-verdict']")).toEqual(["Rallenta"]);
    await choose("ELM-003");
    expect(document.body.querySelector("[data-testid='mockup-twin-notes']")).toBeNull();
    expect(document.body.querySelector("[data-testid='mockup-ask-twins']")).toBeNull();
    expect(document.body.querySelector("[data-testid='mockup-apply-version']")).toBeNull();
    expect(loopApi.evaluate).not.toHaveBeenCalled();
  });

  it("speaks English when the page is in English", async () => {
    let finish!: (run: DesignEvaluationRunPayload) => void;
    const { loopApi } = await proposed({ locale: "en" });
    expect(text("[data-testid='mockup-apply-version']")).toBe("Apply the new version");
    expect(text("[data-testid='mockup-version-note']")).toBe(
      "Once it is applied the twins look at ELM-002: it usually takes a couple of minutes.",
    );
    loopApi.evaluate.mockImplementationOnce(
      () =>
        new Promise<DesignEvaluationRunPayload>((resolve) => {
          finish = resolve;
        }),
    );
    query("[data-testid='mockup-apply-version']").click();
    await flushPromises();
    expect(text("[data-testid='mockup-change-status']")).toBe(
      "You applied the new version: it is now the current one.",
    );
    const running = query("[data-testid='mockup-review-status']");
    expect(running.textContent).toContain("The twins are looking at the element…");
    expect(running.textContent).toContain(
      "It usually takes a couple of minutes: meanwhile you can keep looking at the mockup.",
    );
    expect(loopApi.evaluate.mock.calls[0]?.[1]).toMatchObject({ locale: "en-US", scope: POINTED });
    finish(reviewRun(NEXT));
    await flushPromises();
    expect(text("[data-testid='mockup-review-status']")).toBe(
      "The twins gave their opinion on ELM-002: their notes are next to the element.",
    );
    expect(text("[data-testid='mockup-twin-notes'] h5")).toBe("What the twins say about it");
    expect(texts("[data-testid='mockup-twin-note-verdict']")).toEqual(["Helps", "Blocks"]);
    expect(texts("[data-testid='mockup-twin-note-summary']")[0]).toBe(
      "La modifica mi aiuta: “Nuovo prestito” ora si vede subito.",
    );
    expect(texts("[data-testid='mockup-twin-note-action']")[1]).toBe(
      "What to do: Allontana il collegamento dal titolo.",
    );
    expect(texts("[data-testid='mockup-try-suggestion']")).toEqual(["Try this", "Try this"]);
    query("[data-testid='mockup-review']").click();
    await flushPromises();
    expect(text("[data-testid='mockup-ask-twins']")).toBe(
      "Ask the twins for their opinion on this element",
    );
    expect(text("[data-testid='mockup-ask-time']")).toBe("It usually takes a couple of minutes.");
    all("[data-testid='mockup-try-suggestion']")[0]?.click();
    await flushPromises();
    expect(text("[data-testid='mockup-inspect-announcement']")).toBe(
      "I wrote the suggestion in “What should I change?”: check it and press “Apply the change”.",
    );
  });

  it("has no axe violations while it shows the notes of the twins", async () => {
    await proposed();
    await expectAccessible(query("[data-testid='mockup-inspector']"), { iframes: false });
    query("[data-testid='mockup-apply-version']").click();
    await flushPromises();
    expect(all("[data-testid='mockup-twin-note']")).toHaveLength(2);
    await expectAccessible(query("[data-testid='mockup-inspector']"), { iframes: false });
  });
});
