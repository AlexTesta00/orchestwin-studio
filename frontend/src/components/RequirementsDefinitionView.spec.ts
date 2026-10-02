import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type { RequirementsSpecificationPayload } from "../types/requirements";
import { expectAccessible } from "@/test/axe";
import RequirementsDefinitionView from "./RequirementsDefinitionView.vue";

const source = {
  kind: "SYSTEM_ARTIFACT" as const,
  source_id: "https://example.org/brief-material",
  source_version: 7,
  content_hash: null,
  locator: "page 3",
};
const twin = {
  twin_id: "twin",
  name: "Receptionist",
  version_number: 1,
  content_hash: "a".repeat(64),
};
const reference = { artifact_id: "input", version_number: 1, content_hash: "b".repeat(64) };
function specification(): RequirementsSpecificationPayload {
  return {
    schema_version: 2,
    project_id: "project",
    project_brief_reference: { ...reference, kind: "PROJECT_BRIEF" },
    agent_team_reference: { ...reference, kind: "AGENT_TEAM" },
    user_modeling_reference: { ...reference, kind: "USER_MODELING" },
    catalog_version: 1,
    catalog_content_hash: "c".repeat(64),
    user_twin_references: [twin],
    scenarios: [
      {
        id: "scenario",
        code: "SCN-001",
        title: "A guest arrives",
        actor: twin,
        context: "At the busy reception desk",
        goal: "Recognize the arriving guest",
        preconditions: ["The guest list is available"],
        trigger: "The guest gives their name",
        steps: ["Find the guest", "Confirm the arrival"],
        criticalities: ["Two guests share a name"],
        expected_outcome: "The arrival is recorded",
        requirement_ids: ["requirement"],
        acceptance_criterion_ids: [],
        sources: [source],
      },
    ],
    needs: [
      {
        id: "need",
        code: "NED-001",
        title: "Recognize guests reliably",
        statement: "Identify each guest without losing the list",
        scenario_ids: ["scenario"],
        sources: [source],
      },
    ],
    user_stories: [
      {
        id: "story",
        code: "USR-001",
        user_twin_reference: twin,
        goal: "Find the arriving guest",
        benefit: "Keep the queue moving",
        requirement_ids: ["requirement"],
        need_ids: ["need"],
      },
    ],
    requirements: [
      {
        id: "requirement",
        code: "REQ-001",
        title: "Search guests",
        statement: "Search guests by name",
        kind: "FUNCTIONAL",
        priority: "MUST",
        sources: [source],
        user_twin_references: [twin],
        need_ids: ["need"],
      },
    ],
    acceptance_criteria: [],
    risks: [],
    definition_of_done: [],
  };
}

describe("RequirementsDefinitionView", () => {
  it.each(["en", "it"] as const)(
    "shows journey phases on demand with scenario and need links in %s",
    async (locale) => {
      const value = specification();
      value.journeys = [
        {
          id: "journey",
          code: "JRN-001",
          title: "Welcome a guest",
          scenario_id: "scenario",
          sources: [source],
          phases: [
            {
              title: "Identify",
              action: "Find the guest's name",
              touchpoint: "Guest list",
              criticalities: ["Possible shared names"],
              need_ids: ["need"],
            },
            {
              title: "Welcome",
              action: "Confirm the arrival",
              touchpoint: null,
              criticalities: [],
              need_ids: ["need"],
            },
          ],
        },
      ];
      const wrapper = mount(RequirementsDefinitionView, {
        props: { specification: value, locale },
      });
      expect(
        wrapper
          .findAll("section")
          .slice(0, 2)
          .map((section) => section.attributes("data-testid")),
      ).toEqual(["definition-section-scenarios", "definition-section-needs"]);
      const journey = wrapper.get('[data-testid="definition-journeys-item"]');
      expect(journey.get("summary").text()).toBe("Welcome a guest");
      expect(journey.attributes("open")).toBeUndefined();
      wrapper.vm.openItem("JRN-001");
      await wrapper.vm.$nextTick();
      expect(journey.attributes("open")).toBeDefined();
      expect(
        journey.findAll('[data-testid="journey-phase"] h4').map((phase) => phase.text()),
      ).toEqual(["1. Identify", "2. Welcome"]);
      expect(journey.text()).toContain("Receptionist");
      expect(journey.text()).toContain("Find the guest's name");
      expect(journey.text()).toContain("Guest list");
      expect(journey.text()).toContain("Possible shared names");
      expect(journey.text()).toContain(locale === "it" ? "Punto di contatto" : "Touchpoint");
      expect(journey.get('[data-testid="definition-source-reference"]').text()).toContain(
        source.source_id,
      );
      await journey.findAll('[data-testid="journey-phase"]')[0]!.get("button").trigger("click");
      expect(wrapper.emitted("select-item")).toEqual([["NED-001"]]);
      await journey.get('button[data-testid="definition-reference-link"]').trigger("click");
      expect(wrapper.emitted("select-item")?.[1]).toEqual(["SCN-001"]);
      await expectAccessible(wrapper.element);
    },
  );

  it.each(["en", "it"] as const)(
    "shows titles in chain order with closed details and exact sources in %s",
    async (locale) => {
      const wrapper = mount(RequirementsDefinitionView, {
        props: { specification: specification(), locale },
      });
      expect(
        wrapper.findAll("section").map((section) => section.attributes("data-testid")),
      ).toEqual([
        "definition-section-scenarios",
        "definition-section-needs",
        "definition-section-stories",
      ]);
      expect(wrapper.findAll("summary").map((summary) => summary.text())).toEqual([
        "A guest arrives",
        "Recognize guests reliably",
        "Find the arriving guest",
      ]);
      expect(
        wrapper.findAll("details").every((details) => details.attributes("open") === undefined),
      ).toBe(true);
      expect(wrapper.get('[data-testid="definition-validation-warning"]').text()).toBe(
        locale === "it"
          ? "Questa definizione deriva dal brief e dai twin: resta da verificare con utenti reali."
          : "This definition comes from the brief and the twins: it still needs to be checked with real users.",
      );
      const scenario = wrapper.get('[data-testid="definition-scenarios-item"]');
      expect(scenario.text()).toContain("Receptionist");
      expect(scenario.text()).toContain("At the busy reception desk");
      expect(scenario.text()).toContain("Recognize the arriving guest");
      expect(scenario.text()).toContain("Two guests share a name");
      expect(scenario.get('[data-testid="definition-sources"]').text()).toContain(source.source_id);
      expect(scenario.get('[data-testid="definition-sources"]').text()).toContain("page 3");
      expect(scenario.get("summary").text()).not.toMatch(/SCN-|NED-|USR-|REQ-/);
      await scenario.findAll("button")[0]!.trigger("click");
      expect(wrapper.emitted("select-item")).toEqual([["NED-001"]]);
      wrapper.vm.openItem("NED-001");
      await wrapper.vm.$nextTick();
      expect(wrapper.get('[data-testid="definition-needs-item"]').attributes("open")).toBeDefined();
      await expectAccessible(wrapper.element);
    },
  );

  it("reads legacy fields and declares absent needs without filling them from requirements", () => {
    const value = specification();
    value.schema_version = 1;
    delete value.needs;
    for (const scenario of value.scenarios) {
      delete scenario.context;
      delete scenario.goal;
      delete scenario.criticalities;
      delete scenario.sources;
    }
    const wrapper = mount(RequirementsDefinitionView, {
      props: { specification: value, locale: "it" },
    });
    expect(wrapper.get('[data-testid="definition-legacy-needs"]').text()).toContain(
      "I bisogni non erano registrati",
    );
    expect(wrapper.find('[data-testid="definition-needs-item"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="definition-scenarios-item"]').text()).toContain(
      "The guest gives their name",
    );
    expect(wrapper.get('[data-testid="definition-scenarios-item"]').text()).not.toContain(
      "Contesto:",
    );
    expect(wrapper.get('[data-testid="definition-scenarios-item"]').text()).not.toContain(
      "Obiettivo:",
    );
  });

  it("preserves complete long titles, linked titles and source references after opening details", async () => {
    const value = specification();
    const title = `Arrival${"Details".repeat(30)}`;
    const needTitle = `Recognition${"Context".repeat(30)}`;
    const longSource = {
      ...source,
      source_id: `https://example.org/${"material/".repeat(30)}brief`,
      locator: `section-${"a".repeat(160)}`,
      content_hash: "f".repeat(64),
    };
    value.scenarios[0]!.title = title;
    value.scenarios[0]!.sources = [longSource];
    value.needs![0]!.title = needTitle;
    value.needs![0]!.sources = [longSource];
    const wrapper = mount(RequirementsDefinitionView, {
      props: { specification: value },
    });
    wrapper.vm.openItem("SCN-001");
    wrapper.vm.openItem("NED-001");
    await wrapper.vm.$nextTick();
    const scenario = wrapper.get('[data-testid="definition-scenarios-item"]');
    const need = wrapper.get('[data-testid="definition-needs-item"]');
    expect(scenario.attributes("open")).toBeDefined();
    expect(need.attributes("open")).toBeDefined();
    expect(scenario.get("summary").text()).toBe(title);
    expect(need.get("summary").text()).toBe(needTitle);
    expect(scenario.findAll("button")[0]!.text()).toBe(needTitle);
    for (const item of [scenario, need]) {
      const details = item.get('[data-testid="definition-sources"]').text();
      expect(details).toContain(longSource.source_id);
      expect(details).toContain(longSource.locator);
      expect(details).toContain(longSource.content_hash);
    }
  });
});
