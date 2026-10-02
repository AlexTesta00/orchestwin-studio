import { mount } from "@vue/test-utils";
import { h } from "vue";
import { describe, expect, it } from "vitest";

import { createAppI18n } from "@/i18n";
import { expectAccessible } from "@/test/axe";
import UiStepper, { type StepItem } from "./UiStepper.vue";
import UiSurface from "./UiSurface.vue";

function plugins(locale: "en" | "it" = "it") {
  return { global: { plugins: [createAppI18n(locale)] } };
}

const steps = [
  { key: "brief", label: "Brief", status: "approved" as const },
  { key: "team", label: "Prospettive", status: "current" as const, decision: 1, max: 4 },
  { key: "twins", label: "User Twin", status: "pending" as const },
];

describe("stepper", () => {
  it("marks the current step, keeps future steps unclickable and reports decisions", async () => {
    const wrapper = mount(UiStepper, { props: { steps, active: "team" }, ...plugins() });
    const buttons = wrapper.findAll("button");
    expect(buttons[0]?.text()).toContain("Approvato");
    expect(buttons[1]?.attributes("aria-current")).toBe("step");
    expect(buttons[1]?.text()).toContain("Decisione 1 di 4");
    expect(buttons[1]?.attributes("data-active")).toBe("true");
    expect(buttons[0]?.attributes("data-active")).toBeUndefined();
    expect(buttons[2]?.attributes("disabled")).toBeDefined();
    expect(buttons[2]?.text()).toContain("In attesa");
    await buttons[0]?.trigger("click");
    expect(wrapper.emitted("select")).toEqual([["brief"]]);
  });

  it("shows the large step numbers as decoration and keeps the stage attributes", () => {
    const wrapper = mount(UiStepper, {
      props: {
        steps: [
          { key: "a", label: "Brief", status: "approved" as const, index: 0 },
          { key: "b", label: "Prospettive", status: "current" as const, index: 1 },
          { key: "c", label: "Twin", status: "pending" as const, index: 2 },
        ],
        active: "a",
      },
      ...plugins(),
    });
    const numbers = wrapper.findAll("[data-step-number]");
    expect(numbers.map((number) => number.text())).toEqual(["01", "02", "03"]);
    expect(numbers[0]?.classes()).toContain("font-display");
    expect(numbers[0]?.element.parentElement?.getAttribute("aria-hidden")).toBe("true");
    expect(numbers[0]?.classes()).toContain("text-ink");
    expect(numbers[1]?.classes()).toContain("text-ink/25");
    expect(wrapper.findAll("[data-stage]").map((node) => node.attributes("data-stage"))).toEqual([
      "0",
      "1",
    ]);
    expect(wrapper.get("[data-testid='stepper']").attributes("aria-label")).toBe("Passi");
  });

  it("lets a waiting step that is already open be chosen without marking it as current", async () => {
    const wrapper = mount(UiStepper, {
      props: {
        steps: [
          { key: "brief", label: "Brief", status: "approved" as const, index: 0 },
          { key: "team", label: "Prospettive", status: "current" as const, index: 1 },
          { key: "twins", label: "User Twin", status: "pending" as const, index: 2 },
          {
            key: "package",
            label: "Dossier",
            status: "pending" as const,
            index: 5,
            open: true,
            note: "Cartella parziale",
          },
        ],
        active: "team",
      },
      ...plugins(),
    });
    const buttons = wrapper.findAll("button");
    const opened = buttons[3]!;

    expect(buttons[2]?.attributes("disabled")).toBeDefined();
    expect(opened.attributes("disabled")).toBeUndefined();
    expect(opened.attributes("data-status")).toBe("pending");
    expect(opened.attributes("aria-current")).toBeUndefined();
    expect(opened.classes()).toContain("cursor-pointer");
    expect(opened.text()).toContain("Cartella parziale");
    expect(opened.text()).not.toContain("In attesa");
    expect(wrapper.findAll("[data-stage]").map((node) => node.attributes("data-stage"))).toEqual([
      "0",
      "1",
      "5",
    ]);
    await opened.trigger("click");
    expect(wrapper.emitted("select")).toEqual([["package"]]);
  });

  it("lets a step replace its status line with a note", () => {
    const wrapper = mount(UiStepper, {
      props: {
        steps: [{ key: "package", label: "Dossier", status: "current" as const, note: "Pronto" }],
        active: "package",
      },
      ...plugins("en"),
    });
    expect(wrapper.get("button").text()).toContain("Pronto");
    expect(wrapper.get("button").text()).not.toContain("Your turn");
  });

  it("uses the colours of the dark timeline inside a dark surface", () => {
    const wrapper = mount(UiSurface, {
      props: { tone: "night" },
      slots: { default: () => h(UiStepper, { steps, active: "team" }) },
      ...plugins(),
    });
    expect(wrapper.get("[data-testid='stepper']").attributes("data-surface-context")).toBe("night");
    const numbers = wrapper.findAll("[data-step-number]");
    expect(numbers[0]?.classes()).toContain("text-petrol-on-night");
    expect(numbers[1]?.classes()).toContain("text-on-night");
    expect(numbers[2]?.classes()).toContain("text-on-night/32");
    expect(wrapper.get("ol").classes()).toContain("border-on-night/14");
  });
});

const sections: StepItem[] = [
  {
    key: "s0",
    label: "Brief",
    status: "approved",
    index: 0,
    section: { state: "FINE", version: 2 },
  },
  {
    key: "s1",
    label: "Prospettive",
    status: "current",
    index: 1,
    section: { state: "IN_PROGRESS", version: 3 },
  },
  {
    key: "s2",
    label: "User Twin",
    status: "approved",
    index: 2,
    section: { state: "UPDATE_AVAILABLE", version: 1 },
  },
  {
    key: "s3",
    label: "Definizione",
    status: "approved",
    index: 3,
    section: { state: "TO_UPDATE", version: 4 },
  },
  {
    key: "s4",
    label: "Design e valutazione",
    status: "pending",
    index: 4,
    section: { state: "NOT_STARTED", version: null },
  },
  {
    key: "s5",
    label: "Dossier",
    status: "approved",
    index: 5,
    section: { state: "TO_UPDATE", version: 6 },
  },
];

describe("stepper of the sections", () => {
  it.each<["en" | "it", string, string[]]>([
    [
      "it",
      "Sezioni",
      [
        "✓ A posto · v2",
        "● Tocca a te · v3",
        "+ Aggiornamento disponibile · v1",
        "↻ Da aggiornare · v4",
        "○ In attesa",
        "↻ Da aggiornare · v6",
      ],
    ],
    [
      "en",
      "Sections",
      [
        "✓ Up to date · v2",
        "● Your turn · v3",
        "+ Update available · v1",
        "↻ To update · v4",
        "○ Waiting",
        "↻ To update · v6",
      ],
    ],
  ])(
    "names in %s the state of every section with a mark and its version",
    (locale, name, lines) => {
      const wrapper = mount(UiStepper, {
        props: { steps: sections, active: "s3" },
        ...plugins(locale),
      });
      const shown = wrapper.findAll("[data-testid='stepper-section']");

      expect(wrapper.get("[data-testid='stepper']").attributes("aria-label")).toBe(name);
      expect(shown.map((line) => line.text().replace(/\s+/g, " "))).toEqual(lines);
      expect(shown.map((line) => line.get("span[aria-hidden]").text())).toEqual([
        "✓",
        "●",
        "+",
        "↻",
        "○",
        "↻",
      ]);
      expect(wrapper.findAll("[data-testid='stepper-version']").map((node) => node.text())).toEqual(
        ["v2", "v3", "v1", "v4", "v6"],
      );
      expect(wrapper.findAll("button").map((button) => button.attributes("data-state"))).toEqual([
        "FINE",
        "IN_PROGRESS",
        "UPDATE_AVAILABLE",
        "TO_UPDATE",
        "NOT_STARTED",
        "TO_UPDATE",
      ]);
    },
  );

  it("locks no section and marks only the open one as current", async () => {
    const wrapper = mount(UiStepper, { props: { steps: sections, active: "s4" }, ...plugins() });
    const buttons = wrapper.findAll("button");

    expect(buttons.every((button) => button.attributes("disabled") === undefined)).toBe(true);
    expect(buttons.every((button) => button.classes().includes("cursor-pointer"))).toBe(true);
    expect(wrapper.findAll("[data-stage]").map((node) => node.attributes("data-stage"))).toEqual([
      "0",
      "1",
      "2",
      "3",
      "4",
      "5",
    ]);
    expect(buttons.map((button) => button.attributes("aria-current"))).toEqual([
      undefined,
      undefined,
      undefined,
      undefined,
      "true",
      undefined,
    ]);
    expect(wrapper.text()).not.toContain("Approvato");
    await buttons[4]?.trigger("click");
    await buttons[0]?.trigger("click");
    expect(wrapper.emitted("select")).toEqual([["s4"], ["s0"]]);
  });

  it("tells the states apart by more than colour on a dark surface", () => {
    const wrapper = mount(UiSurface, {
      props: { tone: "night" },
      slots: { default: () => h(UiStepper, { steps: sections, active: "s0" }) },
      ...plugins(),
    });
    const lines = wrapper.findAll("[data-testid='stepper-section']");
    const numbers = wrapper.findAll("[data-step-number]");

    expect(lines[0]?.classes()).toContain("text-petrol-on-night-2");
    expect(lines[3]?.classes()).toContain("text-warn-on-night");
    expect(lines[4]?.classes()).toContain("text-on-night-3");
    expect(numbers[0]?.classes()).toContain("text-on-night");
    expect(numbers[2]?.classes()).toContain("text-petrol-on-night");
    expect(numbers[3]?.classes()).toContain("text-warn-on-night");
    expect(numbers[4]?.classes()).toContain("text-on-night/32");
    expect(new Set(lines.map((line) => line.get("span[aria-hidden]").text())).size).toBe(5);
  });
});

const CUTTING = [
  "truncate",
  "text-ellipsis",
  "text-clip",
  "whitespace-nowrap",
  "text-nowrap",
  "overflow-hidden",
  "overflow-x-hidden",
];

describe("names of the steps", () => {
  it.each<["en" | "it", string, string]>([
    ["it", "Design e valutazione", "✓ A posto · v4"],
    ["en", "Design & Evaluation", "✓ Up to date · v4"],
  ])(
    "lets a long name in %s go on a second line with its state and version still under it",
    (locale, name, state) => {
      const named: StepItem[] = sections.map((step) =>
        step.index === 4 ? { ...step, label: name, section: { state: "FINE", version: 4 } } : step,
      );
      const wrapper = mount(UiStepper, {
        props: { steps: named, active: "s3" },
        ...plugins(locale),
      });
      const labels = wrapper.findAll("[data-testid='stepper-label']");
      const line = labels[4]?.element.nextElementSibling;

      expect(labels.map((label) => label.text())).toEqual(named.map((step) => step.label));
      for (const label of labels) {
        expect(
          label
            .classes()
            .filter((token) => CUTTING.includes(token) || token.startsWith("line-clamp")),
        ).toEqual([]);
        expect(label.attributes("style")).toBeUndefined();
      }
      expect(labels[4]?.classes()).toContain("break-words");
      expect(line?.getAttribute("data-testid")).toBe("stepper-section");
      expect(line?.textContent?.replace(/\s+/g, " ").trim()).toBe(state);
    },
  );
});

describe("primitive accessibility", () => {
  it("has no axe violations across the primitives", async () => {
    const wrappers = [
      mount(UiStepper, { props: { steps, active: "team" }, ...plugins() }),
      mount(UiSurface, {
        props: { tone: "night" },
        slots: { default: () => h(UiStepper, { steps, active: "brief" }) },
        ...plugins(),
      }),
      mount(UiSurface, {
        props: { tone: "night" },
        slots: { default: () => h(UiStepper, { steps: sections, active: "s3" }) },
        ...plugins("en"),
      }),
    ];
    for (const wrapper of wrappers) {
      await expectAccessible(wrapper.element);
    }
  });
});
