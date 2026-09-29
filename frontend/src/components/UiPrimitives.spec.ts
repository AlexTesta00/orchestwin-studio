import { mount } from "@vue/test-utils";
import { h, type VNode } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import { describe, expect, it } from "vitest";

import { createAppI18n } from "@/i18n";
import { expectAccessible } from "@/test/axe";
import UiBrandMark from "./UiBrandMark.vue";
import UiButton from "./UiButton.vue";
import UiCard from "./UiCard.vue";
import UiClaimLabel from "./UiClaimLabel.vue";
import UiStateBlock from "./UiStateBlock.vue";
import UiStatusChip from "./UiStatusChip.vue";
import UiSurface from "./UiSurface.vue";

function plugins(locale: "en" | "it" = "en") {
  return { global: { plugins: [createAppI18n(locale)] } };
}

function onNight(render: () => VNode | VNode[], locale: "en" | "it" = "it") {
  return mount(UiSurface, {
    props: { tone: "night" },
    slots: { default: render },
    ...plugins(locale),
  });
}

describe("design primitives", () => {
  it("renders the robot face with a screen and an accessible name", () => {
    const wrapper = mount(UiBrandMark, { props: { size: 24 } });
    const svg = wrapper.get("svg");
    expect(svg.attributes("role")).toBe("img");
    expect(svg.attributes("aria-label")).toBe("OrchesTwin");
    expect(svg.attributes("width")).toBe("24");
    expect(svg.attributes("height")).toBe("20");
    expect(wrapper.findAll("rect")).toHaveLength(4);
    expect(wrapper.findAll("rect")[0]?.classes()).toContain("fill-ink");
    expect(wrapper.find("[data-testid='brand-wordmark']").exists()).toBe(false);
  });

  it("adds the wordmark in the display font and hides the drawing from assistive technology", () => {
    const wrapper = mount(UiBrandMark, { props: { wordmark: true } });
    expect(wrapper.get("svg").attributes("aria-hidden")).toBe("true");
    expect(wrapper.get("svg").attributes("aria-label")).toBeUndefined();
    const words = wrapper.findAll("[data-testid='brand-wordmark'] span");
    expect(words.map((word) => word.text())).toEqual(["OrchesTwin", "Studio"]);
    expect(words[0]?.classes()).toContain("font-display");
    expect(words[1]?.classes()).toContain("font-mono");
  });

  it("inverts the robot face on a dark surface", () => {
    const wrapper = onNight(() => h(UiBrandMark, { wordmark: true }));
    expect(wrapper.findAll("rect")[0]?.classes()).toContain("fill-on-night");
    expect(wrapper.get("[data-testid='brand-wordmark'] span").classes()).toContain("text-on-night");
  });

  it("styles buttons by variant and keeps disabled buttons readable without opacity", () => {
    const primary = mount(UiButton, { slots: { default: "Go" } });
    expect(primary.get("button").classes()).toContain("bg-action");
    expect(primary.get("button").classes()).toContain("min-h-11");
    expect(primary.get("button").attributes("type")).toBe("button");
    const danger = mount(UiButton, { props: { variant: "danger", disabled: true, full: true } });
    expect(danger.get("button").classes()).toContain("bg-fail-strong");
    expect(danger.get("button").classes()).toContain("w-full");
    expect(danger.get("button").attributes("disabled")).toBeDefined();
    expect(danger.get("button").classes().join(" ")).not.toContain("opacity");
  });

  it("offers the pill, the outlined pill and a quiet button of the new design on a light page", () => {
    const pill = mount(UiButton, { props: { variant: "pill", size: "lg" } });
    expect(pill.get("button").classes()).toEqual(
      expect.arrayContaining(["rounded-pill", "bg-ink", "text-white", "min-h-[50px]"]),
    );
    const outline = mount(UiButton, { props: { variant: "outline" } });
    expect(outline.get("button").classes()).toEqual(
      expect.arrayContaining(["rounded-pill", "border", "border-ink/25", "text-ink"]),
    );
    const quiet = mount(UiButton, { props: { variant: "quiet" } });
    expect(quiet.get("button").classes()).toContain("text-ink-3");
    expect(quiet.get("button").classes().join(" ")).not.toContain("bg-action");
    expect(quiet.get("button").attributes("data-variant")).toBe("quiet");
  });

  it("makes the pill light and the outline light on a dark surface", () => {
    const wrapper = onNight(() => [
      h(UiButton, { variant: "pill", size: "lg", "data-testid": "pill" }, () => "Entra"),
      h(UiButton, { variant: "outline", "data-testid": "outline" }, () => "Cartella"),
    ]);
    expect(wrapper.get("[data-testid='pill']").classes()).toEqual(
      expect.arrayContaining(["rounded-pill", "bg-on-night", "text-ink", "min-h-[50px]"]),
    );
    expect(wrapper.get("[data-testid='outline']").classes()).toEqual(
      expect.arrayContaining(["rounded-pill", "border-on-night/32", "text-on-night"]),
    );
  });

  it("turns the main and secondary actions into pills on a dark surface", () => {
    const wrapper = onNight(() => [
      h(UiButton, { "data-testid": "main" }, () => "Approva"),
      h(UiButton, { variant: "secondary", "data-testid": "other" }, () => "Chiedi modifiche"),
      h(UiButton, { variant: "quiet", "data-testid": "quiet" }, () => "Annulla"),
      h(UiButton, { variant: "danger", "data-testid": "danger" }, () => "Rifiuta"),
      h(UiButton, { surface: "light", "data-testid": "forced" }, () => "Forzato"),
    ]);
    expect(wrapper.get("[data-testid='main']").classes()).toEqual(
      expect.arrayContaining(["rounded-pill", "bg-on-night", "text-ink"]),
    );
    expect(wrapper.get("[data-testid='other']").classes()).toContain("border-on-night/32");
    expect(wrapper.get("[data-testid='quiet']").classes()).toContain("text-on-night-3");
    expect(wrapper.get("[data-testid='danger']").classes()).toContain("text-fail-on-night");
    expect(wrapper.get("[data-testid='forced']").classes()).toContain("bg-action");
  });

  it("renders a link that looks like a button when it has a destination", async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/", component: { render: () => null } }],
    });
    await router.push("/");
    await router.isReady();
    const routed = mount(UiButton, {
      props: { to: "/", variant: "pill" },
      slots: { default: "Entra" },
      global: { plugins: [router] },
    });
    expect(routed.get("a").attributes("href")).toBe("/");
    expect(routed.get("a").classes()).toContain("rounded-pill");
    expect(routed.find("button").exists()).toBe(false);
    const anchor = mount(UiButton, {
      props: { href: "#percorso", variant: "outline" },
      slots: { default: "Scopri" },
    });
    expect(anchor.get("a").attributes("href")).toBe("#percorso");
    expect(anchor.get("a").attributes("type")).toBeUndefined();
  });

  it("gives cards the tone requested", () => {
    const wrapper = mount(UiCard, { props: { tone: "hypothesis" }, slots: { default: "text" } });
    expect(wrapper.classes()).toContain("bg-hypothesis-bg");
    expect(wrapper.classes()).toContain("border-dashed");
    expect(wrapper.text()).toBe("text");
  });

  it("turns cards into dark panels on a dark surface", () => {
    const wrapper = onNight(() => [
      h(UiCard, { "data-testid": "plain" }, () => "a"),
      h(UiCard, { tone: "hypothesis", "data-testid": "guess" }, () => "b"),
    ]);
    expect(wrapper.get("[data-testid='plain']").classes()).toEqual(
      expect.arrayContaining(["bg-night-raised", "border-night-line", "rounded-tile"]),
    );
    expect(wrapper.get("[data-testid='guess']").classes()).toContain("border-violet-on-night/70");
  });

  it("pairs every status with a mark and a translated word", () => {
    const approved = mount(UiStatusChip, { props: { status: "approved" }, ...plugins("it") });
    expect(approved.text()).toContain("Approvato");
    expect(approved.attributes("data-status")).toBe("approved");
    expect(approved.get("[data-status-dot]").attributes("aria-hidden")).toBe("true");
    expect(approved.get("[data-status-dot]").classes()).toContain("bg-action");
    const pending = mount(UiStatusChip, {
      props: { status: "pending", label: "Custom" },
      ...plugins(),
    });
    expect(pending.text()).toContain("Custom");
    expect(pending.classes()).toContain("text-ink-3");
    expect(pending.get("[data-status-dot]").classes()).toContain("border-ink-3");
  });

  it("uses the colours for dark surfaces inside a dark surface", () => {
    const wrapper = onNight(() => h(UiStatusChip, { status: "approved" }));
    const chip = wrapper.get("[data-status='approved']");
    expect(chip.classes()).toContain("text-petrol-on-night-2");
    expect(chip.text()).toContain("Approvato");
  });

  it("distinguishes hypothesis, confirmation and proof with an empty or filled dot", () => {
    const hypothesis = mount(UiClaimLabel, { props: { kind: "hypothesis" }, ...plugins("it") });
    expect(hypothesis.text()).toBe("Proposta dell'AI, non validata");
    expect(hypothesis.classes()).toContain("border-dashed");
    expect(hypothesis.get("span[aria-hidden]").classes()).toContain("bg-transparent");
    const confirmed = mount(UiClaimLabel, { props: { kind: "confirmed" }, ...plugins("it") });
    expect(confirmed.text()).toBe("Confermato da te");
    expect(confirmed.get("span[aria-hidden]").classes()).toContain("bg-action");
    const proof = mount(UiClaimLabel, { props: { kind: "proof" }, ...plugins() });
    expect(proof.text()).toBe("Verified evidence");
    expect(proof.classes()).toContain("bg-ink");
    expect(proof.get("span[aria-hidden]").classes()).toContain("bg-petrol-on-night-2");
  });

  it("keeps the hypothesis label dashed and violet on a dark surface", () => {
    const wrapper = onNight(() => h(UiClaimLabel, { kind: "hypothesis" }));
    const label = wrapper.get("[data-claim='hypothesis']");
    expect(label.classes()).toEqual(
      expect.arrayContaining(["border-dashed", "text-violet-on-night-2"]),
    );
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

  it("draws state blocks with the colours for dark surfaces inside a dark surface", () => {
    const wrapper = onNight(() => h(UiStateBlock, { kind: "error", title: "Errore" }));
    const block = wrapper.get("[data-state='error']");
    expect(block.attributes("role")).toBe("alert");
    expect(block.classes()).toContain("text-fail-on-night");
  });

  it("has no axe violations across the primitives on both surfaces", async () => {
    const light = mount(
      {
        render: () => [
          h(UiBrandMark),
          h(UiButton, () => "Go"),
          h(UiButton, { variant: "quiet" }, () => "Quiet"),
          h(UiCard, () => "Card"),
          h(UiStatusChip, { status: "blocked" }),
          h(UiClaimLabel, { kind: "confirmed" }),
          h(UiStateBlock, { kind: "empty", title: "Nothing yet" }),
        ],
      },
      plugins("it"),
    );
    await expectAccessible(light.element);
    const night = onNight(() => [
      h(UiBrandMark, { wordmark: true }),
      h(UiButton, () => "Go"),
      h(UiButton, { variant: "outline" }, () => "Other"),
      h(UiStatusChip, { status: "observed" }),
      h(UiClaimLabel, { kind: "proof" }),
    ]);
    await expectAccessible(night.element);
  });
});
