import { describe, expect, it, vi } from "vitest";

import { createDesignIterationsApi, DesignIterationsApiError } from "./designIterations";

const PROJECT_ID = "project 1";
const ENCODED_PROJECT = "project%201";

function response(status: number, body: unknown): Response {
  return new Response(body === undefined ? "" : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function calls(fetchImpl: { mock: { calls: unknown[][] } }) {
  return fetchImpl.mock.calls.map((call) => {
    const request = call[1] as RequestInit | undefined;
    return {
      url: String(call[0]),
      method: request?.method,
      headers: request?.headers as Record<string, string> | undefined,
      body: request?.body === undefined ? undefined : (JSON.parse(String(request.body)) as unknown),
    };
  });
}

const ITERATION = {
  generation_id: "generation-1",
  requested_at: "2026-09-29T09:20:00+00:00",
  request: "Sposta il pulsante principale in alto",
  assertions: ["Il pulsante principale resta in alto"],
  changes: ["Il pulsante principale è ora nella barra in alto"],
  status: "PROPOSED",
  base_design_version_number: 2,
  applied_design_version_number: null,
  cost_microusd: 458000,
};

describe("design iterations api", () => {
  it("starts an iteration, reads its job and lists the iterations", async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") {
        return response(202, { job_id: "job-1", kind: "ITERATION", status: "RUNNING" });
      }
      return String(input).includes("/jobs/")
        ? response(200, { job_id: "job-1", kind: "ITERATION", status: "SUCCEEDED" })
        : response(200, { items: [ITERATION] });
    });
    const api = createDesignIterationsApi({ basePath: "/api/v1/", fetchImpl });
    const body = {
      design_version_id: "version-2",
      design_content_hash: "b".repeat(64),
      request: "Sposta il pulsante principale in alto",
      assertions: ["Il pulsante principale resta in alto"],
    };

    expect((await api.startJob(PROJECT_ID, body, "token")).status).toBe("RUNNING");
    expect((await api.job(PROJECT_ID, "job 1", "token")).status).toBe("SUCCEEDED");
    expect(await api.list(PROJECT_ID, "token")).toEqual({ items: [ITERATION] });
    expect(calls(fetchImpl)).toEqual([
      {
        url: `/api/v1/projects/${ENCODED_PROJECT}/design/iterations/jobs`,
        method: "POST",
        headers: {
          Accept: "application/json",
          Authorization: "Bearer token",
          "Content-Type": "application/json",
        },
        body,
      },
      {
        url: `/api/v1/projects/${ENCODED_PROJECT}/design/iterations/jobs/job%201`,
        method: "GET",
        headers: { Accept: "application/json", Authorization: "Bearer token" },
        body: undefined,
      },
      {
        url: `/api/v1/projects/${ENCODED_PROJECT}/design/iterations`,
        method: "GET",
        headers: { Accept: "application/json", Authorization: "Bearer token" },
        body: undefined,
      },
    ]);
  });

  it("sends the screen and the element that a change is aimed at with the request", async () => {
    const fetchImpl = vi.fn(async () =>
      response(202, { job_id: "job-1", kind: "ITERATION", status: "RUNNING" }),
    );
    const api = createDesignIterationsApi({ fetchImpl });
    const body = {
      design_version_id: "version-2",
      design_content_hash: "b".repeat(64),
      request: "Rendi il pulsante più scuro",
      assertions: [],
      target: {
        screen_code: "SCR-002",
        element_code: "ELM-012",
        label: "Prenota",
        html: '<button data-elm="ELM-012" type="button">Prenota</button>',
      },
    };

    await api.startJob(PROJECT_ID, body, "token");

    expect(calls(fetchImpl)[0]).toMatchObject({
      url: `/api/v1/projects/${ENCODED_PROJECT}/design/iterations/jobs`,
      method: "POST",
      body,
    });
  });

  it.each([
    [409, "DESIGN_CONTEXT_CHANGED"],
    [409, "GENERATED_MOCKUP_REQUIRED"],
    [422, "ITERATION_REQUEST_INVALID"],
    [429, "TOO_MANY_GENERATIONS"],
    [402, "GENERATION_BUDGET_EXCEEDED"],
    [503, "GENERATION_BUDGET_UNAVAILABLE"],
    [503, "REAL_MOCKUP_MODEL_NOT_CONFIGURED"],
  ])("surfaces the refusal %i %s when an iteration is started", async (status, code) => {
    const payload = { detail: { code } };
    const api = createDesignIterationsApi({ fetchImpl: async () => response(status, payload) });

    const failure = api.startJob(
      "p",
      { design_version_id: "v", design_content_hash: "b".repeat(64), request: "x", assertions: [] },
      "token",
    );

    await expect(failure).rejects.toBeInstanceOf(DesignIterationsApiError);
    await expect(failure).rejects.toMatchObject({ status, code, payload });
  });

  it("surfaces a lost job, an unreadable answer and a missing token", async () => {
    const answers = [
      response(404, { detail: { code: "GENERATION_JOB_NOT_FOUND" } }),
      new Response("not json", { status: 200 }),
      new Response("", { status: 502 }),
    ];
    const fetchImpl = vi.fn(async () => answers.shift() ?? response(500, undefined));
    const api = createDesignIterationsApi({ fetchImpl });

    await expect(api.job("p", "job-1", "token")).rejects.toMatchObject({
      status: 404,
      code: "GENERATION_JOB_NOT_FOUND",
    });
    await expect(api.list("p", "token")).rejects.toMatchObject({
      code: "INVALID_API_RESPONSE",
    });
    await expect(api.list("p", "token")).rejects.toMatchObject({
      status: 502,
      code: null,
      message: "Design Iterations API request failed with status 502",
    });
    await expect(api.list("p", "")).rejects.toMatchObject({ code: "ACCESS_TOKEN_REQUIRED" });
    expect(fetchImpl).toHaveBeenCalledTimes(3);
  });
});
