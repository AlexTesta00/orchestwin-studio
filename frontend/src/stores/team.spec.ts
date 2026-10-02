import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import type {
  AgentCatalogResponse,
  AgentTeamApi,
  PerspectiveView,
  TeamProposalEditInput,
  TeamProposalVersionResponse,
  TeamSelectionIssueResponse,
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
      agent_id: "BACKEND_ENGINEER",
      catalog_version: 1,
      kind: "SPECIALIST",
      selection_policy: "OWNER_SELECTABLE",
      capabilities: ["BACKEND_ENGINEERING"],
      supported_project_modes: ["GREENFIELD_GENERATION"],
      name_key: "agentCatalog.roles.backend_engineer.name",
      description_key: "agentCatalog.roles.backend_engineer.description",
      is_always_present: false,
    },
  ],
};

const NO_WORDS = { fields: [], terms: [] } as const;

const CONTESTED_SERVICES: PerspectiveView = {
  key: "SOFTWARE_ENGINEERING",
  standing: "ALWAYS",
  applied: true,
  editable: false,
  agent_id: null,
  requested: NO_WORDS,
  excluded: NO_WORDS,
  aspects: [
    {
      key: "SERVICES",
      agent_id: "BACKEND_ENGINEER",
      standing: "CONTESTED",
      applied: false,
      editable: true,
      requested: { fields: ["technical_constraints"], terms: ["api"] },
      excluded: { fields: ["description"], terms: ["senza server"] },
    },
  ],
};

const CONTRADICTION: TeamSelectionIssueResponse = {
  code: "CONTRADICTORY_ROLE_SIGNALS",
  agent_id: "BACKEND_ENGINEER",
  mandatory_reasons: [
    {
      code: "BACKEND_DELIVERY_SIGNAL",
      evidence: { fields: ["technical_constraints"], terms: ["api"] },
    },
  ],
  impossible_reasons: [
    {
      code: "EXPLICIT_SCOPE_EXCLUSION",
      evidence: { fields: ["description"], terms: ["senza server"] },
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
      agent_id: "BACKEND_ENGINEER",
      kind: "CONFLICT",
      owner_editable: true,
      reasons: [...CONTRADICTION.mandatory_reasons, ...CONTRADICTION.impossible_reasons],
    },
  ],
  constraint_issues: [CONTRADICTION],
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
  perspectives: [CONTESTED_SERVICES],

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

  it("loads catalog, proposal with its perspectives, gate, events, and readiness", async () => {
    const store = useTeamStore();

    const loaded = await store.load(PROJECT_ID, buildApi(), authorize);

    expect(loaded).toBe(true);
    expect(store.catalog).toEqual(CATALOG);
    expect(store.currentVersion).toEqual(VERSION);
    expect(store.currentVersion?.perspectives).toEqual([CONTESTED_SERVICES]);
    expect(store.history).toEqual([VERSION]);
    expect(store.gate).toEqual(GATE);
    expect(store.gateEvents).toHaveLength(1);
    expect(store.readiness?.status).toBe("TEAM_APPROVAL_REQUIRED");
    expect(store.errorDetail).toBeNull();
  });

  it("treats a generation that lists the contradictions of the brief as a created version", async () => {
    const api = buildApi();
    let generated: TeamProposalVersionResponse | null = null;

    api.generateProjectTeamProposal = async () => {
      generated = VERSION;

      return {
        status: "CREATED",
        version: VERSION,
        issues: [CONTRADICTION],
      };
    };
    api.getCurrentProjectTeamProposal = async () => {
      if (generated === null) throw new ApiError(404, "team_proposal_not_found");

      return generated;
    };

    const store = useTeamStore();

    await store.load(PROJECT_ID, api, authorize);
    expect(store.currentVersion).toBeNull();

    const result = await store.generateProposal(PROJECT_ID, api, authorize);

    expect(result?.status).toBe("CREATED");
    expect(result?.issues).toEqual([CONTRADICTION]);
    expect(store.lastGeneration).toEqual(result);
    expect(store.currentVersion).toEqual(VERSION);
    expect(store.currentVersion?.perspectives?.[0]?.aspects[0]?.standing).toBe("CONTESTED");
    expect(store.errorDetail).toBeNull();
    expect(store.busy).toBe(false);
  });

  it("sends the complete selection of the owner and no rationale", async () => {
    const store = useTeamStore();
    const api = buildApi();
    const edit = vi.spyOn(api, "editCurrentProjectTeamProposal");

    await store.load(PROJECT_ID, api, authorize);

    const result = await store.editCurrent(
      PROJECT_ID,
      ["REQUIREMENTS_ANALYST", "BACKEND_ENGINEER"],
      api,
      authorize,
    );

    expect(edit).toHaveBeenCalledTimes(1);
    expect(edit.mock.calls[0]?.slice(0, 2)).toEqual(["access-token", PROJECT_ID]);
    expect(edit.mock.calls[0]?.[2]).toStrictEqual<TeamProposalEditInput>({
      selected_agent_ids: ["REQUIREMENTS_ANALYST", "BACKEND_ENGINEER"],
    });
    expect(result?.status).toBe("UPDATED");
    expect(store.lastEdit?.version?.selected_agent_ids).toEqual([
      "REQUIREMENTS_ANALYST",
      "BACKEND_ENGINEER",
    ]);
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
