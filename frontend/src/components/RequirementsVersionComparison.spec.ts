import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type { RequirementsSpecificationVersionPayload } from "../types/requirements";
import RequirementsVersionComparison from "./RequirementsVersionComparison.vue";

const PROJECT_ID = "00000000-0000-4000-8000-000000000001";
const REQUIREMENT_ID = "00000000-0000-4000-8000-000000000010";

function version(
  versionNumber: number,
  statement: string,
): RequirementsSpecificationVersionPayload {
  return {
    id: `00000000-0000-4000-8000-${versionNumber.toString().padStart(12, "0")}`,
    project_id: PROJECT_ID,
    version_number: versionNumber,
    based_on_version_number: versionNumber === 1 ? null : versionNumber - 1,
    content_hash: `${versionNumber}`.repeat(64),
    created_by_user_id: "00000000-0000-4000-8000-000000000002",
    created_at: `2026-08-18T12:0${versionNumber}:00Z`,
    specification: {
      project_id: PROJECT_ID,
      project_brief_reference: {
        kind: "PROJECT_BRIEF",
        artifact_id: "00000000-0000-4000-8000-000000000020",
        version_number: 1,
        content_hash: "a".repeat(64),
      },
      agent_team_reference: {
        kind: "AGENT_TEAM",
        artifact_id: "00000000-0000-4000-8000-000000000030",
        version_number: 1,
        content_hash: "b".repeat(64),
      },
      user_modeling_reference: {
        kind: "USER_MODELING",
        artifact_id: "00000000-0000-4000-8000-000000000040",
        version_number: 1,
        content_hash: "c".repeat(64),
      },
      catalog_version: 1,
      catalog_content_hash: "d".repeat(64),
      user_twin_references: [],
      requirements: [
        {
          id: REQUIREMENT_ID,
          code: "REQ-001",
          title: "Create reservations",
          statement,
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
    },
  };
}

describe("RequirementsVersionComparison", () => {
  it("reports changed artifacts between the latest two versions", () => {
    const wrapper = mount(RequirementsVersionComparison, {
      props: {
        versions: [
          version(1, "The system must create reservations."),
          version(2, "The system must create guest reservations."),
        ],
        locale: "en",
      },
    });

    const table = wrapper.get('[data-testid="version-comparison"]');

    expect(table.text()).toContain("REQ-001");
    expect(table.text()).toContain("Changed");
  });

  it("explains when fewer than two versions exist", () => {
    const wrapper = mount(RequirementsVersionComparison, {
      props: {
        versions: [version(1, "The system must create reservations.")],
        locale: "en",
      },
    });

    expect(wrapper.text()).toContain("At least two versions");
  });
});
