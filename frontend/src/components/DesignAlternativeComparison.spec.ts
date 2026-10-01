import { createPinia, setActivePinia } from "pinia";
import { mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  BASE_DESIGN_PACKAGE,
  DESIGN_ALTERNATIVE_ID,
  SECOND_DESIGN_ALTERNATIVE_ID,
} from "../test/designFixtures";
import { expectAccessible } from "@/test/axe";
import type { DesignAlternativePayload, UserTwinVersionReferencePayload } from "../types/design";
import DesignAlternativeComparison, {
  type AlternativePreview,
  MOCKUP_READ_FAILURE,
} from "./DesignAlternativeComparison.vue";
import GeneratedMockupFrame from "./GeneratedMockupFrame.vue";
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
});
