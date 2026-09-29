import { mount } from "@vue/test-utils";
import { h } from "vue";
import { describe, expect, it } from "vitest";

import { createAppI18n } from "@/i18n";
import { expectAccessible } from "@/test/axe";
import UiClaimFrame from "./UiClaimFrame.vue";
import UiSurface from "./UiSurface.vue";

function plugins(locale: "en" | "it" = "it") {
  return { global: { plugins: [createAppI18n(locale)] } };
}

describe("claim frame", () => {
  it("draws a dashed violet frame around a hypothesis and says so in words", () => {
    const wrapper = mount(UiClaimFrame, {
      props: { status: "hypothesis" },
      slots: { default: "<p>Obiettivi del twin</p>" },
      ...plugins(),
    });
    expect(wrapper.attributes("data-claim-status")).toBe("hypothesis");
    expect(wrapper.classes()).toEqual(
      expect.arrayContaining(["border-dashed", "border-hypothesis/70", "rounded-field"]),
    );
    const words = wrapper.get("[data-claim-text]");
    expect(words.classes()).toContain("sr-only");
    expect(words.text()).toBe("Proposta dell'AI, non validata");
    expect(wrapper.text()).toContain("Obiettivi del twin");
  });

  it("draws a solid petrol frame around a confirmed content and a solid frame around evidence", () => {
    const confirmed = mount(UiClaimFrame, { props: { status: "confirmed" }, ...plugins("en") });
    expect(confirmed.classes()).toEqual(expect.arrayContaining(["border", "border-action"]));
    expect(confirmed.classes()).not.toContain("border-dashed");
    expect(confirmed.get("[data-claim-text]").text()).toBe("Confirmed by you");
    const evidence = mount(UiClaimFrame, { props: { status: "evidence" }, ...plugins("en") });
    expect(evidence.classes()).toEqual(expect.arrayContaining(["border", "border-ink"]));
    expect(evidence.get("[data-claim-text]").text()).toBe("Verified evidence");
  });

  it("can be a list item with a larger radius and no padding", () => {
    const wrapper = mount(
      {
        render: () =>
          h("ul", [
            h(UiClaimFrame, { status: "confirmed", as: "li", radius: "tile", padded: false }, () =>
              h("span", "Volontari"),
            ),
          ]),
      },
      plugins(),
    );
    const item = wrapper.get("li");
    expect(item.classes()).toContain("rounded-tile");
    expect(item.classes()).not.toContain("p-5");
    expect(item.text()).toContain("Volontari");
  });

  it("uses the colours for dark surfaces inside a dark surface", () => {
    const wrapper = mount(UiSurface, {
      slots: {
        default: () => [
          h(UiClaimFrame, { status: "hypothesis", "data-testid": "guess" }),
          h(UiClaimFrame, { status: "confirmed", "data-testid": "sure" }),
        ],
      },
      ...plugins(),
    });
    expect(wrapper.get("[data-testid='guess']").classes()).toContain("border-violet-on-night/70");
    expect(wrapper.get("[data-testid='sure']").classes()).toContain("border-petrol-on-night");
  });

  it("has no axe violations", async () => {
    const wrapper = mount(
      {
        render: () => [
          h(UiClaimFrame, { status: "hypothesis" }, () => h("p", "Ipotesi")),
          h(UiClaimFrame, { status: "confirmed", as: "article" }, () => h("p", "Confermato")),
          h(UiClaimFrame, { status: "evidence", as: "section" }, () => h("p", "Prova")),
        ],
      },
      plugins(),
    );
    await expectAccessible(wrapper.element);
  });
});
