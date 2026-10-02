import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type {
  RequirementsCoveragePayload,
  RequirementsTraceabilityPayload,
} from "../types/requirements";
import RequirementsTraceabilityView from "./RequirementsTraceabilityView.vue";

const REQUIREMENT_ID = "00000000-0000-4000-8000-000000000010";
const STORY_ID = "00000000-0000-4000-8000-000000000020";

const TRACEABILITY: RequirementsTraceabilityPayload = {
  project_id: "00000000-0000-4000-8000-000000000001",
  specification_version_id: "00000000-0000-4000-8000-000000000002",
  specification_version_number: 1,
  specification_content_hash: "a".repeat(64),
  content_hash: "b".repeat(64),
  nodes: [
    {
      reference: {
        kind: "USER_STORY",
        artifact_id: STORY_ID,
      },
      display_code: "USR-001",
    },
    {
      reference: {
        kind: "REQUIREMENT",
        artifact_id: REQUIREMENT_ID,
      },
      display_code: "REQ-001",
    },
  ],
  links: [
    {
      kind: "MOTIVATES",
      source: {
        kind: "USER_STORY",
        artifact_id: STORY_ID,
      },
      target: {
        kind: "REQUIREMENT",
        artifact_id: REQUIREMENT_ID,
      },
    },
  ],
};

const COVERAGE: RequirementsCoveragePayload = {
  project_id: TRACEABILITY.project_id,
  specification_version_id: TRACEABILITY.specification_version_id,
  requirement_count: 1,
  user_story_count: 1,
  acceptance_criterion_count: 0,
  requirement_ids_without_user_stories: [],
  requirement_ids_without_acceptance_criteria: [REQUIREMENT_ID],
  user_story_ids_without_acceptance_criteria: [STORY_ID],
  acceptance_criterion_ids_without_scenarios: [],
  has_full_acceptance_coverage: false,
};

describe("RequirementsTraceabilityView", () => {
  it.each(["en", "it"] as const)(
    "reads the need chain with localized relationship labels in %s",
    (locale) => {
      const traceability: RequirementsTraceabilityPayload = structuredClone(TRACEABILITY);
      const twin = { kind: "USER_TWIN" as const, artifact_id: "twin-32" };
      const scenario = { kind: "SCENARIO" as const, artifact_id: "scenario-32" };
      const need = { kind: "NEED" as const, artifact_id: "need-32" };
      const journey = { kind: "JOURNEY" as const, artifact_id: "journey-32" };
      traceability.nodes.push(
        { reference: twin, display_code: "Receptionist" },
        { reference: scenario, display_code: "SCN-001" },
        { reference: need, display_code: "NED-001" },
        { reference: journey, display_code: "JRN-001" },
      );
      traceability.links.push(
        { kind: "PARTICIPATES_IN", source: twin, target: scenario },
        { kind: "REVEALS", source: scenario, target: need },
        { kind: "MOTIVATES", source: need, target: traceability.nodes[1]!.reference },
        { kind: "EXPANDS", source: scenario, target: journey },
        { kind: "REVEALS", source: journey, target: need },
      );
      const wrapper = mount(RequirementsTraceabilityView, {
        props: { traceability, coverage: COVERAGE, locale },
      });
      expect(wrapper.text()).toContain("NED-001");
      expect(wrapper.text()).toContain(locale === "it" ? "partecipa a" : "participates in");
      expect(wrapper.text()).toContain(locale === "it" ? "rivela" : "reveals");
      expect(wrapper.text()).toContain("JRN-001");
      expect(wrapper.text()).toContain(locale === "it" ? "espande" : "expands");
    },
  );
  it("renders typed traceability links with readable codes", () => {
    const wrapper = mount(RequirementsTraceabilityView, {
      props: {
        traceability: TRACEABILITY,
        coverage: COVERAGE,
        locale: "en",
      },
    });

    const table = wrapper.get('[data-testid="traceability-links"]');

    expect(table.text()).toContain("USR-001");
    expect(table.text()).toContain("motivates");
    expect(table.text()).not.toContain("MOTIVATES");
    expect(table.text()).toContain("REQ-001");
    expect(table.findAll("tbody td").map((cell) => cell.text())).toEqual([
      "USR-001",
      "motivates",
      "REQ-001",
    ]);
  });

  it("names the relations in Italian", () => {
    const wrapper = mount(RequirementsTraceabilityView, {
      props: {
        traceability: TRACEABILITY,
        coverage: COVERAGE,
        locale: "it",
      },
    });

    expect(wrapper.get('[data-testid="traceability-links"] tbody').text()).toContain("motiva");
    const region = wrapper.get('[role="region"]');
    expect(region.attributes("tabindex")).toBe("0");
    expect(wrapper.get(`#${region.attributes("aria-labelledby")}`).text()).toBe(
      "Tracciabilità e copertura",
    );
    expect(wrapper.get('[data-testid="coverage-status"]').text()).toBe(
      "Alcuni elementi non sono ancora coperti.",
    );
  });

  it("keeps uncovered artifacts explicit", () => {
    const wrapper = mount(RequirementsTraceabilityView, {
      props: {
        traceability: TRACEABILITY,
        coverage: COVERAGE,
        locale: "en",
      },
    });

    expect(wrapper.get('[data-testid="coverage-status"]').text()).toContain("not covered yet");
    expect(wrapper.text()).toContain("REQ-001");
    expect(wrapper.text()).toContain("USR-001");
  });
});
