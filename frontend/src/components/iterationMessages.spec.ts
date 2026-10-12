import { describe, expect, it } from "vitest";

import { colourWord, correctionLines, uncorrectedWarnings } from "./iterationMessages";
import type { IterationCorrection } from "./iterationTypes";

const COLOUR_KEYS = [
  "red",
  "orange",
  "yellow",
  "green",
  "teal",
  "blue",
  "purple",
  "pink",
  "brown",
  "grey",
  "black",
  "white",
];

function correction(overrides: Partial<IterationCorrection> = {}): IterationCorrection {
  return {
    code: "TEXT_COLOUR_REPLACED",
    selector: ".topbar a",
    property: "color",
    before: { value: "var(--vl-color-primary)", hex: "#0A84FF", ratio: 2.13, name: "blue" },
    after: { token: "on-primary", hex: "#FFFFFF", ratio: 4.02, name: "white" },
    background: { hex: "#FF3B30", name: "red", inherited: false },
    threshold: 4.5,
    large_text: false,
    count: 1,
    ...overrides,
  };
}

const LARGE_TEXT = correction({
  selector: "h1",
  before: { value: "#ff9f0a", hex: "#ff9f0a", ratio: 2.47, name: "orange" },
  after: { token: "text", hex: "#1D1D1F", ratio: 16.8, name: "black" },
  background: { hex: "#FFFFFF", name: "white", inherited: false },
  threshold: 3,
  large_text: true,
});

const BORDER = correction({
  code: "CONTROL_BORDER_REPLACED",
  selector: "input",
  property: "border-color",
  before: { value: "#c7c7cc", hex: "#C7C7CC", ratio: 1.54, name: "grey" },
  after: { token: "text-muted", hex: "#8E8E93", ratio: 3.12, name: "grey" },
  background: { hex: "#FFFFFF", name: "white", inherited: false },
  threshold: 3,
});

const INHERITED = correction({
  background: { hex: "#FF3B30", name: "red", inherited: true },
  count: 2,
});

describe("corrections of the Studio in words", () => {
  it("says what the Studio replaced in a text, in Italian and in English", () => {
    expect(correctionLines([correction()], "it")).toEqual([
      "Testo della regola «.topbar a»: blu #0A84FF su rosso #FF3B30, 2,1:1, sotto il minimo di 4,5:1; lo Studio l'ha sostituito con bianco #FFFFFF, 4,0:1.",
    ]);
    expect(correctionLines([correction()], "en")).toEqual([
      "Text of the rule “.topbar a”: blue #0A84FF on red #FF3B30, 2.1:1, below the minimum of 4.5:1; the Studio replaced it with white #FFFFFF, 4.0:1.",
    ]);
  });

  it("uses the lower minimum of a large text", () => {
    expect(correctionLines([LARGE_TEXT], "it")).toEqual([
      "Testo della regola «h1»: arancione #FF9F0A su bianco #FFFFFF, 2,4:1, sotto il minimo di 3:1; lo Studio l'ha sostituito con nero #1D1D1F, 16,8:1.",
    ]);
    expect(correctionLines([LARGE_TEXT], "en")).toEqual([
      "Text of the rule “h1”: orange #FF9F0A on white #FFFFFF, 2.4:1, below the minimum of 3:1; the Studio replaced it with black #1D1D1F, 16.8:1.",
    ]);
  });

  it("says what the Studio replaced in the border of the controls", () => {
    expect(correctionLines([BORDER], "it")).toEqual([
      "Bordo dei controlli della regola «input»: grigio #C7C7CC su bianco #FFFFFF, 1,5:1, sotto il minimo di 3:1; sostituito con grigio #8E8E93, 3,1:1.",
    ]);
    expect(correctionLines([BORDER], "en")).toEqual([
      "Border of the controls of the rule “input”: grey #C7C7CC on white #FFFFFF, 1.5:1, below the minimum of 3:1; replaced with grey #8E8E93, 3.1:1.",
    ]);
  });

  it("names an inherited background and the number of rules with the same correction", () => {
    expect(correctionLines([INHERITED], "it")).toEqual([
      "Testo della regola «.topbar a»: blu #0A84FF su sfondo ereditato rosso #FF3B30, 2,1:1, sotto il minimo di 4,5:1; lo Studio l'ha sostituito con bianco #FFFFFF, 4,0:1 (2 regole).",
    ]);
    expect(correctionLines([INHERITED], "en")).toEqual([
      "Text of the rule “.topbar a”: blue #0A84FF on the inherited background red #FF3B30, 2.1:1, below the minimum of 4.5:1; the Studio replaced it with white #FFFFFF, 4.0:1 (2 rules).",
    ]);
  });

  it("writes one line for each correction, in order, without codes, arrows or tokens", () => {
    const corrections = [correction(), BORDER, INHERITED, LARGE_TEXT];
    for (const locale of ["it", "en"] as const) {
      const lines = correctionLines(corrections, locale);
      expect(lines).toHaveLength(corrections.length);
      expect(lines[1]).toBe(correctionLines([BORDER], locale)[0]);
      for (const line of lines) {
        expect(line).not.toMatch(
          /TEXT_COLOUR|CONTROL_BORDER|var\(--vl|→|on-primary|text-muted|border-color/,
        );
      }
    }
    expect(correctionLines([], "it")).toEqual([]);
  });

  it("never shows a ratio under the minimum as if it reached it", () => {
    const close = correction({
      before: { value: "#767676", hex: "#767676", ratio: 4.47, name: "grey" },
      after: { token: "text", hex: "#1D1D1F", ratio: 4.5, name: "black" },
    });
    expect(correctionLines([close], "it")[0]).toContain(
      "4,4:1, sotto il minimo di 4,5:1; lo Studio l'ha sostituito con nero #1D1D1F, 4,5:1.",
    );
  });

  it("writes a colour without a known name with its code alone", () => {
    const unnamed = correction({
      before: { value: "#ff00ff", hex: "#ff00ff", ratio: 3.13, name: "magenta" },
    });
    expect(correctionLines([unnamed], "en")[0]).toContain("“.topbar a”: #FF00FF on red #FF3B30");
  });

  it("names the twelve colours in both languages", () => {
    const italian = COLOUR_KEYS.map((key) => colourWord(key, "it"));
    const english = COLOUR_KEYS.map((key) => colourWord(key, "en"));
    expect(italian).toEqual([
      "rosso",
      "arancione",
      "giallo",
      "verde",
      "turchese",
      "blu",
      "viola",
      "rosa",
      "marrone",
      "grigio",
      "nero",
      "bianco",
    ]);
    expect(english).toEqual(COLOUR_KEYS);
    expect(colourWord("magenta", "it")).toBe("");
  });
});

describe("warnings beside the corrections", () => {
  const warnings = [
    { code: "TEXT_COLOUR_REPLACED", screen_code: null, detail: ".topbar a #0a84ff→on-primary" },
    { code: "STYLE_DECLARATION_REMOVED", screen_code: null, detail: "color" },
    { code: "CONTROL_BORDER_REPLACED", screen_code: null, detail: "input #c7c7cc→text-muted" },
    { code: "TEXT_COLOUR_REPLACED", screen_code: null, detail: "h1 #ff9f0a→text" },
    { code: "ATTRIBUTE_REMOVED", screen_code: "SCR-001", detail: "a: target" },
  ];

  it("keeps in their order only the warnings whose code has no correction", () => {
    expect(uncorrectedWarnings(warnings, [correction()])).toEqual([
      warnings[1],
      warnings[2],
      warnings[4],
    ]);
    expect(uncorrectedWarnings(warnings, [correction(), BORDER, LARGE_TEXT])).toEqual([
      warnings[1],
      warnings[4],
    ]);
  });

  it("keeps every warning when there is no correction and nothing when there is no warning", () => {
    expect(uncorrectedWarnings(warnings, [])).toEqual(warnings);
    expect(uncorrectedWarnings([], [correction(), BORDER])).toEqual([]);
  });
});
