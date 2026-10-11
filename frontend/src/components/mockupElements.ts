import type { DesignChangeTarget } from "../api/designIterations";
import { TARGET_HTML_LIMIT, TARGET_LABEL_LIMIT } from "../stores/designIterations";

export interface InspectorBox {
  code: string;
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface InspectorHighlight {
  hover: InspectorBox | null;
  selected: InspectorBox | null;
}

export interface InspectedElement {
  code: string;
  tag: string;
  text: string;
  screen: string | null;
  requirements: string[];
}

export interface ScreenElements {
  screen: string | null;
  elements: Element[];
}

export const NO_HIGHLIGHT: InspectorHighlight = { hover: null, selected: null };

const SCREEN = "section[id^='SCR-']";
export const MARKED = "[data-elm]";
const PIN = "ot-pin";
const SRCDOC_LINK = /(\shref=")about:srcdoc#(SCR-[0-9]{3}")/g;
const NAME_ATTRIBUTES = ["value", "placeholder", "title", "alt"] as const;
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
  for (const child of node.childNodes) {
    if (child.nodeType === 3) {
      parts.push(child.textContent ?? "");
      continue;
    }
    if (!isElement(child) || silent(child)) {
      continue;
    }
    const block = BLOCKS.has(child.localName);
    if (block) {
      parts.push(" ");
    }
    collect(child, parts);
    if (block) {
      parts.push(" ");
    }
  }
}

function ownText(element: Element): string {
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
  return normalize(names.map((name) => page.getElementById(name)?.textContent ?? "").join(" "));
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

export function elementText(element: Element): string {
  const candidates = [
    () => ownText(element),
    () => referencedText(element),
    () => normalize(element.getAttribute("aria-label") ?? ""),
    () => labelText(element),
    ...NAME_ATTRIBUTES.map((name) => () => normalize(element.getAttribute(name) ?? "")),
  ];
  for (const candidate of candidates) {
    const text = candidate();
    if (text.length > 0) {
      return clip(text, TARGET_LABEL_LIMIT);
    }
  }
  return "";
}

export function requirementsOf(element: Element): string[] {
  const value = element.closest("[data-req]")?.getAttribute("data-req") ?? "";
  return [...new Set(value.split(/[\s,]+/).filter((code) => code.length > 0))];
}

export function describeElement(element: Element): InspectedElement {
  return {
    code: element.getAttribute("data-elm") ?? "",
    tag: element.localName,
    text: elementText(element),
    screen: element.closest(SCREEN)?.id ?? null,
    requirements: requirementsOf(element),
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
    const code = element.getAttribute("data-elm") ?? "";
    if (code.length === 0 || seen.has(code)) {
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

export function changeTarget(element: Element, screen: string | null): DesignChangeTarget | null {
  const code = element.getAttribute("data-elm");
  const screenCode = element.closest(SCREEN)?.id ?? screen;
  if (code === null || code.length === 0 || screenCode === null || screenCode.length === 0) {
    return null;
  }
  const copy = element.cloneNode(true) as Element;
  for (const pin of [...copy.querySelectorAll(`.${PIN}`)]) {
    pin.remove();
  }
  return {
    screen_code: screenCode,
    element_code: code,
    label: elementText(element) || code,
    html: clip(copy.outerHTML.replace(SRCDOC_LINK, "$1#$2"), TARGET_HTML_LIMIT),
  };
}
