import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, describe, expect, it } from "vitest";

import { createAppI18n } from "@/i18n";
import { expectAccessible } from "@/test/axe";
import type { ChangeOpinion, ChangeOpinionRun } from "../types/designOpinions";
import { changeOpinionCopy } from "./changeOpinionCopy";
import MockupChangeOpinions from "./MockupChangeOpinions.vue";

type Locale = "en" | "it";

interface Shown {
  run?: ChangeOpinionRun | null;
  busy?: boolean;
  stale?: boolean;
  canApply?: boolean;
  focusOnArrival?: boolean;
}

const GIULIA = "44444444-4444-4444-8444-444444444441";
const MARCO = "44444444-4444-4444-8444-444444444442";
const ANNA = "44444444-4444-4444-8444-444444444443";
const REWRITTEN = "Rendi la barra rossa con il testo bianco";

function opinion(
  overrides: Partial<ChangeOpinion> & Pick<ChangeOpinion, "twin_id">,
): ChangeOpinion {
  return {
    twin_version: 1,
    twin_name: "Giulia",
    verdict: "HELPS",
    why: "La barra rossa si vede da lontano.",
    what_to_do: "Tieni la barra rossa.",
    try_this: null,
    profile_keys: ["goals"],
    confidence: 0.7,
    generation_id: `${overrides.twin_id}-generation`,
    ...overrides,
  };
}

const RUN: ChangeOpinionRun = {
  run_id: "33333333-3333-4333-8333-333333333333",
  design_version_id: "22222222-2222-4222-8222-222222222222",
  design_content_hash: "a".repeat(64),
  design_version_number: 7,
  request: "Rendi la barra rossa con il testo blu",
  target: {
    screen_code: "SCR-001",
    element_code: "ELM-003",
    label: "Barra in alto",
    html: "<header>Bottega Vicina</header>",
  },
  locale: "it-IT",
  requested_at: "2026-10-12T10:00:00+00:00",
  opinions: [
    opinion({
      twin_id: GIULIA,
      twin_name: "Giulia",
      verdict: "BLOCKS",
      why: "Il testo blu sulla barra rossa non si legge: 2,1:1 è sotto il minimo di 4,5:1.",
      what_to_do: "Tieni il testo bianco sulla barra rossa.",
      try_this: REWRITTEN,
    }),
    opinion({
      twin_id: MARCO,
      twin_name: "Marco",
      verdict: "SLOWS",
      why: "Devo cercare il nome della bottega due volte.",
      what_to_do: "Rendi il nome più grande.",
    }),
    opinion({ twin_id: ANNA, twin_name: "Anna" }),
  ],
  contrast: {
    mode: "LIGHT",
    text_threshold: 4.5,
    large_text_threshold: 3,
    control_border_threshold: 3,
  },
  cost_microusd: null,
};

const BLOCKED: ChangeOpinionRun = {
  ...RUN,
  run_id: "33333333-3333-4333-8333-333333333334",
  opinions: [
    opinion({ twin_id: GIULIA, verdict: "BLOCKS" }),
    opinion({ twin_id: MARCO, twin_name: "Marco", verdict: "BLOCKS" }),
  ],
};

let wrapper: VueWrapper | null = null;

function mountOpinions(shown: Shown = {}, locale: Locale = "it") {
  wrapper = mount(MockupChangeOpinions, {
    props: { run: RUN, busy: false, stale: false, canApply: true, locale, ...shown },
    global: { plugins: [createAppI18n(locale)] },
    attachTo: document.body,
  });
  return wrapper;
}

function texts(view: VueWrapper, testid: string): string[] {
  return view
    .findAll(`[data-testid='${testid}']`)
    .map((item) => item.text().replace(/\s+/g, " ").trim());
}

function shape(value: unknown, path = ""): string[] {
  if (typeof value === "string") {
    const holes = [...value.matchAll(/\{(\w+)\}/g)].map((match) => match[1]);
    return [`${path}:${holes.join(",")}`];
  }
  return Object.entries(value as Record<string, unknown>).flatMap(([key, child]) =>
    shape(child, `${path}.${key}`),
  );
}

afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
  document.body.innerHTML = "";
});

describe("MockupChangeOpinions", () => {
  it("shows one card per twin with the verdict, the reason and what to do", () => {
    const view = mountOpinions();

    expect(view.get("h5").text()).toBe("Che cosa dicono i twin prima della modifica");
    expect(view.text()).toContain(
      "Parere simulato dal modello: un'ipotesi da verificare con persone vere.",
    );
    const cards = view.findAll("[data-testid='mockup-opinion']");
    expect(cards.map((card) => card.attributes("data-verdict"))).toEqual([
      "BLOCKS",
      "SLOWS",
      "HELPS",
    ]);
    expect(texts(view, "mockup-opinion-twin")).toEqual(["Giulia", "Marco", "Anna"]);
    expect(texts(view, "mockup-opinion-verdict")).toEqual(["Blocca", "Rallenta", "Aiuta"]);
    expect(texts(view, "mockup-opinion-why")).toEqual(RUN.opinions.map((item) => item.why));
    expect(texts(view, "mockup-opinion-action")).toEqual([
      "Cosa fare: Tieni il testo bianco sulla barra rossa.",
      "Cosa fare: Rendi il nome più grande.",
      "Cosa fare: Tieni la barra rossa.",
    ]);
    const chips = view.findAll("[data-testid='mockup-opinion-verdict']");
    expect(chips[0]?.classes()).toContain("text-fail-on-night");
    expect(chips[1]?.classes()).toContain("text-warn-on-night");
    expect(chips[2]?.classes()).toContain("text-petrol-on-night-2");
  });

  it("offers the request rewritten by a twin and otherwise what to do", async () => {
    const view = mountOpinions();
    const cards = view.findAll("[data-testid='mockup-opinion']");

    expect(texts(view, "mockup-opinion-suggestion")).toEqual([`La chiederei così: «${REWRITTEN}»`]);
    expect(texts(view, "mockup-opinion-try")).toEqual([
      "Prova questo",
      "Prova questo",
      "Prova questo",
    ]);
    const rewritten = cards[0]?.get("[data-testid='mockup-opinion-try']");
    const plain = cards[1]?.get("[data-testid='mockup-opinion-try']");
    expect(rewritten?.attributes("aria-describedby")).toBe(
      cards[0]?.get("[data-testid='mockup-opinion-suggestion']").attributes("id"),
    );
    expect(plain?.attributes("aria-describedby")).toBe(
      cards[1]?.get("[data-testid='mockup-opinion-action']").attributes("id"),
    );

    await rewritten?.trigger("click");
    await plain?.trigger("click");

    expect(view.emitted("try")).toEqual([[REWRITTEN], ["Rendi il nome più grande."]]);
  });

  it("lets the owner apply anyway, change the request or cancel", async () => {
    const view = mountOpinions();

    expect(texts(view, "mockup-apply-anyway")).toEqual(["Applica comunque"]);
    expect(texts(view, "mockup-change-request")).toEqual(["Cambia la richiesta"]);
    expect(texts(view, "mockup-cancel-request")).toEqual(["Annulla"]);
    await view.get("[data-testid='mockup-apply-anyway']").trigger("click");
    await view.get("[data-testid='mockup-change-request']").trigger("click");
    await view.get("[data-testid='mockup-cancel-request']").trigger("click");

    expect(view.emitted("apply")).toEqual([[]]);
    expect(view.emitted("change")).toEqual([[]]);
    expect(view.emitted("cancel")).toEqual([[]]);
    expect(view.find("[data-testid='mockup-opinion-stale']").exists()).toBe(false);
  });

  it("hides «Applica comunque» and says why when the opinion is stale", () => {
    const view = mountOpinions({ stale: true });

    expect(view.find("[data-testid='mockup-apply-anyway']").exists()).toBe(false);
    expect(texts(view, "mockup-opinion-stale")).toEqual([
      "Il parere riguarda una richiesta diversa: chiedilo di nuovo o applica la richiesta nuova con «Applica la modifica».",
    ]);
    expect(view.find("[data-testid='mockup-change-request']").exists()).toBe(true);
    expect(view.find("[data-testid='mockup-cancel-request']").exists()).toBe(true);
  });

  it("hides «Applica comunque» while the change cannot be applied", () => {
    const view = mountOpinions({ canApply: false });

    expect(view.find("[data-testid='mockup-apply-anyway']").exists()).toBe(false);
    expect(view.find("[data-testid='mockup-opinion-stale']").exists()).toBe(false);
  });

  it("shows the wait while the twins read the request", () => {
    const view = mountOpinions({ run: null, busy: true });
    const busy = view.get("[data-testid='mockup-opinions-busy']");

    expect(busy.findAll("p").map((line) => line.text())).toEqual([
      "I twin stanno leggendo la richiesta…",
      "Di solito servono circa 2 minuti: intanto puoi continuare a guardare il mockup.",
    ]);
    expect(busy.attributes("role")).toBe("status");
    expect(view.find("[data-testid='mockup-opinions']").exists()).toBe(false);
    expect(view.find("[data-testid='mockup-change-request']").exists()).toBe(false);
  });

  it("shows nothing without opinions and without a wait", () => {
    const view = mountOpinions({ run: null });

    expect(view.find("[data-testid='mockup-change-opinions']").exists()).toBe(false);
  });

  it("announces the verdicts and moves the focus to the title when the opinions arrive", async () => {
    const view = mountOpinions({ run: null, busy: true });
    const announcement = view.get("[data-testid='mockup-opinions-announcement']");
    expect(announcement.attributes("aria-live")).toBe("polite");
    expect(announcement.text()).toBe("");

    await view.setProps({ run: RUN, busy: false });
    await flushPromises();

    expect(view.get("[data-testid='mockup-opinions-announcement']").text()).toBe(
      "Parere di 3 twin: 1 aiuta, 1 rallenta, 1 blocca",
    );
    const title = view.get("h5");
    expect(document.activeElement).toBe(title.element);
    expect(view.get("[data-testid='mockup-change-opinions']").attributes("aria-labelledby")).toBe(
      title.attributes("id"),
    );

    await view.setProps({ run: BLOCKED });
    await flushPromises();

    expect(view.get("[data-testid='mockup-opinions-announcement']").text()).toBe(
      "Parere di 2 twin: 2 bloccano",
    );
  });

  it("leaves the focus where it is when asked to", async () => {
    const view = mountOpinions({ run: null, busy: true, focusOnArrival: false });

    await view.setProps({ run: RUN, busy: false });
    await flushPromises();

    expect(view.get("[data-testid='mockup-opinions-announcement']").text()).toBe(
      "Parere di 3 twin: 1 aiuta, 1 rallenta, 1 blocca",
    );
    expect(document.activeElement).toBe(document.body);
  });

  it("speaks English with the same words of the verdicts as the command line", async () => {
    const view = mountOpinions({ run: null, busy: true }, "en");

    await view.setProps({ run: RUN, busy: false });
    await flushPromises();

    expect(view.get("h5").text()).toBe("What the twins say before the change");
    expect(texts(view, "mockup-opinion-verdict")).toEqual(["Blocks", "Slows down", "Helps"]);
    expect(texts(view, "mockup-opinion-suggestion")).toEqual([
      `I would ask for it like this: “${REWRITTEN}”`,
    ]);
    expect(texts(view, "mockup-apply-anyway")).toEqual(["Apply anyway"]);
    expect(view.get("[data-testid='mockup-opinions-announcement']").text()).toBe(
      "Opinion of 3 twins: 1 helps, 1 slows down, 1 blocks",
    );
  });

  it("has the same keys and placeholders in Italian and English", () => {
    expect(shape(changeOpinionCopy.en)).toEqual(shape(changeOpinionCopy.it));
  });

  const states: [string, Shown][] = [
    ["while the twins read the request", { run: null, busy: true }],
    ["with the opinions", {}],
    ["with a stale opinion", { stale: true }],
  ];

  it.each(states)("is accessible %s", async (_case, shown) => {
    const view = mountOpinions(shown);

    await expectAccessible(view.element);
  });
});
