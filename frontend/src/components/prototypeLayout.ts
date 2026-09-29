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

export type DisplayElement = PrototypeElementPayload & { figure?: string; value?: string };

export interface LayoutZone {
  name: LayoutZoneName;
  elements: DisplayElement[];
}

export type ZoneRun =
  | { kind: "pairs"; key: string; elements: DisplayElement[] }
  | { kind: "list"; key: string; items: string[] }
  | { kind: "cards"; key: string; elements: DisplayElement[] }
  | { kind: "element"; key: string; element: DisplayElement; index: number };

const MAIN: LayoutZoneName = "main";
const PAIR = "PAIR";
const TABLE: LayoutZoneName = "table";
const CARD_GRID_ZONES: readonly LayoutZoneName[] = [MAIN, "aside"];
const SPLIT_ARCHETYPES: readonly LayoutArchetype[] = ["LIST_DETAIL", "SPLIT_SCREEN"];
const FIGURE_LENGTH = 40;

const plainKey = (text: string): string =>
  text
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .join(" ")
    .replace(/[ :*.!?]+$/, "");
const labelKey = (text: string): string => plainKey(plainKey(text).replace(/\s*\([^()]*\)$/, ""));
const isLabel = (element: PrototypeElementPayload): boolean =>
  element.kind === "TEXT" && element.content.trimEnd().endsWith(":");
const isField = (element: PrototypeElementPayload): boolean =>
  element.kind === "TEXT_INPUT" || element.kind === "SELECT";

export function displayElements(
  archetype: LayoutArchetype,
  title: string,
  product: string,
  elements: readonly PrototypeElementPayload[],
): DisplayElement[] {
  const repeated = new Set([plainKey(title), plainKey(product)]);
  const visible = elements.filter((element, index) => {
    const next = elements[index + 1];
    if (element.kind === "HEADING" && repeated.has(plainKey(element.content))) return false;
    if (element.kind !== "TEXT" || next === undefined || !isField(next)) return true;
    const key = labelKey(element.content);
    return (
      !key ||
      ![next.accessible_name ?? next.content, next.content].some((label) => labelKey(label) === key)
    );
  });
  const merged: DisplayElement[] = [];
  for (let index = 0; index < visible.length; index += 1) {
    const element = visible[index]!;
    const next = visible[index + 1];
    if (next !== undefined && next.kind === "TEXT" && !isLabel(next)) {
      if (
        archetype === "DASHBOARD" &&
        (element.kind === "STATUS" || element.kind === "CARD") &&
        Array.from(next.content).length <= FIGURE_LENGTH
      ) {
        merged.push({ ...element, figure: next.content });
        index += 1;
        continue;
      }
      if (isLabel(element)) {
        merged.push({ ...element, value: next.content });
        index += 1;
        continue;
      }
    }
    merged.push(element);
  }
  return merged;
}

export function listItems(content: string): string[] {
  const starts: number[] = [];
  for (const match of content.matchAll(/(?<!\S)(\d+)[.)](?=\s)/g)) {
    if (Number(match[1]) === starts.length + 1) starts.push(match.index ?? 0);
  }
  if (starts.length < 2) return [content];
  const bounds = [0, ...starts, content.length];
  return bounds
    .slice(0, -1)
    .map((start, index) => content.slice(start, bounds[index + 1]).trim())
    .filter(Boolean);
}

function runKey(element: DisplayElement): string {
  return element.value === undefined ? element.kind : PAIR;
}

export function zoneRuns(zone: LayoutZoneName, elements: readonly DisplayElement[]): ZoneRun[] {
  const runs: ZoneRun[] = [];
  let start = 0;
  while (start < elements.length) {
    const key = runKey(elements[start]!);
    let end = start + 1;
    while (end < elements.length && runKey(elements[end]!) === key) end += 1;
    const group = elements.slice(start, end);
    const first = group[0]!;
    if (key === PAIR) {
      runs.push({ kind: "pairs", key: first.id, elements: group });
    } else if (key === "LIST" && zone !== TABLE) {
      runs.push({
        kind: "list",
        key: first.id,
        items: group.flatMap((item) => listItems(item.content)),
      });
    } else if (key === "CARD" && CARD_GRID_ZONES.includes(zone)) {
      runs.push({ kind: "cards", key: first.id, elements: group });
    } else {
      group.forEach((element, offset) =>
        runs.push({ kind: "element", key: element.id, element, index: start + offset }),
      );
    }
    start = end;
  }
  return runs;
}

export function splits(archetype: LayoutArchetype, zones: readonly LayoutZone[]): boolean {
  const others = zones.filter((zone) => zone.name !== "column");
  return (
    SPLIT_ARCHETYPES.includes(archetype) &&
    others.length === 2 &&
    others.every((zone) =>
      zone.elements.some((element) => element.kind !== "BUTTON" && element.kind !== "LINK"),
    )
  );
}

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

function kanbanZones(elements: readonly DisplayElement[]): LayoutZone[] {
  const zones: LayoutZone[] = [];
  const main: DisplayElement[] = [];
  let column: DisplayElement[] | null = null;
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

function searchZones(elements: readonly DisplayElement[]): LayoutZone[] {
  const intro: DisplayElement[] = [];
  const search: DisplayElement[] = [];
  const main: DisplayElement[] = [];
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
  elements: readonly DisplayElement[],
): LayoutZone[] {
  if (archetype === "KANBAN_BOARD") return kanbanZones(elements);
  if (archetype === "SEARCH_FIRST") return searchZones(elements);
  const rules = ZONE_RULES[archetype];
  const order: LayoutZoneName[] = rules.map(([name]) => name);
  if (!order.includes(MAIN)) order.push(MAIN);
  const buckets = new Map<LayoutZoneName, DisplayElement[]>(order.map((name) => [name, []]));
  for (const element of elements) {
    const target = rules.find(([, kinds]) => kinds.includes(element.kind))?.[0] ?? MAIN;
    buckets.get(target)!.push(element);
  }
  return order
    .filter((name) => (buckets.get(name)?.length ?? 0) > 0)
    .map((name) => ({ name, elements: buckets.get(name)! }));
}
