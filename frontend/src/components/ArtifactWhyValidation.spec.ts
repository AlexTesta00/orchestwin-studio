import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import ArtifactWhyNode from "./ArtifactWhyNode.vue";
import { validationOutcome } from "../test/humanValidationFixtures";
import { whyNode } from "../test/whyFixtures";
import { whyNodeTitle, whyRelationLabel } from "./whyCopy";

describe("Validation in Why", () => {
  it.each(["it", "en"] as const)(
    "shows a %s session quote with its provenance without calling it support for a claim",
    (locale) => {
      const outcome = validationOutcome({
        effective_status: "RETIRED",
        source_text_available: false,
      });
      const node = whyNode({
        kind: "VALIDATION_OUTCOME",
        title: "UNCERTAIN",
        declared_context: { perspectives: [], outcome, effective_status: "RETIRED" },
        citations: [
          {
            citation: outcome.citation,
            status: "RETIRED",
            session_kind: "SYNTHETIC_EXERCISE",
            source: { title: "Synthetic source", text_available: false },
          },
        ],
      });
      const wrapper = mount(ArtifactWhyNode, { props: { node, locale } });
      expect(wrapper.text()).toContain(locale === "it" ? "Incerta" : "Uncertain");
      expect(wrapper.text()).toContain(
        locale === "it" ? "Prova sintetica, non empirica" : "Synthetic exercise, not empirical",
      );
      expect(wrapper.text()).toContain(locale === "it" ? "Esito ritirato" : "Retired outcome");
      expect(wrapper.text()).not.toContain(
        locale === "it" ? "Sostiene questo claim" : "Supports this claim",
      );
      expect(wrapper.find('[data-testid="epistemic-badge"]').exists()).toBe(false);
      expect(wrapper.get('[data-testid="why-quote"]').element.textContent?.trimStart()).toBe(
        outcome.citation.quote.trimStart(),
      );
      expect(whyNodeTitle(node, locale)).toBe(locale === "it" ? "Incerta" : "Uncertain");
      expect(whyRelationLabel("TESTS_HYPOTHESIS", locale)).toBe(
        locale === "it" ? "Verifica l'ipotesi" : "Tests the hypothesis",
      );
      expect(whyRelationLabel("RECORDED_IN", locale)).toBe(
        locale === "it" ? "È registrato nella fonte" : "Is recorded in the source",
      );
    },
  );
});
