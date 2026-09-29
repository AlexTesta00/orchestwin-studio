import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import { BASE_DESIGN_PACKAGE, SELECTED_DESIGN_PACKAGE } from "../test/designFixtures";
import type {
  DeclarativePrototypePayload,
  PrototypeElementKind,
  PrototypeElementPayload,
  VisualChoicesPayload,
  VisualLanguagePayload,
} from "../types/design";
import DeclarativePrototypePreview from "./DeclarativePrototypePreview.vue";
import source from "./DeclarativePrototypePreview.vue?raw";

function element(
  kind: PrototypeElementKind,
  content: string,
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
    field_name: `${kind}-${content}`,
    required: false,
    options: kind === "SELECT" ? ["Uno", "Due"] : [],
  };
}

function screen(title: string, elements: PrototypeElementPayload[]): DeclarativePrototypePayload {
  const prototype = structuredClone(SELECTED_DESIGN_PACKAGE.prototype!);
  const first = prototype.screens[0]!;
  return {
    ...prototype,
    entry_screen_id: first.id,
    screens: [{ ...first, title, elements }],
    transitions: [],
  };
}

function visual(choices: Partial<VisualChoicesPayload> = {}): VisualLanguagePayload {
  const base = structuredClone(BASE_DESIGN_PACKAGE.alternatives[1]!.visual_language!);
  return {
    ...base,
    choices: { ...base.choices, archetype: "SINGLE_CARD", navigation: "NONE", ...choices },
  };
}

function preview(
  elements: PrototypeElementPayload[],
  choices: Partial<VisualChoicesPayload> = {},
  title = "Nuovo prestito",
) {
  return mount(DeclarativePrototypePreview, {
    props: { prototype: screen(title, elements), visual: visual(choices), locale: "it" },
  });
}

describe("DeclarativePrototypePreview", () => {
  it("does not draw a heading that repeats the title of the screen or the product name", () => {
    const wrapper = preview([
      element("HEADING", "Nuovo prestito"),
      element("HEADING", "Reservation desk"),
      element("HEADING", "Dati del lettore"),
    ]);
    expect(wrapper.get(".vl-title").text()).toBe("Nuovo prestito");
    expect(wrapper.findAll(".vl-h2").map((heading) => heading.text())).toEqual([
      "Dati del lettore",
    ]);
  });

  it("drops a paragraph that repeats the label of the field after it", () => {
    const wrapper = preview([
      element("TEXT", "Titolo del libro:"),
      element("TEXT_INPUT", "Titolo del libro"),
      element("TEXT", "Lettore (obbligatorio)"),
      element("SELECT", "Scegli", "Lettore"),
      element("TEXT", "Controlla la data prima di salvare."),
    ]);
    expect(wrapper.findAll(".vl-text").map((text) => text.text())).toEqual([
      "Controlla la data prima di salvare.",
    ]);
    expect(wrapper.findAll(".vl-field").map((field) => field.text())).toEqual([
      "Titolo del libro",
      expect.stringContaining("Lettore"),
    ]);
  });

  it("shows a label and its value as a row of a summary", () => {
    const wrapper = preview([
      element("TEXT", "Scadenza:"),
      element("TEXT", "12 ottobre"),
      element("TEXT", "Lettore:"),
      element("TEXT", "Ada Rossi"),
    ]);
    const pairs = wrapper.findAll("dl.vl-pairs");
    expect(pairs).toHaveLength(1);
    expect(
      pairs[0]!.findAll(".vl-pair").map((row) => [row.get("dt").text(), row.get("dd").text()]),
    ).toEqual([
      ["Scadenza", "12 ottobre"],
      ["Lettore", "Ada Rossi"],
    ]);
    expect(wrapper.find(".vl-text").exists()).toBe(false);
  });

  it("puts consecutive list items and numbered items in one list with a row each", () => {
    const wrapper = preview([
      element("LIST", "Il nome della rosa"),
      element("LIST", "1. Dune 2. Emma"),
    ]);
    const lists = wrapper.findAll("ul.vl-list");
    expect(lists).toHaveLength(1);
    expect(lists[0]!.findAll("li").map((item) => item.text())).toEqual([
      "Il nome della rosa",
      "1. Dune",
      "2. Emma",
    ]);
  });

  it("sets consecutive cards of the main zone in a grid", () => {
    const wrapper = preview([
      element("CARD", "Dune · in ritardo"),
      element("CARD", "Emma · restituito"),
      element("BUTTON", "Aggiorna", "Aggiorna"),
    ]);
    const grid = wrapper.get(".vl-zone-main > .vl-cards");
    expect(grid.findAll(".vl-card").map((card) => card.text())).toEqual([
      "Dune · in ritardo",
      "Emma · restituito",
    ]);
  });

  it("draws the figure of a tile on a dashboard", () => {
    const wrapper = preview(
      [
        element("STATUS", "Prestiti in ritardo"),
        element("TEXT", "12"),
        element("CARD", "Libri disponibili"),
        element("TEXT", "348"),
      ],
      { archetype: "DASHBOARD" },
    );
    const tiles = wrapper.get(".vl-zone-tiles");
    expect(
      tiles
        .findAll(".vl-status, .vl-card")
        .map((tile) => [tile.get(".vl-tile-label").text(), tile.get(".vl-figure").text()]),
    ).toEqual([
      ["Prestiti in ritardo", "12"],
      ["Libri disponibili", "348"],
    ]);
    expect(wrapper.find(".vl-text").exists()).toBe(false);
  });

  it("uses two columns only when a form has more than three fields and never on a phone", async () => {
    const fields = ["Titolo", "Autore", "Lettore", "Scadenza"].map((name) =>
      element("TEXT_INPUT", name),
    );
    const three = preview(fields.slice(0, 3));
    expect(three.get(".vl-zone-main").classes()).not.toContain("vl-two-columns");
    const four = preview(fields);
    expect(four.get(".vl-zone-main").classes()).toContain("vl-two-columns");
    await four.get('[data-viewport="MOBILE"]').trigger("click");
    expect(four.get(".vl-zone-main").classes()).not.toContain("vl-two-columns");
  });

  it("sets list and detail side by side only when both zones hold more than actions", () => {
    const list = element("LIST", "Dune");
    const alone = preview([list, element("BUTTON", "Nuovo", "Nuovo")], {
      archetype: "LIST_DETAIL",
    });
    expect(alone.find(".vl-split").exists()).toBe(false);
    const both = preview(
      [list, element("HEADING", "Dettaglio"), element("BUTTON", "Nuovo", "Nuovo")],
      {
        archetype: "LIST_DETAIL",
      },
    );
    expect(both.find(".vl-split").exists()).toBe(true);
  });

  it("draws the backgrounds DOTS, GRID and STRIPES as TINTED, with no pattern left", () => {
    const style = source.slice(source.indexOf("<style scoped>"));
    expect(style).toMatch(
      /\.vl-bg-TINTED \.vl-shell,\s*\.vl-bg-DOTS \.vl-shell,\s*\.vl-bg-GRID \.vl-shell,\s*\.vl-bg-STRIPES \.vl-shell \{\s*background: var\(--vl-color-surface-alt\);\s*\}/,
    );
    expect(style).not.toMatch(/radial-gradient|repeating-linear-gradient|background-size/);
    const tokens = style.match(/var\(--[a-z-]+/g) ?? [];
    expect(tokens.length).toBeGreaterThan(0);
    expect(tokens.filter((token) => !token.startsWith("var(--vl-"))).toEqual([]);
    for (const background of ["DOTS", "GRID", "STRIPES"] as const) {
      const wrapper = preview([element("TEXT", "Testo")], { background });
      expect(wrapper.get("article").classes()).toContain(`vl-bg-${background}`);
    }
  });

  it("validates required controls, preserves entered values on return, and resets them", async () => {
    const prototype = structuredClone(SELECTED_DESIGN_PACKAGE.prototype!);
    const first = prototype.screens[0]!;
    first.elements.unshift({
      ...first.elements[0]!,
      id: "name-field",
      code: "ELM-000",
      kind: "TEXT_INPUT",
      content: "Guest name",
      accessible_name: "Guest name",
      field_name: "guest",
      required: true,
    });
    first.elements.unshift({
      ...first.elements[0]!,
      id: "choice-field",
      code: "ELM-CHOICE",
      kind: "SELECT",
      content: "Room",
      accessible_name: "Room",
      field_name: "room",
      required: true,
      options: ["Single", "Double"],
    });
    const wrapper = mount(DeclarativePrototypePreview, {
      props: { prototype },
      attachTo: document.body,
    });
    await wrapper.get("button[data-trigger-element-id]").trigger("click");
    expect(wrapper.get("article").attributes("data-screen-id")).toBe(first.id);
    expect(wrapper.get('[role="alert"]').text()).toContain("required fields");
    await wrapper.get('input[name="guest"]').setValue("Ada");
    await wrapper.get("button[data-trigger-element-id]").trigger("click");
    expect(wrapper.get("article").attributes("data-screen-id")).toBe(first.id);
    await wrapper.get('select[name="room"]').setValue("Double");
    await wrapper.get("button[data-trigger-element-id]").trigger("click");
    expect(wrapper.get("article").attributes("data-screen-id")).toBe(prototype.screens[1]!.id);
    expect(document.activeElement).toBe(wrapper.get("h4").element);
    await wrapper.get("nav button").trigger("click");
    expect((wrapper.get('input[name="guest"]').element as HTMLInputElement).value).toBe("Ada");
    await wrapper.get("header button").trigger("click");
    expect((wrapper.get('input[name="guest"]').element as HTMLInputElement).value).toBe("");
    wrapper.unmount();
  });

  it("renders model content as text and exposes phone sizing through accessible controls", async () => {
    const prototype = structuredClone(SELECTED_DESIGN_PACKAGE.prototype!);
    prototype.screens[0]!.elements[0]!.content = '<img src=x onerror="alert(1)">';
    const wrapper = mount(DeclarativePrototypePreview, { props: { prototype, locale: "it" } });
    expect(wrapper.find("img").exists()).toBe(false);
    expect(wrapper.text()).toContain('<img src=x onerror="alert(1)">');
    await wrapper.get('[data-viewport="MOBILE"]').trigger("click");
    expect(wrapper.get("article").classes()).toContain("max-w-sm");
    expect(wrapper.get('[data-viewport="MOBILE"]').attributes("aria-pressed")).toBe("true");
    expect(wrapper.get('[data-viewport="MOBILE"]').text()).toBe("Telefono");
  });

  it("applies the visual language tokens and the archetype shell", async () => {
    const prototype = SELECTED_DESIGN_PACKAGE.prototype!;
    const visual = BASE_DESIGN_PACKAGE.alternatives[1]!.visual_language!;
    const wrapper = mount(DeclarativePrototypePreview, {
      props: { prototype, visual, locale: "it" },
    });
    const article = wrapper.get("article");
    expect(article.attributes("style")).toContain("--vl-color-primary");
    expect(article.attributes("data-archetype")).toBe("DASHBOARD");
    expect(article.classes()).toContain("vl-shell-DASHBOARD");
    expect(wrapper.get('[data-testid="mockup-product-name"]').text()).toBe("Reservation desk");
    expect(wrapper.find(".vl-rail").exists()).toBe(true);
    expect(wrapper.find(".vl-tabs").exists()).toBe(false);
    await wrapper.get('[data-viewport="MOBILE"]').trigger("click");
    expect(wrapper.find(".vl-rail").exists()).toBe(false);
    expect(wrapper.find(".vl-tabs").exists()).toBe(true);
    await wrapper.get(".vl-tabs button:nth-child(2)").trigger("click");
    expect(article.attributes("data-screen-id")).toBe(prototype.screens[1]!.id);
  });

  it("renders trusted data and follows declared transitions", async () => {
    const prototype = SELECTED_DESIGN_PACKAGE.prototype;

    if (prototype === null) {
      throw new Error("The selected Design fixture requires a prototype");
    }

    const wrapper = mount(DeclarativePrototypePreview, {
      props: {
        prototype,
      },
    });

    expect(wrapper.text()).toContain("Availability");
    expect(wrapper.html()).not.toContain("v-html");

    await wrapper.get("button[data-trigger-element-id]").trigger("click");

    expect(wrapper.text()).toContain("Reservation");
    expect(wrapper.get("article[data-screen-id]").attributes("data-screen-id")).toBe(
      prototype.screens[1]?.id,
    );
  });
});
