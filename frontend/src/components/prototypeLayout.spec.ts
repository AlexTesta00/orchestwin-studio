import { describe, expect, it } from "vitest";

import type {
  LayoutArchetype,
  PrototypeElementKind,
  PrototypeElementPayload,
} from "../types/design";
import { layoutZones } from "./prototypeLayout";

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
): PrototypeElementPayload {
  return {
    id: `${kind}-${content}`,
    code: "ELM-001",
    kind,
    content,
    accessible_name: null,
    requirement_ids: [],
    user_story_ids: [],
    acceptance_criterion_ids: [],
    field_name: null,
    required: false,
    options: [],
  };
}

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
