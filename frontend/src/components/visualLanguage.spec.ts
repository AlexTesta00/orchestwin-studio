import { describe, expect, it } from "vitest";

import {
  ARCHETYPE_LABELS,
  NEUTRAL_CHOICES,
  choiceLabel,
  dimensionLabel,
  valueLabel,
} from "./visualLanguage";

const FONTS = [
  "HUMANIST_SANS",
  "GEOMETRIC_SANS",
  "GROTESQUE_SANS",
  "SOFT_SANS",
  "NARROW_SANS",
  "WIDE_SANS",
  "SYSTEM_UI",
  "TRANSITIONAL_SERIF",
  "OLD_STYLE_SERIF",
  "MODERN_SERIF",
  "SLAB_SERIF",
  "MONOSPACE",
  "DISPLAY_HEAVY",
  "SCRIPT",
];

const CATALOG: Record<string, string[]> = {
  archetype: Object.keys(ARCHETYPE_LABELS.it),
  hue_family: [
    "CRIMSON",
    "CORAL",
    "TERRACOTTA",
    "AMBER",
    "OCHRE",
    "OLIVE",
    "FOREST",
    "EMERALD",
    "TEAL",
    "OCEAN",
    "COBALT",
    "INDIGO",
    "VIOLET",
    "PLUM",
    "MAGENTA",
    "ROSE",
    "SLATE",
    "GRAPHITE",
    "SAND",
  ],
  color_scheme: [
    "MONOCHROME",
    "ANALOGOUS",
    "COMPLEMENTARY",
    "TRIADIC",
    "SPLIT_COMPLEMENTARY",
    "NEUTRAL_ACCENT",
  ],
  color_mode: ["LIGHT", "DARK", "HIGH_CONTRAST_LIGHT", "HIGH_CONTRAST_DARK"],
  saturation: ["MUTED", "BALANCED", "VIVID"],
  surface_tone: ["NEUTRAL", "TINTED", "WARM", "COOL"],
  heading_family: FONTS,
  body_family: FONTS,
  type_scale: ["COMPACT", "REGULAR", "DISPLAY"],
  heading_case: ["SENTENCE", "UPPERCASE", "SMALL_CAPS"],
  heading_weight: ["REGULAR", "SEMIBOLD", "BLACK"],
  corners: ["SHARP", "SOFT", "ROUND", "PILL"],
  density: ["COMPACT", "COMFORTABLE", "SPACIOUS"],
  buttons: ["FILLED", "OUTLINED", "SOFT", "GHOST"],
  inputs: ["BOXED", "UNDERLINED", "FILLED"],
  elevation: ["FLAT", "SUBTLE", "RAISED"],
  borders: ["NONE", "HAIRLINE", "BOLD"],
  navigation: ["NONE", "TOP_BAR", "SIDE_RAIL", "TABS"],
  header: ["MINIMAL", "COMPACT_BAR", "HERO_BAND", "CENTERED_TITLE"],
  background: ["PLAIN", "TINTED", "GRADIENT", "DOTS", "GRID", "STRIPES"],
  emphasis: ["RESTRAINED", "BALANCED", "BOLD"],
  tone: [
    "ESSENTIAL",
    "WARM",
    "INSTITUTIONAL",
    "PLAYFUL",
    "TECHNICAL",
    "EDITORIAL",
    "LUXURIOUS",
    "ENERGETIC",
    "CALM",
    "RUSTIC",
    "FUTURISTIC",
    "CLINICAL",
    "ARTISANAL",
    "CIVIC",
  ],
};

const SAME_WORD = new Set(["TERRACOTTA", "MAGENTA", "DASHBOARD"]);

describe("visualLanguage labels", () => {
  it("names every dimension of the catalog in both languages", () => {
    const dimensions = Object.keys(NEUTRAL_CHOICES);

    expect(Object.keys(CATALOG).sort()).toEqual([...dimensions].sort());
    for (const locale of ["en", "it"] as const) {
      const labels = dimensions.map((dimension) => dimensionLabel(locale, dimension));

      expect(new Set(labels).size).toBe(dimensions.length);
      expect(labels.every((label) => !label.includes("_"))).toBe(true);
    }
    expect(dimensionLabel("it", "heading_weight")).toBe("Peso dei titoli");
    expect(dimensionLabel("en", "heading_weight")).toBe("Heading weight");
  });

  it("names every value of the catalog in Italian", () => {
    const untranslated = Object.entries(CATALOG).flatMap(([dimension, values]) =>
      values
        .filter(
          (value) =>
            !SAME_WORD.has(value) && choiceLabel("it", dimension, value) === valueLabel(value),
        )
        .map((value) => `${dimension}.${value}`),
    );

    expect(untranslated).toEqual([]);
    expect(Object.values(CATALOG).flat()).toHaveLength(136);
  });

  it("keeps values of one dimension distinct from each other", () => {
    for (const [dimension, values] of Object.entries(CATALOG)) {
      const labels = values.map((value) => choiceLabel("it", dimension, value));

      expect(new Set(labels).size, dimension).toBe(values.length);
    }
  });

  it("translates the same word by the dimension it belongs to", () => {
    expect(choiceLabel("it", "buttons", "SOFT")).toBe("Tenui");
    expect(choiceLabel("it", "corners", "SOFT")).toBe("Smussati");
    expect(choiceLabel("it", "borders", "NONE")).toBe("Nessuno");
    expect(choiceLabel("it", "navigation", "NONE")).toBe("Nessuna");
    expect(choiceLabel("it", "archetype", "DASHBOARD")).toBe("Cruscotto");
  });

  it("reads the catalog name in English and falls back to it for unknown values", () => {
    expect(choiceLabel("en", "heading_family", "SLAB_SERIF")).toBe("Slab serif");
    expect(choiceLabel("en", "archetype", "TABLE_FIRST")).toBe("Table first");
    expect(choiceLabel("it", "tone", "NOT_IN_CATALOG")).toBe("Not in catalog");
    expect(choiceLabel("it", "unknown_dimension", "SIDE_RAIL")).toBe("Side rail");
    expect(dimensionLabel("it", "unknown_dimension")).toBe("Unknown dimension");
  });
});
