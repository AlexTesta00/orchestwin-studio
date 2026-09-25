import type {
  LayoutArchetype,
  PrototypeElementKind,
  PrototypeElementPayload,
} from "../types/design";

export type LayoutZoneName =
  | "main"
  | "aside"
  | "tiles"
  | "thread"
  | "composer"
  | "intro"
  | "table"
  | "gallery"
  | "timeline"
  | "column"
  | "search";

export interface LayoutZone {
  name: LayoutZoneName;
  elements: PrototypeElementPayload[];
}

const MAIN: LayoutZoneName = "main";

const ZONE_RULES: Record<
  LayoutArchetype,
  readonly [LayoutZoneName, readonly PrototypeElementKind[]][]
> = {
  GUIDED_STEPS: [],
  SINGLE_CARD: [],
  FOCUS_MODE: [],
  LIST_DETAIL: [["aside", ["LIST", "CARD"]]],
  DASHBOARD: [["tiles", ["STATUS", "CARD"]]],
  SPLIT_SCREEN: [
    [MAIN, ["HEADING", "TEXT_INPUT", "SELECT", "BUTTON", "LINK"]],
    ["aside", ["TEXT", "CARD", "STATUS", "LIST"]],
  ],
  CONVERSATIONAL: [
    [MAIN, ["HEADING"]],
    ["thread", ["TEXT", "STATUS", "CARD", "LIST"]],
    ["composer", ["TEXT_INPUT", "SELECT", "BUTTON", "LINK"]],
  ],
  TABLE_FIRST: [
    ["intro", ["HEADING", "TEXT"]],
    ["table", ["LIST"]],
  ],
  CARD_GALLERY: [
    ["intro", ["HEADING", "TEXT"]],
    ["gallery", ["CARD"]],
  ],
  FEED_TIMELINE: [
    ["intro", ["HEADING"]],
    ["composer", ["TEXT_INPUT", "SELECT", "BUTTON"]],
    ["timeline", ["CARD", "TEXT"]],
  ],
  KANBAN_BOARD: [],
  SEARCH_FIRST: [["intro", ["HEADING", "TEXT"]]],
};

function kanbanZones(elements: readonly PrototypeElementPayload[]): LayoutZone[] {
  const zones: LayoutZone[] = [];
  const main: PrototypeElementPayload[] = [];
  let column: PrototypeElementPayload[] | null = null;
  for (const element of elements) {
    if (element.kind === "HEADING") {
      column = [element];
      zones.push({ name: "column", elements: column });
    } else if (column !== null && ["CARD", "LIST", "TEXT"].includes(element.kind)) {
      column.push(element);
    } else {
      main.push(element);
    }
  }
  if (main.length > 0) zones.push({ name: MAIN, elements: main });
  return zones;
}

function searchZones(elements: readonly PrototypeElementPayload[]): LayoutZone[] {
  const intro: PrototypeElementPayload[] = [];
  const search: PrototypeElementPayload[] = [];
  const main: PrototypeElementPayload[] = [];
  let seenInput = false;
  let seenButton = false;
  for (const element of elements) {
    if ((element.kind === "HEADING" || element.kind === "TEXT") && search.length === 0) {
      intro.push(element);
    } else if (element.kind === "TEXT_INPUT" && !seenInput) {
      search.push(element);
      seenInput = true;
    } else if (element.kind === "BUTTON" && seenInput && !seenButton) {
      search.push(element);
      seenButton = true;
    } else {
      main.push(element);
    }
  }
  const zones: LayoutZone[] = [];
  if (intro.length > 0) zones.push({ name: "intro", elements: intro });
  if (search.length > 0) zones.push({ name: "search", elements: search });
  if (main.length > 0) zones.push({ name: MAIN, elements: main });
  return zones;
}

export function layoutZones(
  archetype: LayoutArchetype,
  elements: readonly PrototypeElementPayload[],
): LayoutZone[] {
  if (archetype === "KANBAN_BOARD") return kanbanZones(elements);
  if (archetype === "SEARCH_FIRST") return searchZones(elements);
  const rules = ZONE_RULES[archetype];
  const order: LayoutZoneName[] = rules.map(([name]) => name);
  if (!order.includes(MAIN)) order.push(MAIN);
  const buckets = new Map<LayoutZoneName, PrototypeElementPayload[]>(
    order.map((name) => [name, []]),
  );
  for (const element of elements) {
    const target = rules.find(([, kinds]) => kinds.includes(element.kind))?.[0] ?? MAIN;
    buckets.get(target)!.push(element);
  }
  return order
    .filter((name) => (buckets.get(name)?.length ?? 0) > 0)
    .map((name) => ({ name, elements: buckets.get(name)! }));
}
