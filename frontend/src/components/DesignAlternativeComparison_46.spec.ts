import { createPinia, setActivePinia } from "pinia";
import { mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  DIRECTED_DESIGN_PACKAGE,
  DIRECTED_DESIGN_VERSION,
  designDistanceReport,
} from "../test/designFixtures";
import type { DesignAlternativePayload } from "../types/design";
import type { DesignDistanceReportPayload } from "../types/designDistance";
import DesignAlternativeComparison from "./DesignAlternativeComparison.vue";

const TIMETABLE = DIRECTED_DESIGN_PACKAGE.alternatives[0]!;
const LEDGER = DIRECTED_DESIGN_PACKAGE.alternatives[1]!;
const THIRD: DesignAlternativePayload = {
  ...LEDGER,
  id: "00000000-0000-4000-8000-000000000146",
  code: "DES-003",
  title: "Third desk",
};

function closeReport(): DesignDistanceReportPayload {
  const report = designDistanceReport(DIRECTED_DESIGN_VERSION, { verdict: "CLOSE" });
  const pair = report.pairs[0]!;
  return {
    ...report,
    pairs: [pair, { ...pair, second: "DES-003" }, { ...pair, first: "DES-002", second: "DES-003" }],
  };
}

let wrapper: VueWrapper | null = null;

function warnings(target: VueWrapper): string[] {
  return target.findAll('[data-testid="design-distance-close"]').map((item) => item.text());
}

function originOf(target: VueWrapper, code: string): string {
  return target
    .get(`[data-test="alternative-${code}"] [data-testid="alternative-direction-origin"]`)
    .text();
}

describe("DesignAlternativeComparison with three alternatives that look alike", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  afterEach(() => {
    wrapper?.unmount();
    wrapper = null;
  });

  it("names in Italian the pair of every warning and goes back to the usual sentences with two alternatives", async () => {
    wrapper = mount(DesignAlternativeComparison, {
      props: { alternatives: [TIMETABLE, LEDGER, THIRD], distance: closeReport(), locale: "it" },
    });
    expect(warnings(wrapper)).toEqual([
      "Le alternative DES-001 e DES-002 si somigliano nello stile disegnato. Puoi rigenerarle.",
      "Le alternative DES-001 e DES-003 si somigliano nello stile disegnato. Puoi rigenerarle.",
      "Le alternative DES-002 e DES-003 si somigliano nello stile disegnato. Puoi rigenerarle.",
    ]);
    expect(originOf(wrapper, "DES-002")).toBe(
      "Proposta dal modello fra 5 candidate; scelta dallo Studio perché lontana dalle altre.",
    );

    await wrapper.setProps({ alternatives: [TIMETABLE, LEDGER] });
    expect(warnings(wrapper)).toEqual([
      "Le due alternative si somigliano nello stile disegnato. Puoi rigenerarle.",
    ]);
    expect(originOf(wrapper, "DES-002")).toBe(
      "Proposta dal modello fra 5 candidate; scelta dallo Studio perché lontana dall'altra.",
    );
  });
});
