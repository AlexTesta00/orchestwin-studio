import { mount, type VueWrapper } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import {
  BASE_DESIGN_PACKAGE,
  DESIGN_ALTERNATIVE_ID,
  SECOND_DESIGN_ALTERNATIVE_ID,
} from "../test/designFixtures";
import type { DesignAlternativePayload } from "../types/design";
import DesignAlternativeComparison from "./DesignAlternativeComparison.vue";
import { expectAccessible } from "@/test/axe";

function layoutOf(wrapper: VueWrapper, code: string): string[] | null {
  const row = wrapper
    .get(`[data-test="alternative-${code}"]`)
    .find('[data-testid="alternative-layout"]');
  return row.exists() ? [row.get("dt").text(), row.get("dd").text()] : null;
}

describe("DesignAlternativeComparison", () => {
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
