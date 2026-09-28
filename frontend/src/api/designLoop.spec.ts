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

  it("posts the insights set aside for the brief in one batch", async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) =>
      String(input).endsWith("/insight-applications/batch") && init?.method === "POST"
        ? response(201, { applications: [{ id: "application-1" }], brief_version_number: 4 })
        : response(404, null),
    );
    const api = createDesignLoopApi({ basePath: "/api/v1/", fetchImpl });
    const body = {
      items: [
        {
          source_kind: "TWIN_CHAT_INSIGHT" as const,
          source_id: "turn-1:0",
          source_twin_id: "twin-1",
          text: "Fast check-in.",
          target: "BRIEF" as const,
          brief_field: "goals" as const,
        },
      ],
    };
    const result = await api.applyInsightBatch("project 1", body, "token");
    expect(result.brief_version_number).toBe(4);
    expect(result.applications).toHaveLength(1);
    const [url, init] = fetchImpl.mock.calls[0]!;
    expect(String(url)).toBe("/api/v1/projects/project%201/insight-applications/batch");
    expect(init?.method).toBe("POST");
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer token");
    expect(JSON.parse(String(init?.body))).toEqual(body);
  });

  it("surfaces a refused batch with its code and the offending sources", async () => {
    const fetchImpl = vi.fn(async () =>
      response(409, { detail: { code: "INSIGHT_ALREADY_APPLIED", sources: ["turn-1:0"] } }),
    );
    const api = createDesignLoopApi({ fetchImpl });
    await expect(api.applyInsightBatch("p", { items: [] }, "token")).rejects.toMatchObject({
      status: 409,
      code: "INSIGHT_ALREADY_APPLIED",
      payload: { detail: { code: "INSIGHT_ALREADY_APPLIED", sources: ["turn-1:0"] } },
    });
    await expect(api.applyInsightBatch("p", { items: [] }, " ")).rejects.toBeInstanceOf(
      DesignLoopApiError,
    );
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("sends the evaluation mode and records the owner's decision on a finding", async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.endsWith("/validations") && init?.method === "POST") {
        return response(201, { finding_id: "UTF-001", decision: "OWNER_DISMISSED" });
      }
      if (path.endsWith("/design/evaluations") && init?.method === "POST") {
        return response(201, { id: "run-2", responses: [] });
      }
      return response(200, [{ finding_id: "UTF-001", decision: "OWNER_CONFIRMED" }]);
    });
    const api = createDesignLoopApi({ fetchImpl });
    await api.evaluate(
      "p",
      { design_version_id: "v", design_content_hash: "a".repeat(64), mode: "STATIC_CHECK" },
      "token",
    );
    expect(JSON.parse(String(fetchImpl.mock.calls[0]?.[1]?.body))).toEqual({
      design_version_id: "v",
      design_content_hash: "a".repeat(64),
      mode: "STATIC_CHECK",
    });
    const validations = await api.validations("p", "token");
    expect(validations[0]?.decision).toBe("OWNER_CONFIRMED");
    expect(String(fetchImpl.mock.calls[1]?.[0])).toBe(
      "/api/v1/projects/p/design/evaluations/validations",
    );
    expect(fetchImpl.mock.calls[1]?.[1]?.method).toBe("GET");
    const decided = await api.validate(
      "p",
      "run 1",
      {
        twin_id: "twin-1",
        finding_id: "UTF-001",
        decision: "OWNER_DISMISSED",
        note: "Out of scope",
      },
      "token",
    );
    expect(decided.decision).toBe("OWNER_DISMISSED");
    const [url, init] = fetchImpl.mock.calls[2]!;
    expect(String(url)).toBe("/api/v1/projects/p/design/evaluations/run%201/validations");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({
      twin_id: "twin-1",
      finding_id: "UTF-001",
      decision: "OWNER_DISMISSED",
      note: "Out of scope",
    });
  });

  it("starts, continues and decides a twin discussion", async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "GET") {
        return response(200, [{ id: "discussion-1", status: "OPEN" }]);
      }
      if (String(input).endsWith("/decision")) {
        return response(200, { id: "discussion-1", status: "APPROVED" });
      }
      return response(201, { id: "discussion-1", status: "OPEN" });
    });
    const api = createDesignLoopApi({ fetchImpl });
    expect((await api.discussions("p", "token"))[0]?.id).toBe("discussion-1");
    await api.startDiscussion(
      "p",
      {
        design_version_id: "v",
        design_content_hash: "a".repeat(64),
        locale: "it-IT",
        owner_note: "Focus on speed",
      },
      "token",
    );
    await api.nextDiscussionRound(
      "p",
      "discussion 1",
      { expected_round_count: 1, owner_note: null },
      "token",
    );
    const decided = await api.decideDiscussion("p", "discussion 1", { action: "APPROVE" }, "token");
    expect(decided.status).toBe("APPROVED");
    const calls = fetchImpl.mock.calls.map(([url, init]) => [
      String(url),
      init?.method,
      init?.body === undefined ? null : JSON.parse(String(init.body)),
    ]);
    expect(calls).toEqual([
      ["/api/v1/projects/p/design/discussions", "GET", null],
      [
        "/api/v1/projects/p/design/discussions",
        "POST",
        {
          design_version_id: "v",
          design_content_hash: "a".repeat(64),
          locale: "it-IT",
          owner_note: "Focus on speed",
        },
      ],
      [
        "/api/v1/projects/p/design/discussions/discussion%201/rounds",
        "POST",
        { expected_round_count: 1, owner_note: null },
      ],
      [
        "/api/v1/projects/p/design/discussions/discussion%201/decision",
        "POST",
        { action: "APPROVE" },
      ],
    ]);
  });

  it("surfaces the discussion conflicts with their code", async () => {
    const fetchImpl = vi.fn(async () =>
      response(409, { detail: { code: "DESIGN_DISCUSSION_OPEN" } }),
    );
    const api = createDesignLoopApi({ fetchImpl });
    await expect(
      api.startDiscussion("p", { design_version_id: "v", design_content_hash: "a" }, "token"),
    ).rejects.toMatchObject({ status: 409, code: "DESIGN_DISCUSSION_OPEN" });
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
