import { mount, type VueWrapper } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import {
  BASE_DESIGN_PACKAGE,
  SECOND_DESIGN_ALTERNATIVE_ID,
  SELECTED_DESIGN_PACKAGE,
} from "../test/designFixtures";
import type { DesignPackagePayload } from "../types/design";
import type { RequirementsSpecificationPayload } from "../types/requirements";
import DesignTableView from "./DesignTableView.vue";
import { expectAccessible } from "@/test/axe";

const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;
const REQUIREMENT_ID = BASE_DESIGN_PACKAGE.grounding.requirement_ids[0]!;

const REQUIREMENTS: RequirementsSpecificationPayload = {
  project_id: BASE_DESIGN_PACKAGE.project_id,
  project_brief_reference: {
    kind: "PROJECT_BRIEF",
    artifact_id: "00000000-0000-4000-8000-000000000170",
    version_number: 1,
    content_hash: "a".repeat(64),
  },
  agent_team_reference: {
    kind: "AGENT_TEAM",
    artifact_id: "00000000-0000-4000-8000-000000000171",
    version_number: 1,
    content_hash: "b".repeat(64),
  },
  user_modeling_reference: {
    kind: "USER_MODELING",
    artifact_id: "00000000-0000-4000-8000-000000000172",
    version_number: 1,
    content_hash: "c".repeat(64),
  },
  catalog_version: 1,
  catalog_content_hash: "d".repeat(64),
  user_twin_references: BASE_DESIGN_PACKAGE.grounding.user_twin_references,
  requirements: [
    {
      id: REQUIREMENT_ID,
      code: "REQ-001",
      title: "Create reservations",
      statement: "The desk can create a reservation for a guest.",
      kind: "FUNCTIONAL",
      priority: "MUST",
      sources: [],
      user_twin_references: [],
    },
  ],
  user_stories: [],
  acceptance_criteria: [],
  scenarios: [],
  risks: [],
  definition_of_done: [],
};

function mounted(
  design: DesignPackagePayload,
  requirements: RequirementsSpecificationPayload | null = REQUIREMENTS,
  locale: "en" | "it" = "en",
) {
  return mount(DesignTableView, { props: { design, requirements, locale } });
}

function section(wrapper: VueWrapper, key: string) {
  return wrapper.get(`[data-testid="design-section-${key}"]`);
}

function comparisonCells(wrapper: VueWrapper, key: string, table = "alternatives"): string[] {
  return section(wrapper, table)
    .get(`[data-testid="design-row-${key}"]`)
    .findAll("td")
    .map((cell) => cell.text());
}

function rowKeys(wrapper: VueWrapper, key: string): (string | undefined)[] {
  return section(wrapper, key)
    .findAll("tbody tr")
    .map((row) => row.attributes("data-row-key"));
}

function rowsOf(wrapper: VueWrapper, key: string): string[][] {
  return section(wrapper, key)
    .findAll("tbody tr")
    .map((row) => row.findAll("th, td").map((cell) => cell.text()));
}

describe("DesignTableView", () => {
  it("shows the sections in order and hides screens and transitions without a mockup", () => {
    const withMockup = mounted(SELECTED_DESIGN_PACKAGE);
    const withoutMockup = mounted(BASE_DESIGN_PACKAGE, REQUIREMENTS, "it");

    expect(withMockup.findAll("h4").map((heading) => heading.text())).toEqual([
      "Alternatives side by side",
      "Visual choices",
      "Workflows",
      "Screens and elements",
      "Transitions",
      "Concerns",
    ]);
    expect(withoutMockup.findAll("h4").map((heading) => heading.text())).toEqual([
      "Alternative a confronto",
      "Scelte visive",
      "Flussi",
      "Criticità",
    ]);
    expect(withoutMockup.find('[data-testid="design-section-screens"]').exists()).toBe(false);
    expect(withoutMockup.find('[data-testid="design-section-transitions"]').exists()).toBe(false);
  });

  it("puts the alternatives in columns with the owner's choice and the recommendation", async () => {
    const wrapper = mounted({
      ...SELECTED_DESIGN_PACKAGE,
      recommended_alternative_id: SECOND_DESIGN_ALTERNATIVE_ID,
    });
    const table = section(wrapper, "alternatives");
    const first = table.get('[data-testid="design-column-DES-001"]');
    const second = table.get('[data-testid="design-column-DES-002"]');

    expect(table.findAll("thead th").map((cell) => cell.attributes("scope"))).toEqual([
      "col",
      "col",
      "col",
    ]);
    expect(first.text()).toContain("Guided reservation flow");
    expect(first.find('[data-testid="badge-chosen"]').text()).toBe("Chosen by you");
    expect(first.find('[data-testid="badge-recommended"]').exists()).toBe(false);
    expect(second.text()).toContain("Reservation operations dashboard");
    expect(second.find('[data-testid="badge-chosen"]').exists()).toBe(false);
    expect(second.get('[data-testid="badge-recommended"]').text()).toBe("Recommended");
    expect(table.findAll('tbody th[scope="row"]').map((cell) => cell.text())).toEqual([
      "Summary",
      "Layout",
      "Product name",
      "Why",
      "Advantages",
      "Trade-offs",
      "Requirements covered",
      "People",
      "Workflows",
    ]);

    await wrapper.setProps({ design: SELECTED_DESIGN_PACKAGE, locale: "it" });

    const badges = section(wrapper, "alternatives").get('[data-testid="design-column-DES-001"]');
    expect(badges.get('[data-testid="badge-chosen"]').text()).toBe("Scelta da te");
    expect(badges.get('[data-testid="badge-recommended"]').text()).toBe("Consigliata");
  });

  it("names the layout archetype and marks a missing value with an em dash", async () => {
    const wrapper = mounted(BASE_DESIGN_PACKAGE);
    const dash = section(wrapper, "alternatives")
      .get('[data-testid="design-row-layout"]')
      .get('[role="img"]');

    expect(comparisonCells(wrapper, "layout")).toEqual(["—", "Dashboard"]);
    expect(dash.attributes("aria-label")).toBe("empty");
    expect(comparisonCells(wrapper, "product")).toEqual(["—", "Reservation desk"]);
    expect(comparisonCells(wrapper, "why")).toEqual([
      "Reduce avoidable cognitive load while keeping recovery visible.",
      "Support rapid orientation across active reservation work.",
    ]);

    await wrapper.setProps({ locale: "it" });

    expect(comparisonCells(wrapper, "layout")).toEqual(["—", "Cruscotto"]);
  });

  it("shows the items of a list one per line", () => {
    const [first, second] = BASE_DESIGN_PACKAGE.alternatives;
    const wrapper = mounted({
      ...BASE_DESIGN_PACKAGE,
      alternatives: [
        {
          ...first!,
          advantages: ["The current step remains explicit.", "Mistakes are caught early."],
        },
        second!,
      ],
    });
    const advantages = section(wrapper, "alternatives")
      .get('[data-testid="design-row-advantages"]')
      .findAll("td")[0]!;

    expect(advantages.findAll("li").map((item) => item.text())).toEqual([
      "The current step remains explicit.",
      "Mistakes are caught early.",
    ]);
    expect(comparisonCells(wrapper, "people")).toEqual(["Receptionist Twin", "Receptionist Twin"]);
    expect(comparisonCells(wrapper, "workflows")).toEqual(["FLOW-001", "FLOW-002"]);
  });

  it("lists the visual choices in the language of the owner and hides them when no style exists", async () => {
    const wrapper = mounted(BASE_DESIGN_PACKAGE, REQUIREMENTS, "it");
    const english = mounted(BASE_DESIGN_PACKAGE, REQUIREMENTS, "en");
    const labels = section(wrapper, "visual")
      .findAll('tbody th[scope="row"]')
      .map((cell) => cell.text());
    const englishLabels = section(english, "visual")
      .findAll('tbody th[scope="row"]')
      .map((cell) => cell.text());

    expect(labels.slice(0, 3)).toEqual(["Impaginazione", "Tinta", "Schema di colori"]);
    expect(labels).toContain("Peso dei titoli");
    expect(labels).toHaveLength(22);
    expect(new Set(labels).size).toBe(22);
    expect(comparisonCells(wrapper, "archetype", "visual")).toEqual(["—", "Cruscotto"]);
    expect(comparisonCells(wrapper, "heading_family", "visual")).toEqual([
      "—",
      "Con grazie squadrate",
    ]);
    expect(comparisonCells(wrapper, "navigation", "visual")).toEqual(["—", "Barra laterale"]);
    expect(englishLabels.slice(0, 3)).toEqual(["Layout", "Hue", "Colour scheme"]);
    expect(comparisonCells(english, "heading_family", "visual")).toEqual(["—", "Slab serif"]);
    expect(comparisonCells(english, "navigation", "visual")).toEqual(["—", "Side rail"]);

    await wrapper.setProps({
      design: {
        ...BASE_DESIGN_PACKAGE,
        alternatives: BASE_DESIGN_PACKAGE.alternatives.map((alternative) => ({
          ...alternative,
          visual_language: null,
        })),
      },
    });

    expect(wrapper.find('[data-testid="design-section-visual"]').exists()).toBe(false);
  });

  it("gives every step its own row even when two alternatives share a workflow code", () => {
    const [first, second] = BASE_DESIGN_PACKAGE.alternatives;
    const wrapper = mounted({
      ...BASE_DESIGN_PACKAGE,
      alternatives: [
        first!,
        {
          ...second!,
          workflows: second!.workflows.map((workflow) => ({ ...workflow, code: "FLOW-001" })),
        },
      ],
    });

    expect(rowsOf(wrapper, "workflows")).toEqual([
      ["DES-001", "FLOW-001", "Create a reservation", "1", "Review availability.", "REQ-001"],
      ["DES-001", "FLOW-001", "Create a reservation", "2", "Enter guest details.", "REQ-001"],
      ["DES-001", "FLOW-001", "Create a reservation", "3", "Confirm the reservation.", "REQ-001"],
      ["DES-002", "FLOW-001", "Review and create reservations", "1", "Review status.", "REQ-001"],
      [
        "DES-002",
        "FLOW-001",
        "Review and create reservations",
        "2",
        "Open the action panel.",
        "REQ-001",
      ],
      [
        "DES-002",
        "FLOW-001",
        "Review and create reservations",
        "3",
        "Confirm the update.",
        "REQ-001",
      ],
    ]);
    expect(rowKeys(wrapper, "workflows")).toEqual([
      "DES-001:FLOW-001:1",
      "DES-001:FLOW-001:2",
      "DES-001:FLOW-001:3",
      "DES-002:FLOW-001:1",
      "DES-002:FLOW-001:2",
      "DES-002:FLOW-001:3",
    ]);
  });

  it("describes every screen element and every transition of the mockup", async () => {
    const wrapper = mounted(SELECTED_DESIGN_PACKAGE);
    const screens = rowsOf(wrapper, "screens");

    expect(screens).toHaveLength(9);
    expect(rowKeys(wrapper, "screens").slice(0, 4)).toEqual([
      "SCR-001:ELM-001",
      "SCR-001:ELM-002",
      "SCR-001:ELM-003",
      "SCR-002:ELM-004",
    ]);
    expect(screens[0]).toEqual([
      "SCR-001",
      "Availability",
      "Default",
      "ELM-001",
      "Heading",
      "Availability",
      "—",
    ]);
    expect(screens[2]).toEqual([
      "SCR-001",
      "Availability",
      "Default",
      "ELM-003",
      "Button",
      "Continue to Reservation",
      "REQ-001",
    ]);
    expect(screens[8]!.slice(0, 5)).toEqual([
      "SCR-003",
      "Confirmation",
      "Success",
      "ELM-009",
      "Status",
    ]);
    expect(rowsOf(wrapper, "transitions")).toEqual([
      [
        "TRN-001",
        "SCR-001 · Availability",
        "SCR-002 · Reservation",
        "ELM-003 · Continue to Reservation",
        "The Reservation screen becomes visible.",
      ],
      [
        "TRN-002",
        "SCR-002 · Reservation",
        "SCR-003 · Confirmation",
        "ELM-006 · Continue to Confirmation",
        "The Confirmation screen becomes visible.",
      ],
    ]);

    await wrapper.setProps({ locale: "it" });

    expect(rowsOf(wrapper, "screens")[2]!.slice(2, 5)).toEqual([
      "Predefinito",
      "ELM-003",
      "Pulsante",
    ]);
    expect(rowsOf(wrapper, "screens")[8]![2]).toBe("Successo");
    expect(rowsOf(wrapper, "screens")[0]![4]).toBe("Titolo");
  });

  it("turns references into codes through the requirements and never shows an identifier", () => {
    const resolved = mounted(SELECTED_DESIGN_PACKAGE);
    const unresolved = mounted(SELECTED_DESIGN_PACKAGE, null);

    expect(comparisonCells(resolved, "requirements")).toEqual(["REQ-001", "REQ-001"]);
    expect(rowsOf(resolved, "concerns")).toEqual([
      [
        "DRK-001",
        "Experienced users may find the guided flow slower.",
        "Evaluate keyboard-efficient shortcuts after owner selection.",
        "DES-001",
        "REQ-001",
      ],
    ]);
    expect(comparisonCells(unresolved, "requirements")).toEqual(["—", "—"]);
    expect(rowsOf(unresolved, "workflows").map((row) => row[5])).toEqual([
      "—",
      "—",
      "—",
      "—",
      "—",
      "—",
    ]);
    expect(rowsOf(unresolved, "concerns")[0]!.slice(3)).toEqual(["DES-001", "—"]);
    expect(resolved.text()).not.toMatch(UUID);
    expect(unresolved.text()).not.toMatch(UUID);
  });

  it("has no axe violations", async () => {
    const wrapper = mounted(SELECTED_DESIGN_PACKAGE);

    await expectAccessible(wrapper.element);
  });

  it("gives every alternative of the visual choices room for its code and a title on two lines", () => {
    const wrapper = mounted(BASE_DESIGN_PACKAGE, REQUIREMENTS, "it");
    const visual = section(wrapper, "visual");

    for (const code of ["DES-001", "DES-002"]) {
      const column = visual.get(`[data-testid="design-column-${code}"]`);
      expect(column.classes()).toContain("min-w-80");
    }
  });
});
