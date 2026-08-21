import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import type { DesignApi } from "../api/design";
import type {
  DesignPackageDiffPayload,
  DesignPackagePayload,
  DesignPackageVersionPayload,
  DesignReadinessPayload,
  HumanGatePayload,
} from "../types/design";
import { type AuthorizedRequest, useDesignStore } from "./design";

const PROJECT_ID = "00000000-0000-4000-8000-000000000010";
const SECOND_PROJECT_ID = "00000000-0000-4000-8000-000000000011";
const VERSION_ID = "00000000-0000-4000-8000-000000000020";
const OWNER_ID = "00000000-0000-4000-8000-000000000001";
const ALTERNATIVE_ID = "00000000-0000-4000-8000-000000000030";
const SECOND_ALTERNATIVE_ID = "00000000-0000-4000-8000-000000000031";
const TWIN_ID = "00000000-0000-4000-8000-000000000040";
const DIFF_ID = "00000000-0000-4000-8000-000000000050";
const GATE_ID = "00000000-0000-4000-8000-000000000060";
const CREATED_AT = "2026-08-21T09:00:00Z";

const PACKAGE: DesignPackagePayload = {
  schema_version: 1,
  project_id: PROJECT_ID,
  grounding: {
    requirements_reference: {
      kind: "REQUIREMENTS_SPECIFICATION",
      artifact_id: "00000000-0000-4000-8000-000000000070",
      version_number: 1,
      content_hash: "a".repeat(64),
    },
    agent_team_reference: {
      kind: "AGENT_TEAM",
      artifact_id: "00000000-0000-4000-8000-000000000071",
      version_number: 1,
      content_hash: "b".repeat(64),
    },
    user_modeling_reference: {
      kind: "USER_MODELING",
      artifact_id: "00000000-0000-4000-8000-000000000072",
      version_number: 1,
      content_hash: "c".repeat(64),
    },
    catalog: {
      version: 1,
      content_hash: "d".repeat(64),
    },
    requirement_ids: ["00000000-0000-4000-8000-000000000080"],
    user_story_ids: ["00000000-0000-4000-8000-000000000081"],
    acceptance_criterion_ids: ["00000000-0000-4000-8000-000000000082"],
    user_twin_references: [
      {
        twin_id: TWIN_ID,
        version_number: 1,
        content_hash: "e".repeat(64),
        name: "Receptionist Twin",
      },
    ],
  },
  alternatives: [
    {
      id: ALTERNATIVE_ID,
      code: "DES-001",
      approach: "GUIDED_WORKFLOW",
      title: "Guided reservation flow",
      summary: "Guide the receptionist through a bounded sequence.",
      rationale: "Keep the current task and recovery state visible.",
      requirement_ids: ["00000000-0000-4000-8000-000000000080"],
      user_story_ids: ["00000000-0000-4000-8000-000000000081"],
      acceptance_criterion_ids: ["00000000-0000-4000-8000-000000000082"],
      user_twin_references: [
        {
          twin_id: TWIN_ID,
          version_number: 1,
          content_hash: "e".repeat(64),
          name: "Receptionist Twin",
        },
      ],
      workflows: [],
      information_architecture: ["Availability", "Reservation", "Confirmation"],
      accessibility_considerations: ["Use persistent labels."],
      security_considerations: ["Minimize guest data in summaries."],
      advantages: ["Clear progression."],
      trade_offs: ["More navigation for experienced users."],
      assumptions: [],
      open_questions: [],
    },
    {
      id: SECOND_ALTERNATIVE_ID,
      code: "DES-002",
      approach: "DASHBOARD_FIRST",
      title: "Reservation operations dashboard",
      summary: "Keep status and frequent actions visible together.",
      rationale: "Support rapid orientation across operational tasks.",
      requirement_ids: ["00000000-0000-4000-8000-000000000080"],
      user_story_ids: ["00000000-0000-4000-8000-000000000081"],
      acceptance_criterion_ids: ["00000000-0000-4000-8000-000000000082"],
      user_twin_references: [
        {
          twin_id: TWIN_ID,
          version_number: 1,
          content_hash: "e".repeat(64),
          name: "Receptionist Twin",
        },
      ],
      workflows: [],
      information_architecture: ["Overview", "Work queue", "Status"],
      accessibility_considerations: ["Expose status programmatically."],
      security_considerations: ["Reveal detailed guest data deliberately."],
      advantages: ["Fast access to frequent actions."],
      trade_offs: ["Higher information density."],
      assumptions: [],
      open_questions: [],
    },
  ],
  critiques: [],
  recommended_alternative_id: ALTERNATIVE_ID,
  owner_selected_alternative_id: ALTERNATIVE_ID,
  prototype: null,
  concerns: [],
  open_questions: [],
};

const VERSION: DesignPackageVersionPayload = {
  id: VERSION_ID,
  project_id: PROJECT_ID,
  version_number: 1,
  based_on_version_number: null,
  content_hash: "f".repeat(64),
  package: PACKAGE,
  created_by_user_id: OWNER_ID,
  created_at: CREATED_AT,
  ready_for_gate: false,
};

const READINESS_EMPTY: DesignReadinessPayload = {
  status: "DESIGN_REQUIRED",
  version: null,
  gate: null,
  has_package: false,
  package_ready_for_gate: false,
  approved_current_package: false,
};

const PENDING_GATE: HumanGatePayload = {
  id: GATE_ID,
  project_id: PROJECT_ID,
  owner_user_id: OWNER_ID,
  gate_type: "DESIGN",
  artifact: {
    project_id: PROJECT_ID,
    gate_type: "DESIGN",
    artifact_id: VERSION_ID,
    version: 1,
    content_hash: VERSION.content_hash,
  },
  iteration: 1,
  max_iterations: 3,
  status: "PENDING_APPROVAL",
  created_at: CREATED_AT,
  updated_at: CREATED_AT,
  event_sequence: 1,
  resume_status: null,
};

const DIFF: DesignPackageDiffPayload = {
  id: DIFF_ID,
  project_id: PROJECT_ID,
  owner_user_id: OWNER_ID,
  base_version_id: VERSION_ID,
  base_version_number: 1,
  base_content_hash: VERSION.content_hash,
  proposed_package: PACKAGE,
  proposal_hash: "1".repeat(64),
  changes: [
    {
      kind: "REPLACE",
      artifact_kind: "SELECTION",
      artifact_id: ALTERNATIVE_ID,
      before: null,
      after: {
        owner_selected_alternative_id: ALTERNATIVE_ID,
      },
    },
  ],
  status: "PROPOSED",
  created_at: CREATED_AT,
  decided_by_user_id: null,
  decided_at: null,
  decision_reason: null,
  applied_version_id: null,
  content_hash: "2".repeat(64),
};

const authorize: AuthorizedRequest = <T>(operation: (accessToken: string) => Promise<T>) =>
  operation("access-token");

class FakeDesignApi implements DesignApi {
  readinessResult: DesignReadinessPayload = READINESS_EMPTY;
  historyResult: DesignPackageVersionPayload[] = [];
  diffsResult: DesignPackageDiffPayload[] = [];
  generationResult = {
    status: "CREATED" as const,
    version: VERSION,
    issue: null,
    proposal_issue: null,
    persistence_status: "APPENDED" as const,
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
    this.diffsResult = [DIFF];

    return {
      status: "CREATED" as const,
      diff: DIFF,
      version: null,
      issue: null,
      domain_issue: null,
      diff_persistence_status: "CREATED" as const,
      version_persistence_status: null,
    };
  }

  async revisionHistory(projectId: string, accessToken: string) {
    void projectId;
    void accessToken;
    return this.diffsResult;
  }

  async getRevision(projectId: string, diffId: string, accessToken: string) {
    void projectId;
    void diffId;
    void accessToken;
    return DIFF;
  }

  async decideRevision(projectId: string, diffId: string, request: unknown, accessToken: string) {
    void projectId;
    void diffId;
    void request;
    void accessToken;
    const decided = {
      ...DIFF,
      status: "APPROVED" as const,
      decided_by_user_id: OWNER_ID,
      decided_at: CREATED_AT,
      applied_version_id: VERSION_ID,
    };
    this.diffsResult = [decided];

    return {
      status: "APPLIED" as const,
      diff: decided,
      version: VERSION,
      issue: null,
      domain_issue: null,
      diff_persistence_status: "UPDATED" as const,
      version_persistence_status: "APPENDED" as const,
    };
  }

  async submitGate(projectId: string, accessToken: string) {
    void projectId;
    void accessToken;
    this.readinessResult = {
      status: "DESIGN_APPROVAL_REQUIRED",
      version: VERSION,
      gate: PENDING_GATE,
      has_package: true,
      package_ready_for_gate: true,
      approved_current_package: false,
    };

    return {
      status: "SUBMITTED" as const,
      gate: PENDING_GATE,
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
      gate: PENDING_GATE,
      event: null,
      issue: null,
    };
  }

  async currentGate(projectId: string, accessToken: string) {
    void projectId;
    void accessToken;
    return PENDING_GATE;
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

describe("Design store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("loads an empty design stage without treating it as an error", async () => {
    const store = useDesignStore();
    const api = new FakeDesignApi();

    await store.load(PROJECT_ID, authorize, api);

    expect(store.projectId).toBe(PROJECT_ID);
    expect(store.current).toBeNull();
    expect(store.history).toEqual([]);
    expect(store.readiness).toEqual(READINESS_EMPTY);
    expect(store.error).toBeNull();
    expect(store.isBusy).toBe(false);
  });

  it("generates a package and derives recommended and selected alternatives", async () => {
    const store = useDesignStore();
    const api = new FakeDesignApi();
    api.readinessResult = {
      status: "DESIGN_REVIEW_REQUIRED",
      version: VERSION,
      gate: null,
      has_package: true,
      package_ready_for_gate: false,
      approved_current_package: false,
    };
    api.historyResult = [VERSION];

    const result = await store.generate(PROJECT_ID, authorize, api);

    expect(result.version).toEqual(VERSION);
    expect(store.current).toEqual(VERSION);
    expect(store.history).toEqual([VERSION]);
    expect(store.recommendedAlternative?.id).toBe(ALTERNATIVE_ID);
    expect(store.selectedAlternative?.id).toBe(ALTERNATIVE_ID);
  });

  it("tracks a reviewable Design Package diff", async () => {
    const store = useDesignStore();
    const api = new FakeDesignApi();

    const result = await store.proposeRevision(PROJECT_ID, PACKAGE, authorize, api);

    expect(result.diff).toEqual(DIFF);
    expect(store.pendingDiffs).toEqual([DIFF]);
  });

  it("ignores a stale load after another project becomes active", async () => {
    const store = useDesignStore();
    const api = new FakeDesignApi();
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
