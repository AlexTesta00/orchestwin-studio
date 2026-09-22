import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import { createAppI18n } from "@/i18n";
import UiDecisionCard from "./UiDecisionCard.vue";
import { expectAccessible } from "@/test/axe";

function mountCard(props: Record<string, unknown> = {}, locale: "en" | "it" = "it") {
  return mount(UiDecisionCard, {
    props: { decision: 2, max: 4, ...props },
    global: { plugins: [createAppI18n(locale)] },
  });
}

describe("human decision card", () => {
  it("shows the counter and emits an approval", async () => {
    const wrapper = mountCard();
    expect(wrapper.get("[data-testid='decision-counter']").text()).toBe("Decisione 2 di 4");
    await wrapper.get("[data-testid='approve']").trigger("click");
    expect(wrapper.emitted("approve")).toHaveLength(1);
  });

  it("requires a written reason before sending a rejection", async () => {
    const wrapper = mountCard();
    await wrapper.get("[data-testid='reject']").trigger("click");
    expect(wrapper.find("[data-testid='approve']").exists()).toBe(false);
    await wrapper.get("[data-testid='confirm-rejection']").trigger("click");
    expect(wrapper.get("[data-testid='note-error']").attributes("role")).toBe("alert");
    expect(wrapper.get("[data-testid='note-error']").text()).toBe(
      "Scrivi un motivo prima di inviare.",
    );
    expect(wrapper.emitted("reject")).toBeUndefined();
    await wrapper.get("[data-testid='rejection-note']").setValue("  Manca il campo data  ");
    await wrapper.get("[data-testid='confirm-rejection']").trigger("click");
    expect(wrapper.emitted("reject")).toEqual([["Manca il campo data"]]);
    expect(wrapper.find("[data-testid='approve']").exists()).toBe(true);
  });

  it("locks both actions until the step has material and explains why", () => {
    const wrapper = mountCard({ enabled: false }, "en");
    expect(wrapper.get("[data-testid='approve']").attributes("disabled")).toBeDefined();
    expect(wrapper.get("[data-testid='reject']").attributes("disabled")).toBeDefined();
    expect(wrapper.text()).toContain("The decision opens when the step has material to decide on.");
  });

  it("lists the decision history most recent first", () => {
    const wrapper = mountCard({
      history: [
        { n: 1, ok: false, note: "Troppo generico" },
        { n: 2, ok: true },
      ],
    });
    const rows = wrapper.get("[data-testid='decision-history']").findAll("li");
    expect(rows).toHaveLength(2);
    expect(rows[0]?.text()).toContain("Approvato");
    expect(rows[0]?.text()).toContain("Decisione 2 di 4");
    expect(rows[1]?.text()).toContain("Troppo generico");
  });

  it("has no axe violations", async () => {
    await expectAccessible(mountCard().element);
  });
});
