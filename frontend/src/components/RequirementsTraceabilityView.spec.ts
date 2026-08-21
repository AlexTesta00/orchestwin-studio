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
    expect(table.text()).toContain("MOTIVATES");
    expect(table.text()).toContain("REQ-001");
  });

  it("keeps uncovered artifacts explicit", () => {
    const wrapper = mount(RequirementsTraceabilityView, {
      props: {
        traceability: TRACEABILITY,
        coverage: COVERAGE,
        locale: "en",
      },
    });

    expect(wrapper.get('[data-testid="coverage-status"]').text()).toContain("uncovered artifacts");
    expect(wrapper.text()).toContain("REQ-001");
    expect(wrapper.text()).toContain("USR-001");
  });
});
