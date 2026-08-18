import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import type { RequirementsApi } from "../api/requirements";
import type {
  RequirementsCoveragePayload,
  RequirementsReadinessPayload,
  RequirementsSpecificationVersionPayload,
  RequirementsTraceabilityPayload,
} from "../types/requirements";
import { type AuthorizedRequest, useRequirementsStore } from "./requirements";

const PROJECT_ID = "00000000-0000-4000-8000-000000000010";
const SECOND_PROJECT_ID = "00000000-0000-4000-8000-000000000011";
const VERSION_ID = "00000000-0000-4000-8000-000000000020";
const OWNER_ID = "00000000-0000-4000-8000-000000000001";
const CREATED_AT = "2026-08-18T12:00:00Z";

const VERSION: RequirementsSpecificationVersionPayload = {
  id: VERSION_ID,
  project_id: PROJECT_ID,
  version_number: 1,
  based_on_version_number: null,
  content_hash: "a".repeat(64),
  created_by_user_id: OWNER_ID,
  created_at: CREATED_AT,
  specification: {
    project_id: PROJECT_ID,
    project_brief_reference: {
      kind: "PROJECT_BRIEF",
      artifact_id: "00000000-0000-4000-8000-000000000030",
      version_number: 1,
      content_hash: "b".repeat(64),
    },
    agent_team_reference: {
      kind: "AGENT_TEAM",
      artifact_id: "00000000-0000-4000-8000-000000000040",
      version_number: 1,
      content_hash: "c".repeat(64),
    },
    user_modeling_reference: {
      kind: "USER_MODELING",
      artifact_id: "00000000-0000-4000-8000-000000000050",
      version_number: 1,
      content_hash: "d".repeat(64),
    },
    catalog_version: 1,
    catalog_content_hash: "e".repeat(64),
    user_twin_references: [],
    requirements: [],
    user_stories: [],
    acceptance_criteria: [],
    scenarios: [],
    risks: [],
    definition_of_done: [],
  },
};

const READINESS_EMPTY: RequirementsReadinessPayload = {
  status: "REQUIREMENTS_REQUIRED",
  version: null,
  gate: null,
  approved_current_specification: false,
};

const TRACEABILITY: RequirementsTraceabilityPayload = {
  project_id: PROJECT_ID,
  specification_version_id: VERSION_ID,
  specification_version_number: 1,
  specification_content_hash: VERSION.content_hash,
  content_hash: "f".repeat(64),
  nodes: [],
  links: [],
};

const COVERAGE: RequirementsCoveragePayload = {
  project_id: PROJECT_ID,
  specification_version_id: VERSION_ID,
  requirement_count: 0,
  user_story_count: 0,
  acceptance_criterion_count: 0,
  requirement_ids_without_user_stories: [],
  requirement_ids_without_acceptance_criteria: [],
  user_story_ids_without_acceptance_criteria: [],
  acceptance_criterion_ids_without_scenarios: [],
  has_full_acceptance_coverage: true,
};

const authorize: AuthorizedRequest = <T>(operation: (accessToken: string) => Promise<T>) =>
  operation("access-token");

class FakeRequirementsApi implements RequirementsApi {
  readinessResult: RequirementsReadinessPayload = READINESS_EMPTY;
  historyResult: RequirementsSpecificationVersionPayload[] = [];
  generationResult = {
    status: "CREATED" as const,
    version: VERSION,
    issue: null,
    proposal_issue: null,
    persistence_status: null,
  };

  async generate(projectId: string, accessToken: string) {
    void projectId;
    void accessToken;
    return this.generationResult;
  }

  async current(projectId: string, accessToken: string) {
    void projectId;
    void accessToken;
    return VERSION;
  }

  async history(projectId: string, accessToken: string) {
    void projectId;
    void accessToken;
    return this.historyResult;
  }

  async proposeRevision(projectId: string, request: unknown, accessToken: string) {
    void projectId;
    void request;
    void accessToken;
    return {
      status: "REJECTED" as const,
      diff: null,
      version: null,
      issue: "INVALID_PROPOSAL",
      proposal_issue: null,
      diff_persistence_status: null,
      version_persistence_status: null,
    };
  }

  async revisionHistory(projectId: string, accessToken: string) {
    void projectId;
    void accessToken;
    return [];
  }

  async getRevision(projectId: string, diffId: string, accessToken: string): Promise<never> {
    void projectId;
    void diffId;
    void accessToken;
    throw new Error("Not configured");
  }

  async decideRevision(
    projectId: string,
    diffId: string,
    request: unknown,
    accessToken: string,
  ): Promise<never> {
    void projectId;
    void diffId;
    void request;
    void accessToken;
    throw new Error("Not configured");
  }

  async traceability(projectId: string, accessToken: string) {
    void projectId;
    void accessToken;
    return TRACEABILITY;
  }

  async coverage(projectId: string, accessToken: string) {
    void projectId;
    void accessToken;
    return COVERAGE;
  }

  async submitGate(projectId: string, accessToken: string) {
    void projectId;
    void accessToken;
    return {
      status: "SUBMITTED" as const,
      gate: null,
      events: [],
      issue: null,
    };
  }

  async decideGate(projectId: string, request: unknown, accessToken: string) {
    void projectId;
    void request;
    void accessToken;
    return {
      status: "APPLIED" as const,
      gate: null,
      event: null,
      issue: null,
    };
  }

  async currentGate(projectId: string, accessToken: string): Promise<never> {
    void projectId;
    void accessToken;
    throw new Error("Not configured");
  }

  async gateEvents(projectId: string, accessToken: string) {
    void projectId;
    void accessToken;
    return [];
  }

  async readiness(projectId: string, accessToken: string) {
    void projectId;
    void accessToken;
    return this.readinessResult;
  }
}

describe("Requirements store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("loads an empty requirements stage without treating it as an error", async () => {
    const store = useRequirementsStore();
    const api = new FakeRequirementsApi();

    await store.load(PROJECT_ID, authorize, api);

    expect(store.projectId).toBe(PROJECT_ID);
    expect(store.current).toBeNull();
    expect(store.history).toEqual([]);
    expect(store.readiness).toEqual(READINESS_EMPTY);
    expect(store.error).toBeNull();
    expect(store.isBusy).toBe(false);
  });

  it("generates and refreshes the current specification state", async () => {
    const store = useRequirementsStore();
    const api = new FakeRequirementsApi();
    api.readinessResult = {
      status: "REQUIREMENTS_APPROVAL_REQUIRED",
      version: VERSION,
      gate: null,
      approved_current_specification: false,
    };
    api.historyResult = [VERSION];

    const result = await store.generate(PROJECT_ID, authorize, api);

    expect(result.version).toEqual(VERSION);
    expect(store.current).toEqual(VERSION);
    expect(store.history).toEqual([VERSION]);
    expect(store.traceability).toEqual(TRACEABILITY);
    expect(store.coverage).toEqual(COVERAGE);
  });

  it("ignores a stale load after another project becomes active", async () => {
    const store = useRequirementsStore();
    const api = new FakeRequirementsApi();
    let release: (() => void) | undefined;
    const waiting = new Promise<void>((resolve) => {
      release = resolve;
    });
    const originalReadiness = api.readiness.bind(api);
    api.readiness = async (projectId: string, accessToken: string) => {
      if (projectId === PROJECT_ID) {
        await waiting;
      }

      return originalReadiness(projectId, accessToken);
    };

    const staleLoad = store.load(PROJECT_ID, authorize, api);
    store.activateProject(SECOND_PROJECT_ID);
    const currentLoad = store.load(SECOND_PROJECT_ID, authorize, api);

    await currentLoad;

    if (release === undefined) {
      throw new Error("Stale request release callback was not initialized");
    }

    release();
    await staleLoad;

    expect(store.projectId).toBe(SECOND_PROJECT_ID);
    expect(store.readiness).toEqual(READINESS_EMPTY);
    expect(store.error).toBeNull();
  });
});
