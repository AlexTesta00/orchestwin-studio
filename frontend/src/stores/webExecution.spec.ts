import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import { WebExecutionApiError, type WebExecutionApi } from "../api/webExecution";
import type {
  ApplyWebRepairProposalInput,
  CreateWebRepairProposalInput,
  CreateWebSourceRevisionInput,
  StartWebExecutionInput,
  WebBrowserEvidencePayload,
  WebExecutionAttemptPayload,
  WebRepairProposalPayload,
  WebSourceRevisionPayload,
} from "../types/webExecution";
import { useWebExecutionStore } from "./webExecution";

const PROJECT_A = "00000000-0000-4000-8000-00000000c101";
const PROJECT_B = "00000000-0000-4000-8000-00000000c102";
const REVISION_ID = "00000000-0000-4000-8000-00000000c103";
const EXECUTION_ID = "00000000-0000-4000-8000-00000000c104";

function revision(projectId: string, version = 1): WebSourceRevisionPayload {
  return {
    id: REVISION_ID,
    project_id: projectId,
    created_by_user_id: "00000000-0000-4000-8000-00000000c105",
    version_number: version,
    based_on: null,
    target_selection: {
      target: "WEB_STATIC",
      language_configuration: { frontend: "STATIC_ASSETS", backend: null },
      layout: "SINGLE_ROOT",
    },
    validation_scope_hash: "1".repeat(64),
    origin: "DETERMINISTIC_FIXTURE",
    files: [],
    provenance_references: [],
    related_failure_signature: null,
    created_at: "2026-08-27T14:00:00+00:00",
    source_tree_hash: "2".repeat(64),
    content_hash: "3".repeat(64),
  };
}

function execution(projectId: string): WebExecutionAttemptPayload {
  const source = revision(projectId);
  return {
    id: EXECUTION_ID,
    project_id: projectId,
    created_by_user_id: source.created_by_user_id,
    attempt_number: 1,
    previous_attempt_id: null,
    source_revision: {
      revision_id: source.id,
      project_id: projectId,
      version_number: 1,
      content_hash: source.content_hash,
      source_tree_hash: source.source_tree_hash,
    },
    profile_validation_content_hash: "4".repeat(64),
    execution_plan_content_hash: "5".repeat(64),
    trigger: "PROFILE_VALIDATION",
    executed_phases: ["VALIDATE"],
    report: {
      source_revision_content_hash: source.content_hash,
      source_tree_hash: source.source_tree_hash,
      profile_id: "web.static",
      profile_version: "1.0.0",
      runner_image_digest: "6".repeat(64),
      policy_content_hash: "7".repeat(64),
      status: "INCOMPLETE",
      phase_results: [],
      failure_signatures: [],
    },
    started_at: "2026-08-27T14:00:00+00:00",
    completed_at: "2026-08-27T14:00:01+00:00",
    content_hash: "8".repeat(64),
  };
}

class FakeWebExecutionApi implements WebExecutionApi {
  revisionResult = revision(PROJECT_A);
  executionResult = execution(PROJECT_A);
  browserResult: WebBrowserEvidencePayload | null = null;
  loadGate: Promise<void> | null = null;

  async createSourceRevision(
    projectId: string,
    input: CreateWebSourceRevisionInput,
  ): Promise<WebSourceRevisionPayload> {
    void input;
    return revision(projectId, 2);
  }

  async sourceRevisions(projectId: string): Promise<WebSourceRevisionPayload[]> {
    await this.loadGate;
    return [revision(projectId)];
  }

  async sourceRevision(): Promise<WebSourceRevisionPayload> {
    return this.revisionResult;
  }

  async startExecution(
    projectId: string,
    input: StartWebExecutionInput,
  ): Promise<WebExecutionAttemptPayload> {
    void input;
    return execution(projectId);
  }

  async executions(projectId: string): Promise<WebExecutionAttemptPayload[]> {
    await this.loadGate;
    return [execution(projectId)];
  }

  async execution(): Promise<WebExecutionAttemptPayload> {
    return this.executionResult;
  }

  async executionReport() {
    return this.executionResult.report;
  }

  async browserEvidence(): Promise<WebBrowserEvidencePayload> {
    if (this.browserResult === null) {
      throw new WebExecutionApiError("not found", {
        status: 404,
        code: "WEB_EXECUTION_RESOURCE_NOT_FOUND",
        payload: null,
      });
    }
    return this.browserResult;
  }

  async repairProposals(): Promise<WebRepairProposalPayload[]> {
    return [];
  }

  async createRepairProposal(
    executionId: string,
    input: CreateWebRepairProposalInput,
  ): Promise<WebRepairProposalPayload> {
    void executionId;
    void input;
    throw new Error("not configured");
  }

  async applyRepairProposal(
    projectId: string,
    proposalId: string,
    input: ApplyWebRepairProposalInput,
  ): Promise<WebSourceRevisionPayload> {
    void proposalId;
    void input;
    return revision(projectId, 2);
  }
}

const authorize = async <T>(operation: (accessToken: string) => Promise<T>): Promise<T> =>
  operation("token");

describe("Web execution store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("loads canonical project revision and attempt histories", async () => {
    const store = useWebExecutionStore();
    const api = new FakeWebExecutionApi();

    await store.loadProject(PROJECT_A, authorize, api);

    expect(store.currentSourceRevision?.project_id).toBe(PROJECT_A);
    expect(store.currentExecution?.project_id).toBe(PROJECT_A);
    expect(store.isBusy).toBe(false);
    expect(store.errorCode).toBeNull();
  });

  it("ignores stale results after another project becomes active", async () => {
    const store = useWebExecutionStore();
    const api = new FakeWebExecutionApi();
    let release!: () => void;
    api.loadGate = new Promise<void>((resolve) => {
      release = resolve;
    });

    const firstLoad = store.loadProject(PROJECT_A, authorize, api);
    store.activateProject(PROJECT_B);
    release();
    await firstLoad;

    expect(store.activeProjectId).toBe(PROJECT_B);
    expect(store.sourceRevisions).toEqual([]);
    expect(store.executions).toEqual([]);
  });

  it("treats missing browser evidence as optional while preserving the report", async () => {
    const store = useWebExecutionStore();
    const api = new FakeWebExecutionApi();

    await store.loadExecution(PROJECT_A, EXECUTION_ID, authorize, api);

    expect(store.selectedExecution?.id).toBe(EXECUTION_ID);
    expect(store.selectedReport?.profile_id).toBe("web.static");
    expect(store.browserEvidence).toBeNull();
    expect(store.errorCode).toBeNull();
  });

  it("appends applied repair revisions without mutating prior versions", async () => {
    const store = useWebExecutionStore();
    const api = new FakeWebExecutionApi();
    await store.loadProject(PROJECT_A, authorize, api);

    const applied = await store.applyRepairProposal(
      PROJECT_A,
      EXECUTION_ID,
      "00000000-0000-4000-8000-00000000c106",
      {
        base_revision_content_hash: "3".repeat(64),
        proposal_content_hash: "9".repeat(64),
        approval_id: null,
      },
      authorize,
      api,
    );

    expect(applied.version_number).toBe(2);
    expect(store.sourceRevisions.map((item) => item.version_number)).toEqual([1, 2]);
  });
});
