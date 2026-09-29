import { flushPromises, mount } from "@vue/test-utils";
import { h } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createAppI18n } from "@/i18n";
import { expectAccessible } from "@/test/axe";
import DesignTwinMatrix, {
  type TwinMatrixAlternative,
  type TwinMatrixCell,
  type TwinMatrixTwin,
} from "./DesignTwinMatrix.vue";

const alternatives: TwinMatrixAlternative[] = [
  { id: "alt-1", code: "DES-001", title: "Vista Scheda" },
  { id: "alt-2", code: "DES-002", title: "Vista Cruscotto" },
];

const twins: TwinMatrixTwin[] = [
  { id: "vb", name: "Volontari al banco dei prestiti", avatar: "/twins/vb.webp" },
  { id: "lb", name: "Lettori della biblioteca" },
  { id: "cp", name: "Coordinatrice dei prestiti" },
];

const cells: TwinMatrixCell[] = [
  {
    twin: "vb",
    alternative: "alt-1",
    verdict: "Utile, con riserve",
    quote: "Semplice e diretta, ma non posso cercare un libro.",
    count: 6,
    severity: "critical",
  },
  {
    twin: "vb",
    alternative: "alt-2",
    verdict: "Troppo complessa",
    quote: "Durante un turno rischio di perdermi.",
    count: 2,
    severity: "major",
  },
  {
    twin: "lb",
    alternative: "alt-1",
    verdict: null,
    quote: null,
    count: 1,
    strengths: ["", "Il promemoria dice da quanto sono in ritardo."],
    concerns: ["Non posso rileggere il promemoria."],
    severity: "moderate",
  },
  {
    twin: "lb",
    alternative: "alt-2",
    count: 0,
    strengths: [],
    concerns: ["Manca un controllo degli errori."],
  },
  { twin: "cp", alternative: "alt-1", verdict: "Mancano dettagli", count: 2 },
];

class FakeResizeObserver {
  static instances: FakeResizeObserver[] = [];
  readonly callback: ResizeObserverCallback;
  disconnected = false;

  constructor(callback: ResizeObserverCallback) {
    this.callback = callback;
    FakeResizeObserver.instances.push(this);
  }

  observe(): void {}

  unobserve(): void {}

  disconnect(): void {
    this.disconnected = true;
  }

  fire(): void {
    this.callback([], this as unknown as ResizeObserver);
  }
}

function areaWidth(width: number): void {
  vi.spyOn(Element.prototype, "clientWidth", "get").mockReturnValue(width);
}

function mountMatrix(props: Partial<InstanceType<typeof DesignTwinMatrix>["$props"]> = {}) {
  return mount(DesignTwinMatrix, {
    props: { alternatives, twins, cells, ...props },
    global: { plugins: [createAppI18n("it")] },
  });
}

function cellOf(wrapper: ReturnType<typeof mountMatrix>, twin: string, alternative: string) {
  return wrapper.get(
    `[data-testid='design-twin-matrix-cell'][data-twin='${twin}'][data-alternative='${alternative}']`,
  );
}

afterEach(() => {
  FakeResizeObserver.instances = [];
});

describe("design twin matrix", () => {
  it("is a table with a header for every alternative and for every twin", () => {
    const wrapper = mountMatrix();
    const table = wrapper.get("table");
    expect(table.attributes("role")).toBe("table");
    expect(table.get("caption").text()).toBe(
      "Il parere di ogni twin su ogni alternativa di design",
    );
    const columns = wrapper.findAll("[role='columnheader']");
    expect(columns.map((column) => column.text())).toEqual([
      "Twin",
      "DES-001 · Vista Scheda",
      "DES-002 · Vista Cruscotto",
    ]);
    expect(columns.every((column) => column.attributes("scope") === "col")).toBe(true);
    const rows = wrapper.findAll("[role='rowheader']");
    expect(rows).toHaveLength(3);
    twins.forEach((twin, index) => expect(rows[index]?.text()).toContain(twin.name));
    expect(rows.every((row) => row.attributes("scope") === "row")).toBe(true);
    expect(wrapper.findAll("tbody [role='row']")).toHaveLength(3);
    expect(wrapper.findAll("[role='cell']")).toHaveLength(6);
    expect(wrapper.findAll("[role='cell'] > button")).toHaveLength(6);
  });

  it("names the section and marks the feedback as simulated", () => {
    const wrapper = mountMatrix();
    const section = wrapper.get("[data-testid='design-twin-matrix']");
    expect(section.attributes("data-surface")).toBe("night");
    expect(section.get("h2").text()).toBe("Il parere dei twin");
    expect(wrapper.get("[data-testid='design-twin-matrix-simulated']").text()).toBe(
      "Feedback simulato, non prove",
    );
  });

  it("shows verdict, quote and number of observations in every cell", () => {
    const wrapper = mountMatrix();
    const first = cellOf(wrapper, "vb", "alt-1");
    expect(first.get("[data-testid='design-twin-matrix-verdict']").text()).toBe(
      "Utile, con riserve",
    );
    expect(first.get("[data-testid='design-twin-matrix-verdict']").classes()).toContain(
      "text-fail-on-night",
    );
    expect(first.get("[data-testid='design-twin-matrix-quote']").text()).toBe(
      "«Semplice e diretta, ma non posso cercare un libro.»",
    );
    expect(first.get("[data-testid='design-twin-matrix-count']").text()).toBe(
      "6 osservazioni · la più grave è critica",
    );
    const second = cellOf(wrapper, "vb", "alt-2");
    expect(second.get("[data-testid='design-twin-matrix-verdict']").classes()).toContain(
      "text-warn-on-night",
    );
    expect(second.get("[data-testid='design-twin-matrix-count']").text()).toBe(
      "2 osservazioni · la più grave è importante",
    );
    const verdictOnly = cellOf(wrapper, "cp", "alt-1");
    expect(verdictOnly.get("[data-testid='design-twin-matrix-verdict']").classes()).toContain(
      "text-on-night-2",
    );
    expect(verdictOnly.find("[data-testid='design-twin-matrix-quote']").exists()).toBe(false);
    expect(verdictOnly.text()).not.toContain("Nessun parere");
  });

  it("uses the first strength or concern of an older critique, without a verdict", () => {
    const wrapper = mountMatrix();
    const strength = cellOf(wrapper, "lb", "alt-1");
    expect(strength.find("[data-testid='design-twin-matrix-verdict']").exists()).toBe(false);
    expect(strength.find("[data-testid='design-twin-matrix-quote']").exists()).toBe(false);
    expect(strength.get("[data-testid='design-twin-matrix-text']").text()).toBe(
      "Il promemoria dice da quanto sono in ritardo.",
    );
    expect(strength.get("[data-testid='design-twin-matrix-count']").text()).toBe("1 osservazione");
    const concern = cellOf(wrapper, "lb", "alt-2");
    expect(concern.get("[data-testid='design-twin-matrix-text']").text()).toBe(
      "Manca un controllo degli errori.",
    );
    expect(concern.get("[data-testid='design-twin-matrix-count']").text()).toBe(
      "Nessuna osservazione",
    );
  });

  it("keeps a button for a twin without an opinion on an alternative", () => {
    const wrapper = mountMatrix();
    const empty = cellOf(wrapper, "cp", "alt-2");
    expect(empty.text()).toContain("Nessun parere su questa alternativa");
    expect(empty.get("[data-testid='design-twin-matrix-count']").text()).toBe(
      "Nessuna osservazione",
    );
  });

  it("marks the selected cell and asks for another one when a cell is chosen", async () => {
    const wrapper = mountMatrix({ selected: { twin: "vb", alternative: "alt-1" } });
    const pressed = wrapper
      .findAll("[data-testid='design-twin-matrix-cell']")
      .map((cell) => cell.attributes("aria-pressed"));
    expect(pressed).toEqual(["true", "false", "false", "false", "false", "false"]);
    expect(cellOf(wrapper, "vb", "alt-1").classes()).toContain("border-petrol-on-night");
    await cellOf(wrapper, "cp", "alt-2").trigger("click");
    expect(wrapper.emitted("select")).toEqual([[{ twin: "cp", alternative: "alt-2" }]]);
  });

  it("names every cell with its twin and alternative for keyboard users", () => {
    const wrapper = mountMatrix();
    const cell = cellOf(wrapper, "vb", "alt-2");
    expect(cell.text()).toMatch(/^Volontari al banco dei prestiti,\s+DES-002 · Vista Cruscotto/);
  });

  it("shows the avatar of a twin or its initials", () => {
    const wrapper = mountMatrix();
    const avatars = wrapper.findAll("[data-testid='design-twin-matrix-avatar']");
    expect(avatars[0]?.get("img").attributes("src")).toBe("/twins/vb.webp");
    expect(avatars[0]?.get("img").attributes("alt")).toBe("");
    expect(avatars[1]?.text()).toBe("LB");
    expect(avatars[2]?.text()).toBe("CP");
    expect(avatars.every((avatar) => avatar.attributes("aria-hidden") === "true")).toBe(true);
  });

  it("becomes one block for each twin when the space is narrow", async () => {
    vi.stubGlobal("ResizeObserver", FakeResizeObserver);
    areaWidth(900);
    const wrapper = mountMatrix();
    await flushPromises();
    const area = wrapper.get("[data-testid='design-twin-matrix-area']");
    expect(area.attributes("data-layout")).toBe("table");
    expect(wrapper.get("thead").classes()).not.toContain("sr-only");
    expect(wrapper.get("[data-testid='design-twin-matrix-cell-alternative']").classes()).toContain(
      "sr-only",
    );
    areaWidth(420);
    FakeResizeObserver.instances[0]?.fire();
    await flushPromises();
    expect(area.attributes("data-layout")).toBe("stack");
    expect(wrapper.get("thead").classes()).toContain("sr-only");
    expect(wrapper.get("tbody").classes()).toContain("grid");
    expect(wrapper.get("[data-testid='design-twin-matrix-row']").classes()).toContain(
      "rounded-tile",
    );
    expect(
      wrapper.get("[data-testid='design-twin-matrix-cell-alternative']").classes(),
    ).not.toContain("sr-only");
    expect(wrapper.find("table").attributes("role")).toBe("table");
    wrapper.unmount();
    expect(FakeResizeObserver.instances[0]?.disconnected).toBe(true);
  });

  it("needs more room before it becomes a table when there are more alternatives", async () => {
    vi.stubGlobal("ResizeObserver", FakeResizeObserver);
    areaWidth(860);
    const four = [
      ...alternatives,
      { id: "alt-3", code: "DES-003", title: "Vista Elenco" },
      { id: "alt-4", code: "DES-004", title: "Vista Calendario" },
    ];
    const wrapper = mountMatrix({ alternatives: four });
    await flushPromises();
    const area = wrapper.get("[data-testid='design-twin-matrix-area']");
    expect(area.attributes("data-layout")).toBe("stack");
    expect(wrapper.findAll("[data-testid='design-twin-matrix-cell']")).toHaveLength(12);
    await wrapper.setProps({ alternatives });
    expect(area.attributes("data-layout")).toBe("table");
    areaWidth(520);
    FakeResizeObserver.instances[0]?.fire();
    await flushPromises();
    expect(area.attributes("data-layout")).toBe("stack");
  });

  it("stays readable with eight twins", () => {
    const many = Array.from({ length: 8 }, (_, index) => ({
      id: `twin-${index}`,
      name: `Twin numero ${index + 1}`,
    }));
    const wrapper = mountMatrix({ twins: many, cells: [] });
    expect(wrapper.findAll("[data-testid='design-twin-matrix-row']")).toHaveLength(8);
    expect(wrapper.findAll("[data-testid='design-twin-matrix-cell']")).toHaveLength(16);
  });

  it("shows the observations of the chosen cell below the matrix", () => {
    const wrapper = mount(DesignTwinMatrix, {
      props: { alternatives, twins, cells },
      slots: { default: () => h("p", { "data-testid": "observations" }, "Osservazioni") },
      global: { plugins: [createAppI18n("it")] },
    });
    expect(wrapper.get("[data-testid='observations']").text()).toBe("Osservazioni");
  });

  it("speaks English when the page is in English", () => {
    const wrapper = mountMatrix({ locale: "en" });
    expect(wrapper.get("h2").text()).toBe("What the twins think");
    expect(wrapper.get("[data-testid='design-twin-matrix-simulated']").text()).toBe(
      "Simulated feedback, not evidence",
    );
    expect(
      cellOf(wrapper, "vb", "alt-1").get("[data-testid='design-twin-matrix-count']").text(),
    ).toBe("6 observations · the most serious is critical");
  });

  it("has no axe violations as a table and as blocks", async () => {
    await expectAccessible(mountMatrix({ selected: { twin: "lb", alternative: "alt-2" } }).element);
    vi.stubGlobal("ResizeObserver", FakeResizeObserver);
    areaWidth(900);
    const wide = mountMatrix();
    await flushPromises();
    await expectAccessible(wide.element);
  });
});
