import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import { ExecutionApiError, type ExecutionApi } from "../api/execution";
import type {
  BrownfieldCapabilityPayload,
  BrownfieldIntakeSummaryPayload,
  BrownfieldInventoryPayload,
  ExecutionProfilePayload,
  HighImpactOperationPayload,
  HighImpactOperationResponsePayload,
  HighImpactReadinessPayload,
  SandboxLogsPayload,
  SandboxRunPayload,
} from "../types/execution";
import { type AuthorizedRequest, useExecutionStore } from "./execution";

const PROJECT_ID = "00000000-0000-4000-8000-000000008101";
const SECOND_PROJECT_ID = "00000000-0000-4000-8000-000000008102";
const INTAKE_ID = "00000000-0000-4000-8000-000000008103";
const REQUEST_ID = "00000000-0000-4000-8000-000000008104";
const CREATED_AT = "2026-08-25T17:00:00Z";

const INTAKE: BrownfieldIntakeSummaryPayload = {
  id: INTAKE_ID,
  project_id: PROJECT_ID,
  version_number: 1,
  based_on_version_number: null,
  content_hash: "a".repeat(64),
  archive_sha256: "b".repeat(64),
  archive_size_bytes: 128,
  archive_storage_key: `sha256/bb/${"b".repeat(64)}.zip`,
  inventory_content_hash: "c".repeat(64),
  capability_status: "DESIGN_ONLY_LEVEL_C_SELECTED",
  effective_capability_status: "DESIGN_ONLY_LEVEL_C",
  selected_profile_reference: {
    profile_id: "WEB_STATIC",
    profile_version: "1.0.0",
    content_hash: "d".repeat(64),
  },
  created_by_user_id: "00000000-0000-4000-8000-000000008105",
  created_at: CREATED_AT,
};

const INVENTORY: BrownfieldInventoryPayload = {
  intake: INTAKE,
  inventory: {
    content_hash: INTAKE.inventory_content_hash,
    entries: [],
  },
};

const CAPABILITY: BrownfieldCapabilityPayload = {
  intake: INTAKE,
  capability: {
    status: "DESIGN_ONLY_LEVEL_C_SELECTED",
    effective_capability_status: "DESIGN_ONLY_LEVEL_C",
  },
};

const PROFILE: ExecutionProfilePayload = {
  profile_id: "WEB_STATIC",
  name: "Static Web",
  version: "1.0.0",
  capability_status: "DESIGN_ONLY_LEVEL_C",
  supported_targets: ["WEB_STATIC"],
  file_indicators: ["html.source"],
  required_runners: [],
  base_images: [],
  network_policy: { BUILD: "DISABLED" },
  resource_defaults: {
    cpu_count: 2,
    memory_mib: 4096,
    pids_limit: 256,
    writable_tmpfs_mib: 512,
  },
  command_schema_version: 1,
  maintainer: "OrchesTwin Studio",
  license_notes: "Design-only descriptor.",
  validation_evidence_refs: [],
  requires_owner_approval: false,
  content_hash: "d".repeat(64),
};

const OPERATION: HighImpactOperationPayload = {
  version: {
    id: REQUEST_ID,
    project_id: PROJECT_ID,
    version_number: 1,
    based_on_version_number: null,
    content_hash: "e".repeat(64),
    request: {},
    created_by_user_id: INTAKE.created_by_user_id,
    created_at: CREATED_AT,
  },
  classification: {
    request_reference: {},
    policy_content_hash: "f".repeat(64),
    classification: "REQUIRES_OWNER_APPROVAL",
    reasons: [],
  },
};

const READINESS: HighImpactReadinessPayload = {
  status: "OWNER_APPROVAL_REQUIRED",
  operation: OPERATION,
  gate: null,
};

const authorize: AuthorizedRequest = async <T>(
  operation: (accessToken: string) => Promise<T>,
): Promise<T> => operation("access-token");

class FakeExecutionApi implements ExecutionApi {
  historyResult = { items: [] as BrownfieldIntakeSummaryPayload[] };
  capabilityResult: BrownfieldCapabilityPayload | null = null;
  profilesResult = [PROFILE];
  sandboxRunsResult: SandboxRunPayload[] = [];
  highImpactOperationsResult: HighImpactOperationPayload[] = [];
  readinessResult = READINESS;
  uploaded = false;

  async uploadSourceArchive() {
    this.uploaded = true;
    this.historyResult = { items: [INTAKE] };
    this.capabilityResult = CAPABILITY;
    return INTAKE;
  }

  async sourceArchiveHistory() {
    return this.historyResult;
  }

  async sourceInventory() {
    return INVENTORY;
  }

  async capabilities() {
    if (this.capabilityResult === null) {
      throw new ExecutionApiError("not found", {
        status: 404,
        code: "BROWNFIELD_INTAKE_NOT_FOUND",
        payload: null,
      });
    }
    return this.capabilityResult;
  }

  async profiles() {
    return this.profilesResult;
  }

  async profile() {
    return PROFILE;
  }

  async sandboxRuns() {
    return this.sandboxRunsResult;
  }

  async sandboxRun(): Promise<SandboxRunPayload> {
    throw new Error("not configured");
  }

  async sandboxLogs(): Promise<SandboxLogsPayload> {
    throw new Error("not configured");
  }

  async highImpactOperations() {
    return this.highImpactOperationsResult;
  }

  async createHighImpactOperation(): Promise<HighImpactOperationResponsePayload> {
    this.highImpactOperationsResult = [OPERATION];
    return {
      status: "CREATED",
      operation: OPERATION,
      gate: null,
      event: null,
    };
  }

  async submitHighImpactGate(): Promise<HighImpactOperationResponsePayload> {
    return {
      status: "SUBMITTED",
      operation: OPERATION,
      gate: null,
      event: null,
    };
  }

  async decideHighImpactGate(): Promise<HighImpactOperationResponsePayload> {
    return {
      status: "APPLIED",
      operation: OPERATION,
      gate: null,
      event: null,
    };
  }

  async highImpactReadiness() {
    return this.readinessResult;
  }

  async highImpactEvents() {
    return [];
  }
}

describe("Execution store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("loads capability-honest project state and updates it after a source upload", async () => {
    const api = new FakeExecutionApi();
    const store = useExecutionStore();

    await store.load(PROJECT_ID, authorize, api);

    expect(store.profiles).toEqual([PROFILE]);
    expect(store.intakes).toEqual([]);
    expect(store.capability).toBeNull();

    await store.uploadSourceArchive(
      PROJECT_ID,
      new File(["archive"], "source.zip", { type: "application/zip" }),
      { requestedTarget: "WEB_STATIC" },
      authorize,
      api,
    );

    expect(api.uploaded).toBe(true);
    expect(store.currentIntake).toEqual(INTAKE);
    expect(store.inventory).toEqual(INVENTORY);
    expect(store.selectedCapability).toBe("DESIGN_ONLY_LEVEL_C");
    expect(store.error).toBeNull();
  });

  it("keeps exact Gate 7 state and discards stale project responses", async () => {
    const api = new FakeExecutionApi();
    const store = useExecutionStore();
    let resolveHistory!: (value: { items: BrownfieldIntakeSummaryPayload[] }) => void;
    const delayedHistory = new Promise<{ items: BrownfieldIntakeSummaryPayload[] }>((resolve) => {
      resolveHistory = resolve;
    });
    api.sourceArchiveHistory = async () => delayedHistory;
    const load = store.load(PROJECT_ID, authorize, api);

    store.activateProject(SECOND_PROJECT_ID);
    resolveHistory({ items: [INTAKE] });
    await load;

    expect(store.projectId).toBe(SECOND_PROJECT_ID);
    expect(store.intakes).toEqual([]);

    await store.createHighImpactOperation(
      SECOND_PROJECT_ID,
      {
        operation_kind: "SANDBOX_EXECUTION",
        summary: "Execute the reviewed plan.",
        profile_reference: {
          profile_id: "custom.web",
          profile_version: "1.0.0",
          content_hash: "1".repeat(64),
        },
        capability_status: "EXPERIMENTAL_LEVEL_D",
        command_plan_id: "web.validation",
        command_plan_content_hash: "2".repeat(64),
        image_reference: `example/web@sha256:${"3".repeat(64)}`,
        network_mode: "CONTROLLED",
        secret_reference_ids: [],
        resources: {
          cpu_count: 2,
          memory_mib: 4096,
          pids_limit: 256,
          writable_tmpfs_mib: 512,
        },
        destructive_workspace_paths: [],
        requests_privileged_container: false,
        requests_docker_socket_mount: false,
        requests_host_filesystem_mount: false,
        requests_arbitrary_host_command: false,
      },
      authorize,
      api,
    );

    expect(store.highImpactOperations).toEqual([OPERATION]);
    expect(store.highImpactReadiness).toEqual(READINESS);
    expect(store.requiresHighImpactApproval).toBe(true);
  });
});
