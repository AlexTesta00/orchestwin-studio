import { mount } from "@vue/test-utils";
import { h } from "vue";
import { describe, expect, it } from "vitest";

import { expectAccessible } from "@/test/axe";
import UiSurface from "./UiSurface.vue";
import UserModelingEpistemicBadge from "./UserModelingEpistemicBadge.vue";

describe("UserModelingEpistemicBadge", () => {
  it("names the status, the confidence and whether a person must verify the information", async () => {
    const wrapper = mount(UserModelingEpistemicBadge, {
      props: { status: "MODEL_INFERRED", confidence: 0.424, humanValidation: "REQUIRED" },
    });

    expect(wrapper.get('[data-testid="epistemic-status"]').text()).toBe("Inferred");
    expect(wrapper.text()).toContain("Confidence 42%");
    const bar = wrapper.get('[role="progressbar"]');
    expect(bar.attributes("aria-valuenow")).toBe("42");
    expect(bar.attributes("aria-label")).toBe("Confidence: 42%");
    expect(wrapper.get('[data-testid="human-validation"]').text()).toBe(
      "Human validation required",
    );
    await expectAccessible(wrapper.element);
  });

  it("keeps the confidence between zero and one hundred and speaks Italian", () => {
    const wrapper = mount(UserModelingEpistemicBadge, {
      props: {
        status: "USER_PROVIDED",
        confidence: 1.7,
        humanValidation: "NOT_REQUIRED",
        locale: "it",
      },
    });

    expect(wrapper.get('[data-testid="epistemic-status"]').text()).toBe("Ipotizzato");
    expect(wrapper.text()).toContain("Confidenza 100%");
    expect(wrapper.get('[data-testid="human-validation"]').text()).toBe(
      "Nessuna validazione aggiuntiva richiesta",
    );
  });

  it("draws a hypothesis with a dashed violet chip on a dark surface", () => {
    const wrapper = mount(UiSurface, {
      slots: {
        default: () =>
          h(UserModelingEpistemicBadge, {
            status: "MODEL_INFERRED",
            confidence: 0.5,
            humanValidation: "REQUIRED",
          }),
      },
    });

    const chip = wrapper.get('[data-testid="epistemic-status"]');
    expect(chip.classes()).toEqual(
      expect.arrayContaining(["border-dashed", "border-violet-on-night", "text-violet-on-night-2"]),
    );
  });
});
