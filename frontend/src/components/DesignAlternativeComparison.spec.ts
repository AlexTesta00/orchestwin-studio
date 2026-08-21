import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import {
  BASE_DESIGN_PACKAGE,
  DESIGN_ALTERNATIVE_ID,
  SECOND_DESIGN_ALTERNATIVE_ID,
} from "../test/designFixtures";
import DesignAlternativeComparison from "./DesignAlternativeComparison.vue";

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
});
