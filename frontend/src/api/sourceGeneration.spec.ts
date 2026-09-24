import { describe, expect, it, vi } from "vitest";
import { ApiError } from "./client";
import { createSourceGenerationApi, SourceGenerationApiError } from "./sourceGeneration";

describe("source generation API", () => {
  it("sends the approved version and exact failure binding to the governed endpoints", async () => {
    const fetchImpl = vi
      .fn()
      .mockImplementation(() =>
        Promise.resolve(
          new Response(JSON.stringify({ snapshot: { id: "result" } }), { status: 201 }),
        ),
      );
    const api = createSourceGenerationApi({ fetchImpl });
    const source = {
      target: "WEB_STATIC" as const,
      architecture_version_id: "arch",
      architecture_content_hash: "a".repeat(64),
    };
    const repair = {
      base_revision_content_hash: "b".repeat(64),
      failure_signature_digest: "c".repeat(64),
    };
    expect(await api.source("project/a", "web", source, "token")).toEqual({ id: "result" });
    await api.repair("project/a", "web", "execution/a", repair, "token");
    expect(fetchImpl.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/projects/project%2Fa/source-generations/web",
      "/api/v1/projects/project%2Fa/repair-generations/web/execution%2Fa",
    ]);
    expect(fetchImpl.mock.calls[0]![1]).toMatchObject({
      method: "POST",
      body: JSON.stringify(source),
      credentials: "include",
      headers: { Authorization: "Bearer token" },
    });
    expect(fetchImpl.mock.calls[1]![1].body).toBe(JSON.stringify(repair));
  });

  it.each([401, 409, 422, 502, 503])(
    "preserves status %s and never retries generation",
    async (status) => {
      const fetchImpl = vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ detail: { code: "SOURCE_REJECTED" } }), { status }),
        );
      const api = createSourceGenerationApi({ fetchImpl });
      const operation = api.repair(
        "p",
        "web",
        "e",
        { base_revision_content_hash: "b", failure_signature_digest: "f" },
        "token",
      );
      await expect(operation).rejects.toBeInstanceOf(ApiError);
      await expect(operation).rejects.toMatchObject({ status, code: "SOURCE_REJECTED" });
      expect(fetchImpl).toHaveBeenCalledTimes(1);
    },
  );

  it("rejects unauthenticated calls before sending a request", async () => {
    const fetchImpl = vi.fn();
    await expect(
      createSourceGenerationApi({ fetchImpl }).repair(
        "p",
        "web",
        "e",
        { base_revision_content_hash: "b", failure_signature_digest: "f" },
        " ",
      ),
    ).rejects.toBeInstanceOf(SourceGenerationApiError);
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
