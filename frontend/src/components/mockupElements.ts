import type { DesignChangeTarget, DesignChangeTargetElement } from "../api/designIterations";
import { PART_CODE, TARGET_HTML_LIMIT, TARGET_LABEL_LIMIT } from "../stores/designIterations";

export type PartKind = "element" | "zone";

export type ZoneKind =
  | "header"
  | "navigation"
  | "main"
  | "footer"
  | "aside"
  | "section"
  | "form"
  | "list"
  | "table"
  | "details"
  | "figure"
  | "group"
  | "cards";

export interface InspectorBox {
  code: string;
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface InspectorHighlight {
  hover: InspectorBox | null;
  selected: InspectorBox[];
}

export interface InspectorElement {
  code: string;
  kind: PartKind;
  zoneKind?: ZoneKind;
  tag: string;
  label: string;
  holds: string[];
  parent: string | null;
  screen: string | null;
  requirements: string[];
  node: Element;
}

export interface ScreenElements {
  screen: string | null;
  elements: Element[];
}

export const NO_HIGHLIGHT: InspectorHighlight = { hover: null, selected: [] };

const SCREEN = "section[id^='SCR-']";
const ELEMENT_ATTRIBUTE = "data-elm";
const ZONE_ATTRIBUTE = "data-ot-zone";
const ELEMENT = `[${ELEMENT_ATTRIBUTE}]`;
const ZONE = `[${ZONE_ATTRIBUTE}]`;
export const MARKED = `${ELEMENT},${ZONE}`;
const PIN = "ot-pin";
const SRCDOC_LINK = /(\shref=")about:srcdoc#(SCR-[0-9]{3}")/g;
const NAME_ATTRIBUTES = ["value", "placeholder", "title", "alt"] as const;
const CAPTIONS = new Set(["legend", "caption", "summary", "figcaption"]);
const HEADINGS = "h1, h2, h3, h4";
const SILENT = new Set(["script", "style", "template", "noscript", "select", "textarea", "svg"]);
const BLOCKS = new Set([
  "article",
  "aside",
  "blockquote",
  "br",
  "caption",
  "dd",
  "details",
  "div",
  "dl",
  "dt",
  "fieldset",
  "figcaption",
  "figure",
  "footer",
  "form",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "header",
  "hr",
  "legend",
  "li",
  "main",
  "nav",
  "ol",
  "p",
  "section",
  "summary",
  "table",
  "tbody",
  "td",
  "tfoot",
  "th",
  "thead",
  "tr",
  "ul",
]);

const ZONE_ROLES = new Map<string, ZoneKind>([
  ["navigation", "navigation"],
  ["banner", "header"],
  ["main", "main"],
  ["contentinfo", "footer"],
  ["complementary", "aside"],
  ["region", "section"],
  ["form", "form"],
  ["search", "form"],
  ["list", "list"],
  ["group", "group"],
  ["radiogroup", "group"],
  ["toolbar", "group"],
  ["tablist", "group"],
]);

const ZONE_TAGS = new Map<string, ZoneKind>([
  ["header", "header"],
  ["nav", "navigation"],
  ["main", "main"],
  ["footer", "footer"],
  ["aside", "aside"],
  ["section", "section"],
  ["form", "form"],
  ["ul", "list"],
  ["ol", "list"],
  ["dl", "list"],
  ["table", "table"],
  ["details", "details"],
  ["figure", "figure"],
  ["fieldset", "group"],
]);

function normalize(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

export function clip(value: string, limit: number): string {
  const characters = [...value];
  return characters.length <= limit ? value : characters.slice(0, limit).join("").trimEnd();
}

export function isElement(node: Node): node is Element {
  return node.nodeType === 1;
}

function silent(element: Element): boolean {
  return (
    SILENT.has(element.localName) ||
    element.hasAttribute("hidden") ||
    element.classList.contains(PIN)
  );
}

function collect(node: Node, parts: string[]): void {
  let afterElement = false;
  for (const child of node.childNodes) {
    if (child.nodeType === 3) {
      parts.push(child.textContent ?? "");
      afterElement = false;
      continue;
    }
    if (!isElement(child)) {
      continue;
    }
    if (afterElement) {
      parts.push(" ");
    }
    afterElement = true;
    if (silent(child)) {
      continue;
    }
    const spacer = BLOCKS.has(child.localName) ? " " : "";
    parts.push(spacer);
    collect(child, parts);
    parts.push(spacer);
  }
}

function ownText(element: Element | null): string {
  if (element === null) {
    return "";
  }
  if (element.localName === "select") {
    const option = element.querySelector("option[selected]") ?? element.querySelector("option");
    return normalize(option?.textContent ?? "");
  }
  if (element.localName === "textarea") {
    return normalize(element.textContent ?? "");
  }
  const parts: string[] = [];
  collect(element, parts);
  return normalize(parts.join(""));
}

function referencedText(element: Element): string {
  const page = element.ownerDocument;
  const names = (element.getAttribute("aria-labelledby") ?? "").split(/\s+/).filter(Boolean);
  return normalize(names.map((name) => ownText(page.getElementById(name))).join(" "));
}

function labelText(element: Element): string {
  const id = element.getAttribute("id");
  const labels = [...element.ownerDocument.querySelectorAll("label[for]")].filter(
    (label) => id !== null && label.getAttribute("for") === id,
  );
  const owner = element.closest("label");
  return normalize(
    [...labels, ...(owner === null ? [] : [owner])].map((label) => ownText(label)).join(" "),
  );
}

function firstText(candidates: readonly (() => string)[]): string {
  for (const candidate of candidates) {
    const text = candidate();
    if (text.length > 0) {
      return clip(text, TARGET_LABEL_LIMIT);
    }
  }
  return "";
}

export function elementText(element: Element): string {
  return firstText([
    () => ownText(element),
    () => referencedText(element),
    () => normalize(element.getAttribute("aria-label") ?? ""),
    () => labelText(element),
    ...NAME_ATTRIBUTES.map((name) => () => normalize(element.getAttribute(name) ?? "")),
  ]);
}

function zoneText(zone: Element): string {
  return firstText([
    () => referencedText(zone),
    () => normalize(zone.getAttribute("aria-label") ?? ""),
    () => ownText([...zone.children].find((child) => CAPTIONS.has(child.localName)) ?? null),
    () => ownText(zone.querySelector(HEADINGS)),
    () => ownText(zone),
  ]);
}

function zoneKindOf(zone: Element): ZoneKind {
  const role = (zone.getAttribute("role") ?? "").trim().split(/\s+/)[0] ?? "";
  const kind = zone.localName === "div" ? ZONE_ROLES.get(role) : ZONE_TAGS.get(zone.localName);
  return kind ?? "cards";
}

export function codeOf(element: Element): string {
  return element.getAttribute(ELEMENT_ATTRIBUTE) ?? element.getAttribute(ZONE_ATTRIBUTE) ?? "";
}

function heldCodes(zone: Element): string[] {
  return [
    ...new Set(
      [...zone.querySelectorAll(ELEMENT)].map(codeOf).filter((code) => PART_CODE.test(code)),
    ),
  ];
}

function containerOf(element: Element): string | null {
  const zone = element.parentElement?.closest(ZONE) ?? null;
  return zone === null ? null : codeOf(zone);
}

export function requirementsOf(element: Element): string[] {
  const value = element.closest("[data-req]")?.getAttribute("data-req") ?? "";
  return [...new Set(value.split(/[\s,]+/).filter((code) => code.length > 0))];
}

export function describeElement(element: Element, screen: string | null = null): InspectorElement {
  const part = {
    code: codeOf(element),
    tag: element.localName,
    parent: containerOf(element),
    screen: element.closest(SCREEN)?.id ?? screen,
    requirements: requirementsOf(element),
    node: element,
  };
  if (!element.hasAttribute(ZONE_ATTRIBUTE)) {
    return { ...part, kind: "element", label: elementText(element), holds: [] };
  }
  return {
    ...part,
    kind: "zone",
    zoneKind: zoneKindOf(element),
    label: zoneText(element),
    holds: heldCodes(element),
  };
}

function rendered(element: Element): boolean {
  const box = element.getBoundingClientRect();
  return box.width > 0 && box.height > 0;
}

export function visibleScreen(page: Document): Element | null {
  const screens = [...page.querySelectorAll(SCREEN)];
  return (
    screens.find(rendered) ??
    screens.find((screen) => screen.hasAttribute("data-entry")) ??
    screens[0] ??
    null
  );
}

export function screenElements(page: Document): ScreenElements {
  const screen = visibleScreen(page);
  const scope = screen ?? page.body ?? page.documentElement;
  const seen = new Set<string>();
  const elements = [...scope.querySelectorAll(MARKED)].filter((element) => {
    const code = codeOf(element);
    if (!PART_CODE.test(code) || seen.has(code)) {
      return false;
    }
    seen.add(code);
    return true;
  });
  return { screen: screen?.id ?? null, elements };
}

export function markedElements(html: string): boolean {
  return new DOMParser().parseFromString(html, "text/html").querySelector(MARKED) !== null;
}

function markupOf(element: Element): string {
  const copy = element.cloneNode(true) as Element;
  for (const pin of [...copy.querySelectorAll(`.${PIN}`)]) {
    pin.remove();
  }
  return clip(copy.outerHTML.replace(SRCDOC_LINK, "$1#$2"), TARGET_HTML_LIMIT);
}

function namedPart(part: InspectorElement): DesignChangeTargetElement {
  return { element_code: part.code, label: part.label || part.code };
}

export function changeTarget(parts: readonly InspectorElement[]): DesignChangeTarget | null {
  const [first] = parts;
  const screen = first?.screen ?? null;
  if (first === undefined || screen === null) {
    return null;
  }
  if (parts.length > 1) {
    return { screen_code: screen, elements: parts.map(namedPart) };
  }
  const named = { screen_code: screen, ...namedPart(first) };
  return first.kind === "zone" ? named : { ...named, html: markupOf(first.node) };
}
