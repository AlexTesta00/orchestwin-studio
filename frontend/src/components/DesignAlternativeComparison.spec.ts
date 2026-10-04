import { createPinia, setActivePinia } from "pinia";
import { mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  BASE_DESIGN_PACKAGE,
  DESIGN_ALTERNATIVE_ID,
  DIRECTED_DESIGN_PACKAGE,
  DIRECTED_DESIGN_VERSION,
  LEDGER_DIRECTION,
  SECOND_DESIGN_ALTERNATIVE_ID,
  designDistanceReport,
} from "../test/designFixtures";
import { expectAccessible } from "@/test/axe";
import type { DesignAlternativePayload, UserTwinVersionReferencePayload } from "../types/design";
import type {
  DesignDistanceReportPayload,
  DesignDistanceVerdict,
  StyleDifference,
} from "../types/designDistance";
import DesignAlternativeComparison, {
  type AlternativePreview,
  MOCKUP_READ_FAILURE,
} from "./DesignAlternativeComparison.vue";
import GeneratedMockupFrame from "./GeneratedMockupFrame.vue";
import { DIRECTION_AXES, DIRECTION_VALUE_LABELS } from "./visualLanguage";
import source from "./DesignAlternativeComparison.vue?raw";

const RECEPTIONIST = BASE_DESIGN_PACKAGE.grounding.user_twin_references[0]!;
const AUDITOR: UserTwinVersionReferencePayload = {
  twin_id: "00000000-0000-4000-8000-000000000114",
  version_number: 2,
  content_hash: "9".repeat(64),
  name: "Night Auditor Twin",
};
const GUIDED = BASE_DESIGN_PACKAGE.alternatives[0]!;
const DASHBOARD = BASE_DESIGN_PACKAGE.alternatives[1]!;
const RECEPTIONIST_FIT = DASHBOARD.visual_language!.twin_fit[0]!.statement;
const AUDITOR_FIT = "Muted tiles keep the night shift focused on the open folios.";

const ALTERNATIVES: DesignAlternativePayload[] = [
  GUIDED,
  {
    ...DASHBOARD,
    visual_language: {
      ...DASHBOARD.visual_language!,
      twin_fit: [
        ...DASHBOARD.visual_language!.twin_fit,
        { twin_id: AUDITOR.twin_id, name: AUDITOR.name, statement: AUDITOR_FIT },
      ],
    },
  },
];

const HTML =
  "<!doctype html><html lang='en'><body><h1 class='thumbnail-marker'>Desk</h1></body></html>";

let wrapper: VueWrapper | null = null;

function mountCards(
  props: Partial<InstanceType<typeof DesignAlternativeComparison>["$props"]> = {},
) {
  wrapper = mount(DesignAlternativeComparison, {
    props: {
      alternatives: ALTERNATIVES,
      twins: [RECEPTIONIST, AUDITOR],
      recommendedAlternativeId: DESIGN_ALTERNATIVE_ID,
      ...props,
    },
  });
  return wrapper;
}

function card(target: VueWrapper, code: string) {
  return target.get(`[data-test="alternative-${code}"]`);
}

function layoutOf(target: VueWrapper, code: string): string[] | null {
  const row = card(target, code).find('[data-testid="alternative-layout"]');
  return row.exists() ? [row.get("dt").text(), row.get("dd").text()] : null;
}

const DIRECTED = DIRECTED_DESIGN_PACKAGE.alternatives;
const MEASURE_IDS = [
  "FAR",
  "CLOSE",
  "UNKNOWN",
  "MAYBE",
  "FOLLOWED",
  "NOT_FOLLOWED",
  "NOT_CHECKED",
  "RADIUS",
  "BORDER",
  "BOXING",
  "SHADOW",
  "TYPE_SCALE",
  "TITLE_SCALE",
  "UPPERCASE",
  "COLOUR_FIELDS",
  "TINTS",
  "GRADIENT",
  "CONTAINER",
  "COLUMNS",
  "SPACING",
  "MONOSPACE",
  "FUTURE_FEATURE",
  "OUTLINE",
  "TAGS",
  "TABLE",
  "CARDS",
  "SIDE_COLUMN",
  "NAVIGATION",
  "FORMS",
];
const DIRECTION_IDS = DIRECTION_AXES.flatMap((axis) =>
  Object.keys(DIRECTION_VALUE_LABELS.en[axis]),
);
const INTERNAL_IDS = new RegExp(`\\b(?:${[...DIRECTION_IDS, ...MEASURE_IDS].join("|")})\\b`);

function chipsOf(target: VueWrapper, code: string): string[] {
  return card(target, code)
    .findAll('[data-testid="alternative-direction-axis"]')
    .map((chip) => chip.text());
}

function detailsOf(target: VueWrapper): (string | null)[] {
  return target
    .findAll('[data-testid="design-distance-level"]')
    .map((level) => (level.find("p").exists() ? level.get("p").text() : null));
}

function scoresOf(target: VueWrapper): string[] {
  return target.findAll('[data-testid="design-distance-score"]').map((score) => score.text());
}

describe("DesignAlternativeComparison", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  afterEach(() => {
    wrapper?.unmount();
    wrapper = null;
    vi.useRealTimers();
  });

  it("shows each alternative as a card with its code, title, summary and one point for and against", () => {
    const cards = mountCards({ locale: "it" });
    const guided = card(cards, "DES-001");
    expect(guided.text()).toContain("DES-001");
    expect(guided.get('[data-testid="alternative-recommended"]').text()).toBe(
      "· consigliata dal designer",
    );
    expect(guided.get("h3").text()).toBe("Guided reservation flow");
    expect(guided.text()).toContain("Guide the receptionist through one decision at a time.");
    expect(guided.get('[data-testid="alternative-pro"]').text()).toBe(
      "A favore The current step remains explicit.",
    );
    expect(guided.get('[data-testid="alternative-con"]').text()).toBe(
      "Contro Frequent users may need additional navigation.",
    );
    expect(card(cards, "DES-002").find('[data-testid="alternative-recommended"]').exists()).toBe(
      false,
    );
    expect(guided.get('[data-testid="alternative-open"]').text()).toBe("Prova il mockup");
    expect(guided.get('[data-testid="alternative-choose"]').text()).toBe("Scegli questa");
    expect(guided.get('[data-testid="alternative-choose"]').attributes("aria-label")).toBe(
      "Scegli DES-001 · Guided reservation flow",
    );
  });

  it("emits the exact alternative chosen by the owner and the one to try", async () => {
    const cards = mountCards();
    await card(cards, "DES-002").get('[data-testid="alternative-choose"]').trigger("click");
    await card(cards, "DES-001").get('[data-testid="alternative-open"]').trigger("click");
    expect(cards.emitted("select")).toEqual([[SECOND_DESIGN_ALTERNATIVE_ID]]);
    expect(cards.emitted("open")).toEqual([[DESIGN_ALTERNATIVE_ID]]);
  });

  it("marks the applied choice instead of offering it again and never chooses while disabled or busy", async () => {
    const cards = mountCards({ selectedAlternativeId: DESIGN_ALTERNATIVE_ID });
    const guided = card(cards, "DES-001");
    expect(guided.attributes("data-chosen")).toBe("true");
    expect(guided.classes()).toContain("border-petrol-on-night");
    expect(guided.find('[data-testid="alternative-choose"]').exists()).toBe(false);
    expect(guided.get('[data-testid="alternative-chosen"]').text()).toBe("Your choice");

    await cards.setProps({ choosable: { [SECOND_DESIGN_ALTERNATIVE_ID]: false } });
    const choose = card(cards, "DES-002").get('[data-testid="alternative-choose"]');
    expect(choose.attributes("disabled")).toBeDefined();
    await choose.trigger("click");
    await cards.setProps({ choosable: {}, disabled: true });
    await card(cards, "DES-002").get('[data-testid="alternative-choose"]').trigger("click");
    await cards.setProps({ disabled: false, choosing: SECOND_DESIGN_ALTERNATIVE_ID });
    expect(card(cards, "DES-002").get('[data-testid="alternative-choose"]').text()).toBe(
      "Applying your choice…",
    );
    await card(cards, "DES-002").get('[data-testid="alternative-choose"]').trigger("click");
    expect(cards.emitted("select")).toBeUndefined();
  });

  it("shows the first screen of a drawn mockup only in an inert sandboxed thumbnail", () => {
    const previews: Record<string, AlternativePreview> = {
      [DESIGN_ALTERNATIVE_ID]: { kind: "document", html: HTML },
    };
    const cards = mountCards({ previews });
    const frame = cards.getComponent(GeneratedMockupFrame);
    expect(frame.props()).toMatchObject({
      html: HTML,
      interactive: false,
      title: "Preview of DES-001 · Guided reservation flow",
    });
    const iframe = card(cards, "DES-001").get("iframe");
    expect(iframe.attributes("sandbox")).toBe("");
    expect(cards.find(".thumbnail-marker").exists()).toBe(false);
    expect(source).not.toMatch(/v-html|innerHTML/);
    expect(card(cards, "DES-002").find('[data-testid="design-style-tile"]').exists()).toBe(true);
  });

  it("says while the designer draws, with the stage and the time elapsed", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-29T09:14:03+00:00"));
    const cards = mountCards({
      locale: "it",
      previews: {
        [DESIGN_ALTERNATIVE_ID]: {
          kind: "drawing",
          startedAt: "2026-09-29T09:12:03+00:00",
          stage: "VALIDATING",
        },
      },
    });
    const drawing = card(cards, "DES-001").get('[data-testid="alternative-drawing"]');
    expect(drawing.attributes("aria-busy")).toBe("true");
    expect(drawing.text()).toContain("Il designer sta disegnando il mockup");
    expect(drawing.get('[role="status"]').text()).toBe("Lo Studio controlla il mockup.");
    expect(drawing.get('[data-testid="alternative-elapsed"]').text()).toBe("In corso da 2 min 0 s");
    expect(card(cards, "DES-001").find('[data-testid="alternative-open"]').exists()).toBe(false);
    vi.advanceTimersByTime(5000);
    await cards.vm.$nextTick();
    expect(card(cards, "DES-001").get('[data-testid="alternative-elapsed"]').text()).toBe(
      "In corso da 2 min 5 s",
    );
    await cards.setProps({ previews: {} });
    expect(vi.getTimerCount()).toBe(0);
  });

  it("says how long a mockup usually takes and lets the block grow with its text on a phone", async () => {
    const cards = mountCards({
      locale: "it",
      previews: {
        [DESIGN_ALTERNATIVE_ID]: {
          kind: "drawing",
          startedAt: "2026-09-29T09:12:03+00:00",
          stage: "GENERATING",
        },
      },
    });
    const drawing = card(cards, "DES-001").get('[data-testid="alternative-drawing"]');
    const elapsed = drawing.get('[data-testid="alternative-elapsed"]').element;
    const duration = drawing.get('[data-testid="alternative-duration"]');
    expect(duration.text()).toBe(
      "Di solito servono da 5 a 10 minuti. Puoi continuare a lavorare: il disegno prosegue anche se chiudi la pagina.",
    );
    expect(
      elapsed.compareDocumentPosition(duration.element) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(drawing.classes()).not.toContain("aspect-[16/10]");
    expect(drawing.classes()).toContain("sm:aspect-[16/10]");
    expect(drawing.classes()).toContain("min-h-[180px]");
    expect(card(cards, "DES-002").find('[data-testid="alternative-duration"]').exists()).toBe(
      false,
    );
    await cards.setProps({ locale: "en" });
    expect(card(cards, "DES-001").get('[data-testid="alternative-duration"]').text()).toBe(
      "It usually takes 5 to 10 minutes. You can keep working: the drawing goes on even if you close the page.",
    );
    await expectAccessible(cards.element, { iframes: false });
  });

  it("explains a discarded answer in plain words and offers to try again only when it helps", async () => {
    const cards = mountCards({
      locale: "it",
      previews: {
        [DESIGN_ALTERNATIVE_ID]: {
          kind: "rejected",
          code: "MOCKUP_QUALITY_REJECTED",
          reasons: [
            { code: "TABLE_TOO_SHORT", screen_code: "SCR-001", detail: "table has 2 rows" },
            { code: "TABLE_TOO_SHORT", screen_code: "SCR-002", detail: "table has 1 row" },
            { code: "LOW_CONTRAST", screen_code: null, detail: ".badge 2.10" },
            { code: "EMPTY_CELL", screen_code: null, detail: "td" },
            { code: "PLACEHOLDER_TEXT", screen_code: null, detail: "Lorem" },
            { code: "SINGLE_STATE", screen_code: null, detail: "default only" },
          ],
          retryable: true,
        },
        [SECOND_DESIGN_ALTERNATIVE_ID]: {
          kind: "failed",
          code: "GENERATION_BUDGET_EXCEEDED",
          reasons: [],
          retryable: false,
        },
      },
    });
    const rejected = card(cards, "DES-001").get('[data-testid="alternative-failure"]');
    expect(rejected.attributes("role")).toBe("alert");
    expect(rejected.text()).toContain("Il mockup va rifatto");
    expect(
      rejected.text().match(/scartato/g),
      "the title and the sentence under it do not repeat the same words",
    ).toHaveLength(1);
    expect(card(cards, "DES-001").find('[data-testid="alternative-open"]').exists()).toBe(false);
    expect(card(cards, "DES-002").find('[data-testid="alternative-open"]').exists()).toBe(false);
    expect(rejected.findAll("li").map((item) => item.text())).toEqual([
      "Una tabella aveva troppo poche righe per sembrare vera",
      "Un testo non si leggeva bene sul suo sfondo",
      "Una cella di una tabella era vuota",
      "e altri 2 punti",
    ]);
    expect(rejected.text()).not.toMatch(/TABLE_TOO_SHORT|SCR-00|badge/);
    await rejected.get('[data-testid="alternative-retry"]').trigger("click");
    expect(cards.emitted("retry")).toEqual([[DESIGN_ALTERNATIVE_ID]]);

    const failed = card(cards, "DES-002").get('[data-testid="alternative-failure"]');
    expect(failed.text()).toContain("Il mockup non è stato disegnato");
    expect(failed.text()).toContain(
      "Il tetto di spesa impostato non basta per questa generazione.",
    );
    expect(failed.find('[data-testid="alternative-retry"]').exists()).toBe(false);
  });

  it("still offers to open a drawn mockup whose picture could not be read", async () => {
    const cards = mountCards({
      locale: "it",
      previews: {
        [DESIGN_ALTERNATIVE_ID]: {
          kind: "failed",
          code: MOCKUP_READ_FAILURE,
          reasons: [],
          retryable: true,
        },
      },
    });
    const guided = card(cards, "DES-001");
    expect(guided.get('[data-testid="alternative-failure"]').text()).toContain(
      "Il mockup non si è caricato",
    );
    await guided.get('[data-testid="alternative-open"]').trigger("click");
    await guided.get('[data-testid="alternative-retry"]').trigger("click");
    expect(cards.emitted("open")).toEqual([[DESIGN_ALTERNATIVE_ID]]);
    expect(cards.emitted("retry")).toEqual([[DESIGN_ALTERNATIVE_ID]]);
  });

  it("offers to draw a missing mockup and says that drawing has a cost", async () => {
    const cards = mountCards({
      previews: { [SECOND_DESIGN_ALTERNATIVE_ID]: { kind: "missing" } },
    });
    const missing = card(cards, "DES-002").get('[data-testid="alternative-missing"]');
    expect(card(cards, "DES-002").find('[data-testid="alternative-open"]').exists()).toBe(false);
    expect(card(cards, "DES-001").find('[data-testid="alternative-open"]').exists()).toBe(true);
    expect(missing.text()).toContain("The mockup of this alternative has not been drawn yet.");
    expect(missing.text()).toContain("Drawing uses the hosted model and has a cost.");
    await missing.get('[data-testid="alternative-draw"]').trigger("click");
    expect(cards.emitted("retry")).toEqual([[SECOND_DESIGN_ALTERNATIVE_ID]]);
  });

  it("says that drawing uses the Claude subscription and spends no credit when it is not paid", async () => {
    const cards = mountCards({
      paid: false,
      previews: { [SECOND_DESIGN_ALTERNATIVE_ID]: { kind: "missing" } },
    });
    const note = () => card(cards, "DES-002").get('[data-testid="alternative-draw-cost"]');
    expect(note().text()).toBe("Drawing uses your Claude subscription: it spends no credit.");
    expect(cards.text()).not.toContain("has a cost");
    await cards.setProps({ locale: "it" });
    expect(note().text()).toBe("Il disegno usa il tuo abbonamento di Claude: non spende credito.");
    expect(cards.text()).not.toContain("ha un costo");
    await cards.setProps({ paid: true });
    expect(note().text()).toBe("Il disegno usa il modello ospitato e ha un costo.");
  });

  it("shows a hint under the actions when the page gives one", () => {
    const cards = mountCards({
      hints: { [SECOND_DESIGN_ALTERNATIVE_ID]: "Try the mockup first: then you can choose it." },
    });
    expect(card(cards, "DES-002").get('[data-testid="alternative-hint"]').text()).toBe(
      "Try the mockup first: then you can choose it.",
    );
    expect(card(cards, "DES-001").find('[data-testid="alternative-hint"]').exists()).toBe(false);
  });

  it("shows a note of the page on the card without calling it an error", () => {
    const cards = mountCards({
      notes: {
        [DESIGN_ALTERNATIVE_ID]: "The mockup does not show these requirements yet: REQ-004.",
      },
    });
    const note = card(cards, "DES-001").get('[data-testid="alternative-note"]');
    expect(note.text()).toBe("The mockup does not show these requirements yet: REQ-004.");
    expect(note.attributes("role")).toBeUndefined();
    expect(card(cards, "DES-002").find('[data-testid="alternative-note"]').exists()).toBe(false);
  });

  it("shows the layout archetype, a stored approach as before, or no row at all", async () => {
    const cards = mountCards({ alternatives: BASE_DESIGN_PACKAGE.alternatives });

    expect(layoutOf(cards, "DES-001")).toEqual(["Approach", "GUIDED_WORKFLOW"]);
    expect(layoutOf(cards, "DES-002")).toEqual(["Layout", "Dashboard"]);

    await cards.setProps({ locale: "it" });

    expect(layoutOf(cards, "DES-001")).toEqual(["Approccio", "GUIDED_WORKFLOW"]);
    expect(layoutOf(cards, "DES-002")).toEqual(["Impostazione", "Cruscotto"]);

    const variants: DesignAlternativePayload[] = BASE_DESIGN_PACKAGE.alternatives.map(
      (alternative) =>
        alternative.visual_language
          ? {
              ...alternative,
              approach: "DASHBOARD_FIRST",
              visual_language: {
                ...alternative.visual_language,
                choices: { ...alternative.visual_language.choices, archetype: "LIST_DETAIL" },
              },
            }
          : { ...alternative, approach: null },
    );
    await cards.setProps({ alternatives: variants });

    expect(layoutOf(cards, "DES-001")).toBeNull();
    expect(layoutOf(cards, "DES-002")).toEqual(["Impostazione", "Elenco e dettaglio"]);

    await cards.setProps({ locale: "en" });

    expect(layoutOf(cards, "DES-002")).toEqual(["Layout", "List and detail"]);
    expect(cards.text()).not.toContain("DASHBOARD_FIRST");
  });

  it("keeps the details of an alternative closed, with how it serves every twin", async () => {
    const cards = mountCards({ locale: "it" });
    const details = card(cards, "DES-002").get('[data-testid="alternative-details"]');
    expect(details.attributes("open")).toBeUndefined();
    expect(details.get("summary").text()).toBe(
      "Dettagli dell'alternativa: Reservation operations dashboard",
    );
    const fits = details.get('[data-testid="alternative-twin-fit"]');
    expect(fits.get("h4").text()).toBe("Come serve i twin");
    expect(fits.findAll("li").map((item) => item.text())).toEqual([
      `Receptionist Twin · ${RECEPTIONIST_FIT}`,
      `Night Auditor Twin · ${AUDITOR_FIT}`,
    ]);
    expect(details.text()).toContain("Support rapid orientation across active reservation work.");
    expect(details.text()).toContain("Frequent actions remain close to status information.");
    expect(details.text()).toContain("FLOW-002 · Review and create reservations");
    expect(
      card(cards, "DES-001")
        .get('[data-testid="alternative-details"]')
        .find('[data-testid="alternative-twin-fit"]')
        .exists(),
    ).toBe(false);
  });

  it("has no axe violations in every state of a card", async () => {
    const cards = mountCards({
      selectedAlternativeId: DESIGN_ALTERNATIVE_ID,
      previews: {
        [DESIGN_ALTERNATIVE_ID]: { kind: "document", html: HTML },
        [SECOND_DESIGN_ALTERNATIVE_ID]: {
          kind: "rejected",
          code: "MOCKUP_QUALITY_REJECTED",
          reasons: [{ code: "LOW_CONTRAST", screen_code: null, detail: "" }],
          retryable: true,
        },
      },
    });
    await expectAccessible(cards.element, { iframes: false });
    await cards.setProps({
      previews: {
        [DESIGN_ALTERNATIVE_ID]: { kind: "loading" },
        [SECOND_DESIGN_ALTERNATIVE_ID]: { kind: "missing" },
      },
    });
    await expectAccessible(cards.element, { iframes: false });
  });

  it("shows the visual direction of each alternative in one line with its five axes, also under a drawn thumbnail", () => {
    const cards = mountCards({
      alternatives: DIRECTED,
      previews: { [DESIGN_ALTERNATIVE_ID]: { kind: "document", html: HTML } },
    });
    const timetable = card(cards, "DES-001");
    expect(timetable.find('[data-testid="alternative-thumbnail"]').exists()).toBe(true);
    const direction = timetable.get('[data-testid="alternative-direction"]');
    expect(direction.get("p").text()).toBe("Visual direction: Printed timetable");
    const chips = direction.findAll('[data-testid="alternative-direction-axis"]');
    expect(chips.map((chip) => chip.text())).toEqual([
      "Layout: Editorial page",
      "Shapes: Square corners and rules",
      "Type: Very large titles",
      "Colour: Almost monochrome",
      "Density: Spacious",
    ]);
    expect(chips.map((chip) => chip.get(".sr-only").text())).toEqual([
      "Layout:",
      "Shapes:",
      "Type:",
      "Colour:",
      "Density:",
    ]);
    expect(chips.map((chip) => chip.attributes("data-axis"))).toEqual([...DIRECTION_AXES]);

    const ledger = card(cards, "DES-002");
    expect(ledger.find('[data-testid="design-style-tile"]').exists()).toBe(true);
    expect(ledger.get('[data-testid="alternative-direction"] p').text()).toBe(
      "Visual direction: Front desk ledger",
    );
    expect(chipsOf(cards, "DES-002")).toEqual([
      "Layout: Workbench",
      "Shapes: Rounded outlines",
      "Type: Upper-case labels",
      "Colour: Tinted surfaces",
      "Density: Spacious",
    ]);
    expect(
      timetable.get("h3").element.compareDocumentPosition(direction.element) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(cards.text()).not.toMatch(INTERNAL_IDS);
  });

  it("names the visual direction and its axes in Italian", () => {
    const cards = mountCards({ alternatives: DIRECTED, locale: "it" });
    expect(card(cards, "DES-001").get('[data-testid="alternative-direction"] p').text()).toBe(
      "Direzione visiva: Printed timetable",
    );
    expect(chipsOf(cards, "DES-001")).toEqual([
      "Impianto: Pagina editoriale",
      "Forme: Angoli vivi e filetti",
      "Tipografia: Titoli molto grandi",
      "Colore: Quasi monocromo",
      "Densità: Ariosa",
    ]);
    expect(chipsOf(cards, "DES-002")).toEqual([
      "Impianto: Banco di lavoro",
      "Forme: Contorni arrotondati",
      "Tipografia: Etichette maiuscole",
      "Colore: Superfici tinte",
      "Densità: Ariosa",
    ]);
    expect(cards.text()).not.toMatch(INTERNAL_IDS);
  });

  it("keeps a card without a visual direction as it was, without an empty line or a placeholder", async () => {
    const cards = mountCards({ alternatives: BASE_DESIGN_PACKAGE.alternatives });
    const before = BASE_DESIGN_PACKAGE.alternatives.map((item) => card(cards, item.code).html());
    expect(cards.find('[data-testid="alternative-direction"]').exists()).toBe(false);
    expect(cards.find('[data-testid="alternative-direction-detail"]').exists()).toBe(false);
    expect(cards.find('[data-testid="design-distance"]').exists()).toBe(false);
    expect(cards.text()).not.toMatch(/Visual direction|Rules|Distance/);

    await cards.setProps({
      alternatives: BASE_DESIGN_PACKAGE.alternatives.map((item) =>
        item.visual_language === null
          ? item
          : { ...item, visual_language: { ...item.visual_language, direction: null } },
      ),
      distance: null,
    });

    const after = BASE_DESIGN_PACKAGE.alternatives.map((item) => card(cards, item.code).html());
    expect(after).toEqual(before);
    await cards.setProps({ locale: "it" });
    expect(cards.text()).not.toMatch(/Direzione visiva|Regole|Distanza/);
  });

  it("puts the concept, the rules and the origin of the direction in the details of the card", async () => {
    const cards = mountCards({ alternatives: DIRECTED });
    const details = card(cards, "DES-002").get('[data-testid="alternative-details"]');
    expect(details.attributes("open")).toBeUndefined();
    const direction = details.get('[data-testid="alternative-direction-detail"]');
    expect(direction.get("h4").text()).toBe("Visual direction");
    expect(direction.get("p").text()).toBe(LEDGER_DIRECTION.concept);
    expect(direction.get("h5").text()).toBe("Rules");
    expect(
      direction
        .findAll('[data-testid="alternative-direction-rules"] li')
        .map((item) => item.text()),
    ).toEqual(LEDGER_DIRECTION.rules);
    expect(direction.get('[data-testid="alternative-direction-origin"]').text()).toBe(
      "Proposed by the model among 5 candidates; chosen by the Studio because it is far from the other.",
    );
    expect(
      direction.element.compareDocumentPosition(details.get("dl").element) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    await cards.setProps({ locale: "it" });
    const italian = card(cards, "DES-002").get('[data-testid="alternative-direction-detail"]');
    expect(italian.get("h4").text()).toBe("Direzione visiva");
    expect(italian.get("h5").text()).toBe("Regole");
    expect(italian.get('[data-testid="alternative-direction-origin"]').text()).toBe(
      "Proposta dal modello fra 5 candidate; scelta dallo Studio perché lontana dall'altra.",
    );
  });

  it("says above the alternatives how far apart they are and keeps the measure on request", () => {
    const cards = mountCards({ alternatives: DIRECTED, distance: designDistanceReport() });
    const blocks = cards.findAll('[data-testid="design-distance"]');
    expect(blocks).toHaveLength(1);
    const block = blocks[0]!;
    const grid = cards.get('[data-testid="design-alternative"]').element;
    expect(
      block.element.compareDocumentPosition(grid) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(block.attributes("data-verdict")).toBe("FAR");
    expect(block.get("h3").text()).toBe("Distance between the alternatives");
    expect(block.get('[data-testid="design-distance-verdict"]').text()).toBe("They differ");
    expect(block.get('[data-testid="design-distance-axes"]').text()).toBe("4 of 5 axes differ");
    expect(block.find('[role="status"]').exists()).toBe(false);

    const details = block.get('[data-testid="design-distance-details"]');
    expect(details.attributes("open")).toBeUndefined();
    expect(details.get("summary").text()).toBe("Details of the measure");
    const levels = details.findAll('[data-testid="design-distance-level"]');
    expect(levels.map((level) => level.attributes("data-level"))).toEqual([
      "declared",
      "styles",
      "structure",
    ]);
    expect(levels.map((level) => level.get("span").text())).toEqual([
      "Declared choices",
      "Drawn style",
      "Structure of the screens",
    ]);
    expect(scoresOf(cards)).toEqual(["80/100", "64/100", "41/100"]);
    const meters = details.findAll('[data-testid="design-distance-meter"]');
    expect(meters.map((meter) => meter.attributes("style"))).toEqual([
      "width: 80%;",
      "width: 64%;",
      "width: 41%;",
    ]);
    const hidden = details.findAll('[aria-hidden="true"] [data-testid="design-distance-meter"]');
    expect(hidden).toHaveLength(3);
    expect(detailsOf(cards)).toEqual([
      "Differences: Layout, Shapes, Type, and Colour",
      "Differences: corner radius, borders, size of the titles against the text, fields of colour, and width of the content",
      "Differences: arrangement of the first screen, tables, and cards",
    ]);
    expect(details.find('[data-testid="design-distance-missing"]').exists()).toBe(false);
    expect(details.get('[data-testid="design-distance-caveat"]').text()).toBe(
      "Measure computed by the Studio: it does not replace your judgement.",
    );
    expect(cards.text()).not.toMatch(INTERNAL_IDS);
  });

  it("warns in Italian when the two alternatives are too close", () => {
    const cards = mountCards({
      alternatives: DIRECTED,
      locale: "it",
      distance: designDistanceReport(DIRECTED_DESIGN_VERSION, {
        styles: { available: true, score: 12, differences: [] },
        structure: { available: true, score: 9, differences: ["NAVIGATION"] },
        verdict: "CLOSE",
      }),
    });
    const block = cards.get('[data-testid="design-distance"]');
    expect(block.attributes("data-verdict")).toBe("CLOSE");
    expect(block.get("h3").text()).toBe("Distanza fra le alternative");
    expect(block.get('[data-testid="design-distance-verdict"]').text()).toBe("Troppo vicine");
    expect(block.get('[data-testid="design-distance-axes"]').text()).toBe("4 assi diversi su 5");
    const warning = block.get('[data-testid="design-distance-close"]');
    expect(warning.attributes("role")).toBe("status");
    expect(warning.text()).toBe(
      "Le due alternative si somigliano nello stile disegnato. Puoi rigenerarle.",
    );
    expect(block.get("summary").text()).toBe("Dettagli della misura");
    expect(scoresOf(cards)).toEqual(["80/100", "12/100", "9/100"]);
    expect(detailsOf(cards)).toEqual([
      "Differenze: Impianto, Forme, Tipografia e Colore",
      null,
      "Differenze: posizione della navigazione",
    ]);
    expect(block.get('[data-testid="design-distance-caveat"]').text()).toBe(
      "Misura calcolata dallo Studio: non sostituisce il tuo giudizio.",
    );
    expect(cards.text()).not.toMatch(INTERNAL_IDS);
  });

  it("warns in English about the drawn style alone and keeps the structure as information", () => {
    const cards = mountCards({
      alternatives: DIRECTED,
      distance: designDistanceReport(DIRECTED_DESIGN_VERSION, {
        styles: { available: true, score: 12, differences: [] },
        verdict: "CLOSE",
      }),
    });
    const block = cards.get('[data-testid="design-distance"]');
    expect(block.get('[data-testid="design-distance-verdict"]').text()).toBe("Too close");
    expect(block.get('[data-testid="design-distance-close"]').text()).toBe(
      "The two alternatives look alike in drawn style. You can regenerate them.",
    );
    expect(scoresOf(cards)).toEqual(["80/100", "12/100", "41/100"]);
    expect(detailsOf(cards)).toEqual([
      "Differences: Layout, Shapes, Type, and Colour",
      null,
      "Differences: arrangement of the first screen, tables, and cards",
    ]);
    expect(cards.text()).not.toMatch(INTERNAL_IDS);
  });

  it("waits for both mockups to measure the drawn style and the structure, and says it once", async () => {
    const cards = mountCards({
      alternatives: DIRECTED,
      distance: designDistanceReport(DIRECTED_DESIGN_VERSION, {
        styles: { available: false, score: null, differences: [] },
        structure: { available: false, score: null, differences: [] },
        verdict: "UNKNOWN",
      }),
    });
    const block = cards.get('[data-testid="design-distance"]');
    const unknown = "Complete measure when both mockups are ready";
    expect(block.get('[data-testid="design-distance-verdict"]').text()).toBe(unknown);
    expect(block.get('[data-testid="design-distance-axes"]').text()).toBe("4 of 5 axes differ");
    expect(block.find('[role="status"]').exists()).toBe(false);
    const details = block.get('[data-testid="design-distance-details"]');
    const levels = details.findAll('[data-testid="design-distance-level"]');
    expect(levels.map((level) => level.attributes("data-level"))).toEqual(["declared"]);
    expect(scoresOf(cards)).toEqual(["80/100"]);
    expect(detailsOf(cards)).toEqual(["Differences: Layout, Shapes, Type, and Colour"]);
    expect(details.get('[data-testid="design-distance-missing"]').text()).toBe(
      `Drawn style and Structure of the screens · ${unknown}`,
    );
    expect(details.text().split(unknown)).toHaveLength(2);

    await cards.setProps({ locale: "it" });
    expect(cards.get('[data-testid="design-distance-missing"]').text()).toBe(
      "Stile disegnato e Struttura delle schermate · Misura completa quando i due mockup sono pronti",
    );
    expect(cards.get('[data-testid="design-distance-verdict"]').text()).toBe(
      "Misura completa quando i due mockup sono pronti",
    );
  });

  it("measures the declared choices of alternatives without a direction or without a visual language", async () => {
    const report = designDistanceReport(DIRECTED_DESIGN_VERSION, {
      declared: {
        score: 77,
        axes_different: null,
        axes: [],
        choices_different: 17,
        choices_total: 22,
        primary_colour_distance: 0.4,
      },
    });
    const cards = mountCards({ alternatives: BASE_DESIGN_PACKAGE.alternatives, distance: report });
    expect(cards.find('[data-testid="design-distance-axes"]').exists()).toBe(false);
    expect(cards.find('[data-testid="alternative-direction"]').exists()).toBe(false);
    expect(scoresOf(cards)).toEqual(["77/100", "64/100", "41/100"]);
    expect(detailsOf(cards)[0]).toBe("17 of 22 choices differ");

    await cards.setProps({ locale: "it" });
    expect(detailsOf(cards)[0]).toBe("17 scelte diverse su 22");

    const single = designDistanceReport(DIRECTED_DESIGN_VERSION, {
      declared: { ...report.pairs[0]!.declared, score: 5, choices_different: 1 },
    });
    await cards.setProps({ distance: single, locale: "en" });
    expect(detailsOf(cards)[0]).toBe("1 of 22 choices differs");

    const unmeasured = designDistanceReport(DIRECTED_DESIGN_VERSION, {
      declared: { ...report.pairs[0]!.declared, score: null, choices_different: null },
      styles: { available: false, score: null, differences: [] },
      structure: { available: false, score: null, differences: [] },
      verdict: "UNKNOWN",
    });
    await cards.setProps({ distance: unmeasured });
    expect(cards.find('[data-testid="design-distance-level"]').exists()).toBe(false);
    expect(cards.find('[data-testid="design-distance-details"] ul').exists()).toBe(false);
    expect(cards.get('[data-testid="design-distance-missing"]').text()).toBe(
      "Drawn style and Structure of the screens · Complete measure when both mockups are ready",
    );
  });

  it("shows no distance without a report or with a report about other alternatives", async () => {
    const cards = mountCards({ alternatives: DIRECTED });
    expect(cards.find('[data-testid="design-distance"]').exists()).toBe(false);

    const report = designDistanceReport();
    await cards.setProps({
      distance: {
        ...report,
        pairs: report.pairs.map((pair) => ({ ...pair, second: "DES-003" })),
      },
    });
    expect(cards.find('[data-testid="design-distance"]').exists()).toBe(false);

    await cards.setProps({ distance: report });
    expect(cards.findAll('[data-testid="design-distance"]')).toHaveLength(1);
    await cards.setProps({ distance: null });
    expect(cards.find('[data-testid="design-distance"]').exists()).toBe(false);
  });

  it("never shows an internal id of the measure, even for a value it does not know", () => {
    const cards = mountCards({
      alternatives: DIRECTED,
      distance: designDistanceReport(DIRECTED_DESIGN_VERSION, {
        styles: {
          available: true,
          score: 100,
          differences: [
            "RADIUS",
            "BORDER",
            "BOXING",
            "SHADOW",
            "TYPE_SCALE",
            "TITLE_SCALE",
            "UPPERCASE",
            "COLOUR_FIELDS",
            "TINTS",
            "GRADIENT",
            "CONTAINER",
            "COLUMNS",
            "SPACING",
            "MONOSPACE",
            "FUTURE_FEATURE",
          ] as unknown as StyleDifference[],
        },
        structure: {
          available: true,
          score: 140,
          differences: ["OUTLINE", "TAGS", "TABLE", "CARDS", "SIDE_COLUMN", "NAVIGATION", "FORMS"],
        },
        verdict: "MAYBE" as unknown as DesignDistanceVerdict,
      }),
    });
    expect(cards.get('[data-testid="design-distance"]').attributes("data-verdict")).toBe("UNKNOWN");
    expect(cards.get('[data-testid="design-distance-verdict"]').text()).toBe(
      "Complete measure when both mockups are ready",
    );
    expect(scoresOf(cards)).toEqual(["80/100", "100/100", "100/100"]);
    expect(detailsOf(cards).slice(1)).toEqual([
      "Differences: corner radius, borders, boxes or rules, shadows, size of the titles against the text, title size, upper-case text, fields of colour, tinted surfaces, gradients, width of the content, columns, spacing, and fixed-width type",
      "Differences: arrangement of the first screen, elements used in the screens, tables, cards, side column, position of the navigation, and forms",
    ]);
    expect(cards.text()).not.toMatch(INTERNAL_IDS);
  });

  it("names the boxes or rules and the title size of the drawn style in plain words, in English and in Italian", async () => {
    const cards = mountCards({
      alternatives: DIRECTED,
      distance: designDistanceReport(DIRECTED_DESIGN_VERSION, {
        styles: { available: true, score: 58, differences: ["BOXING", "TITLE_SCALE", "RADIUS"] },
      }),
    });
    expect(scoresOf(cards)).toEqual(["80/100", "58/100", "41/100"]);
    expect(detailsOf(cards)).toEqual([
      "Differences: Layout, Shapes, Type, and Colour",
      "Differences: boxes or rules, title size, and corner radius",
      "Differences: arrangement of the first screen, tables, and cards",
    ]);
    expect(cards.text()).not.toMatch(INTERNAL_IDS);

    await cards.setProps({ locale: "it" });
    expect(detailsOf(cards)).toEqual([
      "Differenze: Impianto, Forme, Tipografia e Colore",
      "Differenze: riquadri o filetti, grandezza del titolo e raggio degli angoli",
      "Differenze: disposizione della prima schermata, tabelle e schede",
    ]);
    expect(cards.text()).not.toMatch(INTERNAL_IDS);
  });

  it("adds to the notes of a card the axes of the direction that its mockup does not follow", async () => {
    const report = designDistanceReport();
    const distance: DesignDistanceReportPayload = {
      ...report,
      alternatives: [
        report.alternatives[0]!,
        {
          ...report.alternatives[1]!,
          adherence: {
            available: true,
            axes: {
              layout: "NOT_FOLLOWED",
              shape: "FOLLOWED",
              type: "NOT_FOLLOWED",
              colour: "FOLLOWED",
              density: "NOT_CHECKED",
            },
          },
        },
      ],
    };
    const cards = mountCards({
      alternatives: DIRECTED,
      distance,
      notes: {
        [SECOND_DESIGN_ALTERNATIVE_ID]: "The mockup does not show these requirements yet: REQ-004.",
      },
    });
    const note = card(cards, "DES-002").get('[data-testid="alternative-note"]');
    expect(note.findAll("span").map((line) => line.text())).toEqual([
      "The mockup does not show these requirements yet: REQ-004.",
      "The mockup does not follow the direction on: Layout and Type",
    ]);
    expect(note.attributes("role")).toBeUndefined();
    expect(card(cards, "DES-001").find('[data-testid="alternative-note"]').exists()).toBe(false);

    await cards.setProps({ locale: "it", notes: {} });
    expect(card(cards, "DES-002").get('[data-testid="alternative-note"]').text()).toBe(
      "Il mockup non segue la direzione su: Impianto e Tipografia",
    );

    await cards.setProps({
      distance: {
        ...distance,
        alternatives: distance.alternatives.map((item) => ({
          ...item,
          adherence: { ...item.adherence, available: false },
        })),
      },
    });
    expect(card(cards, "DES-002").find('[data-testid="alternative-note"]').exists()).toBe(false);
  });

  it("lets the direction and the distance wrap on a narrow screen", () => {
    const cards = mountCards({ alternatives: DIRECTED, distance: designDistanceReport() });
    const list = card(cards, "DES-001").get('[data-testid="alternative-direction"] ul');
    expect(list.classes()).toEqual(expect.arrayContaining(["flex", "flex-wrap"]));
    for (const chip of list.findAll("li")) {
      expect(chip.classes()).toEqual(expect.arrayContaining(["max-w-full", "break-words"]));
    }
    expect(cards.get('[data-testid="design-distance-verdict"]').classes()).toEqual(
      expect.arrayContaining(["max-w-full", "break-words"]),
    );
    expect(cards.get('[data-testid="design-distance"] > div').classes()).toContain("flex-wrap");
    expect(source).not.toMatch(/v-html|innerHTML/);
  });

  it("has no axe violations with the directions and the distance, details open", async () => {
    const cards = mountCards({
      alternatives: DIRECTED,
      selectedAlternativeId: DESIGN_ALTERNATIVE_ID,
      previews: { [DESIGN_ALTERNATIVE_ID]: { kind: "document", html: HTML } },
      distance: designDistanceReport(DIRECTED_DESIGN_VERSION, { verdict: "CLOSE" }),
      notes: { [SECOND_DESIGN_ALTERNATIVE_ID]: "The mockup does not show REQ-004 yet." },
    });
    for (const details of cards.findAll("details")) {
      details.element.setAttribute("open", "");
    }
    await expectAccessible(cards.element, { iframes: false });
  });
});
