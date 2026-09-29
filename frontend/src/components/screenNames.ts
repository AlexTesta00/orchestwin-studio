export type ScreenNameLocale = "en" | "it";

export interface ScreenName {
  code: string;
  title: string;
}

export interface WorkflowName {
  code: string;
  title: string;
}

export interface ScreenNaming {
  screens: readonly ScreenName[];
  elements?: Readonly<Record<string, string>> | undefined;
  workflows?: readonly WorkflowName[] | undefined;
  locale: ScreenNameLocale;
}

const CODE = /(?<![\p{L}\p{N}_-])(?:SCR|ELM|FLOW)-\d+(?![\p{L}\p{N}_])/gu;
const PLACE_CODE = /^(?:SCR|ELM)-\d+(?![\p{L}\p{N}_])[\s:·\-–—]*/u;
const PLACE_NAME = /^((?:SCR|ELM)-\d+)(?![\p{L}\p{N}_])[\s:·\-–—]*(.*)$/u;
const SEPARATOR = /[\s:·\-–—]/u;
const WORD = /[\p{L}\p{N}_]/u;
const TRAILING_SPACE = /\s+$/u;
const CLOSING_MARKS = new Set(["»", "”", "“", '"', "'", "’"]);

const MARKS: Readonly<Record<string, string>> = {
  "«": "»",
  "“": "”",
  "„": "“",
  '"': '"',
  "'": "'",
  "‘": "’",
  "(": ")",
  "[": "]",
};

const QUOTES: Readonly<Record<ScreenNameLocale, readonly [string, string]>> = {
  it: ["«", "»"],
  en: ["“", "”"],
};

function namesAfter(prefix: "SCR" | "ELM", locations: readonly string[]): Record<string, string> {
  const names: Record<string, string> = {};
  for (const location of locations) {
    for (const part of location.split("·")) {
      const match = PLACE_NAME.exec(part.trim());
      const code = match?.[1];
      const name = match?.[2]?.trim() ?? "";
      if (
        code !== undefined &&
        code.startsWith(`${prefix}-`) &&
        name.length > 0 &&
        !(code in names)
      ) {
        names[code] = name;
      }
    }
  }
  return names;
}

export function placeLabel(location: string): string {
  const place = location.trim();
  const names = place
    .split("·")
    .map((part) => part.trim().replace(PLACE_CODE, "").trim())
    .filter((part) => part.length > 0);
  return names.length === 0 ? place : names.join(" · ");
}

export function elementNames(locations: readonly string[]): Record<string, string> {
  return namesAfter("ELM", locations);
}

export function placeScreens(locations: readonly string[]): ScreenName[] {
  return Object.entries(namesAfter("SCR", locations)).map(([code, title]) => ({ code, title }));
}

function sameWords(left: string, right: string, locale: ScreenNameLocale): boolean {
  return left.toLocaleLowerCase(locale) === right.toLocaleLowerCase(locale);
}

function nameAfter(text: string, from: number, name: string, locale: ScreenNameLocale): number {
  let position = from;
  while (position < text.length && SEPARATOR.test(text.charAt(position))) {
    position += 1;
  }
  const closing = MARKS[text.charAt(position)];
  if (closing !== undefined) {
    position += 1;
  }
  if (!sameWords(text.slice(position, position + name.length), name, locale)) {
    return from;
  }
  position += name.length;
  if (WORD.test(text.charAt(position))) {
    return from;
  }
  if (closing === undefined) {
    return position;
  }
  return text.charAt(position) === closing ? position + 1 : from;
}

function endsWithName(head: string, name: string, locale: ScreenNameLocale): boolean {
  let text = head.replace(TRAILING_SPACE, "");
  if (CLOSING_MARKS.has(text.charAt(text.length - 1))) {
    text = text.slice(0, -1);
  }
  if (text.length < name.length) {
    return false;
  }
  const start = text.length - name.length;
  return sameWords(text.slice(start), name, locale) && !WORD.test(text.charAt(start - 1));
}

function knownNames(naming: ScreenNaming): Map<string, string> {
  const names = new Map<string, string>();
  for (const screen of naming.screens) {
    const title = screen.title.trim();
    if (title.length > 0 && !names.has(screen.code)) {
      names.set(screen.code, title);
    }
  }
  for (const [code, name] of Object.entries(naming.elements ?? {})) {
    const label = name.trim();
    if (code.startsWith("ELM-") && label.length > 0 && !names.has(code)) {
      names.set(code, label);
    }
  }
  for (const workflow of naming.workflows ?? []) {
    const title = workflow.title.trim();
    if (workflow.code.startsWith("FLOW-") && title.length > 0 && !names.has(workflow.code)) {
      names.set(workflow.code, title);
    }
  }
  return names;
}

export function withScreenNames(text: string, naming: ScreenNaming): string {
  const names = knownNames(naming);
  if (names.size === 0) {
    return text;
  }
  const [open, close] = QUOTES[naming.locale];
  let result = "";
  let cursor = 0;
  for (const match of text.matchAll(CODE)) {
    const name = names.get(match[0]);
    if (name === undefined || match.index < cursor) {
      continue;
    }
    let start = match.index;
    let end = start + match[0].length;
    const before = text.charAt(start - 1);
    const wrapped =
      start > cursor && MARKS[before] !== undefined && text.charAt(end) === MARKS[before];
    if (wrapped && (before === "(" || before === "[")) {
      const head = text.slice(cursor, start - 1);
      if (endsWithName(head, name, naming.locale)) {
        result += head.replace(TRAILING_SPACE, "");
        cursor = end + 1;
        continue;
      }
    }
    if (wrapped) {
      start -= 1;
      end += 1;
    } else {
      end = nameAfter(text, end, name, naming.locale);
    }
    result += `${text.slice(cursor, start)}${open}${name}${close}`;
    cursor = end;
  }
  return result + text.slice(cursor);
}
