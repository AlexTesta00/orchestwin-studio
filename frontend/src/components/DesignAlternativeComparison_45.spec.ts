import { createPinia, setActivePinia } from "pinia";
import { mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  DIRECTED_DESIGN_PACKAGE,
  DIRECTED_DESIGN_VERSION,
  designDistanceReport,
} from "../test/designFixtures";
import { expectAccessible } from "@/test/axe";
import type { DesignAlternativePayload, VisualDirection } from "../types/design";
import type { DesignDistanceReportPayload } from "../types/designDistance";
import DesignAlternativeComparison from "./DesignAlternativeComparison.vue";

const SYSTEM_ALTERNATIVE_ID = "00000000-0000-4000-8000-000000000145";
const TIMETABLE = DIRECTED_DESIGN_PACKAGE.alternatives[0]!;
const LEDGER = DIRECTED_DESIGN_PACKAGE.alternatives[1]!;

const APPLE_DIRECTION: VisualDirection = {
  name: "Apple Human Interface Guidelines",
  concept:
    "The desk looks like an app of the system: clear panels on a light grey ground, one tinted action and generous touch targets.",
  rules: [
    "Content sits on white rounded panels over a light grey background.",
    "Colour marks only the main action and the selected state.",
    "Every control is at least 44 points tall.",
  ],
  axes: {
    layout: "PANELS",
    shape: "SOFT_FILL",
    type: "EVEN",
    colour: "ACCENT_ONLY",
    density: "COMFORTABLE",
  },
  typicality: 50,
  candidates: 2,
  vocabulary_version: 1,
};

function systemAlternative(designSystem?: string | null): DesignAlternativePayload {
  const visual = LEDGER.visual_language!;
  return {
    ...LEDGER,
    id: SYSTEM_ALTERNATIVE_ID,
    code: "DES-003",
    title: "System desk",
    summary: "Arrivals on clear panels, like an app of the system.",
    visual_language:
      designSystem === undefined
        ? { ...visual, direction: APPLE_DIRECTION }
        : { ...visual, direction: APPLE_DIRECTION, design_system: designSystem },
  };
}

const THREE: DesignAlternativePayload[] = [TIMETABLE, LEDGER, systemAlternative("apple-hig")];

function threeWayReport(): DesignDistanceReportPayload {
  const report = designDistanceReport(DIRECTED_DESIGN_VERSION);
  const pair = report.pairs[0]!;
  return {
    ...report,
    pairs: [
      pair,
      { ...pair, first: "DES-001", second: "DES-003" },
      { ...pair, first: "DES-002", second: "DES-003", verdict: "CLOSE" },
    ],
    alternatives: [
      ...report.alternatives,
      {
        code: "DES-003",
        direction: APPLE_DIRECTION.name,
        adherence: { available: true, axes: { layout: "FOLLOWED", shape: "FOLLOWED" } },
      },
    ],
  };
}

let wrapper: VueWrapper | null = null;

function mountCards(
  props: Partial<InstanceType<typeof DesignAlternativeComparison>["$props"]> = {},
) {
  wrapper = mount(DesignAlternativeComparison, {
    props: { alternatives: THREE, ...props },
  });
  return wrapper;
}

function card(target: VueWrapper, code: string) {
  return target.get(`[data-test="alternative-${code}"]`);
}

function originOf(target: VueWrapper, code: string): string {
  return card(target, code).get('[data-testid="alternative-direction-origin"]').text();
}

describe("DesignAlternativeComparison with three alternatives", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  afterEach(() => {
    wrapper?.unmount();
    wrapper = null;
  });

  it.each([
    ["en", "Apple guidelines"],
    ["it", "Linee guida Apple"],
  ] as const)(
    "shows a card for each of the three alternatives and labels only the one of the Apple guidelines (%s)",
    (locale, label) => {
      const cards = mountCards({ locale });
      expect(
        cards
          .findAll('[data-testid="design-alternative"]')
          .map((item) => item.attributes("data-test")),
      ).toEqual(["alternative-DES-001", "alternative-DES-002", "alternative-DES-003"]);
      const labels = cards.findAll('[data-testid="alternative-system"]');
      expect(labels).toHaveLength(1);
      expect(labels[0]!.text()).toBe(label);
      expect(card(cards, "DES-003").find('[data-testid="alternative-system"]').exists()).toBe(true);
      expect(card(cards, "DES-003").get("h3").text()).toBe("System desk");
      expect(cards.text()).not.toContain("apple-hig");
    },
  );

  it("says that the direction of the Apple alternative comes from the design system and the other two from the model", async () => {
    const cards = mountCards();
    expect(originOf(cards, "DES-003")).toBe(
      "Direction of the Apple Human Interface Guidelines design system.",
    );
    expect(originOf(cards, "DES-002")).toBe(
      "Proposed by the model among 5 candidates; chosen by the Studio because it is far from the others.",
    );
    expect(card(cards, "DES-003").get('[data-testid="alternative-direction"] p').text()).toBe(
      "Visual direction: Apple Human Interface Guidelines",
    );
    expect(cards.text()).not.toContain("among 2 candidates");

    await cards.setProps({ locale: "it" });
    expect(originOf(cards, "DES-003")).toBe(
      "Direzione del sistema di design Apple Human Interface Guidelines.",
    );
    expect(originOf(cards, "DES-001")).toBe(
      "Proposta dal modello fra 5 candidate; scelta dallo Studio perché lontana dalle altre.",
    );
    expect(cards.text()).not.toContain("fra 2 candidate");
  });

  it.each([undefined, null, "material", "constructor"])(
    "shows no label and the usual origin without a known design system (%s)",
    (designSystem) => {
      const cards = mountCards({
        alternatives: [TIMETABLE, LEDGER, systemAlternative(designSystem)],
      });
      expect(cards.find('[data-testid="alternative-system"]').exists()).toBe(false);
      expect(originOf(cards, "DES-003")).toBe(
        "Proposed by the model among 2 candidates; chosen by the Studio because it is far from the others.",
      );
    },
  );

  it("emits the choice of the third alternative and lets the owner try its mockup", async () => {
    const cards = mountCards({ locale: "it" });
    const choose = card(cards, "DES-003").get('[data-testid="alternative-choose"]');
    expect(choose.attributes("aria-label")).toBe("Scegli DES-003 · System desk");
    await choose.trigger("click");
    await card(cards, "DES-003").get('[data-testid="alternative-open"]').trigger("click");
    expect(cards.emitted("select")).toEqual([[SYSTEM_ALTERNATIVE_ID]]);
    expect(cards.emitted("open")).toEqual([[SYSTEM_ALTERNATIVE_ID]]);
  });

  it("names the two codes of every pair when the three alternatives are measured", () => {
    const cards = mountCards({ distance: threeWayReport() });
    const blocks = cards.findAll('[data-testid="design-distance"]');
    expect(blocks.map((block) => block.get("h3").text())).toEqual([
      "Distance between the alternatives · DES-001 · DES-002",
      "Distance between the alternatives · DES-001 · DES-003",
      "Distance between the alternatives · DES-002 · DES-003",
    ]);
    expect(blocks.map((block) => block.attributes("data-verdict"))).toEqual([
      "FAR",
      "FAR",
      "CLOSE",
    ]);
    expect(blocks[2]!.get('[data-testid="design-distance-close"]').text()).toBe(
      "Alternatives DES-002 and DES-003 look alike in the drawn style. You can regenerate them.",
    );
  });

  it("has no axe violations with the three cards, the label and the details open", async () => {
    const cards = mountCards({ locale: "it", distance: threeWayReport() });
    for (const details of cards.findAll("details")) {
      details.element.setAttribute("open", "");
    }
    await expectAccessible(cards.element, { iframes: false });
  });
});
