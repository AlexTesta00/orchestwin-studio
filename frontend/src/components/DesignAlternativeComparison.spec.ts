import { createPinia, setActivePinia } from "pinia";
import { mount, type DOMWrapper, type VueWrapper } from "@vue/test-utils";
import { beforeEach, describe, expect, it } from "vitest";

import {
  BASE_DESIGN_PACKAGE,
  DESIGN_ALTERNATIVE_ID,
  DESIGN_PROJECT_ID,
  SECOND_DESIGN_ALTERNATIVE_ID,
} from "../test/designFixtures";
import type {
  DesignAlternativePayload,
  SyntheticDesignCritiquePayload,
  UserTwinVersionReferencePayload,
} from "../types/design";
import DesignAlternativeComparison from "./DesignAlternativeComparison.vue";
import InsightApplyMenu from "./InsightApplyMenu.vue";
import { expectAccessible } from "@/test/axe";

const RECEPTIONIST = BASE_DESIGN_PACKAGE.grounding.user_twin_references[0]!;
const AUDITOR: UserTwinVersionReferencePayload = {
  twin_id: "00000000-0000-4000-8000-000000000114",
  version_number: 2,
  content_hash: "9".repeat(64),
  name: "Night Auditor Twin",
};
const GUIDED_CRITIQUE = BASE_DESIGN_PACKAGE.critiques[0]!;
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

const AUDITOR_CRITIQUE: SyntheticDesignCritiquePayload = {
  ...GUIDED_CRITIQUE,
  id: "00000000-0000-4000-8000-000000000141",
  code: "CRQ-002",
  design_alternative_id: SECOND_DESIGN_ALTERNATIVE_ID,
  user_twin_reference: AUDITOR,
  strengths: ["Night totals are easy to reconcile."],
  concerns: ["The bright palette tires the eyes at night."],
  unmet_needs: [],
  accessibility_observations: [],
  trust_concerns: [],
  questions: [],
  suggested_changes: [],
  confidence: 0.4,
  rationale: "The overview helps the audit, though the palette is bright for the night shift.",
};

const RECEPTIONIST_CRITIQUE: SyntheticDesignCritiquePayload = {
  ...GUIDED_CRITIQUE,
  id: "00000000-0000-4000-8000-000000000142",
  code: "CRQ-003",
  design_alternative_id: SECOND_DESIGN_ALTERNATIVE_ID,
  strengths: ["Availability stays visible at a glance.", "Frequent actions are one click away."],
  concerns: ["Dense tiles may hide the next arrival.", "The side rail competes with the queue."],
  unmet_needs: ["A quick way to flag guests who need assistance."],
  accessibility_observations: ["Status colours need a text label."],
  trust_concerns: ["Automatic updates may surprise the desk."],
  questions: ["How many tiles fit a small reception screen?"],
  suggested_changes: ["Pin the next arrival above the tiles."],
  confidence: 0.72,
  rationale: "The dashboard matches how the desk scans the day, but its density needs care.",
};

const CRITIQUES = [GUIDED_CRITIQUE, AUDITOR_CRITIQUE, RECEPTIONIST_CRITIQUE];
const OPINION_TEXTS = [
  RECEPTIONIST_FIT,
  AUDITOR_FIT,
  ...[GUIDED_CRITIQUE, AUDITOR_CRITIQUE, RECEPTIONIST_CRITIQUE].flatMap((critique) => [
    critique.rationale,
    ...critique.strengths,
    ...critique.concerns,
    ...critique.unmet_needs,
    ...critique.accessibility_observations,
    ...critique.trust_concerns,
    ...critique.questions,
    ...critique.suggested_changes,
  ]),
];

function layoutOf(wrapper: VueWrapper, code: string): string[] | null {
  const row = wrapper
    .get(`[data-test="alternative-${code}"]`)
    .find('[data-testid="alternative-layout"]');
  return row.exists() ? [row.get("dt").text(), row.get("dd").text()] : null;
}

function mountOpinions(
  props: {
    twins?: UserTwinVersionReferencePayload[];
    projectId?: string;
    locale?: "en" | "it";
  } = {},
) {
  return mount(DesignAlternativeComparison, {
    props: {
      alternatives: ALTERNATIVES,
      critiques: CRITIQUES,
      twins: [RECEPTIONIST, AUDITOR],
      ...props,
    },
  });
}

function opinionsOf(wrapper: VueWrapper, code: string): DOMWrapper<Element>[] {
  return wrapper
    .get(`[data-test="alternative-${code}"]`)
    .findAll('[data-testid="twin-opinions"] [data-testid="twin-opinion"]');
}

function listOf(card: DOMWrapper<Element>, key: string): string[] {
  return card
    .get(`[data-testid="twin-opinion-${key}"]`)
    .findAll("li")
    .map((item) => item.text());
}

function labelsOf(card: DOMWrapper<Element>): string[] {
  return card.findAll("h6").map((heading) => heading.text());
}

function occurrences(text: string, value: string): number {
  return text.split(value).length - 1;
}

describe("DesignAlternativeComparison", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("renders provider recommendations and explicit synthetic-feedback safeguards", () => {
    const wrapper = mount(DesignAlternativeComparison, {
      props: {
        alternatives: BASE_DESIGN_PACKAGE.alternatives,
        critiques: BASE_DESIGN_PACKAGE.critiques,
        recommendedAlternativeId: DESIGN_ALTERNATIVE_ID,
        selectedAlternativeId: null,
      },
    });

    expect(wrapper.text()).toContain("Provider recommendation");
    expect(wrapper.text()).toContain("simulated feedback and design hypotheses");
    expect(wrapper.text()).toContain("MODEL_INFERRED");
    expect(wrapper.text()).toContain("REQUIRED");
    expect(wrapper.findAll('[data-testid="design-style-tile"]')).toHaveLength(1);
    expect(wrapper.get('[data-testid="style-product-name"]').text()).toBe("Reservation desk");
  });

  it("emits the exact alternative selected by the owner", async () => {
    const wrapper = mount(DesignAlternativeComparison, {
      props: {
        alternatives: BASE_DESIGN_PACKAGE.alternatives,
        critiques: BASE_DESIGN_PACKAGE.critiques,
      },
    });

    await wrapper
      .get(`input[data-alternative-id="${SECOND_DESIGN_ALTERNATIVE_ID}"]`)
      .setValue(true);

    expect(wrapper.emitted("select")).toEqual([[SECOND_DESIGN_ALTERNATIVE_ID]]);
  });

  it("shows the layout archetype, a stored approach as before, or no row at all", async () => {
    const wrapper = mount(DesignAlternativeComparison, {
      props: { alternatives: BASE_DESIGN_PACKAGE.alternatives, critiques: [] },
    });

    expect(layoutOf(wrapper, "DES-001")).toEqual(["Approach", "GUIDED_WORKFLOW"]);
    expect(layoutOf(wrapper, "DES-002")).toEqual(["Layout", "Dashboard"]);

    await wrapper.setProps({ locale: "it" });

    expect(layoutOf(wrapper, "DES-001")).toEqual(["Approccio", "GUIDED_WORKFLOW"]);
    expect(layoutOf(wrapper, "DES-002")).toEqual(["Impostazione", "Cruscotto"]);

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
    await wrapper.setProps({ alternatives: variants });

    expect(layoutOf(wrapper, "DES-001")).toBeNull();
    expect(layoutOf(wrapper, "DES-002")).toEqual(["Impostazione", "Elenco e dettaglio"]);

    await wrapper.setProps({ locale: "en" });

    expect(layoutOf(wrapper, "DES-002")).toEqual(["Layout", "List and detail"]);
    expect(wrapper.text()).not.toContain("DASHBOARD_FIRST");
  });

  it("shows what every twin thinks of each alternative in the order of the grounding", async () => {
    const wrapper = mountOpinions();
    const section = wrapper.get('[data-test="alternative-DES-002"] [data-testid="twin-opinions"]');

    expect(section.get("h4").text()).toBe("What the twins think: Reservation operations dashboard");
    const [receptionist, auditor] = opinionsOf(wrapper, "DES-002");
    expect(opinionsOf(wrapper, "DES-002").map((card) => card.attributes("data-twin-id"))).toEqual([
      RECEPTIONIST.twin_id,
      AUDITOR.twin_id,
    ]);
    expect(receptionist!.get('[data-testid="twin-identity"]').text()).toContain(
      "Receptionist Twin",
    );
    expect(auditor!.get('[data-testid="twin-identity"]').text()).toContain("Night Auditor Twin");

    expect(labelsOf(receptionist!)).toEqual([
      "How this design serves them",
      "Strengths",
      "Concerns",
      "Unmet needs",
      "Accessibility",
      "Trust",
      "Open questions",
      "Suggested changes",
    ]);
    expect(receptionist!.get('[data-testid="twin-opinion-fit"] p').text()).toBe(RECEPTIONIST_FIT);
    expect(receptionist!.get('[data-testid="twin-opinion-rationale"]').text()).toBe(
      RECEPTIONIST_CRITIQUE.rationale,
    );
    expect(receptionist!.get('[data-testid="twin-opinion-confidence"]').text()).toBe(
      "Self-assessed confidence: 72%",
    );
    expect(listOf(receptionist!, "strengths")).toEqual(RECEPTIONIST_CRITIQUE.strengths);
    expect(listOf(receptionist!, "concerns")).toEqual(RECEPTIONIST_CRITIQUE.concerns);
    expect(listOf(receptionist!, "unmet_needs")).toEqual(RECEPTIONIST_CRITIQUE.unmet_needs);
    expect(listOf(receptionist!, "accessibility_observations")).toEqual(
      RECEPTIONIST_CRITIQUE.accessibility_observations,
    );
    expect(listOf(receptionist!, "trust_concerns")).toEqual(RECEPTIONIST_CRITIQUE.trust_concerns);
    expect(listOf(receptionist!, "questions")).toEqual(RECEPTIONIST_CRITIQUE.questions);
    expect(listOf(receptionist!, "suggested_changes")).toEqual(
      RECEPTIONIST_CRITIQUE.suggested_changes,
    );

    expect(labelsOf(auditor!)).toEqual(["How this design serves them", "Strengths", "Concerns"]);
    expect(auditor!.get('[data-testid="twin-opinion-fit"] p').text()).toBe(AUDITOR_FIT);
    expect(auditor!.get('[data-testid="twin-opinion-rationale"]').text()).toBe(
      AUDITOR_CRITIQUE.rationale,
    );
    expect(auditor!.get('[data-testid="twin-opinion-confidence"]').text()).toBe(
      "Self-assessed confidence: 40%",
    );
    for (const key of [
      "unmet_needs",
      "accessibility_observations",
      "trust_concerns",
      "questions",
      "suggested_changes",
    ]) {
      expect(auditor!.find(`[data-testid="twin-opinion-${key}"]`).exists()).toBe(false);
    }

    const [guided] = opinionsOf(wrapper, "DES-001");
    expect(opinionsOf(wrapper, "DES-001")).toHaveLength(1);
    expect(guided!.attributes("data-twin-id")).toBe(RECEPTIONIST.twin_id);
    expect(guided!.find('[data-testid="twin-opinion-fit"]').exists()).toBe(false);
    expect(labelsOf(guided!)).toEqual([
      "Strengths",
      "Concerns",
      "Accessibility",
      "Trust",
      "Open questions",
      "Suggested changes",
    ]);

    await wrapper.setProps({ locale: "it" });

    expect(section.get("h4").text()).toBe(
      "Cosa ne pensano i twin: Reservation operations dashboard",
    );
    expect(labelsOf(opinionsOf(wrapper, "DES-002")[0]!)).toEqual([
      "Come gli serve questo design",
      "Punti di forza",
      "Criticità",
      "Bisogni non coperti",
      "Accessibilità",
      "Fiducia",
      "Domande aperte",
      "Modifiche suggerite",
    ]);
    expect(
      opinionsOf(wrapper, "DES-002")[0]!.get('[data-testid="twin-opinion-confidence"]').text(),
    ).toBe("Confidenza auto-valutata: 72%");
  });

  it("follows the critiques without a grounding order and shows a fit without a critique", () => {
    const unordered = mountOpinions({ twins: [] });
    const fitOnly = mount(DesignAlternativeComparison, {
      props: {
        alternatives: BASE_DESIGN_PACKAGE.alternatives,
        critiques: BASE_DESIGN_PACKAGE.critiques,
      },
    });

    expect(opinionsOf(unordered, "DES-002").map((card) => card.attributes("data-twin-id"))).toEqual(
      [AUDITOR.twin_id, RECEPTIONIST.twin_id],
    );
    const [card] = opinionsOf(fitOnly, "DES-002");
    expect(opinionsOf(fitOnly, "DES-002")).toHaveLength(1);
    expect(card!.get('[data-testid="twin-opinion-fit"] p').text()).toBe(RECEPTIONIST_FIT);
    expect(card!.find('[data-testid="twin-opinion-rationale"]').exists()).toBe(false);
    expect(card!.find('[data-testid="twin-opinion-confidence"]').exists()).toBe(false);
    expect(labelsOf(card!)).toEqual(["How this design serves them"]);
    expect(
      mount(DesignAlternativeComparison, {
        props: { alternatives: [GUIDED], critiques: [] },
      })
        .find('[data-testid="twin-opinions"]')
        .exists(),
    ).toBe(false);
  });

  it("lets the owner bring every concern into the project and shows nothing twice", async () => {
    const wrapper = mountOpinions({ projectId: DESIGN_PROJECT_ID, locale: "it" });
    const [receptionist, auditor] = opinionsOf(wrapper, "DES-002");

    expect(
      receptionist!.findAll(
        '[data-testid="twin-opinion-concerns"] [data-testid="insight-apply-menu"]',
      ),
    ).toHaveLength(2);
    expect(receptionist!.findAll('[data-testid="insight-apply-menu"]')).toHaveLength(2);
    expect(auditor!.findAll('[data-testid="insight-apply-menu"]')).toHaveLength(1);
    const menus = wrapper.findAllComponents(InsightApplyMenu);
    expect(menus.map((menu) => menu.props("source"))).toEqual([
      {
        kind: "DESIGN_CRITIQUE",
        id: "CRQ-001:0",
        twinId: RECEPTIONIST.twin_id,
        text: GUIDED_CRITIQUE.concerns[0],
        mitigation: GUIDED_CRITIQUE.suggested_changes[0],
      },
      {
        kind: "DESIGN_CRITIQUE",
        id: "CRQ-003:0",
        twinId: RECEPTIONIST.twin_id,
        text: RECEPTIONIST_CRITIQUE.concerns[0],
        mitigation: RECEPTIONIST_CRITIQUE.suggested_changes[0],
      },
      {
        kind: "DESIGN_CRITIQUE",
        id: "CRQ-003:1",
        twinId: RECEPTIONIST.twin_id,
        text: RECEPTIONIST_CRITIQUE.concerns[1],
        mitigation: RECEPTIONIST_CRITIQUE.suggested_changes[0],
      },
      {
        kind: "DESIGN_CRITIQUE",
        id: "CRQ-002:0",
        twinId: AUDITOR.twin_id,
        text: AUDITOR_CRITIQUE.concerns[0],
        mitigation: null,
      },
    ]);
    expect(menus.every((menu) => menu.props("projectId") === DESIGN_PROJECT_ID)).toBe(true);
    expect(menus.every((menu) => menu.props("locale") === "it")).toBe(true);

    for (const code of ["DES-001", "DES-002"]) {
      const details = wrapper.get(
        `[data-test="alternative-${code}"] [data-testid="alternative-details"]`,
      );
      expect(details.find('[data-testid="twin-opinion"]').exists()).toBe(false);
      expect(details.find('[data-testid="insight-apply-menu"]').exists()).toBe(false);
      expect(details.text()).not.toContain("Confidenza auto-valutata");
      for (const text of OPINION_TEXTS) {
        expect(details.text()).not.toContain(text);
      }
    }
    for (const text of OPINION_TEXTS) {
      expect(occurrences(wrapper.text(), text)).toBeGreaterThan(0);
    }
    expect(occurrences(wrapper.text(), RECEPTIONIST_FIT)).toBe(1);
    expect(occurrences(wrapper.text(), RECEPTIONIST_CRITIQUE.rationale)).toBe(1);
    expect(
      occurrences(
        wrapper.text(),
        "Le critiche dei User Twin sono feedback simulato e ipotesi progettuali.",
      ),
    ).toBe(1);
    expect(wrapper.find('[data-testid="style-twin-fit"]').exists()).toBe(false);

    const provenance = wrapper.get(
      '[data-test="alternative-DES-002"] [data-testid="critique-provenance"]',
    );
    expect(provenance.get("h4").text()).toBe("Provenienza delle critiche");
    expect(provenance.text()).toContain("CRQ-002 · Night Auditor Twin");
    expect(provenance.text()).toContain("CRQ-003 · Receptionist Twin");
    expect(provenance.text()).toContain("MODEL_INFERRED · REQUIRED");
    expect(provenance.text()).toContain("MODEL_OUTPUT · fake-deterministic-design");

    await expectAccessible(wrapper.element);
  });

  it("has no axe violations", async () => {
    const wrapper = mount(DesignAlternativeComparison, {
      props: {
        alternatives: BASE_DESIGN_PACKAGE.alternatives,
        critiques: BASE_DESIGN_PACKAGE.critiques,
        recommendedAlternativeId: DESIGN_ALTERNATIVE_ID,
        selectedAlternativeId: DESIGN_ALTERNATIVE_ID,
      },
    });
    await expectAccessible(wrapper.element);
  });
});
