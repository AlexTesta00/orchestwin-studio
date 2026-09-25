import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import { BASE_DESIGN_PACKAGE } from "../test/designFixtures";
import DesignStyleTile from "./DesignStyleTile.vue";
import { expectAccessible } from "@/test/axe";

const VISUAL = BASE_DESIGN_PACKAGE.alternatives[1]!.visual_language!;

function rgb(hex: string): string {
  const value = Number.parseInt(hex.slice(1), 16);
  return `rgb(${(value >> 16) & 255}, ${(value >> 8) & 255}, ${value & 255})`;
}

describe("DesignStyleTile", () => {
  it("shows the product name, the archetype, the palette and the key choices", () => {
    const wrapper = mount(DesignStyleTile, { props: { visual: VISUAL, locale: "it" } });
    expect(wrapper.get('[data-testid="style-product-name"]').text()).toBe("Reservation desk");
    expect(wrapper.get('[data-testid="style-archetype"]').text()).toBe("Cruscotto");
    const swatches = wrapper.findAll("li[data-role]");
    expect(swatches.map((item) => item.attributes("data-role"))).toEqual([
      "background",
      "surface",
      "primary",
      "accent",
      "text",
      "success",
      "danger",
    ]);
    expect(swatches[2]!.attributes("style")).toContain(rgb(VISUAL.palette.primary!));
    expect(wrapper.text()).toContain("Light");
    expect(wrapper.text()).toContain("Calm");
    expect(wrapper.text()).toContain(VISUAL.rationale);
    expect(wrapper.get('[data-testid="style-twin-fit"]').text()).toContain(
      VISUAL.twin_fit[0]!.statement,
    );
    expect(wrapper.get('[data-testid="design-style-tile"]').attributes("style")).toContain(
      "--vl-color-primary",
    );
  });

  it("omits the sample and rationale when compact and has no axe violations", async () => {
    const wrapper = mount(DesignStyleTile, { props: { visual: VISUAL, compact: true } });
    expect(wrapper.text()).not.toContain(VISUAL.rationale);
    expect(wrapper.get('[data-testid="style-archetype"]').text()).toBe("Dashboard");
    await expectAccessible(wrapper.element);
  });
});
