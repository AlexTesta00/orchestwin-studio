import { describe, expect, it, vi } from "vitest";
import { ApiError } from "./client";
import { modelRuntimeReadiness } from "./modelRuntime";

describe("model readiness", () => {
  it("preserves explicit development mode even with an HTTP 503", async () => {
    const payload = { mode: "DEVELOPMENT_FIXTURES", ready: false };
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(payload), { status: 503 }));
    expect(await modelRuntimeReadiness("token", fetchImpl)).toEqual(payload);
  });
  it("keeps authentication failures compatible with session refresh", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response("{}", { status: 401 }));
    await expect(modelRuntimeReadiness("token", fetchImpl)).rejects.toBeInstanceOf(ApiError);
  });
  it("does not turn an invalid readiness response into ready status", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ mode: "REAL_REQUIRED", ready: true }), { status: 503 }),
      );
    await expect(modelRuntimeReadiness("token", fetchImpl)).rejects.toMatchObject({ status: 503 });
  });
});
