import { createPinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import { ExecutionApiError, type ExecutionApi } from "../api/execution";
import type {
  BrownfieldCapabilityPayload,
  BrownfieldIntakeListPayload,
  BrownfieldInventoryPayload,
  ExecutionProfilePayload,
  HighImpactDecisionInput,
  HighImpactExpectedReferenceInput,
  HighImpactOperationPayload,
  HighImpactOperationResponsePayload,
  HighImpactReadinessPayload,
  HumanGateEventPayload,
  HumanGatePayload,
  SandboxLogsPayload,
  SandboxRunPayload,
} from "../types/execution";
import ProjectSandboxGovernanceFlow from "./ProjectSandboxGovernanceFlow.vue";

const PROJECT_ID = "00000000-0000-4000-8000-000000009101";
const OWNER_ID = "00000000-0000-4000-8000-000000009102";
const RUN_ID = "00000000-0000-4000-8000-000000009103";
const REQUEST_ID = "00000000-0000-4000-8000-000000009104";
const GATE_ID = "00000000-0000-4000-8000-000000009105";
const CREATED_AT = "2026-08-26T09:00:00+00:00";
const REQUEST_HASH = "a".repeat(64);

const PROFILE: ExecutionProfilePayload = {
  profile_id: "builtin.web.static",
  name: "Static Web",
  version: "1.0.0",
  capability_status: "DESIGN_ONLY_LEVEL_C",
  supported_targets: ["WEB_STATIC"],
  file_indicators: ["index.html"],
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
  content_hash: "b".repeat(64),
};

const SANDBOX_RUN: SandboxRunPayload = {
  run_id: RUN_ID,
  project_id: PROJECT_ID,
  intake_reference: null,
  schema_version: 1,
  evidence_content_hash: "c".repeat(64),
  evidence_snapshot: {
    evidence: {
      status: "SUCCEEDED",
      plan_id: "web.static.verify",
      plan_content_hash: "d".repeat(64),
      image_reference: `example/web@sha256:${"e".repeat(64)}`,
      runtime_reference: "fake-container-runtime@1",
      failure_message: null,
    },
  },
  created_by_user_id: OWNER_ID,
  recorded_at: CREATED_AT,
  command_results: [
    {
      run_id: RUN_ID,
      ordinal: 1,
      command_id: "quality.tests",
      status: "SUCCEEDED",
      started_at: CREATED_AT,
      finished_at: "2026-08-26T09:00:01+00:00",
      exit_code: 0,
      output_parser_id: "pytest.v1",
      failure_message: null,
      stdout_log: {
        storage_key: `sha256/ff/${"f".repeat(64)}`,
        sha256_digest: "f".repeat(64),
        size_bytes: 9,
      },
      stderr_log: {
        storage_key: `sha256/00/${"0".repeat(64)}`,
        sha256_digest: "0".repeat(64),
        size_bytes: 0,
      },
      artifacts: [],
    },
  ],
};

const LOGS: SandboxLogsPayload = {
  run_id: RUN_ID,
  logs: [
    {
      command_id: "quality.tests",
      stdout: SANDBOX_RUN.command_results[0]?.stdout_log ?? {},
      stderr: SANDBOX_RUN.command_results[0]?.stderr_log ?? {},
    },
  ],
};

const OPERATION: HighImpactOperationPayload = {
  version: {
    id: REQUEST_ID,
    project_id: PROJECT_ID,
    version_number: 1,
    based_on_version_number: null,
    content_hash: REQUEST_HASH,
    request: {
      summary: "Run the reviewed experimental validation plan.",
      capability_status: "EXPERIMENTAL_LEVEL_D",
    },
    created_by_user_id: OWNER_ID,
    created_at: CREATED_AT,
  },
  classification: {
    request_reference: {
      request_id: REQUEST_ID,
      version_number: 1,
      content_hash: REQUEST_HASH,
    },
    policy_content_hash: "1".repeat(64),
    classification: "REQUIRES_OWNER_APPROVAL",
    reasons: [
      {
        code: "EXPERIMENTAL_PROFILE",
        message: "Experimental execution requires exact owner approval.",
      },
    ],
  },
};

function gate(status: HumanGatePayload["status"]): HumanGatePayload {
  return {
    id: GATE_ID,
    project_id: PROJECT_ID,
    owner_user_id: OWNER_ID,
    gate_type: "HIGH_IMPACT_OPERATION",
    artifact: {
      artifact_id: REQUEST_ID,
      version_number: 1,
      content_hash: REQUEST_HASH,
    },
    iteration: 1,
    max_iterations: 3,
    status,
    created_at: CREATED_AT,
    updated_at: CREATED_AT,
    event_sequence: status === "DRAFT" ? 0 : 1,
    resume_status: null,
  };
}

class FakeExecutionApi implements ExecutionApi {
  readiness: HighImpactReadinessPayload = {
    status: "OWNER_APPROVAL_REQUIRED",
    operation: OPERATION,
    gate: gate("DRAFT"),
  };
  events: HumanGateEventPayload[] = [];
  submittedReference: HighImpactExpectedReferenceInput | null = null;
  decision: HighImpactDecisionInput | null = null;

  async uploadSourceArchive(): Promise<never> {
    throw new Error("not configured");
  }

  async sourceArchiveHistory(): Promise<BrownfieldIntakeListPayload> {
    return { items: [] };
  }

  async sourceInventory(): Promise<BrownfieldInventoryPayload> {
    throw new Error("not configured");
  }

  async capabilities(): Promise<BrownfieldCapabilityPayload> {
    throw new ExecutionApiError("not found", {
      status: 404,
      code: "BROWNFIELD_INTAKE_NOT_FOUND",
      payload: null,
    });
  }

  async profiles() {
    return [PROFILE];
  }

  async profile() {
    return PROFILE;
  }

  async sandboxRuns() {
    return [SANDBOX_RUN];
  }

  async sandboxRun() {
    return SANDBOX_RUN;
  }

  async sandboxLogs() {
    return LOGS;
  }

  async highImpactOperations() {
    return [OPERATION];
  }

  async createHighImpactOperation(): Promise<HighImpactOperationResponsePayload> {
    throw new Error("not configured");
  }

  async submitHighImpactGate(
    _projectId: string,
    _requestId: string,
    input: HighImpactExpectedReferenceInput,
  ): Promise<HighImpactOperationResponsePayload> {
    this.submittedReference = input;
    const pendingGate = gate("PENDING_APPROVAL");
    this.readiness = {
      status: "OWNER_APPROVAL_REQUIRED",
      operation: OPERATION,
      gate: pendingGate,
    };
    return {
      status: "SUBMITTED",
      operation: OPERATION,
      gate: pendingGate,
      event: null,
    };
  }

  async decideHighImpactGate(
    _projectId: string,
    _requestId: string,
    input: HighImpactDecisionInput,
  ): Promise<HighImpactOperationResponsePayload> {
    this.decision = input;
    const approvedGate = gate("APPROVED");
    this.readiness = {
      status: "APPROVED",
      operation: OPERATION,
      gate: approvedGate,
    };
    this.events = [
      {
        id: "00000000-0000-4000-8000-000000009106",
        gate_id: GATE_ID,
        sequence_number: 1,
        kind: input.action,
        previous_status: "PENDING_APPROVAL",
        resulting_status: "APPROVED",
        artifact: approvedGate.artifact,
        occurred_at: CREATED_AT,
        actor_user_id: OWNER_ID,
        reason: input.reason,
      },
    ];
    return {
      status: "APPLIED",
      operation: OPERATION,
      gate: approvedGate,
      event: this.events[0] ?? null,
    };
  }

  async highImpactReadiness() {
    return this.readiness;
  }

  async highImpactEvents() {
    return this.events;
  }
}

const authorize = <T>(operation: (accessToken: string) => Promise<T>) => operation("access-token");

function mountFlow(api: FakeExecutionApi) {
  return mount(ProjectSandboxGovernanceFlow, {
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

function buttonContaining(wrapper: ReturnType<typeof mountFlow>, text: string) {
  const button = wrapper.findAll("button").find((candidate) => candidate.text().includes(text));
  if (button === undefined) {
    throw new Error(`Button containing ${text} was not rendered`);
  }
  return button;
}

describe("ProjectSandboxGovernanceFlow", () => {
  it("shows capability honesty and preserves content-addressed raw log references", async () => {
    const api = new FakeExecutionApi();
    const wrapper = mountFlow(api);

    await flushPromises();

    expect(wrapper.text()).toContain("DESIGN_ONLY_LEVEL_C");
    expect(wrapper.text()).toContain("SUCCEEDED");
    expect(wrapper.text()).toContain("No Level D validation evidence");

    await buttonContaining(wrapper, "Inspect run evidence").trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("web.static.verify");
    expect(wrapper.text()).toContain(`sha256/ff/${"f".repeat(64)}`);
    expect(wrapper.text()).toContain("pytest.v1");
    expect(wrapper.findAll("table")).toHaveLength(2);
  });

  it("submits and approves only the exact Gate 7 request version and hash", async () => {
    const api = new FakeExecutionApi();
    const wrapper = mountFlow(api);

    await flushPromises();
    await buttonContaining(wrapper, "Review Gate 7").trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain(REQUEST_HASH);
    expect(wrapper.text()).toContain("EXPERIMENTAL_PROFILE");
    expect(wrapper.text()).toContain("cannot authorize forbidden operations");

    await buttonContaining(wrapper, "Submit for owner approval").trigger("click");
    await flushPromises();

    expect(api.submittedReference).toEqual({
      version_number: 1,
      content_hash: REQUEST_HASH,
    });

    await wrapper.get("#gate-7-reason").setValue("The exact reviewed plan is accepted.");
    await buttonContaining(wrapper, "Approve exact request").trigger("click");
    await flushPromises();

    expect(api.decision).toEqual({
      version_number: 1,
      content_hash: REQUEST_HASH,
      action: "APPROVE",
      reason: "The exact reviewed plan is accepted.",
    });
    expect(wrapper.text()).toContain("APPROVED");
  });
});
