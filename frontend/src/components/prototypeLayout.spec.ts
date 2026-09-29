import { describe, expect, it } from "vitest";

import type {
  LayoutArchetype,
  PrototypeElementKind,
  PrototypeElementPayload,
} from "../types/design";
import {
  displayElements,
  layoutZones,
  listItems,
  splits,
  zoneRuns,
  type DisplayElement,
} from "./prototypeLayout";

const ARCHETYPES: LayoutArchetype[] = [
  "GUIDED_STEPS",
  "SINGLE_CARD",
  "LIST_DETAIL",
  "DASHBOARD",
  "SPLIT_SCREEN",
  "CONVERSATIONAL",
  "TABLE_FIRST",
  "CARD_GALLERY",
  "FEED_TIMELINE",
  "KANBAN_BOARD",
  "SEARCH_FIRST",
  "FOCUS_MODE",
];

function element(
  kind: PrototypeElementKind,
  content = kind.toLowerCase(),
  accessibleName: string | null = null,
): PrototypeElementPayload {
  return {
    id: `${kind}-${content}`,
    code: "ELM-001",
    kind,
    content,
    accessible_name: accessibleName,
    requirement_ids: [],
    user_story_ids: [],
    acceptance_criterion_ids: [],
    field_name: null,
    required: false,
    options: [],
  };
}

function contents(elements: readonly DisplayElement[]): string[] {
  return elements.map((item) => item.content);
}

describe("displayElements", () => {
  it("does not draw a heading that repeats the title of the screen or the product name", () => {
    const shown = displayElements("SINGLE_CARD", "Nuovo prestito", "Prestiti Biblio", [
      element("HEADING", "Nuovo  prestito:"),
      element("HEADING", "PRESTITI biblio!"),
      element("HEADING", "Dati del prestito"),
      element("TEXT", "Nuovo prestito"),
    ]);
    expect(contents(shown)).toEqual(["Dati del prestito", "Nuovo prestito"]);
  });

  it("drops a paragraph that only repeats the label of the field that follows it", () => {
    const shown = displayElements("SINGLE_CARD", "Registrazione", "Prestiti", [
      element("TEXT", "Titolo del libro:"),
      element("TEXT_INPUT", "Titolo del libro"),
      element("TEXT", "Lettore (obbligatorio) *"),
      element("SELECT", "Scegli", "Lettore"),
      element("TEXT", "Scrivi il titolo completo"),
      element("TEXT_INPUT", "Titolo"),
      element("TEXT", "Titolo:"),
      element("BUTTON", "Titolo"),
    ]);
    expect(contents(shown)).toEqual([
      "Titolo del libro",
      "Scegli",
      "Scrivi il titolo completo",
      "Titolo",
      "Titolo:",
      "Titolo",
    ]);
  });

  it("turns a label followed by its value into a pair and leaves two labels apart", () => {
    const shown = displayElements("SINGLE_CARD", "Riepilogo", "Prestiti", [
      element("TEXT", "Scadenza:"),
      element("TEXT", "12 ottobre"),
      element("TEXT", "Lettore:"),
      element("TEXT", "Stato:"),
      element("TEXT", "Restituito"),
    ]);
    expect(shown.map((item) => [item.content, item.value])).toEqual([
      ["Scadenza:", "12 ottobre"],
      ["Lettore:", undefined],
      ["Stato:", "Restituito"],
    ]);
  });

  it("makes a short paragraph after a status or a card the figure of its tile only on a dashboard", () => {
    const elements = [
      element("STATUS", "Prestiti in ritardo"),
      element("TEXT", "12"),
      element("CARD", "Libri disponibili"),
      element("TEXT", "Un paragrafo che supera di molto i quaranta caratteri."),
    ];
    const dashboard = displayElements("DASHBOARD", "Cruscotto", "Prestiti", elements);
    expect(dashboard.map((item) => [item.content, item.figure])).toEqual([
      ["Prestiti in ritardo", "12"],
      ["Libri disponibili", undefined],
      ["Un paragrafo che supera di molto i quaranta caratteri.", undefined],
    ]);
    const card = displayElements("SINGLE_CARD", "Cruscotto", "Prestiti", elements);
    expect(card.every((item) => item.figure === undefined)).toBe(true);
    expect(card).toHaveLength(4);
  });
});

describe("listItems", () => {
  it("splits a paragraph that numbers its items and keeps anything else whole", () => {
    expect(listItems("1. Il nome della rosa 2. Il gattopardo 3. Lessico famigliare")).toEqual([
      "1. Il nome della rosa",
      "2. Il gattopardo",
      "3. Lessico famigliare",
    ]);
    expect(listItems("Da restituire: 1) Dune 2) Emma")).toEqual([
      "Da restituire:",
      "1) Dune",
      "2) Emma",
    ]);
    expect(listItems("1. Un solo libro")).toEqual(["1. Un solo libro"]);
    expect(listItems("Versione 2.0 del 3. piano")).toEqual(["Versione 2.0 del 3. piano"]);
  });
});

describe("zoneRuns", () => {
  const pair = (label: string, value: string): DisplayElement => ({
    ...element("TEXT", label),
    value,
  });

  it("groups pairs, list items and cards and keeps the index of every other element", () => {
    const runs = zoneRuns("main", [
      pair("Scadenza:", "12 ottobre"),
      pair("Lettore:", "Ada"),
      element("LIST", "Dune"),
      element("LIST", "1. Emma 2. Ulisse"),
      element("CARD", "Primo"),
      element("CARD", "Secondo"),
      element("BUTTON", "Salva"),
    ]);
    expect(runs.map((run) => run.kind)).toEqual(["pairs", "list", "cards", "element"]);
    expect(runs[0]).toMatchObject({
      kind: "pairs",
      elements: [{ value: "12 ottobre" }, { value: "Ada" }],
    });
    expect(runs[1]).toMatchObject({ kind: "list", items: ["Dune", "1. Emma", "2. Ulisse"] });
    expect(runs[2]).toMatchObject({
      kind: "cards",
      elements: [{ content: "Primo" }, { content: "Secondo" }],
    });
    expect(runs[3]).toMatchObject({ kind: "element", index: 6, element: { content: "Salva" } });
  });

  it("keeps the rows of a table and the cards of a column as single elements", () => {
    const table = zoneRuns("table", [element("LIST", "1 · Dune"), element("LIST", "2 · Emma")]);
    expect(table.map((run) => [run.kind, run.kind === "element" ? run.index : null])).toEqual([
      ["element", 0],
      ["element", 1],
    ]);
    const column = zoneRuns("column", [
      element("HEADING", "Da fare"),
      element("CARD", "Primo"),
      element("CARD", "Secondo"),
    ]);
    expect(column.map((run) => run.kind)).toEqual(["element", "element", "element"]);
  });
});

describe("splits", () => {
  it("sets list and detail side by side only when both zones hold more than actions", () => {
    const aside = { name: "aside" as const, elements: [element("LIST", "Dune")] };
    const main = {
      name: "main" as const,
      elements: [element("HEADING", "Dettaglio"), element("BUTTON", "Salva")],
    };
    const actions = { name: "main" as const, elements: [element("BUTTON", "Salva")] };
    expect(splits("LIST_DETAIL", [aside, main])).toBe(true);
    expect(splits("SPLIT_SCREEN", [aside, main])).toBe(true);
    expect(splits("LIST_DETAIL", [aside, actions])).toBe(false);
    expect(splits("DASHBOARD", [aside, main])).toBe(false);
    expect(
      splits("LIST_DETAIL", [aside, main, { name: "intro", elements: [element("TEXT")] }]),
    ).toBe(false);
  });
});

describe("layoutZones", () => {
  it("mirrors the backend zone rules for dashboards, lists, boards and search", () => {
    const dashboard = layoutZones("DASHBOARD", [
      element("HEADING"),
      element("STATUS"),
      element("CARD"),
      element("LIST"),
      element("BUTTON"),
    ]);
    expect(dashboard.map((zone) => zone.name)).toEqual(["tiles", "main"]);
    expect(dashboard[0]!.elements.map((item) => item.kind)).toEqual(["STATUS", "CARD"]);

    const detail = layoutZones("LIST_DETAIL", [
      element("HEADING"),
      element("LIST"),
      element("BUTTON"),
    ]);
    expect(detail.map((zone) => zone.name)).toEqual(["aside", "main"]);

    const board = layoutZones("KANBAN_BOARD", [
      element("CARD", "orphan"),
      element("HEADING", "To do"),
      element("CARD", "a"),
      element("HEADING", "Done"),
      element("CARD", "c"),
      element("BUTTON"),
    ]);
    expect(board.map((zone) => zone.name)).toEqual(["column", "column", "main"]);
    expect(board[0]!.elements.map((item) => item.content)).toEqual(["To do", "a"]);
    expect(board[2]!.elements.map((item) => item.content)).toEqual(["orphan", "button"]);

    const search = layoutZones("SEARCH_FIRST", [
      element("HEADING"),
      element("TEXT_INPUT", "query"),
      element("BUTTON", "search"),
      element("LIST"),
      element("BUTTON", "apply"),
    ]);
    expect(search.map((zone) => zone.name)).toEqual(["intro", "search", "main"]);
    expect(search[1]!.elements.map((item) => item.content)).toEqual(["query", "search"]);
  });

  it("places every element exactly once for every archetype", () => {
    const kinds: PrototypeElementKind[] = [
      "HEADING",
      "TEXT",
      "TEXT_INPUT",
      "SELECT",
      "BUTTON",
      "LINK",
      "LIST",
      "CARD",
      "STATUS",
    ];
    const elements = [...kinds, ...kinds].map((kind, index) => element(kind, `${kind}-${index}`));
    for (const archetype of ARCHETYPES) {
      const zones = layoutZones(archetype, elements);
      const placed = zones.flatMap((zone) => zone.elements.map((item) => item.content)).sort();
      expect(placed).toEqual(elements.map((item) => item.content).sort());
      expect(zones.every((zone) => zone.elements.length > 0)).toBe(true);
    }
  });
});
