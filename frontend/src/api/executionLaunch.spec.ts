import { describe, expect, it, vi } from "vitest";
import { createExecutionLaunchApi, type ExecutionOperation } from "./executionLaunch";
import { ApiError } from "./client";

describe("execution launch transport", () => {
  it.each(["web", "jvm"] as const)(
    "starts %s with its actual API runner shape and exact approval",
    async (platform) => {
      const fetchImpl = vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ snapshot: { id: "attempt" } }), { status: 201 }),
        );
      const shared = {
        source_revision_id: "source",
        profile_id: "profile",
        profile_version: "1",
        policy_content_hash: "c".repeat(64),
        purpose: "OWNER_PROJECT",
        trigger: "INITIAL",
        authorization_id: null,
        rerun_phases: null,
      };
      const command =
        platform === "web"
          ? {
              ...shared,
              execution_runner_image_digest: "a".repeat(64),
              browser_runner_image_digest: "b".repeat(64),
              declared_routes: [],
              browser_interactions: [],
            }
          : { ...shared, runner_image_digest: "a".repeat(64) };
      const before = structuredClone(command);
      await createExecutionLaunchApi(fetchImpl).start(
        "project",
        platform,
        {
          id: "approved-operation",
          source_revision_id: "source",
          kind: "EXECUTION",
          content_hash: "d".repeat(64),
          state: "APPROVED",
          gate_current: true,
          gate: { id: "gate", status: "APPROVED", event_sequence: 2 },
          payload: { command },
        },
        "token",
      );
      const body = JSON.parse(fetchImpl.mock.calls[0]![1].body);
      expect(fetchImpl.mock.calls[0]![0]).toBe(`/api/v1/projects/project/${platform}-executions`);
      expect(body).toEqual(
        platform === "web"
          ? {
              ...shared,
              authorization_id: "approved-operation",
              runners: {
                execution_runner_image_digest: "a".repeat(64),
                browser_runner_image_digest: "b".repeat(64),
              },
              declared_routes: [],
              browser_interactions: [],
            }
          : { ...command, authorization_id: "approved-operation" },
      );
      expect(command).toEqual(before);
    },
  );

  it("does not send incomplete or repair operations to the execution endpoint", async () => {
    const fetchImpl = vi.fn();
    for (const operation of [
      { id: "repair", kind: "REPAIR", payload: { command: {} } },
      { id: "missing", kind: "EXECUTION", payload: {} },
    ]) {
      await expect(
        createExecutionLaunchApi(fetchImpl).start(
          "project",
          "web",
          operation as ExecutionOperation,
          "token",
        ),
      ).rejects.toThrow("Incomplete execution operation");
    }
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("prepares only the selected source, without browser-supplied runner settings", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ snapshot: { id: "op" } }), { status: 201 }));
    await createExecutionLaunchApi(fetchImpl).prepare(
      "project/id",
      "jvm",
      { id: "source", content_hash: "a".repeat(64) },
      "token",
    );
    expect(fetchImpl).toHaveBeenCalledWith(
      "/api/v1/projects/project%2Fid/execution-launch/jvm/prepare",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          source_revision_id: "source",
          source_revision_content_hash: "a".repeat(64),
        }),
      }),
    );
  });

  it("binds an approval to its exact hash and event sequence", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ snapshot: { id: "op" } })));
    await createExecutionLaunchApi(fetchImpl).decide(
      "p",
      "web",
      { id: "op", content_hash: "b".repeat(64), gate: { event_sequence: 3 } } as ExecutionOperation,
      "APPROVE",
      "token",
    );
    const body = JSON.parse(fetchImpl.mock.calls[0]![1].body);
    expect(body).toEqual({
      expected_content_hash: "b".repeat(64),
      expected_gate_event_sequence: 3,
      action: "APPROVE",
    });
  });

  it("propagates authentication errors through the existing refresh contract without retrying", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ detail: { code: "EXPIRED" } }), { status: 401 }),
      );
    await expect(
      createExecutionLaunchApi(fetchImpl).history("p", "jvm", "token"),
    ).rejects.toBeInstanceOf(ApiError);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("applies the exact operation using its gate ID, independently from its proposal ID", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ snapshot: { id: "revision" } })));
    await createExecutionLaunchApi(fetchImpl).applyRepair(
      "jvm",
      {
        id: "operation",
        kind: "REPAIR",
        content_hash: "b".repeat(64),
        gate: { id: "different-gate-id", status: "APPROVED", event_sequence: 2 },
        payload: {
          execution_id: "attempt",
          proposal: { base_revision: { content_hash: "a".repeat(64) } },
        },
      } as ExecutionOperation,
      "token",
    );
    expect(fetchImpl.mock.calls[0]![0]).toBe(
      "/api/v1/jvm-executions/attempt/repair-proposals/operation/apply",
    );
    expect(JSON.parse(fetchImpl.mock.calls[0]![1].body)).toEqual({
      base_revision_content_hash: "a".repeat(64),
      proposal_content_hash: "b".repeat(64),
      approval_id: "different-gate-id",
    });
  });
});
