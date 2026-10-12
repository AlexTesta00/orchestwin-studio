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
import {
  DesignIterationsApiError,
  type DesignChangeTarget,
  type DesignIterationsApi,
} from "../api/designIterations";
import { DesignLoopApiError, type DesignLoopApi } from "../api/designLoop";
import { DesignOpinionsApiError, type DesignOpinionsApi } from "../api/designOpinions";
import { useDesignStore } from "../stores/design";
import { useDesignIterationsStore } from "../stores/designIterations";
import { useDesignLoopStore } from "../stores/designLoop";
import { POLL_INTERVAL_MILLISECONDS, type AuthorizedMockupRequest } from "../stores/designMockups";
import { useDesignOpinionsStore } from "../stores/designOpinions";
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
import type {
  GenerationJobPayload,
  MockupCorrectionPayload,
  MockupResultPayload,
} from "../types/designMockups";
import type { ChangeOpinion, ChangeOpinionRun } from "../types/designOpinions";
import type { InspectorHighlight } from "./mockupElements";
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

const ZONED = [
  "<!doctype html><html lang='it'><head><title>Bottega Vicina</title></head><body class='ot-mockup'>",
  "<section class='ot-screen' id='SCR-001' aria-label='Bottega Vicina' data-entry>",
  "<header class='topbar' data-ot-zone='ZON-001'>",
  "<a href='about:srcdoc#SCR-001' data-elm='ELM-001'>Bottega Vicina</a> ",
  "<button type='button' data-elm='ELM-002'>Accedi</button> ",
  "<button type='button' data-elm='ELM-003'>Carrello</button></header>",
  "<form role='search' aria-label='Cerca nel quartiere' data-ot-zone='ZON-002'>",
  "<input type='search' data-elm='ELM-004' placeholder='Cosa cerchi oggi?'>",
  "<button type='submit' data-elm='ELM-005'>Cerca</button></form>",
  "<main data-ot-zone='ZON-003' data-req='REQ-001'>",
  "<h1 data-elm='ELM-006'>Botteghe del quartiere</h1>",
  "<div class='hero-row' data-ot-zone='ZON-004'>",
  "<section class='panel' aria-labelledby='forno' data-ot-zone='ZON-005'>",
  "<h2 id='forno' data-elm='ELM-007'>Forno Ravasi</h2>",
  "<p data-elm='ELM-008'>Pane caldo dalle sette</p>",
  "<a href='about:srcdoc#SCR-002' data-elm='ELM-009'>Vedi il forno</a></section>",
  "<section class='panel' data-ot-zone='ZON-006' data-req='REQ-002'>",
  "<h2 data-elm='ELM-010'>Panificio Colombo</h2>",
  "<p data-elm='ELM-011'>Focacce e grissini</p>",
  "<a href='about:srcdoc#SCR-002' data-elm='ELM-012'>Vedi il panificio</a></section>",
  "</div></main></section>",
  "<section class='ot-screen' id='SCR-002' aria-label='Forno Ravasi'>",
  "<h1 data-elm='ELM-013'>Forno Ravasi</h1>",
  "<fieldset data-ot-zone='ZON-007'><legend>Ritiro</legend>",
  "<input data-elm='ELM-014' aria-label='Nome'><input data-elm='ELM-015' aria-label='Telefono'>",
  "</fieldset><button type='button' data-elm='ELM-016'>Ordina</button>",
  "</section></body></html>",
].join("");

const SHOP_SCREENS = [
  { code: "SCR-001", title: "Bottega Vicina" },
  { code: "SCR-002", title: "Forno Ravasi" },
];

const SPACED = [
  "<!doctype html><html lang='it'><head><title>Bottega Vicina</title></head><body class='ot-mockup'>",
  "<section class='ot-screen' id='SCR-001' aria-label='Ritiro' data-entry>",
  "<section data-ot-zone='ZON-001' aria-labelledby='ritiro'>",
  "<p id='ritiro' data-elm='ELM-001'>Ritiro e consegna vicino a<br><span>Via Padova 98</span></p>",
  "<ul><li data-elm='ELM-002'><div>Pane di segale</div><span>3,80 €</span><span>Disponibile</span>",
  "<button type='button' data-elm='ELM-003'>Apri</button></li></ul></section>",
  "<button type='button' data-elm='ELM-004'><span>Carrello</span><span>vuoto</span>",
  "<svg></svg><span hidden>0</span></button>",
  "<p data-elm='ELM-005'>A<b>B</b> e <i>C</i>D</p>",
  "<p data-elm='ELM-006'>Totale<svg></svg><textarea>nota</textarea>12 €</p>",
  "</section></body></html>",
].join("");

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

function pointer(
  target: Element,
  type: string,
  bubbles = true,
  keys: Pick<MouseEventInit, "ctrlKey" | "metaKey"> = {},
): boolean {
  return target.dispatchEvent(
    new (windowOf(target).MouseEvent)(type, { bubbles, cancelable: true, ...keys }),
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

async function addPart(code: string): Promise<void> {
  query(`[data-testid='mockup-element'][data-code='${code}']`).dispatchEvent(
    new MouseEvent("click", { bubbles: true, cancelable: true, ctrlKey: true }),
  );
  await flushPromises();
}

function description(element: Element): string {
  const described = document.getElementById(element.getAttribute("aria-describedby") ?? "");
  return (described?.textContent ?? "").replace(/\s+/g, " ").trim();
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
      kind: "element",
      tag: "a",
      label: "Nuovo prestito",
      holds: [],
      parent: null,
      screen: "SCR-001",
      requirements: ["REQ-001", "REQ-004"],
      node: element("ELM-002"),
    });
    expect(describeElement(element("ELM-003")).label).toBe("Cerca un libro");
    expect(describeElement(element("ELM-004")).label).toBe("Rossi 12 giorni");
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
    const part = (selector: string) => describeElement(page.querySelector(selector) as Element);

    expect(changeTarget([part("[data-elm='ELM-002']")])).toEqual({
      screen_code: "SCR-001",
      element_code: "ELM-002",
      label: "Nuovo prestito",
      html: '<a href="#SCR-002" class="btn" data-elm="ELM-002">Nuovo <b>prestito</b></a>',
    });
    const row = changeTarget([part("[data-elm='ELM-004']")]);
    expect(row?.html).not.toContain("ot-pin");
    expect(row?.html).toContain("<td>Rossi</td><td>12 giorni</td>");
    expect(page.querySelector(".ot-pin")).not.toBeNull();

    const loose = parsed(
      `<p data-elm='ELM-020'>${"è".repeat(3000)}</p><button data-elm='ELM-021'></button>`,
    );
    const looseParts = (selector: string, screen: string | null) => [
      describeElement(loose.querySelector(selector) as Element, screen),
    ];
    const long = changeTarget(looseParts("p", "SCR-003"));
    expect(long?.screen_code).toBe("SCR-003");
    expect([...(long?.html ?? "")].length).toBe(2048);
    expect([...(long?.label ?? "")].length).toBe(120);
    expect(changeTarget(looseParts("button", "SCR-003"))?.label).toBe("ELM-021");
    expect(changeTarget(looseParts("button", null))).toBeNull();
    expect(changeTarget([])).toBeNull();
  });

  it("separates the texts of the children as the Studio does, in elements and zones", () => {
    const page = parsed(SPACED);
    const label = (code: string) =>
      describeElement(
        page.querySelector(`[data-elm='${code}'],[data-ot-zone='${code}']`) as Element,
      ).label;

    expect(label("ELM-001")).toBe("Ritiro e consegna vicino a Via Padova 98");
    expect(label("ZON-001")).toBe("Ritiro e consegna vicino a Via Padova 98");
    expect(label("ELM-002")).toBe("Pane di segale 3,80 € Disponibile Apri");
    expect(label("ELM-004")).toBe("Carrello vuoto");
    expect(label("ELM-005")).toBe("AB e CD");
    expect(label("ELM-006")).toBe("Totale 12 €");
  });

  it("knows whether a mockup has elements to point at", () => {
    expect(markedElements(MOCKUP)).toBe(true);
    expect(markedElements("<!doctype html><html><body><h1>Vecchio</h1></body></html>")).toBe(false);
  });

  it("reads the zones of the screen in the order of the page, before the elements they hold", () => {
    const page = parsed(ZONED);
    const codes = screenElements(page).elements.map((element) =>
      describeElement(element, "SCR-001"),
    );

    expect(codes.map((item) => [item.code, item.kind])).toEqual([
      ["ZON-001", "zone"],
      ["ELM-001", "element"],
      ["ELM-002", "element"],
      ["ELM-003", "element"],
      ["ZON-002", "zone"],
      ["ELM-004", "element"],
      ["ELM-005", "element"],
      ["ZON-003", "zone"],
      ["ELM-006", "element"],
      ["ZON-004", "zone"],
      ["ZON-005", "zone"],
      ["ELM-007", "element"],
      ["ELM-008", "element"],
      ["ELM-009", "element"],
      ["ZON-006", "zone"],
      ["ELM-010", "element"],
      ["ELM-011", "element"],
      ["ELM-012", "element"],
    ]);
    expect(
      codes
        .filter((item) => item.kind === "zone")
        .map(({ code, zoneKind, label, holds, parent }) => ({
          code,
          zoneKind,
          label,
          holds,
          parent,
        })),
    ).toEqual([
      {
        code: "ZON-001",
        zoneKind: "header",
        label: "Bottega Vicina Accedi Carrello",
        holds: ["ELM-001", "ELM-002", "ELM-003"],
        parent: null,
      },
      {
        code: "ZON-002",
        zoneKind: "form",
        label: "Cerca nel quartiere",
        holds: ["ELM-004", "ELM-005"],
        parent: null,
      },
      {
        code: "ZON-003",
        zoneKind: "main",
        label: "Botteghe del quartiere",
        holds: ["ELM-006", "ELM-007", "ELM-008", "ELM-009", "ELM-010", "ELM-011", "ELM-012"],
        parent: null,
      },
      {
        code: "ZON-004",
        zoneKind: "cards",
        label: "Forno Ravasi",
        holds: ["ELM-007", "ELM-008", "ELM-009", "ELM-010", "ELM-011", "ELM-012"],
        parent: "ZON-003",
      },
      {
        code: "ZON-005",
        zoneKind: "section",
        label: "Forno Ravasi",
        holds: ["ELM-007", "ELM-008", "ELM-009"],
        parent: "ZON-004",
      },
      {
        code: "ZON-006",
        zoneKind: "section",
        label: "Panificio Colombo",
        holds: ["ELM-010", "ELM-011", "ELM-012"],
        parent: "ZON-004",
      },
    ]);
    const element = codes.find((item) => item.code === "ELM-011");
    expect(element).toMatchObject({
      kind: "element",
      tag: "p",
      label: "Focacce e grissini",
      holds: [],
      parent: "ZON-006",
      screen: "SCR-001",
      requirements: ["REQ-002"],
    });
    expect(element?.zoneKind).toBeUndefined();
    const fieldset = page.querySelector("[data-ot-zone='ZON-007']") as Element;
    expect(describeElement(fieldset)).toMatchObject({
      zoneKind: "group",
      label: "Ritiro",
      tag: "fieldset",
      screen: "SCR-002",
      holds: ["ELM-014", "ELM-015"],
    });
    expect(markedElements("<main data-ot-zone='ZON-001'></main>")).toBe(true);
  });

  it("names the kind of a zone from its tag or from the role of a div, and takes only valid codes", () => {
    const cases = [
      ["nav", "", "navigation"],
      ["div", "navigation", "navigation"],
      ["header", "", "header"],
      ["div", "banner", "header"],
      ["main", "", "main"],
      ["div", "main", "main"],
      ["footer", "", "footer"],
      ["div", "contentinfo", "footer"],
      ["aside", "", "aside"],
      ["div", "complementary", "aside"],
      ["section", "", "section"],
      ["div", "region", "section"],
      ["form", "", "form"],
      ["div", "form", "form"],
      ["div", "search", "form"],
      ["ul", "", "list"],
      ["ol", "", "list"],
      ["dl", "", "list"],
      ["div", "list", "list"],
      ["table", "", "table"],
      ["details", "", "details"],
      ["figure", "", "figure"],
      ["fieldset", "", "group"],
      ["div", "group", "group"],
      ["div", "radiogroup", "group"],
      ["div", "toolbar", "group"],
      ["div", "tablist", "group"],
      ["ul", "tablist", "list"],
      ["section", "navigation", "section"],
      ["div", "presentation", "cards"],
      ["div", "", "cards"],
    ] as const;
    const zones = cases.map(([tag, role], index) => {
      const code = `ZON-${String(index + 1).padStart(3, "0")}`;
      const named = role === "" ? "" : ` role='${role} other'`;
      return `<${tag} data-ot-zone='${code}'${named}></${tag}>`;
    });
    const invalid =
      "<p data-ot-zone='ZONE-1'></p><p data-elm='ELM-12'></p><p data-elm='ELM-1234'>Quattro</p>";

    const page = parsed(zones.join("") + invalid);
    const found = screenElements(page).elements.map((element) => describeElement(element));
    expect(found.map((item) => item.zoneKind ?? item.code)).toEqual([
      ...cases.map(([, , kind]) => kind),
      "ELM-1234",
    ]);
  });

  it("builds the target of a zone without its markup and of several parts in the order of the page", () => {
    const page = parsed(ZONED);
    const part = (code: string) =>
      describeElement(
        page.querySelector(`[data-elm='${code}'],[data-ot-zone='${code}']`) as Element,
      );

    expect(changeTarget([part("ZON-005")])).toEqual({
      screen_code: "SCR-001",
      element_code: "ZON-005",
      label: "Forno Ravasi",
    });
    expect(changeTarget([part("ELM-007"), part("ELM-011"), part("ZON-002")])).toEqual({
      screen_code: "SCR-001",
      elements: [
        { element_code: "ELM-007", label: "Forno Ravasi" },
        { element_code: "ELM-011", label: "Focacce e grissini" },
        { element_code: "ZON-002", label: "Cerca nel quartiere" },
      ],
    });
    const empty = parsed("<section id='SCR-004'><div data-ot-zone='ZON-009'></div></section>");
    expect(changeTarget([describeElement(empty.querySelector("div") as Element)])).toEqual({
      screen_code: "SCR-004",
      element_code: "ZON-009",
      label: "ZON-009",
    });
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

  it("lists every element and zone with the texts of their children kept apart", async () => {
    inspector(frameWith(SPACED), { screens: [{ code: "SCR-001", title: "Ritiro" }] });
    await flushPromises();
    const options = all("[data-testid='mockup-element']");

    expect(options.map((option) => option.getAttribute("aria-label"))).toEqual([
      "ZON-001, sezione, 3 elementi, Ritiro e consegna vicino a Via Padova 98",
      "ELM-001, p, Ritiro e consegna vicino a Via Padova 98",
      "ELM-002, li, Pane di segale 3,80 € Disponibile Apri",
      "ELM-003, button, Apri",
      "ELM-004, button, Carrello vuoto",
      "ELM-005, p, AB e CD",
      "ELM-006, p, Totale 12 €",
    ]);
    expect(options[2]?.textContent).toContain("Pane di segale 3,80 € Disponibile Apri");
    expect(options[4]?.textContent).toContain("Carrello vuoto");
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
    expect(list.hasAttribute("aria-multiselectable")).toBe(false);
    expect(press(list, " ").defaultPrevented).toBe(true);
    await flushPromises();
    expect(options().map((option) => option.getAttribute("aria-selected"))).toEqual([
      "false",
      "true",
      "false",
      "true",
    ]);
    expect(list.getAttribute("aria-multiselectable")).toBe("true");
    expect(all("[data-testid='mockup-part']").map((part) => part.dataset.code)).toEqual([
      "ELM-002",
      "ELM-004",
    ]);
    expect(text("[data-testid='mockup-inspect-announcement']")).toBe(
      "Hai aggiunto ELM-004 (2 parti scelte): Rossi 12 giorni",
    );
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
      selected: [],
    });

    expect(pointer(inFrame(frame, "[data-elm='ELM-002'] b"), "click")).toBe(false);
    await flushPromises();
    expect(last()).toEqual({
      hover: null,
      selected: [{ code: "ELM-002", left: 40, top: 80, width: 120, height: 32 }],
    });
    expect(text("[data-testid='mockup-selection-code']")).toBe("ELM-002");
    expect(
      query("[data-testid='mockup-element'][data-code='ELM-002']").getAttribute("aria-selected"),
    ).toBe("true");

    pointer(title, "mousemove");
    await flushPromises();
    expect(last()).toEqual({
      hover: { code: "ELM-001", left: 24, top: 16, width: 600, height: 48 },
      selected: [{ code: "ELM-002", left: 40, top: 80, width: 120, height: 32 }],
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
    expect(last()).toEqual({ hover: null, selected: [] });
  });

  it("follows the scroll of the document and stops listening to it once it is closed", async () => {
    const frame = frameWith(MOCKUP);
    const link = inFrame(frame, "[data-elm='ELM-002']");
    placed(link, 40, 80, 120, 32);
    const view = inspector(frame);
    await choose("ELM-002");
    placed(link, 40, 20, 120, 32);

    scrolled(frame);
    expect(view.emitted("highlight")?.at(-1)?.[0]).toMatchObject({ selected: [{ top: 20 }] });
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

interface ProposedSetup {
  html?: string;
  codes?: readonly string[];
  run?: DesignEvaluationRunPayload;
}

async function proposed(
  props: Partial<InstanceType<typeof MockupInspector>["$props"]> = {},
  { html = MOCKUP, codes = ["ELM-002"], run = reviewRun(NEXT) }: ProposedSetup = {},
) {
  const iterationsApi = fakeApi(job("SUCCEEDED", { result: proposal() }));
  const designApi = fakeDesignApi();
  const loopApi = fakeLoopApi(run);
  current(VERSION);
  const view = inspector(frameWith(html), {
    api: iterationsApi,
    designApi: designApi as unknown as DesignApi,
    loopApi: loopApi as unknown as DesignLoopApi,
    ...props,
  });
  for (const [index, code] of codes.entries()) {
    await (index === 0 ? choose(code) : addPart(code));
  }
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
      "HELPS",
      "BLOCKS",
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

const SHOP_FINDINGS = [
  twinFinding(
    6,
    "major",
    "ZON-002",
    "La ricerca è nascosta in mezzo alla pagina.",
    "Metti la ricerca in alto.",
  ),
  twinFinding(7, "observation", "ELM-011", "Le focacce si leggono bene.", "Tieni questo testo."),
  twinFinding(8, "minor", "ELM-001", "Il nome della bottega è piccolo.", "Ingrandisci il nome."),
];

function parts(): string[] {
  return all("[data-testid='mockup-part']").map((part) => part.dataset.code ?? "");
}

function chosenOptions(): string[] {
  return all("[data-testid='mockup-element'][aria-selected='true']").map(
    (option) => option.dataset.code ?? "",
  );
}

function chosenBoxes(view: VueWrapper): string[] | undefined {
  const highlight = view.emitted<[InspectorHighlight]>("highlight")?.at(-1)?.[0];
  return highlight?.selected.map((box) => box.code);
}

async function ask(request: string): Promise<void> {
  const field = query<HTMLTextAreaElement>("[data-testid='mockup-request']");
  field.value = request;
  field.dispatchEvent(new Event("input"));
  await flushPromises();
}

describe("pointing at zones and several parts", () => {
  it("lists the zones before their elements with their kind in words and the number of elements", async () => {
    inspector(frameWith(ZONED), { screens: SHOP_SCREENS });
    await flushPromises();
    const options = all("[data-testid='mockup-element']");
    const first = options.slice(0, 5);

    expect(first.map((option) => [option.dataset.code, option.dataset.kind])).toEqual([
      ["ZON-001", "zone"],
      ["ELM-001", "element"],
      ["ELM-002", "element"],
      ["ELM-003", "element"],
      ["ZON-002", "zone"],
    ]);
    expect(options.map((option) => option.getAttribute("aria-label")).slice(0, 2)).toEqual([
      "ZON-001, intestazione, 3 elementi, Bottega Vicina Accedi Carrello",
      "ELM-001, a, Bottega Vicina",
    ]);
    expect(options[9]?.getAttribute("aria-label")).toBe(
      "ZON-004, gruppo di schede, 6 elementi, Forno Ravasi",
    );
    expect(options[0]?.textContent).toContain("intestazione, 3 elementi");
    expect(options[0]?.textContent).toContain("Bottega Vicina Accedi Carrello");
    const toggle = query<HTMLInputElement>("[data-testid='mockup-multi']");
    expect(toggle.type).toBe("checkbox");
    expect(toggle.checked).toBe(false);
    expect(toggle.closest("label")?.textContent?.trim()).toBe("Scegli più elementi");
    expect(description(toggle)).toBe(
      "Quando è acceso, ogni clic aggiunge o toglie un elemento, fino a 8. Quando è spento puoi farlo con Ctrl o ⌘ e un clic sul mockup, o con la barra spaziatrice nell'elenco.",
    );
    expect(query("[data-testid='mockup-elements']").hasAttribute("aria-multiselectable")).toBe(
      false,
    );
  });

  it("shows a chosen zone with its text, its requirements and the first elements it holds", async () => {
    inspector(frameWith(ZONED), { screens: SHOP_SCREENS });
    await choose("ZON-005");

    expect(text("[data-testid='mockup-selection'] h4")).toBe("Zona scelta");
    expect(text("[data-testid='mockup-selection-code']")).toBe("ZON-005");
    expect(text("[data-testid='mockup-selection-screen']")).toBe("SCR-001 · Bottega Vicina");
    expect(text("[data-testid='mockup-selection-text']")).toBe("Forno Ravasi");
    expect(texts("[data-testid='mockup-requirement']")).toEqual(["REQ-001"]);
    expect(text("[data-testid='mockup-selection-holds'] p")).toBe("Contiene 3 elementi");
    expect(texts("[data-testid='mockup-selection-held']")).toEqual([
      "ELM-007 Forno Ravasi",
      "ELM-008 Pane caldo dalle sette",
      "ELM-009 Vedi il forno",
    ]);
    expect(text("[data-testid='mockup-inspect-announcement']")).toBe(
      "Hai scelto ZON-005: Forno Ravasi",
    );
    expect(document.body.querySelector("[data-testid='mockup-parts']")).toBeNull();

    await choose("ZON-003");
    expect(text("[data-testid='mockup-selection-holds'] p")).toBe("Contiene 7 elementi");
    expect(texts("[data-testid='mockup-selection-held']")).toEqual([
      "ELM-006 Botteghe del quartiere",
      "ELM-007 Forno Ravasi",
      "ELM-008 Pane caldo dalle sette",
    ]);
    query<HTMLInputElement>("[data-testid='mockup-review']").click();
    await flushPromises();
    expect(text("[data-testid='mockup-ask-twins']")).toBe(
      "Chiedi il parere dei twin su questa zona",
    );

    await choose("ELM-008");
    expect(document.body.querySelector("[data-testid='mockup-selection-holds']")).toBeNull();
    expect(text("[data-testid='mockup-selection'] h4")).toBe("Elemento scelto");
  });

  it("adds and removes parts with Ctrl or ⌘ and a click, with the space bar and with the switch on", async () => {
    const frame = frameWith(ZONED);
    const view = inspector(frame, { screens: SHOP_SCREENS });
    await flushPromises();
    const list = query("[data-testid='mockup-elements']");
    const announced = () => text("[data-testid='mockup-inspect-announcement']");

    pointer(inFrame(frame, "[data-elm='ELM-008']"), "click");
    pointer(inFrame(frame, "[data-elm='ELM-011']"), "click", true, { ctrlKey: true });
    await flushPromises();
    expect(announced()).toBe("Hai aggiunto ELM-011 (2 parti scelte): Focacce e grissini");
    pointer(inFrame(frame, "[data-ot-zone='ZON-002']"), "click", true, { metaKey: true });
    await flushPromises();

    expect(parts()).toEqual(["ZON-002", "ELM-008", "ELM-011"]);
    expect(chosenOptions()).toEqual(["ZON-002", "ELM-008", "ELM-011"]);
    expect(list.getAttribute("aria-multiselectable")).toBe("true");
    expect(text("[data-testid='mockup-selection'] h4")).toBe("Parti scelte");
    expect(
      all("[data-testid='mockup-part-remove']").map((button) => button.getAttribute("aria-label")),
    ).toEqual([
      "Togli ZON-002, modulo, 2 elementi, Cerca nel quartiere",
      "Togli ELM-008, p, Pane caldo dalle sette",
      "Togli ELM-011, p, Focacce e grissini",
    ]);
    expect(all("[data-testid='mockup-part']")[0]?.textContent).toContain("Cerca nel quartiere");
    expect(texts("[data-testid='mockup-requirement']")).toEqual(["REQ-001", "REQ-002"]);
    expect(text("[data-testid='mockup-selection-screen']")).toBe("SCR-001 · Bottega Vicina");
    expect(document.body.querySelector("[data-testid='mockup-selection-code']")).toBeNull();
    expect(document.body.querySelector("[data-testid='mockup-selection-text']")).toBeNull();
    expect(chosenBoxes(view)).toEqual(["ZON-002", "ELM-008", "ELM-011"]);

    pointer(inFrame(frame, "[data-elm='ELM-011']"), "click", true, { ctrlKey: true });
    await flushPromises();
    expect(parts()).toEqual(["ZON-002", "ELM-008"]);
    expect(announced()).toBe("Hai tolto ELM-011 (2 parti scelte).");

    pointer(inFrame(frame, "[data-elm='ELM-001']"), "click");
    await flushPromises();
    expect(chosenOptions()).toEqual(["ELM-001"]);
    expect(text("[data-testid='mockup-selection-code']")).toBe("ELM-001");
    expect(announced()).toBe("Hai scelto ELM-001: Bottega Vicina");
    expect(list.hasAttribute("aria-multiselectable")).toBe(false);

    query("[data-testid='mockup-multi']").click();
    await flushPromises();
    expect(list.getAttribute("aria-multiselectable")).toBe("true");
    await choose("ELM-002");
    pointer(inFrame(frame, "[data-elm='ELM-003']"), "click");
    await flushPromises();
    expect(chosenOptions()).toEqual(["ELM-001", "ELM-002", "ELM-003"]);
    press(list, "End");
    await flushPromises();
    expect(press(list, " ").defaultPrevented).toBe(true);
    await flushPromises();
    expect(chosenOptions()).toEqual(["ELM-001", "ELM-002", "ELM-003", "ELM-012"]);
    expect(press(list, "Enter").defaultPrevented).toBe(true);
    await flushPromises();
    expect(chosenOptions()).toEqual(["ELM-012"]);
    await choose("ELM-012");
    expect(chosenOptions()).toEqual([]);
    expect(announced()).toBe("Nessun elemento scelto.");
  });

  it("chooses at most eight parts and says so", async () => {
    inspector(frameWith(ZONED));
    await flushPromises();
    query("[data-testid='mockup-multi']").click();
    await flushPromises();
    const codes = ["ZON-001", "ELM-001", "ELM-002", "ELM-003", "ZON-002", "ELM-004", "ELM-005"];
    for (const code of [...codes, "ZON-003", "ELM-006"]) {
      await choose(code);
    }

    expect(parts()).toEqual([...codes, "ZON-003"]);
    expect(text("[data-testid='mockup-inspect-announcement']")).toBe(
      "Puoi scegliere al massimo 8 parti.",
    );
    expect(
      query("[data-testid='mockup-element'][data-code='ELM-006']").getAttribute("aria-selected"),
    ).toBe("false");
    await choose("ZON-003");
    expect(parts()).toEqual(codes);
    await choose("ELM-006");
    expect(parts()).toEqual([...codes, "ELM-006"]);
  });

  it("chooses the zone that holds the last part, one level at a time", async () => {
    inspector(frameWith(ZONED), { screens: SHOP_SCREENS });
    await choose("ELM-008");
    const parent = () => query("[data-testid='mockup-select-parent']");

    expect(text("[data-testid='mockup-select-parent']")).toBe("Scegli la zona che lo contiene");
    expect(description(parent())).toBe("ZON-005, sezione, 3 elementi, Forno Ravasi");
    parent().focus();
    parent().click();
    await flushPromises();
    expect(text("[data-testid='mockup-selection-code']")).toBe("ZON-005");
    expect(text("[data-testid='mockup-inspect-announcement']")).toBe(
      "Hai scelto ZON-005: Forno Ravasi",
    );
    expect(document.activeElement).toBe(parent());
    expect(description(parent())).toBe("ZON-004, gruppo di schede, 6 elementi, Forno Ravasi");

    parent().click();
    await flushPromises();
    expect(description(parent())).toBe(
      "ZON-003, contenuto principale, 7 elementi, Botteghe del quartiere",
    );
    parent().click();
    await flushPromises();
    expect(text("[data-testid='mockup-selection-code']")).toBe("ZON-003");
    expect(document.body.querySelector("[data-testid='mockup-select-parent']")).toBeNull();
    expect(document.activeElement).toBe(query("[data-testid='mockup-request']"));

    await choose("ELM-001");
    await addPart("ELM-010");
    expect(description(parent())).toBe("ZON-006, sezione, 3 elementi, Panificio Colombo");
    parent().click();
    await flushPromises();
    expect(parts()).toEqual(["ELM-001", "ZON-006"]);
    expect(text("[data-testid='mockup-inspect-announcement']")).toBe(
      "Hai aggiunto ZON-006 (2 parti scelte): Panificio Colombo",
    );
    expect(description(parent())).toBe("ZON-004, gruppo di schede, 6 elementi, Forno Ravasi");
  });

  it("removes a part from the chosen ones and keeps the focus on the list of parts", async () => {
    inspector(frameWith(ZONED));
    await choose("ELM-001");
    await addPart("ELM-008");
    await addPart("ZON-006");
    const removers = () => all("[data-testid='mockup-part-remove']");

    expect(removers().map((button) => button.textContent?.trim())).toEqual([
      "Togli",
      "Togli",
      "Togli",
    ]);
    expect(removers()[1]?.getAttribute("aria-label")).toBe(
      "Togli ELM-008, p, Pane caldo dalle sette",
    );
    removers()[1]?.focus();
    removers()[1]?.click();
    await flushPromises();
    expect(parts()).toEqual(["ELM-001", "ZON-006"]);
    expect(text("[data-testid='mockup-inspect-announcement']")).toBe(
      "Hai tolto ELM-008 (2 parti scelte).",
    );
    expect(document.activeElement).toBe(removers()[1]);

    removers()[1]?.click();
    await flushPromises();
    expect(document.body.querySelector("[data-testid='mockup-parts']")).toBeNull();
    expect(text("[data-testid='mockup-selection-code']")).toBe("ELM-001");
    expect(text("[data-testid='mockup-inspect-announcement']")).toBe(
      "Hai tolto ZON-006 (1 parte scelta).",
    );
    expect(document.activeElement).toBe(query("[data-testid='mockup-request']"));
  });

  it("keeps in a new version only the parts that stayed the same and clears them with Esc or another screen", async () => {
    const frame = frameWith(ZONED);
    const view = inspector(frame, { screens: SHOP_SCREENS });
    const announced = () => text("[data-testid='mockup-inspect-announcement']");
    await choose("ELM-008");
    await addPart("ELM-011");
    await addPart("ZON-006");

    load(frame, "<!doctype html><html><head></head><body></body></html>");
    await view.setProps({ loads: 2 });
    expect(document.body.querySelector("[data-testid='mockup-selection']")).toBeNull();
    load(frame, ZONED.replace("Focacce e grissini", "Focacce, grissini e taralli"));
    await view.setProps({ loads: 3 });
    expect(parts()).toEqual(["ELM-008", "ZON-006"]);
    expect(announced()).toBe(
      "Ho tolto dalla scelta ELM-011: nella nuova versione sono cambiati o non ci sono più.",
    );

    load(frame, ZONED.replace("dalle sette", "dalle sei").replace(" data-ot-zone='ZON-006'", ""));
    await view.setProps({ loads: 4 });
    expect(document.body.querySelector("[data-testid='mockup-selection']")).toBeNull();
    expect(announced()).toBe(
      "Ho tolto dalla scelta ELM-008 e ZON-006: nella nuova versione sono cambiati o non ci sono più.",
    );

    load(frame, ZONED);
    await view.setProps({ loads: 5 });
    await choose("ELM-001");
    await addPart("ELM-002");
    expect(press(inFrame(frame, "body"), "Escape").defaultPrevented).toBe(true);
    await flushPromises();
    expect(document.body.querySelector("[data-testid='mockup-selection']")).toBeNull();
    expect(announced()).toBe("Nessun elemento scelto.");
    expect(chosenBoxes(view)).toEqual([]);

    await choose("ELM-008");
    await addPart("ELM-011");
    const entry = " data-entry";
    load(frame, ZONED.replace(entry, "").replace("id='SCR-002'", `id='SCR-002'${entry}`));
    await view.setProps({ loads: 6, screen: "SCR-002" });
    expect(document.body.querySelector("[data-testid='mockup-selection']")).toBeNull();
    expect(announced()).toBe("Scelta azzerata: la schermata è cambiata.");
    expect(all("[data-testid='mockup-element']").map((option) => option.dataset.code)).toEqual([
      "ELM-013",
      "ZON-007",
      "ELM-014",
      "ELM-015",
      "ELM-016",
    ]);
  });

  it("asks for a change aimed at several parts and asks the twins about the same parts once applied", async () => {
    let finish!: (run: DesignEvaluationRunPayload) => void;
    const run = reviewRun(NEXT, SHOP_FINDINGS);
    const { iterationsApi, loopApi } = await proposed(
      { screens: SHOP_SCREENS },
      { html: ZONED, codes: ["ELM-011", "ZON-002", "ELM-008"], run },
    );

    expect(iterationsApi.startJob.mock.calls[0]?.[1]).toEqual({
      design_version_id: VERSION.id,
      design_content_hash: HASH,
      request: "Rendi il collegamento più evidente",
      assertions: [],
      target: {
        screen_code: "SCR-001",
        elements: [
          { element_code: "ZON-002", label: "Cerca nel quartiere" },
          { element_code: "ELM-008", label: "Pane caldo dalle sette" },
          { element_code: "ELM-011", label: "Focacce e grissini" },
        ],
      },
    });
    expect(text("[data-testid='mockup-version-note']")).toBe(
      "Dopo l'applicazione i twin guardano ZON-002, ELM-008 e ELM-011: di solito serve un paio di minuti.",
    );
    loopApi.evaluate.mockImplementationOnce(
      () =>
        new Promise<DesignEvaluationRunPayload>((resolve) => {
          finish = resolve;
        }),
    );
    query("[data-testid='mockup-apply-version']").click();
    await flushPromises();

    expect(text("[data-testid='mockup-review-status']")).toContain(
      "I twin stanno guardando le parti scelte…",
    );
    expect(loopApi.evaluate).toHaveBeenCalledExactlyOnceWith(
      DESIGN_PROJECT_ID,
      {
        design_version_id: NEXT.id,
        design_content_hash: NEXT_HASH,
        mode: "TWIN_REVIEW",
        locale: "it-IT",
        scope: { screen_code: "SCR-001", element_codes: ["ZON-002", "ELM-008", "ELM-011"] },
      },
      "token",
    );
    finish(run);
    await flushPromises();
    expect(text("[data-testid='mockup-review-status']")).toBe(
      "I twin hanno detto la loro su ZON-002, ELM-008 e ELM-011: le loro note sono accanto alle parti scelte.",
    );
    expect(texts("[data-testid='mockup-twin-note-summary']")).toEqual([
      "La ricerca è nascosta in mezzo alla pagina.",
      "Le focacce si leggono bene.",
    ]);
    query<HTMLInputElement>("[data-testid='mockup-review']").click();
    await flushPromises();
    expect(text("[data-testid='mockup-ask-twins']")).toBe(
      "Chiedi il parere dei twin su queste parti",
    );
  });

  it("asks for a change aimed at a zone without its markup and asks the twins about that zone", async () => {
    let finish!: (run: DesignEvaluationRunPayload) => void;
    const run = reviewRun(NEXT, [
      twinFinding(9, "moderate", "ZON-005", "La scheda del forno è affollata.", "Lascia spazio."),
      ...SHOP_FINDINGS,
    ]);
    const { iterationsApi, loopApi } = await proposed(
      { screens: SHOP_SCREENS },
      { html: ZONED, codes: ["ZON-005"], run },
    );

    expect(iterationsApi.startJob.mock.calls[0]?.[1]).toMatchObject({
      target: { screen_code: "SCR-001", element_code: "ZON-005", label: "Forno Ravasi" },
    });
    expect(iterationsApi.startJob.mock.calls[0]?.[1].target).not.toHaveProperty("html");
    expect(text("[data-testid='mockup-version-note']")).toBe(
      "Dopo l'applicazione i twin guardano ZON-005: di solito serve un paio di minuti.",
    );
    loopApi.evaluate.mockImplementationOnce(
      () =>
        new Promise<DesignEvaluationRunPayload>((resolve) => {
          finish = resolve;
        }),
    );
    query("[data-testid='mockup-apply-version']").click();
    await flushPromises();
    expect(text("[data-testid='mockup-review-status']")).toContain(
      "I twin stanno guardando la zona…",
    );
    expect(loopApi.evaluate.mock.calls[0]?.[1]).toMatchObject({
      scope: { screen_code: "SCR-001", element_code: "ZON-005" },
    });
    finish(run);
    await flushPromises();
    expect(text("[data-testid='mockup-review-status']")).toBe(
      "I twin hanno detto la loro su ZON-005: le loro note sono accanto alla zona.",
    );
    expect(texts("[data-testid='mockup-twin-note-summary']")).toEqual([
      "La scheda del forno è affollata.",
    ]);
  });

  it("speaks English for zones and several parts", async () => {
    inspector(frameWith(ZONED), { locale: "en", screens: SHOP_SCREENS });
    await flushPromises();
    expect(query("[data-testid='mockup-multi']").closest("label")?.textContent?.trim()).toBe(
      "Choose several elements",
    );
    expect(text("[data-testid='mockup-multi-hint']")).toBe(
      "When it is on, each click adds or removes an element, up to 8. When it is off you can do it with Ctrl or ⌘ and a click on the mockup, or with the space bar in the list.",
    );
    expect(all("[data-testid='mockup-element']")[0]?.getAttribute("aria-label")).toBe(
      "ZON-001, header, 3 elements, Bottega Vicina Accedi Carrello",
    );
    await choose("ZON-004");
    expect(text("[data-testid='mockup-selection'] h4")).toBe("Chosen zone");
    expect(text("[data-testid='mockup-selection-holds'] p")).toBe("Holds 6 elements");
    expect(text("[data-testid='mockup-select-parent']")).toBe("Choose the zone that holds it");
    await addPart("ELM-001");
    expect(text("[data-testid='mockup-inspect-announcement']")).toBe(
      "You added ELM-001 (2 parts chosen): Bottega Vicina",
    );
    expect(text("[data-testid='mockup-selection'] h4")).toBe("Chosen parts");
    expect(texts("[data-testid='mockup-part-remove']")).toEqual(["Remove", "Remove"]);
    expect(query("[data-testid='mockup-part-remove']").getAttribute("aria-label")).toBe(
      "Remove ELM-001, a, Bottega Vicina",
    );
    await ask("Make them larger");
    query("[data-testid='mockup-review']").click();
    await flushPromises();
    expect(text("[data-testid='mockup-ask-twins']")).toBe(
      "Ask the twins for their opinion on these parts",
    );
  });

  it("has no axe violations with the zones, with several parts and with a chosen zone", async () => {
    inspector(frameWith(ZONED), { screens: SHOP_SCREENS });
    await flushPromises();
    query("[data-testid='mockup-multi']").click();
    await flushPromises();
    await expectAccessible(query("[data-testid='mockup-inspector']"), { iframes: false });
    await choose("ELM-008");
    await choose("ZON-006");
    expect(parts()).toEqual(["ELM-008", "ZON-006"]);
    await expectAccessible(query("[data-testid='mockup-inspector']"), { iframes: false });
    query("[data-testid='mockup-multi']").click();
    await choose("ZON-005");
    expect(text("[data-testid='mockup-selection-code']")).toBe("ZON-005");
    await expectAccessible(query("[data-testid='mockup-inspector']"), { iframes: false });
  });
});

const OPINION_ID = "44444444-4444-4444-8444-444444444444";
const BLUE_ON_RED = "Rendi la barra rossa con il testo blu";
const REWRITTEN = "Rendi la barra rossa con il testo bianco";
const BAR: DesignChangeTarget = {
  screen_code: "SCR-001",
  element_code: "ZON-001",
  label: "Bottega Vicina Accedi Carrello",
};

const CORRECTIONS: MockupCorrectionPayload[] = [
  {
    code: "TEXT_COLOUR_REPLACED",
    selector: ".topbar a",
    property: "color",
    before: { value: "#0a84ff", hex: "#0A84FF", ratio: 2.13, name: "blue" },
    after: { token: "on-primary", hex: "#FFFFFF", ratio: 4.02, name: "white" },
    background: { hex: "#FF3B30", name: "red", inherited: false },
    threshold: 4.5,
    large_text: false,
    count: 1,
  },
  {
    code: "CONTROL_BORDER_REPLACED",
    selector: "input",
    property: "border-color",
    before: { value: "#c7c7cc", hex: "#C7C7CC", ratio: 1.53, name: "grey" },
    after: { token: "text-muted", hex: "#8E8E93", ratio: 3.12, name: "grey" },
    background: { hex: "#FFFFFF", name: "white", inherited: true },
    threshold: 3,
    large_text: false,
    count: 3,
  },
];

function twinOpinion(
  opinion: Pick<ChangeOpinion, "twin_id" | "twin_name" | "verdict" | "why" | "what_to_do"> &
    Partial<ChangeOpinion>,
): ChangeOpinion {
  return {
    twin_version: 1,
    try_this: null,
    profile_keys: ["goals"],
    confidence: 0.7,
    generation_id: `${opinion.twin_id}-generation`,
    ...opinion,
  };
}

const OPINION_RUN: ChangeOpinionRun = {
  run_id: OPINION_ID,
  design_version_id: VERSION.id,
  design_content_hash: HASH,
  design_version_number: 1,
  request: BLUE_ON_RED,
  target: BAR,
  locale: "it-IT",
  requested_at: "2026-10-12T10:00:00+00:00",
  opinions: [
    twinOpinion({
      twin_id: "55555555-5555-4555-8555-555555555551",
      twin_name: "Piccolo produttore locale",
      verdict: "BLOCKS",
      why: "Il testo blu su ZON-001 non si legge: 2,1:1 è sotto il minimo di 4,5:1.",
      what_to_do: "Tieni bianco il testo di ELM-002.",
      try_this: REWRITTEN,
    }),
    twinOpinion({
      twin_id: "55555555-5555-4555-8555-555555555552",
      twin_name: "Acquirente di fretta in pausa pranzo",
      verdict: "SLOWS",
      why: "Con il rosso cerco ELM-003 due volte.",
      what_to_do: "Ingrandisci ELM-003.",
    }),
  ],
  contrast: {
    mode: "LIGHT",
    text_threshold: 4.5,
    large_text_threshold: 3,
    control_border_threshold: 3,
  },
  cost_microusd: null,
};

function fakeOpinionsApi() {
  return {
    ask: vi.fn<DesignOpinionsApi["ask"]>(async () => OPINION_RUN),
  };
}

function corrected(): MockupResultPayload {
  return { ...proposal(), corrections: CORRECTIONS };
}

function opinionBody(target: DesignChangeTarget) {
  return {
    design_version_id: VERSION.id,
    design_content_hash: HASH,
    request: BLUE_ON_RED,
    target,
    locale: "it-IT",
  };
}

async function pointedWithRequest(
  props: Partial<InstanceType<typeof MockupInspector>["$props"]>,
  codes: readonly string[] = ["ZON-001"],
): Promise<VueWrapper> {
  current(VERSION);
  const view = inspector(frameWith(ZONED), { screens: SHOP_SCREENS, ...props });
  for (const [index, code] of codes.entries()) {
    await (index === 0 ? choose(code) : addPart(code));
  }
  await ask(BLUE_ON_RED);
  return view;
}

async function askedFirst(props: Partial<InstanceType<typeof MockupInspector>["$props"]> = {}) {
  const opinionsApi = fakeOpinionsApi();
  const iterationsApi = fakeApi(job("SUCCEEDED", { result: proposal() }));
  const view = await pointedWithRequest({ api: iterationsApi, opinionsApi, ...props });
  query("[data-testid='mockup-ask-first']").click();
  await flushPromises();
  return { view, opinionsApi, iterationsApi };
}

function follows(first: Element, second: Element): boolean {
  return (first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
}

describe("asking the twins before the change", () => {
  it("offers «Chiedi ai twin prima di applicare» after the change only with a part and a text", async () => {
    current(VERSION);
    inspector(frameWith(ZONED), { screens: SHOP_SCREENS, opinionsApi: fakeOpinionsApi() });
    await choose("ZON-001");
    const button = () => query("[data-testid='mockup-ask-first']");

    expect(text("[data-testid='mockup-ask-first']")).toBe("Chiedi ai twin prima di applicare");
    expect(button().getAttribute("aria-disabled")).toBe("true");
    expect(description(button())).toBe("Di solito servono circa 2 minuti.");
    expect(follows(query("[data-testid='mockup-apply']"), button())).toBe(true);
    await ask("   ");
    expect(button().getAttribute("aria-disabled")).toBe("true");
    await ask(BLUE_ON_RED);
    expect(button().hasAttribute("aria-disabled")).toBe(false);
    expect(document.body.querySelector("[data-testid='mockup-change-opinions']")).toBeNull();
  });

  it("keeps the button off while another version waits for a decision", async () => {
    const opinionsApi = fakeOpinionsApi();
    current(VERSION);
    await useDesignIterationsStore().start({ request: "Altro" }, authorize, {
      api: fakeApi(job("SUCCEEDED", { result: proposal() })),
    });
    inspector(frameWith(ZONED), { screens: SHOP_SCREENS, opinionsApi });
    await choose("ZON-001");
    await ask(BLUE_ON_RED);
    const button = query("[data-testid='mockup-ask-first']");

    expect(button.getAttribute("aria-disabled")).toBe("true");
    expect(button.getAttribute("aria-describedby")?.split(" ")).toHaveLength(2);
    button.click();
    await flushPromises();
    expect(opinionsApi.ask).not.toHaveBeenCalled();
  });

  it("keeps the button off while the designer draws the change", async () => {
    const opinionsApi = fakeOpinionsApi();
    await pointedWithRequest({ api: fakeApi(job("RUNNING")), opinionsApi });
    query("[data-testid='mockup-apply']").click();
    await flushPromises();
    await ask(BLUE_ON_RED);
    const button = query("[data-testid='mockup-ask-first']");

    expect(text("[data-testid='mockup-change-status']")).toContain(
      "Il designer sta disegnando le schermate.",
    );
    expect(button.getAttribute("aria-disabled")).toBe("true");
    button.click();
    await flushPromises();
    expect(opinionsApi.ask).not.toHaveBeenCalled();
  });

  it("asks the twins about the request and the zone, waits under the field and shows their opinions", async () => {
    let answer!: (run: ChangeOpinionRun) => void;
    const opinionsApi = fakeOpinionsApi();
    opinionsApi.ask.mockImplementationOnce(
      () =>
        new Promise<ChangeOpinionRun>((resolve) => {
          answer = resolve;
        }),
    );
    await pointedWithRequest({ opinionsApi });
    query("[data-testid='mockup-ask-first']").click();
    await flushPromises();

    expect(opinionsApi.ask).toHaveBeenCalledExactlyOnceWith(
      DESIGN_PROJECT_ID,
      opinionBody(BAR),
      "token",
    );
    const opinions = query("[data-testid='mockup-change-opinions']");
    expect(follows(query("[data-testid='mockup-request']"), opinions)).toBe(true);
    expect(follows(opinions, query("[data-testid='mockup-apply']"))).toBe(true);
    expect(text("[data-testid='mockup-opinions-busy']")).toContain(
      "I twin stanno leggendo la richiesta…",
    );
    expect(document.body.querySelector("[data-testid='mockup-change-status']")).toBeNull();
    expect(query("[data-testid='mockup-ask-first']").getAttribute("aria-disabled")).toBe("true");

    answer(OPINION_RUN);
    await flushPromises();

    expect(all("[data-testid='mockup-opinion']").map((card) => card.dataset.verdict)).toEqual([
      "BLOCKS",
      "SLOWS",
    ]);
    expect(texts("[data-testid='mockup-opinion-twin']")).toEqual([
      "Piccolo produttore locale",
      "Acquirente di fretta in pausa pranzo",
    ]);
    expect(texts("[data-testid='mockup-opinion-verdict']")).toEqual(["Blocca", "Rallenta"]);
    expect(texts("[data-testid='mockup-opinion-why']")).toEqual([
      "Il testo blu su «Bottega Vicina Accedi Carrello» non si legge: 2,1:1 è sotto il minimo di 4,5:1.",
      "Con il rosso cerco «Carrello» due volte.",
    ]);
    expect(texts("[data-testid='mockup-opinion-action']")).toEqual([
      "Cosa fare: Tieni bianco il testo di «Accedi».",
      "Cosa fare: Ingrandisci «Carrello».",
    ]);
    expect(text("[data-testid='mockup-opinions-announcement']")).toBe(
      "Parere di 2 twin: 1 rallenta, 1 blocca",
    );
    expect(document.activeElement).toBe(query("[data-testid='mockup-change-opinions'] h5"));
    expect(text("[data-testid='mockup-apply-anyway']")).toBe("Applica comunque");
    expect(document.body.querySelector("[data-testid='mockup-opinion-stale']")).toBeNull();
    expect(query("[data-testid='mockup-ask-first']").hasAttribute("aria-disabled")).toBe(false);
  });

  it("asks about several parts with their codes and labels in the order of the page", async () => {
    const opinionsApi = fakeOpinionsApi();
    await pointedWithRequest({ opinionsApi }, ["ELM-011", "ZON-002"]);
    query("[data-testid='mockup-ask-first']").click();
    await flushPromises();

    expect(opinionsApi.ask.mock.calls[0]?.[1]).toEqual(
      opinionBody({
        screen_code: "SCR-001",
        elements: [
          { element_code: "ZON-002", label: "Cerca nel quartiere" },
          { element_code: "ELM-011", label: "Focacce e grissini" },
        ],
      }),
    );
  });

  it("applies anyway with the same text, the same parts and the opinion, which then gets stale", async () => {
    const { iterationsApi } = await askedFirst({
      designApi: fakeDesignApi() as unknown as DesignApi,
      loopApi: fakeLoopApi(reviewRun(NEXT, [])) as unknown as DesignLoopApi,
    });
    query("[data-testid='mockup-apply-anyway']").click();
    await flushPromises();

    expect(iterationsApi.startJob).toHaveBeenCalledExactlyOnceWith(
      DESIGN_PROJECT_ID,
      {
        design_version_id: VERSION.id,
        design_content_hash: HASH,
        request: BLUE_ON_RED,
        assertions: [],
        target: BAR,
        opinion_id: OPINION_ID,
      },
      "token",
    );
    expect(text("[data-testid='mockup-change-status']")).toBe(
      "Ecco la nuova versione. Confrontala con quella attuale e decidi se applicarla.",
    );
    expect(all("[data-testid='mockup-opinion']")).toHaveLength(2);
    expect(text("[data-testid='mockup-opinion-stale']")).toContain(
      "Il parere riguarda una richiesta diversa",
    );
    expect(document.body.querySelector("[data-testid='mockup-apply-anyway']")).toBeNull();
    expect(document.body.querySelector("[data-testid='mockup-version-corrections']")).toBeNull();

    query("[data-testid='mockup-apply-version']").click();
    await flushPromises();
    await ask(BLUE_ON_RED);
    expect(useDesignStore().current?.id).toBe(NEXT.id);
    expect(all("[data-testid='mockup-opinion']")).toHaveLength(2);
    expect(document.body.querySelector("[data-testid='mockup-opinion-stale']")).not.toBeNull();
    expect(document.body.querySelector("[data-testid='mockup-apply-anyway']")).toBeNull();
  });

  it("sends the opinion with «Applica la modifica» too while it is not stale", async () => {
    const { iterationsApi } = await askedFirst();
    query("[data-testid='mockup-apply']").click();
    await flushPromises();

    expect(iterationsApi.startJob.mock.calls[0]?.[1]).toMatchObject({
      request: BLUE_ON_RED,
      target: BAR,
      opinion_id: OPINION_ID,
    });
  });

  it("marks the opinion stale when the text or the parts change and sends a new text without it", async () => {
    const { iterationsApi } = await askedFirst();
    const stale = () => document.body.querySelector("[data-testid='mockup-opinion-stale']");
    const anyway = () => document.body.querySelector("[data-testid='mockup-apply-anyway']");

    await ask("Rendi la barra verde");
    expect(stale()).not.toBeNull();
    expect(anyway()).toBeNull();
    expect(all("[data-testid='mockup-opinion']")).toHaveLength(2);
    await ask("  Rendi la barra   rossa con il testo blu ");
    expect(stale()).toBeNull();
    expect(anyway()).not.toBeNull();
    await addPart("ELM-004");
    expect(parts()).toEqual(["ZON-001", "ELM-004"]);
    expect(stale()).not.toBeNull();
    await addPart("ELM-004");
    expect(stale()).toBeNull();

    await ask("Rendi la barra verde");
    query("[data-testid='mockup-apply']").click();
    await flushPromises();
    expect(iterationsApi.startJob.mock.calls[0]?.[1]).toEqual({
      design_version_id: VERSION.id,
      design_content_hash: HASH,
      request: "Rendi la barra verde",
      assertions: [],
      target: BAR,
    });
  });

  it("changes the request or cancels it and keeps the chosen parts", async () => {
    const { opinionsApi, iterationsApi } = await askedFirst();
    const field = query<HTMLTextAreaElement>("[data-testid='mockup-request']");

    query("[data-testid='mockup-change-request']").click();
    await flushPromises();
    expect(document.activeElement).toBe(field);
    expect(field.value).toBe(BLUE_ON_RED);

    query("[data-testid='mockup-cancel-request']").click();
    await flushPromises();
    expect(field.value).toBe("");
    expect(document.body.querySelector("[data-testid='mockup-change-opinions']")).toBeNull();
    expect(useDesignOpinionsStore().current).toBeNull();
    expect(text("[data-testid='mockup-selection-code']")).toBe("ZON-001");
    expect(text("[data-testid='mockup-inspect-announcement']")).toBe(
      "Richiesta annullata; il parere resta registrato.",
    );
    expect(document.activeElement).toBe(field);
    expect(opinionsApi.ask).toHaveBeenCalledTimes(1);
    expect(iterationsApi.startJob).not.toHaveBeenCalled();
  });

  it("writes in the field the request a twin suggests, or else what to do", async () => {
    await askedFirst();
    const field = query<HTMLTextAreaElement>("[data-testid='mockup-request']");
    const tries = all("[data-testid='mockup-opinion-try']");

    tries[0]?.click();
    await flushPromises();
    expect(field.value).toBe(REWRITTEN);
    expect(document.activeElement).toBe(field);
    expect(text("[data-testid='mockup-inspect-announcement']")).toBe(
      "Ho scritto il suggerimento in «Che cosa cambio?»: controllalo e premi «Applica la modifica».",
    );
    expect(document.body.querySelector("[data-testid='mockup-opinion-stale']")).not.toBeNull();

    tries[1]?.click();
    await flushPromises();
    expect(field.value).toBe("Ingrandisci «Carrello».");
  });

  it("says why the opinion of the twins did not arrive and lets the owner ask again", async () => {
    const opinionsApi = fakeOpinionsApi();
    opinionsApi.ask.mockRejectedValueOnce(
      new DesignOpinionsApiError("failed", {
        status: 503,
        code: "DESIGN_REVIEWER_NOT_CONFIGURED",
        payload: null,
      }),
    );
    await pointedWithRequest({ opinionsApi });
    query("[data-testid='mockup-ask-first']").click();
    await flushPromises();

    const failure = query("[data-testid='mockup-change-status']");
    expect(failure.getAttribute("role")).toBe("alert");
    expect(failure.textContent).toContain("Il parere dei twin non è arrivato");
    expect(failure.textContent).toContain(
      "Il modello che interpreta i twin non è collegato, quindi i twin non possono dare il loro parere.",
    );
    expect(document.body.querySelector("[data-testid='mockup-change-opinions']")).toBeNull();
    expect(query("[data-testid='mockup-ask-first']").hasAttribute("aria-disabled")).toBe(false);

    query("[data-testid='mockup-ask-first']").click();
    await flushPromises();
    expect(document.body.querySelector("[data-testid='mockup-change-status']")).toBeNull();
    expect(all("[data-testid='mockup-opinion']")).toHaveLength(2);
  });

  it("lists under the note of the new version the corrections the Studio made", async () => {
    current(VERSION);
    inspector(frameWith(MOCKUP), { api: fakeApi(job("SUCCEEDED", { result: corrected() })) });
    await choose("ELM-002");
    await ask("Rendi il collegamento rosso con il testo blu");
    query("[data-testid='mockup-apply']").click();
    await flushPromises();

    const box = query("[data-testid='mockup-version-corrections']");
    expect(query("[data-testid='mockup-version']").contains(box)).toBe(true);
    expect(follows(query("[data-testid='mockup-version-note']"), box)).toBe(true);
    expect(document.getElementById(box.getAttribute("aria-labelledby") ?? "")?.textContent).toBe(
      "Correzioni fatte dallo Studio",
    );
    expect(texts("[data-testid='mockup-version-correction']")).toEqual([
      "Testo della regola «.topbar a»: blu #0A84FF su rosso #FF3B30, 2,1:1, sotto il minimo di 4,5:1; lo Studio l'ha sostituito con bianco #FFFFFF, 4,0:1.",
      "Bordo dei controlli della regola «input»: grigio #C7C7CC su sfondo ereditato bianco #FFFFFF, 1,5:1, sotto il minimo di 3:1; sostituito con grigio #8E8E93, 3,1:1 (3 regole).",
    ]);
    await expectAccessible(query("[data-testid='mockup-inspector']"), { iframes: false });
  });

  it("forgets the opinion when it closes", async () => {
    const { view } = await askedFirst();
    expect(useDesignOpinionsStore().current?.run_id).toBe(OPINION_ID);

    view.unmount();
    wrapper = null;
    expect(useDesignOpinionsStore().current).toBeNull();
  });

  it("speaks English before the change and in the corrections", async () => {
    const { opinionsApi } = await askedFirst({
      locale: "en",
      api: fakeApi(job("SUCCEEDED", { result: corrected() })),
    });

    expect(opinionsApi.ask.mock.calls[0]?.[1]).toMatchObject({ locale: "en-US" });
    expect(text("[data-testid='mockup-ask-first']")).toBe("Ask the twins before applying");
    expect(text("[data-testid='mockup-ask-first-time']")).toBe("It usually takes about 2 minutes.");
    expect(text("[data-testid='mockup-change-opinions'] h5")).toBe(
      "What the twins say before the change",
    );
    expect(texts("[data-testid='mockup-opinion-why']")[0]).toBe(
      "Il testo blu su “Bottega Vicina Accedi Carrello” non si legge: 2,1:1 è sotto il minimo di 4,5:1.",
    );
    query("[data-testid='mockup-apply-anyway']").click();
    await flushPromises();
    expect(text("[data-testid='mockup-version-corrections'] h4")).toBe(
      "Corrections made by the Studio",
    );
    expect(texts("[data-testid='mockup-version-correction']")).toEqual([
      "Text of the rule “.topbar a”: blue #0A84FF on red #FF3B30, 2.1:1, below the minimum of 4.5:1; the Studio replaced it with white #FFFFFF, 4.0:1.",
      "Border of the controls of the rule “input”: grey #C7C7CC on the inherited background white #FFFFFF, 1.5:1, below the minimum of 3:1; replaced with grey #8E8E93, 3.1:1 (3 rules).",
    ]);
    query("[data-testid='mockup-cancel-request']").click();
    await flushPromises();
    expect(text("[data-testid='mockup-inspect-announcement']")).toBe(
      "Request cancelled; the opinion stays recorded.",
    );
  });

  it("has no axe violations with the opinion of the twins, fresh or stale", async () => {
    await askedFirst();
    await expectAccessible(query("[data-testid='mockup-inspector']"), { iframes: false });
    await ask("Rendi la barra verde");
    expect(document.body.querySelector("[data-testid='mockup-opinion-stale']")).not.toBeNull();
    await expectAccessible(query("[data-testid='mockup-inspector']"), { iframes: false });
  });
});
