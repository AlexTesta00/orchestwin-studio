import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import { createAppI18n } from "@/i18n";
import UiBrandMark from "./UiBrandMark.vue";
import UiButton from "./UiButton.vue";
import UiCard from "./UiCard.vue";
import UiClaimLabel from "./UiClaimLabel.vue";
import UiStateBlock from "./UiStateBlock.vue";
import UiStatusChip from "./UiStatusChip.vue";

function plugins(locale: "en" | "it" = "en") {
  return { global: { plugins: [createAppI18n(locale)] } };
}

describe("design primitives", () => {
  it("renders the eight-point brand mark with an accessible name", () => {
    const wrapper = mount(UiBrandMark, { props: { size: 24 } });
    expect(wrapper.findAll("circle")).toHaveLength(8);
    expect(wrapper.get("svg").attributes("aria-label")).toBe("OrchesTwin");
    expect(wrapper.get("circle").attributes("r")).toBe("4.4");
  });

  it("styles buttons by variant and keeps disabled buttons readable without opacity", () => {
    const primary = mount(UiButton, { slots: { default: "Go" } });
    expect(primary.get("button").classes()).toContain("bg-action");
    expect(primary.get("button").attributes("type")).toBe("button");
    const danger = mount(UiButton, { props: { variant: "danger", disabled: true, full: true } });
    expect(danger.get("button").classes()).toContain("bg-fail-strong");
    expect(danger.get("button").classes()).toContain("w-full");
    expect(danger.get("button").attributes("disabled")).toBeDefined();
    expect(danger.get("button").classes().join(" ")).not.toContain("opacity");
  });

  it("gives cards the tone requested", () => {
    const wrapper = mount(UiCard, { props: { tone: "hypothesis" }, slots: { default: "text" } });
    expect(wrapper.classes()).toContain("bg-hypothesis-bg");
    expect(wrapper.text()).toBe("text");
  });

  it("pairs every status with a sign and a translated word", () => {
    const approved = mount(UiStatusChip, { props: { status: "approved" }, ...plugins("it") });
    expect(approved.text()).toContain("✓");
    expect(approved.text()).toContain("Approvato");
    const pending = mount(UiStatusChip, {
      props: { status: "pending", label: "Custom" },
      ...plugins(),
    });
    expect(pending.text()).toContain("Custom");
    expect(pending.classes()).toContain("text-ink-3");
  });

  it("distinguishes hypothesis from proof with an empty or filled dot", () => {
    const hypothesis = mount(UiClaimLabel, { props: { kind: "hypothesis" }, ...plugins("it") });
    expect(hypothesis.text()).toBe("Proposta dell'AI, non validata");
    expect(hypothesis.get("span[aria-hidden]").classes()).toContain("bg-transparent");
    const proof = mount(UiClaimLabel, { props: { kind: "proof" }, ...plugins() });
    expect(proof.text()).toBe("Observed in the sandbox");
    expect(proof.get("span[aria-hidden]").classes()).toContain("bg-proof");
  });

  it("announces loading and error states with the right roles", () => {
    const loading = mount(UiStateBlock, { props: { kind: "loading" }, ...plugins("it") });
    expect(loading.attributes("role")).toBe("status");
    expect(loading.attributes("aria-live")).toBe("polite");
    expect(loading.text()).toContain("Caricamento in corso");
    const error = mount(UiStateBlock, {
      props: { kind: "error", title: "Failed", text: "Try again from the step." },
      slots: { default: "<button>Retry</button>" },
      ...plugins(),
    });
    expect(error.attributes("role")).toBe("alert");
    expect(error.text()).toContain("Try again from the step.");
    expect(error.find("button").exists()).toBe(true);
  });
});
