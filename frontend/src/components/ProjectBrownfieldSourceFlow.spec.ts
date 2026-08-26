import { createPinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type { ExecutionApi } from "../api/execution";
import type {
  BrownfieldCapabilityPayload,
  BrownfieldIntakeSummaryPayload,
  BrownfieldInventoryPayload,
  ExecutionProfilePayload,
  HighImpactOperationPayload,
  HighImpactOperationResponsePayload,
  HighImpactReadinessPayload,
  HumanGateEventPayload,
  SandboxLogsPayload,
  SandboxRunPayload,
  SourceArchiveUploadOptions,
} from "../types/execution";
import ProjectBrownfieldSourceFlow from "./ProjectBrownfieldSourceFlow.vue";

const PROJECT_ID = "00000000-0000-4000-8000-000000009001";
const INTAKE_ID = "00000000-0000-4000-8000-000000009002";
const OWNER_ID = "00000000-0000-4000-8000-000000009003";

const INTAKE: BrownfieldIntakeSummaryPayload = {
  id: INTAKE_ID,
  project_id: PROJECT_ID,
  version_number: 1,
  based_on_version_number: null,
  content_hash: "a".repeat(64),
  archive_sha256: "b".repeat(64),
  archive_size_bytes: 512,
  archive_storage_key: `sha256/bb/${"b".repeat(64)}.zip`,
  inventory_content_hash: "c".repeat(64),
  capability_status: "DESIGN_ONLY_LEVEL_C_SELECTED",
  effective_capability_status: "DESIGN_ONLY_LEVEL_C",
  selected_profile_reference: {
    profile_id: "WEB_STATIC",
    profile_version: "1.0.0",
    content_hash: "d".repeat(64),
  },
  created_by_user_id: OWNER_ID,
  created_at: "2026-08-26T08:00:00+00:00",
};

const INVENTORY: BrownfieldInventoryPayload = {
  intake: INTAKE,
  inventory: {
    schema_version: 1,
    archive_sha256: INTAKE.archive_sha256,
    content_hash: INTAKE.inventory_content_hash,
    entries: [
      {
        normalized_path: "index.html",
        kind: "FILE",
        classification: "SOURCE",
        size_bytes: 42,
        sha256_digest: "e".repeat(64),
        disposition: "INCLUDE",
        disposition_reason: null,
      },
      {
        normalized_path: "node_modules",
        kind: "DIRECTORY",
        classification: "GENERATED",
        size_bytes: 0,
        sha256_digest: null,
        disposition: "IGNORE",
        disposition_reason: "GENERATED_DIRECTORY",
      },
    ],
  },
};

const CAPABILITY: BrownfieldCapabilityPayload = {
  intake: INTAKE,
  capability: {
    status: "DESIGN_ONLY_LEVEL_C_SELECTED",
    effective_capability_status: "DESIGN_ONLY_LEVEL_C",
    requires_human_decision: false,
    candidates: [
      {
        profile_reference: {
          profile_id: "WEB_STATIC",
          profile_version: "1.0.0",
          content_hash: "d".repeat(64),
        },
        capability_status: "DESIGN_ONLY_LEVEL_C",
        detection: {
          confidence: 100,
          positive_indicators: ["index.html"],
          conflicting_indicators: [],
        },
        missing_runners: [],
        selectable: true,
      },
    ],
    issues: [],
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

class FakeExecutionApi implements ExecutionApi {
  uploadedOptions: SourceArchiveUploadOptions | null = null;
  inventoryRequests: string[] = [];

  async uploadSourceArchive(
    _projectId: string,
    _archive: File,
    _accessToken: string,
    options?: SourceArchiveUploadOptions,
  ) {
    this.uploadedOptions = options ?? {};
    return INTAKE;
  }

  async sourceArchiveHistory() {
    return { items: [INTAKE] };
  }

  async sourceInventory(_projectId: string, intakeId: string) {
    this.inventoryRequests.push(intakeId);
    return INVENTORY;
  }

  async capabilities() {
    return CAPABILITY;
  }

  async profiles() {
    return [PROFILE];
  }

  async profile() {
    return PROFILE;
  }

  async sandboxRuns(): Promise<SandboxRunPayload[]> {
    return [];
  }

  async sandboxRun(): Promise<SandboxRunPayload> {
    throw new Error("not configured");
  }

  async sandboxLogs(): Promise<SandboxLogsPayload> {
    throw new Error("not configured");
  }

  async highImpactOperations(): Promise<HighImpactOperationPayload[]> {
    return [];
  }

  async createHighImpactOperation(): Promise<HighImpactOperationResponsePayload> {
    throw new Error("not configured");
  }

  async submitHighImpactGate(): Promise<HighImpactOperationResponsePayload> {
    throw new Error("not configured");
  }

  async decideHighImpactGate(): Promise<HighImpactOperationResponsePayload> {
    throw new Error("not configured");
  }

  async highImpactReadiness(): Promise<HighImpactReadinessPayload> {
    throw new Error("not configured");
  }

  async highImpactEvents(): Promise<HumanGateEventPayload[]> {
    return [];
  }
}

const authorize = <T>(operation: (accessToken: string) => Promise<T>) => operation("access-token");

function mountFlow(api: FakeExecutionApi) {
  return mount(ProjectBrownfieldSourceFlow, {
    global: {
      plugins: [createPinia()],
    },
    props: {
      projectId: PROJECT_ID,
      authorize,
      api,
    },
  });
}

describe("ProjectBrownfieldSourceFlow", () => {
  it("renders capability honesty and an accessible canonical inventory", async () => {
    const api = new FakeExecutionApi();
    const wrapper = mountFlow(api);

    await flushPromises();

    expect(wrapper.text()).toContain("DESIGN_ONLY_LEVEL_C");
    expect(wrapper.text()).toContain("does not prove Level D");
    expect(wrapper.text()).toContain("WEB_STATIC");

    const inspect = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Inspect inventory"));
    if (inspect === undefined) {
      throw new Error("The inventory inspection action was not rendered");
    }
    await inspect.trigger("click");
    await flushPromises();

    expect(api.inventoryRequests).toEqual([INTAKE_ID]);
    expect(wrapper.text()).toContain("index.html");
    expect(wrapper.text()).toContain("node_modules");
    expect(wrapper.findAll("tbody tr")).toHaveLength(2);

    await wrapper.get("#inventory-disposition").setValue("IGNORE");
    expect(wrapper.findAll("tbody tr")).toHaveLength(1);
    expect(wrapper.text()).toContain("GENERATED_DIRECTORY");
  });

  it("uploads only a bounded ZIP with canonical target and runner options", async () => {
    const api = new FakeExecutionApi();
    const wrapper = mountFlow(api);

    await flushPromises();

    const input = wrapper.get<HTMLInputElement>("#brownfield-archive");
    const archive = new File(["archive"], "source.zip", { type: "application/zip" });
    Object.defineProperty(input.element, "files", {
      configurable: true,
      value: [archive],
    });
    await input.trigger("change");
    await wrapper.get("#brownfield-target").setValue("WEB_STATIC");
    await wrapper.get("#brownfield-runners").setValue("runner.web\nrunner.base\nrunner.web");
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(api.uploadedOptions).toEqual({
      requestedTarget: "WEB_STATIC",
      availableRunners: ["runner.base", "runner.web"],
    });
    expect(wrapper.get('[role="status"]').text()).toContain("immutable intake version 1");
  });
});
