import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import { RequirementsApiError, type RequirementsApi } from "../api/requirements";
import type {
  RequirementsCoveragePayload,
  RequirementsReadinessPayload,
  RequirementsRevisionPayload,
  RequirementsSpecificationDiffPayload,
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

const DIFF: RequirementsSpecificationDiffPayload = {
  id: "00000000-0000-4000-8000-000000000060",
  project_id: PROJECT_ID,
  base_version_id: VERSION_ID,
  base_version_number: 1,
  base_content_hash: VERSION.content_hash,
  proposed_content_hash: "1".repeat(64),
  proposal_hash: "2".repeat(64),
  status: "PROPOSED",
  proposed_specification: VERSION.specification,
  operations: [],
  created_by_user_id: OWNER_ID,
  created_at: CREATED_AT,
  decided_by_user_id: null,
  decided_at: null,
  decision_reason: null,
  applied_specification_version_id: null,
};

const PROPOSED_CHANGE: RequirementsRevisionPayload = {
  status: "CREATED",
  diff: DIFF,
  version: null,
  issue: null,
  proposal_issue: null,
  diff_persistence_status: "APPENDED",
  version_persistence_status: null,
};

const REQUEST = "Add the search by the name of the guest.";

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

  changeRequests: string[] = [];
  changeResult: RequirementsRevisionPayload | Error = PROPOSED_CHANGE;

  async requestChange(projectId: string, request: string, accessToken: string) {
    void projectId;
    void accessToken;
    this.changeRequests.push(request);

    if (this.changeResult instanceof Error) {
      throw this.changeResult;
    }

    return this.changeResult;
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

  it("stays loading until the last of two loads that overlap has finished", async () => {
    const store = useRequirementsStore();
    const api = new FakeRequirementsApi();
    let release: () => void = () => undefined;
    const waiting = new Promise<void>((resolve) => {
      release = resolve;
    });
    let first = true;
    api.history = async () => {
      if (first) {
        first = false;
        return [];
      }
      await waiting;
      return [VERSION];
    };

    const earlier = store.load(PROJECT_ID, authorize, api);
    const later = store.load(PROJECT_ID, authorize, api);
    await earlier;

    expect(store.pending.load).toBe(true);
    expect(store.isBusy).toBe(true);

    release();
    await later;

    expect(store.pending.load).toBe(false);
    expect(store.history).toEqual([VERSION]);
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

  it("does not let an older load erase a newly generated specification", async () => {
    const store = useRequirementsStore();
    const api = new FakeRequirementsApi();
    let release!: () => void;
    let started!: () => void;
    const waiting = new Promise<void>((resolve) => {
      release = resolve;
    });
    const historyStarted = new Promise<void>((resolve) => {
      started = resolve;
    });
    let first = true;
    api.history = async () => {
      if (first) {
        first = false;
        started();
        await waiting;
        return [];
      }
      return [VERSION];
    };
    const staleLoad = store.load(PROJECT_ID, authorize, api);
    await historyStarted;
    api.readinessResult = {
      status: "REQUIREMENTS_APPROVAL_REQUIRED",
      version: VERSION,
      gate: null,
      approved_current_specification: false,
    };
    await store.generate(PROJECT_ID, authorize, api);
    release();
    await staleLoad;
    expect(store.current).toEqual(VERSION);
    expect(store.traceability).toEqual(TRACEABILITY);
    expect(store.coverage).toEqual(COVERAGE);
    expect(store.readiness?.status).toBe("REQUIREMENTS_APPROVAL_REQUIRED");
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

  it("keeps the requirements written from a request as a proposed revision", async () => {
    const store = useRequirementsStore();
    const api = new FakeRequirementsApi();
    let release!: (value: RequirementsRevisionPayload) => void;
    api.requestChange = async (projectId: string, request: string) => {
      void projectId;
      api.changeRequests.push(request);
      return new Promise<RequirementsRevisionPayload>((resolve) => {
        release = resolve;
      });
    };

    const pending = store.requestChange(PROJECT_ID, REQUEST, authorize, api);

    expect(store.pending["request-change"]).toBe(true);
    expect(store.isBusy).toBe(true);
    release(PROPOSED_CHANGE);
    await expect(pending).resolves.toEqual(PROPOSED_CHANGE);

    expect(api.changeRequests).toEqual([REQUEST]);
    expect(store.pendingDiffs).toEqual([DIFF]);
    expect(store.changeRequests).toEqual({ [DIFF.id]: REQUEST });
    expect(store.current).toBeNull();
    expect(store.isBusy).toBe(false);
    expect(store.error).toBeNull();
  });

  it("keeps the code of a refused request and hands the error back", async () => {
    const store = useRequirementsStore();
    const api = new FakeRequirementsApi();
    const refusal = new RequirementsApiError("REQUIREMENTS_UNCHANGED", {
      status: 409,
      code: "REQUIREMENTS_UNCHANGED",
      payload: { detail: { code: "REQUIREMENTS_UNCHANGED" } },
    });
    api.changeResult = refusal;

    await expect(store.requestChange(PROJECT_ID, REQUEST, authorize, api)).rejects.toBe(refusal);

    expect(store.error).toEqual({
      message: "REQUIREMENTS_UNCHANGED",
      code: "REQUIREMENTS_UNCHANGED",
      status: 409,
    });
    expect(store.pendingDiffs).toEqual([]);
    expect(store.changeRequests).toEqual({});
    expect(store.isBusy).toBe(false);
  });

  it("drops a revision that arrives after another project became active", async () => {
    const store = useRequirementsStore();
    const api = new FakeRequirementsApi();
    let release!: (value: RequirementsRevisionPayload) => void;
    api.requestChange = async () =>
      new Promise<RequirementsRevisionPayload>((resolve) => {
        release = resolve;
      });

    const pending = store.requestChange(PROJECT_ID, REQUEST, authorize, api);
    store.activateProject(SECOND_PROJECT_ID);
    release(PROPOSED_CHANGE);
    await pending;

    expect(store.projectId).toBe(SECOND_PROJECT_ID);
    expect(store.diffs).toEqual({});
    expect(store.changeRequests).toEqual({});
  });
});
