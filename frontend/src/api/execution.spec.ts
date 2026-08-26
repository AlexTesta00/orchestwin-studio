import { describe, expect, it, vi } from "vitest";

import type {
  BrownfieldIntakeSummaryPayload,
  ExecutionProfilePayload,
  HighImpactOperationInput,
} from "../types/execution";
import { ExecutionApiError, createExecutionApi } from "./execution";

const PROJECT_ID = "00000000-0000-4000-8000-000000008001";
const INTAKE_ID = "00000000-0000-4000-8000-000000008002";
const REQUEST_ID = "00000000-0000-4000-8000-000000008003";
const CREATED_AT = "2026-08-25T16:00:00Z";

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
  created_by_user_id: "00000000-0000-4000-8000-000000008004",
  created_at: CREATED_AT,
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

const HIGH_IMPACT_INPUT: HighImpactOperationInput = {
  operation_kind: "SANDBOX_EXECUTION",
  summary: "Execute the owner-reviewed plan.",
  profile_reference: {
    profile_id: "custom.web",
    profile_version: "1.0.0",
    content_hash: "e".repeat(64),
  },
  capability_status: "EXPERIMENTAL_LEVEL_D",
  command_plan_id: "web.validation",
  command_plan_content_hash: "f".repeat(64),
  image_reference: `example/web@sha256:${"1".repeat(64)}`,
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
};

function jsonResponse(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(payload),
  } as Response;
}

function firstCall<T>(values: readonly T[], label: string): T {
  const value = values[0];

  if (value === undefined) {
    throw new Error(`${label} was expected`);
  }

  return value;
}

describe("Execution API client", () => {
  it("uploads a ZIP as multipart data with canonical capability query parameters", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(INTAKE, 201));
    const api = createExecutionApi({ fetchImpl: fetchMock });
    const archive = new File(["archive"], "source.zip", { type: "application/zip" });

    const result = await api.uploadSourceArchive(PROJECT_ID, archive, "access-token", {
      requestedTarget: "WEB_STATIC",
      availableRunners: ["runner.web", "runner.base"],
    });

    const [input, init] = firstCall(
      fetchMock.mock.calls as unknown as [RequestInfo | URL, RequestInit?][],
      "source archive fetch call",
    );
    expect(input).toBe(
      `/api/v1/projects/${PROJECT_ID}/source-archives?requested_target=WEB_STATIC&available_runner=runner.base&available_runner=runner.web`,
    );
    expect(init?.method).toBe("POST");
    expect(init?.credentials).toBe("include");
    expect(init?.body).toBeInstanceOf(FormData);
    const headers = new Headers(init?.headers);
    expect(headers.get("Authorization")).toBe("Bearer access-token");
    expect(headers.has("Content-Type")).toBe(false);
    expect(result).toEqual(INTAKE);
  });

  it("unwraps profile snapshots and sends exact Gate 7 request versions", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.includes("execution-profiles")) {
        return jsonResponse({ items: [PROFILE] });
      }
      return jsonResponse({
        status: "CREATED",
        operation: {
          version: {
            id: REQUEST_ID,
            project_id: PROJECT_ID,
            version_number: 1,
            based_on_version_number: null,
            content_hash: "2".repeat(64),
            request: {},
            created_by_user_id: INTAKE.created_by_user_id,
            created_at: CREATED_AT,
          },
          classification: {
            request_reference: {},
            policy_content_hash: "3".repeat(64),
            classification: "REQUIRES_OWNER_APPROVAL",
            reasons: [],
          },
        },
        gate: null,
        event: null,
      });
    });
    const api = createExecutionApi({ fetchImpl: fetchMock });

    const profiles = await api.profiles("access-token");
    await api.createHighImpactOperation(PROJECT_ID, HIGH_IMPACT_INPUT, "access-token");
    await api.submitHighImpactGate(
      PROJECT_ID,
      REQUEST_ID,
      { version_number: 1, content_hash: "2".repeat(64) },
      "access-token",
    );

    expect(profiles).toEqual([PROFILE]);
    const createCall = fetchMock.mock.calls[1] as unknown as [RequestInfo | URL, RequestInit?];
    const submitCall = fetchMock.mock.calls[2] as unknown as [RequestInfo | URL, RequestInit?];
    expect(createCall[0]).toBe(`/api/v1/projects/${PROJECT_ID}/high-impact-operations`);
    expect(JSON.parse(String(createCall[1]?.body))).toEqual(HIGH_IMPACT_INPUT);
    expect(submitCall[0]).toBe(
      `/api/v1/projects/${PROJECT_ID}/high-impact-operations/${REQUEST_ID}/gate/submit`,
    );
    expect(JSON.parse(String(submitCall[1]?.body))).toEqual({
      version_number: 1,
      content_hash: "2".repeat(64),
    });
  });

  it("preserves typed owner-scoped failures and rejects a blank access token", async () => {
    const api = createExecutionApi({
      fetchImpl: async () =>
        jsonResponse(
          {
            detail: {
              code: "BROWNFIELD_INTAKE_NOT_FOUND",
            },
          },
          404,
        ),
    });

    await expect(api.capabilities(PROJECT_ID, "access-token")).rejects.toEqual(
      expect.objectContaining({
        name: "ExecutionApiError",
        status: 404,
        code: "BROWNFIELD_INTAKE_NOT_FOUND",
      }),
    );
    await expect(api.profiles(" ")).rejects.toBeInstanceOf(ExecutionApiError);
  });
});
