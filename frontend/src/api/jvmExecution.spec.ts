import { describe, expect, it, vi } from "vitest";

import { createJvmExecutionApi, JvmExecutionApiError } from "./jvmExecution";

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("JVM execution API", () => {
  it("loads profiles and owner-scoped histories with bearer authorization", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ items: [{ profile_id: "jvm.kotlin-gradle" }] }))
      .mockResolvedValueOnce(jsonResponse({ items: [{ id: "revision-1" }] }))
      .mockResolvedValueOnce(jsonResponse({ items: [{ id: "execution-1" }] }));
    const api = createJvmExecutionApi({ basePath: "/api/v1", fetchImpl });

    await api.profiles("token");
    await api.sourceRevisions("project / one", "token");
    await api.executions("project / one", "token");

    expect(fetchImpl).toHaveBeenNthCalledWith(
      1,
      "/api/v1/jvm-execution-profiles",
      expect.objectContaining({ credentials: "include" }),
    );
    expect(fetchImpl.mock.calls[1]?.[0]).toBe(
      "/api/v1/projects/project%20%2F%20one/jvm-source-revisions",
    );
    const headers = fetchImpl.mock.calls[0]?.[1]?.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer token");
  });

  it("sends typed source, execution, and repair payloads without command strings", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockImplementation(() =>
        Promise.resolve(jsonResponse({ status: "OK", snapshot: { id: "item" }, message: "ok" })),
      );
    const api = createJvmExecutionApi({ fetchImpl });
    const source = {
      target: "JVM_KOTLIN" as const,
      rationale: "Materialize the formal Kotlin case.",
      files: [
        {
          normalized_path: "src/main/kotlin/Main.kt",
          content: "fun main() = Unit",
          media_type: "text/x-kotlin",
        },
      ],
      provenance_references: [
        {
          kind: "SOURCE_PLAN",
          reference_id: "plan-1",
          version_number: 1,
          content_hash: "a".repeat(64),
        },
      ],
    };
    const execution = {
      source_revision_id: "revision-1",
      profile_id: "jvm.kotlin-gradle",
      profile_version: "1.0.0",
      policy_content_hash: "b".repeat(64),
      runner_image_digest: "c".repeat(64),
      purpose: "PROFILE_VALIDATION" as const,
      trigger: "PROFILE_VALIDATION" as const,
      authorization_id: "authorization-1",
      rerun_phases: null,
    };

    await api.createSourceRevision("project-1", source, "token");
    await api.startExecution("project-1", execution, "token");
    await api.createRepairProposal(
      "execution-1",
      {
        base_revision_content_hash: "a".repeat(64),
        failure_signature: "b".repeat(64),
        changes: [
          {
            operation: "REPLACE",
            normalized_path: "src/main/kotlin/Main.kt",
            content: "fun main() = Unit",
            media_type: "text/x-kotlin",
          },
        ],
        rationale: "Repair the exact failure.",
      },
      "token",
    );

    const bodies = fetchImpl.mock.calls.map((call) => JSON.parse(call[1]?.body as string));
    expect(bodies[0]).toEqual(source);
    expect(bodies[1]).toEqual(execution);
    expect(bodies.every((body) => !("command" in body))).toBe(true);
  });

  it("maps structured API failures and rejects missing access tokens", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        jsonResponse({ detail: { code: "JVM_EXECUTION_RESOURCE_NOT_FOUND" } }, 404),
      );
    const api = createJvmExecutionApi({ fetchImpl });

    await expect(api.execution("missing", "token")).rejects.toMatchObject({
      status: 404,
      code: "JVM_EXECUTION_RESOURCE_NOT_FOUND",
    });
    await expect(api.profiles(" ")).rejects.toBeInstanceOf(JvmExecutionApiError);
  });
});
