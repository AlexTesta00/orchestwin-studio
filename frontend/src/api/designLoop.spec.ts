import { describe, expect, it, vi } from "vitest";

import { createDesignLoopApi, DesignLoopApiError } from "./designLoop";

function response(status: number, body: unknown): Response {
  return new Response(body === null ? "" : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("designLoop api", () => {
  it("posts evaluations and insight applications with the bearer token", async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.endsWith("/design/evaluations") && init?.method === "POST") {
        return response(201, { id: "run-1", responses: [] });
      }
      if (path.endsWith("/insight-applications") && init?.method === "POST") {
        return response(201, { id: "application-1", target_code: "REQ-002" });
      }
      if (path.endsWith("/design/regenerations")) {
        return response(201, { status: "CREATED" });
      }
      return response(200, []);
    });
    const api = createDesignLoopApi({ basePath: "/api/v1/", fetchImpl });
    const run = await api.evaluate(
      "project 1",
      { design_version_id: "v", design_content_hash: "a".repeat(64) },
      "token",
    );
    expect(run.id).toBe("run-1");
    const [url, init] = fetchImpl.mock.calls[0]!;
    expect(String(url)).toBe("/api/v1/projects/project%201/design/evaluations");
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer token");
    expect(init?.body).toBe(
      JSON.stringify({ design_version_id: "v", design_content_hash: "a".repeat(64) }),
    );
    const applied = await api.applyInsight(
      "project 1",
      { source_kind: "SYNTHETIC_FINDING", source_id: "x", text: "y", target: "REQUIREMENTS" },
      "token",
    );
    expect(applied.target_code).toBe("REQ-002");
    expect((await api.regenerate("project 1", "token")).status).toBe("CREATED");
    expect(await api.runs("project 1", "token")).toEqual([]);
  });

  it("treats a missing comparison as null and surfaces other failures with their code", async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/comparison")) {
        return response(404, { detail: { code: "DESIGN_EVALUATION_COMPARISON_UNAVAILABLE" } });
      }
      return response(503, { detail: { code: "DESIGN_EVALUATOR_NOT_CONFIGURED" } });
    });
    const api = createDesignLoopApi({ fetchImpl });
    expect(await api.comparison("p", "token")).toBeNull();
    await expect(
      api.evaluate("p", { design_version_id: "v", design_content_hash: "a".repeat(64) }, "token"),
    ).rejects.toMatchObject({ status: 503, code: "DESIGN_EVALUATOR_NOT_CONFIGURED" });
    await expect(api.runs("p", " ")).rejects.toBeInstanceOf(DesignLoopApiError);
  });
});
