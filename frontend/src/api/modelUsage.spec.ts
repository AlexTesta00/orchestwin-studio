import { describe, expect, it, vi } from "vitest";

import { createModelUsageApi, ModelUsageApiError } from "./modelUsage";

function response(status: number, body: unknown): Response {
  return new Response(body === undefined ? "" : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const USAGE = {
  items: [
    {
      generation_id: "generation-1",
      recorded_at: "2026-09-29T09:12:03+00:00",
      task: "design",
      purpose: "DESIGN_MOCKUP_HTML",
      provider_kind: "ANTHROPIC_HOSTED",
      model: "claude-opus-5-5",
      status: "SUCCEEDED",
      failure_code: null,
      input_tokens: 10234,
      output_tokens: 17890,
      cache_read_input_tokens: 0,
      cache_write_input_tokens: 0,
      cost_microusd: 398736,
      latency_milliseconds: 184000,
    },
  ],
  totals: { generations: 1, input_tokens: 10234, output_tokens: 17890, cost_microusd: 398736 },
};

const BUDGET = {
  currency: "USD",
  per_generation_microusd: 1500000,
  per_project_microusd: 10000000,
  total_microusd: 60000000,
  spent_total_microusd: 1250000,
  remaining_total_microusd: 58750000,
  period_start: "2026-09-01",
};

describe("model usage api", () => {
  it("reads the usage of a project and the spending ceiling", async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) =>
      String(input).endsWith("/budget") ? response(200, BUDGET) : response(200, USAGE),
    );
    const api = createModelUsageApi({ basePath: "/api/v1/", fetchImpl });

    expect(await api.usage("project 1", "token")).toEqual(USAGE);
    expect(await api.budget("token")).toEqual(BUDGET);
    expect(fetchImpl.mock.calls.map((call) => String(call[0]))).toEqual([
      "/api/v1/projects/project%201/model-usage",
      "/api/v1/model-runtime/budget",
    ]);
    for (const call of fetchImpl.mock.calls as unknown[][]) {
      const init = call[1] as RequestInit;
      expect(init.method).toBe("GET");
      expect(init.credentials).toBe("include");
      expect(init.headers).toEqual({ Accept: "application/json", Authorization: "Bearer token" });
    }
  });

  it.each([
    [404, "PROJECT_NOT_FOUND"],
    [503, "PROPOSAL_EVIDENCE_UNAVAILABLE"],
    [503, "REAL_MODEL_RUNTIME_NOT_CONFIGURED"],
    [503, "GENERATION_BUDGET_NOT_CONFIGURED"],
  ])("surfaces the answer %i %s", async (status, code) => {
    const api = createModelUsageApi({
      fetchImpl: async () => response(status, { detail: { code } }),
    });

    const failure = api.budget("token");

    await expect(failure).rejects.toBeInstanceOf(ModelUsageApiError);
    await expect(failure).rejects.toMatchObject({ status, code, message: code });
  });

  it("refuses to call the server without a token and reports unreadable answers", async () => {
    const fetchImpl = vi.fn(async () => new Response("{", { status: 200 }));
    const api = createModelUsageApi({ fetchImpl });

    await expect(api.usage("p", "")).rejects.toMatchObject({ code: "ACCESS_TOKEN_REQUIRED" });
    expect(fetchImpl).not.toHaveBeenCalled();
    await expect(api.usage("p", "token")).rejects.toMatchObject({
      code: "INVALID_API_RESPONSE",
    });
  });
});
