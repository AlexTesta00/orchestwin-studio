import { createPinia, setActivePinia } from "pinia";
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type {
  AgentCatalogResponse,
  AgentIdentifier,
  AgentTeamApi,
  OwnerAgentRationaleInput,
  TeamProposalVersionResponse,
} from "@/api/team-contracts";
import { ApiError } from "@/api/client";
import { createAppI18n } from "@/i18n";
import type { TeamAuthorizedRequest } from "@/stores/team";

import ProjectTeamSelectionFlow from "./ProjectTeamSelectionFlow.vue";

enableAutoUnmount(afterEach);

const PROJECT_ID = "project-id";

const CATALOG: AgentCatalogResponse = {
  catalog_version: 1,
  content_hash: "a".repeat(64),
  agents: [
    {
      agent_id: "REQUIREMENTS_ANALYST",
      catalog_version: 1,
      kind: "SPECIALIST",
      selection_policy: "OWNER_SELECTABLE",
      capabilities: ["REQUIREMENTS_ANALYSIS"],
      supported_project_modes: ["GREENFIELD_GENERATION"],
      name_key: "agentCatalog.roles.requirements_analyst.name",
      description_key: "agentCatalog.roles.requirements_analyst.description",
      is_always_present: false,
    },
    {
      agent_id: "MOBILE_ENGINEER",
      catalog_version: 1,
      kind: "SPECIALIST",
      selection_policy: "OWNER_SELECTABLE",
      capabilities: ["MOBILE_ENGINEERING"],
      supported_project_modes: ["GREENFIELD_GENERATION"],
      name_key: "agentCatalog.roles.mobile_engineer.name",
      description_key: "agentCatalog.roles.mobile_engineer.description",
      is_always_present: false,
    },
  ],
};

function proposalVersion(
  selectedAgentIds: readonly AgentIdentifier[],
  versionNumber = 1,
): TeamProposalVersionResponse {
  return {
    id: versionNumber === 1 ? "proposal-id" : "proposal-id-2",
    project_id: PROJECT_ID,
    version_number: versionNumber,
    revision_kind: versionNumber === 1 ? "PROPOSER_GENERATED" : "OWNER_EDITED",
    based_on_version_number: versionNumber === 1 ? null : 1,

    schema_version: 1,
    provider_kind: "FAKE_DETERMINISTIC",
    provider_id: "fake-deterministic-team-proposal",
    provider_version: 1,

    project_mode: "GREENFIELD_GENERATION",
    brief_version_id: "brief-version-id",
    brief_version_number: 1,
    brief_content_hash: "b".repeat(64),

    catalog_version: 1,
    catalog_content_hash: "a".repeat(64),
    constraints_content_hash: "c".repeat(64),
    content_hash: versionNumber === 1 ? "d".repeat(64) : "e".repeat(64),

    selected_agent_ids: selectedAgentIds,
    role_constraints: [
      {
        agent_id: "REQUIREMENTS_ANALYST",
        kind: "MANDATORY",
        owner_editable: false,
        reasons: [
          {
            code: "CORE_REQUIREMENTS_DISCIPLINE",
            evidence: {
              fields: [],
              terms: [],
            },
          },
        ],
      },
      {
        agent_id: "MOBILE_ENGINEER",
        kind: "OPTIONAL",
        owner_editable: true,
        reasons: [],
      },
    ],
    constraint_issues: [],
    members: [
      {
        agent_id: "REQUIREMENTS_ANALYST",
        source: "DETERMINISTIC_MANDATORY",
        justifications: [
          {
            kind: "DETERMINISTIC_RULE",
            code: "CORE_REQUIREMENTS_DISCIPLINE",
            evidence_fields: [],
            evidence_terms: [],
            statement: null,
          },
        ],
      },
      ...(selectedAgentIds.includes("MOBILE_ENGINEER")
        ? [
            {
              agent_id: "MOBILE_ENGINEER" as const,
              source: "OWNER_ADDED" as const,
              justifications: [
                {
                  kind: "OWNER_RATIONALE" as const,
                  code: "OWNER_SELECTED_ROLE",
                  evidence_fields: [],
                  evidence_terms: [],
                  statement: "The owner wants an optional mobile companion.",
                },
              ],
            },
          ]
        : []),
    ],

    created_by_user_id: "owner-id",
    created_at: "2026-08-12T12:00:00Z",
  };
}

describe("ProjectTeamSelectionFlow", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("submits the complete team and rationale for a new optional role", async () => {
    let currentVersion = proposalVersion(["REQUIREMENTS_ANALYST"]);
    const history = [currentVersion];
    let submittedAgentIds: readonly AgentIdentifier[] = [];
    let submittedRationales: readonly OwnerAgentRationaleInput[] = [];

    const api: AgentTeamApi = {
      async getAgentCatalog() {
        return CATALOG;
      },

      async generateProjectTeamProposal() {
        return {
          status: "UNCHANGED",
          version: currentVersion,
          issues: [],
        };
      },

      async listProjectTeamProposals() {
        return history;
      },

      async getCurrentProjectTeamProposal() {
        return currentVersion;
      },

      async editCurrentProjectTeamProposal(_accessToken, _projectId, input) {
        submittedAgentIds = input.selected_agent_ids;
        submittedRationales = input.owner_rationales;

        currentVersion = proposalVersion(input.selected_agent_ids, 2);
        history.push(currentVersion);

        return {
          status: "UPDATED",
          version: currentVersion,
          issues: [],
          events: [],
        };
      },

      async submitAgentTeamGate() {
        return {
          status: "PROPOSAL_NOT_FOUND",
          gate: null,
          events: [],
          issue: null,
        };
      },

      async getCurrentAgentTeamGate() {
        throw new ApiError(404, "agent_team_gate_not_found");
      },

      async listAgentTeamGateEvents() {
        return [];
      },

      async decideAgentTeamGate() {
        return {
          status: "GATE_NOT_FOUND",
          gate: null,
          event: null,
          issue: null,
        };
      },

      async getProjectWorkflowReadiness() {
        return {
          status: "TEAM_APPROVAL_REQUIRED",
        };
      },
    };

    const executeAuthorized: TeamAuthorizedRequest = <T>(
      operation: (accessToken: string) => Promise<T>,
    ): Promise<T> => operation("access-token");

    const wrapper = mount(ProjectTeamSelectionFlow, {
      props: {
        projectId: PROJECT_ID,
        api,
        authorize: executeAuthorized,
      },
      global: {
        plugins: [createPinia(), createAppI18n()],
      },
    });

    await flushPromises();

    const mandatoryCheckbox = wrapper.get('[data-testid="role-REQUIREMENTS_ANALYST"]');

    expect(mandatoryCheckbox.attributes("disabled")).toBeDefined();

    await wrapper.get('[data-testid="role-MOBILE_ENGINEER"]').setValue(true);

    await wrapper
      .get('[data-testid="rationale-MOBILE_ENGINEER"]')
      .setValue("The owner wants an optional mobile companion.");

    await wrapper.get('[data-testid="team-selection-form"]').trigger("submit");

    await flushPromises();

    expect(submittedAgentIds).toEqual(["REQUIREMENTS_ANALYST", "MOBILE_ENGINEER"]);

    expect(submittedRationales).toEqual([
      {
        agent_id: "MOBILE_ENGINEER",
        statement: "The owner wants an optional mobile companion.",
      },
    ]);

    expect(wrapper.text()).toContain("Owner edited");
  });
});
