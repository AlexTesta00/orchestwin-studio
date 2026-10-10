import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import { expectAccessible } from "@/test/axe";
import { whyNode } from "@/test/whyFixtures";
import type { WhyNode } from "@/types/why";
import ArtifactWhyNode from "./ArtifactWhyNode.vue";

type Direction = NonNullable<WhyNode["declared_context"]["direction"]>;

const direction: Direction = {
  name: "Apple Human Interface Guidelines",
  concept: "Pannelli chiari su un fondo grigio chiaro.",
  axes: {
    layout: "PANELS",
    shape: "SOFT_FILL",
    type: "EVEN",
    colour: "ACCENT_ONLY",
    density: "COMFORTABLE",
  },
  candidates: 2,
  origin: "MODEL",
  selected_by: "STUDIO",
};

const origins = {
  it: {
    system: "Direzione del sistema di design Apple Human Interface Guidelines.",
    model: "Proposta dal modello fra 2 candidate; scelta dallo Studio perché lontana dall'altra.",
  },
  en: {
    system: "Direction of the Apple Human Interface Guidelines design system.",
    model:
      "Proposed by the model among 2 candidates; chosen by the Studio because it is far from the other.",
  },
} as const;

function alternative(value: Direction): WhyNode {
  return whyNode({
    key: "DESIGN_ALTERNATIVE:alternative:3:alternative-hash",
    code: "DES-003",
    kind: "DESIGN_ALTERNATIVE",
    title: "Pannelli chiari",
    reference: { artifact_id: "alternative", version_number: 3, content_hash: "alternative-hash" },
    declared_context: { perspectives: [], direction: value },
  });
}

function origin(value: Direction, locale: "it" | "en"): string {
  const wrapper = mount(ArtifactWhyNode, { props: { node: alternative(value), locale } });
  const text = wrapper.get('[data-testid="why-direction-origin"]').text();
  wrapper.unmount();
  return text;
}

describe("design system of a direction in Why in sprint 45", () => {
  it.each(["it", "en"] as const)(
    "says in %s that the direction comes from the Apple design system",
    async (locale) => {
      const node = alternative({ ...direction, design_system: "apple-hig" });
      const original = structuredClone(node);
      const wrapper = mount(ArtifactWhyNode, { props: { node, locale } });
      const block = wrapper.get('[data-testid="why-direction"]');
      expect(block.get('[data-testid="why-direction-origin"]').text()).toBe(origins[locale].system);
      expect(wrapper.text()).not.toContain(origins[locale].model);
      expect(wrapper.html()).not.toContain("apple-hig");
      expect(node).toEqual(original);
      await expectAccessible(wrapper.element);
      wrapper.unmount();
    },
  );

  it.each(["it", "en"] as const)(
    "keeps the %s origin of the model without a known design system",
    (locale) => {
      const values: Direction[] = [
        direction,
        { ...direction, design_system: null },
        { ...direction, design_system: "" },
        { ...direction, design_system: "material" },
        { ...direction, design_system: "toString" },
      ];
      for (const value of values) {
        expect(origin(value, locale)).toBe(origins[locale].model);
      }
    },
  );

  it.each(["it", "en"] as const)("changes only the %s origin line of the direction", (locale) => {
    const plain = mount(ArtifactWhyNode, { props: { node: alternative(direction), locale } });
    const system = mount(ArtifactWhyNode, {
      props: { node: alternative({ ...direction, design_system: "apple-hig" }), locale },
    });
    expect(system.html()).not.toBe(plain.html());
    expect(system.html().replace(origins[locale].system, origins[locale].model)).toBe(plain.html());
    plain.unmount();
    system.unmount();
  });
});
