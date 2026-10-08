import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createAppI18n } from "@/i18n";
import { expectAccessible } from "@/test/axe";
import {
  BASE_DESIGN_PACKAGE,
  DESIGN_ALTERNATIVE_ID,
  DESIGN_PROJECT_ID,
  PROPOSED_DESIGN_DIFF,
  UNSELECTED_DESIGN_VERSION,
} from "@/test/designFixtures";
import GeneratedMockupDialog, {
  type MockupDocument,
  type MockupObservation,
  type MockupPin,
  type MockupUnanchoredPin,
} from "./GeneratedMockupDialog.vue";
import GeneratedMockupFrame from "./GeneratedMockupFrame.vue";
import source from "./GeneratedMockupDialog.vue?raw";
import { whyContextKey } from "./whyContext";
import type { DesignApi } from "../api/design";
import type { DesignIterationsApi } from "../api/designIterations";
import type { DesignLoopApi } from "../api/designLoop";
import { activitySignalKey } from "../stores/activityJournal";
import { useDesignStore } from "../stores/design";
import { useDesignIterationsStore } from "../stores/designIterations";
import { useDesignLoopStore } from "../stores/designLoop";
import type { AuthorizedMockupRequest } from "../stores/designMockups";
import type { DesignPackageDiffPayload, DesignPackageVersionPayload } from "../types/design";
import type { DesignEvaluationRunPayload, SyntheticFindingPayload } from "../types/designLoop";
import type { GenerationJobPayload } from "../types/designMockups";
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

function markedDocument(label = "Nuovo prestito", hash = "b"): MockupDocument {
  return {
    ...documentFor("SCR-001"),
    html: [
      "<!doctype html><html lang='it'><body class='ot-mockup'>",
      "<section class='ot-screen' id='SCR-001' data-entry>",
      "<h1 data-elm='ELM-001'>Registro dei prestiti</h1>",
      `<a href="#SCR-002" data-elm="ELM-002" data-req="REQ-003">${label}</a>`,
      "</section><section class='ot-screen' id='SCR-002'>",
      "<h1 data-elm='ELM-003'>Nuovo prestito</h1></section></body></html>",
    ].join(""),
    content_hash: hash.repeat(64),
  };
}

function succeeded(): GenerationJobPayload {
  return {
    job_id: "iteration-job-1",
    kind: "ITERATION",
    status: "SUCCEEDED",
    stage: null,
    attempt: 1,
    started_at: "2026-10-08T09:00:00+00:00",
    finished_at: "2026-10-08T09:06:00+00:00",
    alternative_id: DESIGN_ALTERNATIVE_ID,
    result: {
      status: "MOCKUP_GENERATED",
      generation_id: "iteration-1",
      design_version_id: VERSION.id,
      design_content_hash: HASH,
      package: VERSION.package,
      approach: null,
      changes: [],
      warnings: [],
      cost_microusd: null,
    },
    failure: null,
  };
}

function fakeIterationsApi() {
  return {
    startJob: vi.fn<DesignIterationsApi["startJob"]>(async () => succeeded()),
    job: vi.fn<DesignIterationsApi["job"]>(async () => succeeded()),
    list: vi.fn<DesignIterationsApi["list"]>(async () => ({ items: [] })),
  };
}

const NEXT: DesignPackageVersionPayload = {
  ...VERSION,
  id: "00000000-0000-4000-8000-333333333333",
  version_number: 2,
  based_on_version_number: 1,
  content_hash: "3".repeat(64),
};

function decidedDiff(status: DesignPackageDiffPayload["status"]): DesignPackageDiffPayload {
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

function fakeDesignApi() {
  const revision = (version: DesignPackageVersionPayload | null) => ({
    status: version === null ? ("CREATED" as const) : ("APPLIED" as const),
    diff: decidedDiff(version === null ? "PROPOSED" : "APPROVED"),
    version,
    issue: null,
    domain_issue: null,
    diff_persistence_status: null,
    version_persistence_status: null,
  });
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
    revisionHistory: vi.fn<DesignApi["revisionHistory"]>(async () => [decidedDiff("APPROVED")]),
  };
}

function elementReview(): DesignEvaluationRunPayload {
  const twin = BASE_DESIGN_PACKAGE.grounding.user_twin_references[0]!;
  const finding: SyntheticFindingPayload = {
    finding_id: "UTF-001",
    twin_id: twin.twin_id,
    twin_version: 1,
    artifact_id: NEXT.id,
    artifact_version: 2,
    location: "SCR-001 Registro dei prestiti · ELM-002 Nuovo prestito",
    summary: "La modifica mi aiuta: ora trovo subito il prestito.",
    rationale: "Al banco cerco subito il prossimo prestito.",
    criterion: "actionability",
    severity: "observation",
    epistemic_status: "MODEL_INFERRED",
    evidence_refs: [],
    confidence: 0.7,
    confidence_semantics: "MODEL_SELF_ASSESSMENT_UNLESS_CALIBRATED",
    recommended_action: "Prova con un blu più scuro.",
    requires_human_validation: true,
    model_config_ref: "c".repeat(64),
    prompt_version_ref: "s24-design-twin-review-v3+s43-changed-element-v1",
    is_simulated_feedback: true,
    content_hash: "1".repeat(64),
  };
  const marked: SyntheticFindingPayload & { element_code: string } = {
    ...finding,
    element_code: "ELM-002",
  };
  return {
    schema_version: 1,
    id: "run-2",
    project_id: DESIGN_PROJECT_ID,
    owner_user_id: "owner-1",
    design_version_id: NEXT.id,
    design_version_number: 2,
    design_content_hash: NEXT.content_hash,
    alternative_id: DESIGN_ALTERNATIVE_ID,
    alternative_code: "DES-001",
    bundle: {},
    responses: [
      {
        evaluation_run_id: "run-2",
        artifact_bundle_id: "bundle-1",
        artifact_bundle_hash: "b".repeat(64),
        twin_id: twin.twin_id,
        twin_version: 1,
        evaluator: {
          evaluator_id: "proposer-design-twin-review",
          evaluator_version: "1.0.0",
          model_config_ref: "c".repeat(64),
          prompt_version_ref: finding.prompt_version_ref,
        },
        findings: [marked],
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

async function loadFrame(): Promise<HTMLIFrameElement> {
  await flushPromises();
  const frame = query<HTMLIFrameElement>("[data-testid='mockup-dialog'] iframe");
  const page = frame.contentDocument;
  if (page === null) {
    throw new Error("missing frame document");
  }
  const parsed = new DOMParser().parseFromString(frame.getAttribute("srcdoc") ?? "", "text/html");
  page.replaceChild(page.importNode(parsed.documentElement, true), page.documentElement);
  frame.dispatchEvent(new Event("load"));
  await flushPromises();
  return frame;
}

function inFrame(frame: HTMLIFrameElement, selector: string): HTMLElement {
  const element = frame.contentDocument?.querySelector<HTMLElement>(selector) ?? null;
  if (element === null) {
    throw new Error(`missing ${selector} in the frame`);
  }
  return element;
}

function pointer(target: Element, type: string): boolean {
  const view = target.ownerDocument.defaultView;
  if (view === null) {
    throw new Error("missing window");
  }
  return target.dispatchEvent(new view.MouseEvent(type, { bubbles: true, cancelable: true }));
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

beforeEach(() => {
  sessionStorage.clear();
  setActivePinia(createPinia());
});

afterEach(() => {
  useDesignIterationsStore().reset();
  wrapper?.unmount();
  wrapper = null;
  document.body.innerHTML = "";
  sessionStorage.clear();
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

  it("wraps the tabs on more lines and a long title between its words, without cutting it", () => {
    const long: MockupDocument = {
      ...documentFor("SCR-001"),
      screens: [
        {
          code: "SCR-001",
          title: "Beverly Hills, palestra indipendente a Riccione",
          state: "DEFAULT",
        },
        { code: "SCR-002", title: "Chiamata avviata", state: "SUCCESS" },
        {
          code: "SCR-003",
          title: "Chiamata non disponibile su questo dispositivo",
          state: "ERROR",
        },
        ...Array.from({ length: 3 }, (_item, index) => ({
          code: `SCR-00${index + 4}`,
          title: `Schermata ${index + 4} con un titolo davvero molto lungo da leggere intero`,
          state: "DEFAULT",
        })),
      ],
    };
    open({ document: long, observations: [], pins: [], unanchored: [] });
    const list = query("[role='tablist']");
    expect(list.className).toContain("flex-wrap");
    expect(list.className).not.toContain("overflow-x-auto");
    const tabs = all("[data-testid='mockup-dialog-screen']");
    expect(tabs).toHaveLength(6);
    for (const [index, tab] of tabs.entries()) {
      const title = long.screens[index]?.title ?? "";
      const label = tab.querySelector("[data-testid='mockup-dialog-screen-title']");
      expect(tab.getAttribute("title")).toBe(title);
      expect(tab.textContent?.trim()).toBe(title);
      expect(label?.textContent).toBe(title);
      expect(tab.className).toContain("max-w-[calc(28ch+1.75rem)]");
      expect(tab.className).not.toMatch(/\b(?:truncate|whitespace-nowrap|line-clamp-\d)\b/);
      expect(label?.className.split(" ")).toEqual(["min-w-0", "break-words"]);
    }
    expect(tabs.map((tab) => tab.getAttribute("aria-selected"))).toEqual([
      "true",
      "false",
      "false",
      "false",
      "false",
      "false",
    ]);
    expect(tabs[0]?.className).toContain("bg-on-night text-ink");
    expect(tabs[0]?.getAttribute("tabindex")).toBe("0");
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

  it("tells the study session the code of the opened alternative and nothing of its title", async () => {
    const signal = { whyOpened: vi.fn(), mockupOpened: vi.fn() };
    const openTitled = (title: string) =>
      mount(GeneratedMockupDialog, {
        props: { title, document: documentFor("SCR-001") },
        global: {
          plugins: [createAppI18n("it")],
          provide: { [activitySignalKey as symbol]: signal },
        },
        attachTo: document.body,
      });

    wrapper = openTitled("DES-002 · Registro con tabella");
    await flushPromises();
    all("[data-testid='mockup-dialog-screen']")[1]?.click();
    await flushPromises();
    expect(signal.mockupOpened).toHaveBeenCalledExactlyOnceWith("DES-002");

    wrapper.unmount();
    wrapper = openTitled("Registro con tabella");
    await flushPromises();
    expect(signal.mockupOpened).toHaveBeenCalledTimes(2);
    expect(signal.mockupOpened).toHaveBeenLastCalledWith(null);
    expect(signal.whyOpened).not.toHaveBeenCalled();
  });
});

describe("pointing at an element of the mockup", () => {
  it("offers «Indica un elemento» only on a mockup that can change, as a toggle of the frame", async () => {
    open({ document: markedDocument() });
    expect(document.body.querySelector("[data-testid='mockup-inspect']")).toBeNull();
    wrapper?.unmount();

    open({ document: markedDocument(), editable: true });
    const toggle = query("[data-testid='mockup-inspect']");
    expect(toggle.tagName).toBe("BUTTON");
    expect(toggle.textContent?.trim()).toBe("Indica un elemento");
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    expect(toggle.hasAttribute("aria-disabled")).toBe(false);
    expect(query("iframe").getAttribute("sandbox")).toBe("");
    expect(document.body.querySelector("[data-testid='mockup-inspector']")).toBeNull();

    toggle.click();
    await flushPromises();
    expect(toggle.getAttribute("aria-pressed")).toBe("true");
    expect(query("iframe").getAttribute("sandbox")).toBe("allow-same-origin");
    expect(
      query("[data-testid='mockup-dialog-sidecar'] [data-testid='mockup-inspector']"),
    ).toBeTruthy();
    expect(query("[role='dialog'] header").textContent).toContain(
      "Un clic sul mockup sceglie l'elemento; Esc toglie la scelta.",
    );

    toggle.click();
    await flushPromises();
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    expect(query("iframe").getAttribute("sandbox")).toBe("");
    expect(document.body.querySelector("[data-testid='mockup-inspector']")).toBeNull();
    expect(query("[role='dialog'] header").textContent).toContain(
      "Il mockup è navigabile: i suoi collegamenti portano alle altre schermate.",
    );
  });

  it("draws the highlight over the frame and keeps the dialog open while Escape clears a choice", async () => {
    const dialog = open({ document: markedDocument(), editable: true });
    query("[data-testid='mockup-inspect']").click();
    const frame = await loadFrame();
    const link = inFrame(frame, "[data-elm='ELM-002']");
    placed(link, 30, 40, 200, 24);

    pointer(link, "mousemove");
    await flushPromises();
    let boxes = all("[data-testid='mockup-inspect-highlight']");
    expect(boxes).toHaveLength(1);
    expect(boxes[0]?.dataset.kind).toBe("hover");
    expect(boxes[0]?.dataset.code).toBe("ELM-002");
    expect(boxes[0]?.textContent?.trim()).toBe("ELM-002");
    expect(boxes[0]?.style.left).toBe("30px");
    expect(boxes[0]?.style.top).toBe("40px");
    expect(boxes[0]?.style.width).toBe("200px");
    expect(boxes[0]?.style.height).toBe("24px");
    expect(
      boxes[0]?.closest("[data-testid='generated-mockup-overlay']")?.getAttribute("aria-hidden"),
    ).toBe("true");

    expect(pointer(link, "click")).toBe(false);
    await flushPromises();
    boxes = all("[data-testid='mockup-inspect-highlight']");
    expect(boxes.map((box) => box.dataset.kind)).toEqual(["selected"]);
    expect(query("[data-testid='mockup-selection-code']").textContent).toBe("ELM-002");
    expect(
      all("[data-testid='mockup-requirement']").map((item) => item.textContent?.trim()),
    ).toEqual(["REQ-003"]);

    const list = query("[data-testid='mockup-elements']");
    keydown(list, "Escape");
    await flushPromises();
    expect(dialog.emitted("close")).toBeUndefined();
    expect(document.body.querySelector("[data-testid='mockup-selection']")).toBeNull();
    expect(all("[data-testid='mockup-inspect-highlight']").map((box) => box.dataset.kind)).toEqual([
      "hover",
    ]);
    keydown(list, "Escape");
    expect(dialog.emitted("close")).toHaveLength(1);
  });

  it("asks for the change of the element and comes back to the same element in the new version", async () => {
    const signal = { whyOpened: vi.fn(), mockupOpened: vi.fn() };
    const api = fakeIterationsApi();
    useDesignIterationsStore().activate(DESIGN_PROJECT_ID, VERSION);
    wrapper = mount(GeneratedMockupDialog, {
      props: {
        title: "DES-002 · Registro con tabella",
        document: markedDocument(),
        editable: true,
        authorize,
        iterationsApi: api,
      },
      global: {
        plugins: [createAppI18n("it")],
        provide: { [activitySignalKey as symbol]: signal },
      },
      attachTo: document.body,
    });
    const dialog = wrapper;
    query("[data-testid='mockup-inspect']").click();
    await loadFrame();
    query("[data-testid='mockup-element'][data-code='ELM-002']").click();
    await flushPromises();
    const field = query<HTMLTextAreaElement>("[data-testid='mockup-request']");
    field.value = "Rendi il collegamento un pulsante";
    field.dispatchEvent(new Event("input"));
    await flushPromises();
    expect(api.startJob).not.toHaveBeenCalled();

    query("[data-testid='mockup-apply']").click();
    await flushPromises();

    expect(api.startJob).toHaveBeenCalledExactlyOnceWith(
      DESIGN_PROJECT_ID,
      expect.objectContaining({
        request: "Rendi il collegamento un pulsante",
        target: {
          screen_code: "SCR-001",
          element_code: "ELM-002",
          label: "Nuovo prestito",
          html: '<a href="#SCR-002" data-elm="ELM-002" data-req="REQ-003">Nuovo prestito</a>',
        },
      }),
      "token",
    );
    expect(dialog.emitted("version")).toEqual([["SCR-001"]]);

    await dialog.setProps({ busy: true, document: null });
    expect(query("[data-testid='mockup-inspect']").getAttribute("aria-pressed")).toBe("true");
    expect(query("[data-testid='mockup-elements-reading']")).toBeTruthy();
    await dialog.setProps({ busy: false, document: markedDocument("Prenota un prestito", "c") });
    await loadFrame();

    expect(query("iframe").getAttribute("sandbox")).toBe("allow-same-origin");
    expect(query("[data-testid='mockup-selection-code']").textContent).toBe("ELM-002");
    expect(query("[data-testid='mockup-selection-text']").textContent?.trim()).toBe(
      "Prenota un prestito",
    );
    expect(signal.mockupOpened).toHaveBeenCalledTimes(1);
    expect(signal.whyOpened).not.toHaveBeenCalled();
  });

  it("applies the new version inside the dialog, draws it again on the same element and shows the twins", async () => {
    const iterationsApi = fakeIterationsApi();
    const designApi = fakeDesignApi();
    const loopApi = {
      evaluate: vi.fn<DesignLoopApi["evaluate"]>(async () => elementReview()),
      comparison: vi.fn<DesignLoopApi["comparison"]>(async () => null),
    };
    useDesignIterationsStore().activate(DESIGN_PROJECT_ID, VERSION);
    const design = useDesignStore();
    design.activateProject(DESIGN_PROJECT_ID);
    design.applyVersion(VERSION);
    useDesignLoopStore().reset(DESIGN_PROJECT_ID);
    const dialog = open({
      document: markedDocument(),
      editable: true,
      authorize,
      iterationsApi,
      designApi: designApi as unknown as DesignApi,
      loopApi: loopApi as unknown as DesignLoopApi,
    });
    query("[data-testid='mockup-inspect']").click();
    await loadFrame();
    query("[data-testid='mockup-element'][data-code='ELM-002']").click();
    await flushPromises();
    const field = query<HTMLTextAreaElement>("[data-testid='mockup-request']");
    field.value = "Rendi il collegamento un pulsante";
    field.dispatchEvent(new Event("input"));
    await flushPromises();
    query("[data-testid='mockup-apply']").click();
    await flushPromises();
    expect(dialog.emitted("version")).toEqual([["SCR-001"]]);
    expect(query("[data-testid='mockup-version-note']").textContent?.trim()).toBe(
      "Dopo l'applicazione i twin guardano ELM-002: di solito serve un paio di minuti.",
    );
    expect(designApi.proposeRevision).not.toHaveBeenCalled();
    expect(loopApi.evaluate).not.toHaveBeenCalled();
    const before = query("iframe");

    query("[data-testid='mockup-apply-version']").click();
    await flushPromises();

    expect(designApi.proposeRevision).toHaveBeenCalledTimes(1);
    expect(designApi.decideRevision).toHaveBeenCalledTimes(1);
    expect(dialog.emitted("applied")).toEqual([[NEXT.id]]);
    expect(loopApi.evaluate).toHaveBeenCalledExactlyOnceWith(
      DESIGN_PROJECT_ID,
      expect.objectContaining({
        design_version_id: NEXT.id,
        mode: "TWIN_REVIEW",
        scope: { screen_code: "SCR-001", element_code: "ELM-002" },
      }),
      "token",
    );
    const after = query("iframe");
    expect(after).not.toBe(before);
    expect(after.getAttribute("srcdoc")).toBe(before.getAttribute("srcdoc"));
    expect(after.getAttribute("sandbox")).toBe("allow-same-origin");
    await loadFrame();

    expect(query("[data-testid='mockup-selection-code']").textContent).toBe("ELM-002");
    expect(query("[data-testid='mockup-review-status']").textContent).toContain(
      "I twin hanno detto la loro su ELM-002",
    );
    const notes = all("[data-testid='mockup-twin-note']");
    expect(notes).toHaveLength(1);
    expect(notes[0]?.textContent).toContain("Receptionist Twin");
    expect(notes[0]?.textContent).toContain("Aiuta");
    expect(notes[0]?.textContent).toContain("La modifica mi aiuta: ora trovo subito il prestito.");
    expect(notes[0]?.textContent).toContain("Cosa fare: Prova con un blu più scuro.");
    query("[data-testid='mockup-try-suggestion']").click();
    await flushPromises();
    expect(query<HTMLTextAreaElement>("[data-testid='mockup-request']").value).toBe(
      "Prova con un blu più scuro.",
    );
    expect(iterationsApi.startJob).toHaveBeenCalledTimes(1);
    expect(loopApi.evaluate).toHaveBeenCalledTimes(1);
    await expectAccessible(query("[data-testid='mockup-dialog']"), { iframes: false });
  });

  it("says when the mockup has no elements to point at and stops pointing on such a screen", async () => {
    const dialog = open({ document: documentFor("SCR-001"), editable: true });
    const toggle = query("[data-testid='mockup-inspect']");
    expect(toggle.getAttribute("aria-disabled")).toBe("true");
    expect(
      document.getElementById(toggle.getAttribute("aria-describedby") ?? "")?.textContent?.trim(),
    ).toBe("Questo mockup non ha elementi indicabili");
    toggle.click();
    await flushPromises();
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    expect(query("iframe").getAttribute("sandbox")).toBe("");

    await dialog.setProps({ document: markedDocument() });
    expect(toggle.hasAttribute("aria-disabled")).toBe(false);
    expect(document.body.querySelector("[data-testid='mockup-inspect-none']")).toBeNull();
    toggle.click();
    await flushPromises();
    expect(toggle.getAttribute("aria-pressed")).toBe("true");
    await dialog.setProps({ document: documentFor("SCR-002") });
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    expect(query("iframe").getAttribute("sandbox")).toBe("");
    expect(document.body.querySelector("[data-testid='mockup-inspector']")).toBeNull();

    await dialog.setProps({ document: markedDocument() });
    toggle.click();
    await flushPromises();
    expect(query("iframe").getAttribute("sandbox")).toBe("allow-same-origin");
    await dialog.setProps({ editable: false });
    expect(document.body.querySelector("[data-testid='mockup-inspect']")).toBeNull();
    expect(query("iframe").getAttribute("sandbox")).toBe("");
    expect(document.body.querySelector("[data-testid='mockup-inspector']")).toBeNull();
  });

  it("speaks English when the page is in English", async () => {
    const dialog = open({ document: documentFor("SCR-001"), editable: true, locale: "en" });
    expect(query("[data-testid='mockup-inspect']").textContent?.trim()).toBe("Point at an element");
    expect(query("[data-testid='mockup-inspect-none']").textContent?.trim()).toBe(
      "This mockup has no elements to point at",
    );
    await dialog.setProps({ document: markedDocument() });
    query("[data-testid='mockup-inspect']").click();
    await loadFrame();
    expect(query("[role='dialog'] header").textContent).toContain(
      "A click on the mockup chooses the element; Esc clears the choice.",
    );
    expect(query("[data-testid='mockup-inspector'] h3").textContent).toBe(
      "Elements you can point at",
    );
  });

  it("has no axe violations while it points at an element", async () => {
    open({ document: markedDocument(), editable: true, authorize });
    query("[data-testid='mockup-inspect']").click();
    const frame = await loadFrame();
    placed(inFrame(frame, "[data-elm='ELM-001']"), 10, 10, 300, 40);
    pointer(inFrame(frame, "[data-elm='ELM-001']"), "click");
    await flushPromises();
    await expectAccessible(query("[data-testid='mockup-dialog']"), { iframes: false });
  });
});
