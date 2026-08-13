import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import { ApiError } from "@/api/client";
import type {
  AgentCatalogResponse,
  AgentTeamApi,
  TeamProposalVersionResponse,
} from "@/api/team-contracts";
import type { HumanGateResponse } from "@/api/workflow-contracts";

import { type TeamAuthorizedRequest, useTeamStore } from "./team";

const PROJECT_ID = "project-id";
const GATE_ID = "gate-id";

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

const VERSION: TeamProposalVersionResponse = {
  id: "proposal-id",
  project_id: PROJECT_ID,
  version_number: 1,
  revision_kind: "PROPOSER_GENERATED",
  based_on_version_number: null,

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
  content_hash: "d".repeat(64),

  selected_agent_ids: ["REQUIREMENTS_ANALYST"],
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
  ],

  created_by_user_id: "owner-id",
  created_at: "2026-08-12T12:00:00Z",
};

const GATE: HumanGateResponse = {
  id: GATE_ID,
  project_id: PROJECT_ID,
  owner_user_id: "owner-id",
  gate_type: "AGENT_TEAM",
  artifact: {
    project_id: PROJECT_ID,
    gate_type: "AGENT_TEAM",
    artifact_id: VERSION.id,
    version: VERSION.version_number,
    content_hash: VERSION.content_hash,
  },
  iteration: 1,
  max_iterations: 3,
  status: "PENDING_APPROVAL",
  created_at: "2026-08-12T12:01:00Z",
  updated_at: "2026-08-12T12:01:00Z",
  event_sequence: 1,
  resume_status: null,
};

const authorize: TeamAuthorizedRequest = <T>(
  operation: (accessToken: string) => Promise<T>,
): Promise<T> => operation("access-token");

function buildApi(): AgentTeamApi {
  return {
    async getAgentCatalog() {
      return CATALOG;
    },

    async generateProjectTeamProposal() {
      return {
        status: "UNCHANGED",
        version: VERSION,
        issues: [],
      };
    },

    async listProjectTeamProposals() {
      return [VERSION];
    },

    async getCurrentProjectTeamProposal() {
      return VERSION;
    },

    async editCurrentProjectTeamProposal(_accessToken, _projectId, input) {
      return {
        status: "UPDATED",
        version: {
          ...VERSION,
          id: "proposal-id-2",
          version_number: 2,
          revision_kind: "OWNER_EDITED",
          based_on_version_number: 1,
          selected_agent_ids: input.selected_agent_ids,
          content_hash: "e".repeat(64),
        },
        issues: [],
        events: [],
      };
    },

    async submitAgentTeamGate() {
      return {
        status: "ALREADY_PENDING",
        gate: GATE,
        events: [],
        issue: null,
      };
    },

    async getCurrentAgentTeamGate() {
      return GATE;
    },

    async listAgentTeamGateEvents() {
      return [
        {
          id: "event-id",
          gate_id: GATE_ID,
          sequence_number: 1,
          kind: "SUBMIT",
          previous_status: "DRAFT",
          resulting_status: "PENDING_APPROVAL",
          artifact: GATE.artifact,
          occurred_at: "2026-08-12T12:01:00Z",
          actor_user_id: "owner-id",
          reason: null,
        },
      ];
    },

    async decideAgentTeamGate() {
      return {
        status: "APPLIED",
        gate: {
          ...GATE,
          status: "APPROVED",
          event_sequence: 2,
        },
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
}

describe("useTeamStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("loads catalog, proposal, gate, events, and readiness", async () => {
    const store = useTeamStore();

    const loaded = await store.load(PROJECT_ID, buildApi(), authorize);

    expect(loaded).toBe(true);
    expect(store.catalog).toEqual(CATALOG);
    expect(store.currentVersion).toEqual(VERSION);
    expect(store.history).toEqual([VERSION]);
    expect(store.gate).toEqual(GATE);
    expect(store.gateEvents).toHaveLength(1);
    expect(store.readiness?.status).toBe("TEAM_APPROVAL_REQUIRED");
    expect(store.errorDetail).toBeNull();
  });

  it("records the complete owner-edited selection", async () => {
    const store = useTeamStore();
    const api = buildApi();

    await store.load(PROJECT_ID, api, authorize);

    const result = await store.editCurrent(
      PROJECT_ID,
      ["REQUIREMENTS_ANALYST", "MOBILE_ENGINEER"],
      [
        {
          agent_id: "MOBILE_ENGINEER",
          statement: "The owner wants a mobile companion.",
        },
      ],
      api,
      authorize,
    );

    expect(result?.status).toBe("UPDATED");
    expect(store.lastEdit?.version?.selected_agent_ids).toContain("MOBILE_ENGINEER");
  });

  it("treats missing current proposal and gate as empty state", async () => {
    const api = buildApi();

    api.getCurrentProjectTeamProposal = async () => {
      throw new ApiError(404, "team_proposal_not_found");
    };

    api.getCurrentAgentTeamGate = async () => {
      throw new ApiError(404, "agent_team_gate_not_found");
    };

    const store = useTeamStore();

    const loaded = await store.load(PROJECT_ID, api, authorize);

    expect(loaded).toBe(true);
    expect(store.currentVersion).toBeNull();
    expect(store.gate).toBeNull();
    expect(store.gateEvents).toEqual([]);
  });
});
