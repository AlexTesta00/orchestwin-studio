import { describe, expect, it, vi } from "vitest";

import { createDesignMockupsApi, DesignMockupsApiError } from "./designMockups";

const PROJECT_ID = "project 1";
const ENCODED_PROJECT = "project%201";
const ALTERNATIVE_ID = "00000000-0000-4000-8000-000000000104";
const JOB_ID = "job/1";

function response(status: number, body: unknown): Response {
  return new Response(body === undefined ? "" : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function job(status = "RUNNING") {
  return {
    job_id: "job-1",
    kind: "MOCKUP",
    status,
    stage: status === "RUNNING" ? "GENERATING" : null,
    attempt: 1,
    started_at: "2026-09-29T09:12:03+00:00",
    finished_at: null,
    alternative_id: ALTERNATIVE_ID,
    result: null,
    failure: null,
  };
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

describe("design mockups api", () => {
  it("reads the capabilities of the project with the bearer token", async () => {
    const fetchImpl = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      expect(init?.credentials).toBe("include");
      return response(200, {
        generated_mockups: true,
        iterations: true,
        model: "claude-opus-5-5",
      });
    });
    const api = createDesignMockupsApi({ basePath: "/api/v1/", fetchImpl });

    const capabilities = await api.capabilities(PROJECT_ID, "token");

    expect(capabilities).toEqual({
      generated_mockups: true,
      iterations: true,
      model: "claude-opus-5-5",
    });
    const [call] = calls(fetchImpl);
    expect(call?.url).toBe(`/api/v1/projects/${ENCODED_PROJECT}/design/mockups/capabilities`);
    expect(call?.method).toBe("GET");
    expect(call?.headers).toMatchObject({
      Accept: "application/json",
      Authorization: "Bearer token",
    });
    expect(call?.body).toBeUndefined();
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("reads the capabilities of a local model", async () => {
    const api = createDesignMockupsApi({
      fetchImpl: async () =>
        response(200, { generated_mockups: false, iterations: false, model: null }),
    });

    expect(await api.capabilities("p", "token")).toEqual({
      generated_mockups: false,
      iterations: false,
      model: null,
    });
  });

  it("starts a mockup job with the design context and reads it back", async () => {
    const fetchImpl = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) =>
      init?.method === "POST" ? response(202, job()) : response(200, job("SUCCEEDED")),
    );
    const api = createDesignMockupsApi({ fetchImpl });
    const body = {
      design_version_id: "version-1",
      design_content_hash: "a".repeat(64),
      alternative_id: ALTERNATIVE_ID,
    };

    const started = await api.startJob(PROJECT_ID, body, "token");
    const read = await api.job(PROJECT_ID, JOB_ID, "token");

    expect(started.status).toBe("RUNNING");
    expect(read.status).toBe("SUCCEEDED");
    expect(calls(fetchImpl)).toEqual([
      {
        url: `/api/v1/projects/${ENCODED_PROJECT}/design/mockups/jobs`,
        method: "POST",
        headers: {
          Accept: "application/json",
          Authorization: "Bearer token",
          "Content-Type": "application/json",
        },
        body,
      },
      {
        url: `/api/v1/projects/${ENCODED_PROJECT}/design/mockups/jobs/job%2F1`,
        method: "GET",
        headers: { Accept: "application/json", Authorization: "Bearer token" },
        body: undefined,
      },
    ]);
  });

  it("returns the newest accepted mockup or null when there is none", async () => {
    const result = {
      status: "MOCKUP_GENERATED",
      generation_id: "generation-1",
      design_version_id: "version-1",
      design_content_hash: "a".repeat(64),
      package: {},
      approach: "Dashboard first",
      changes: [],
      warnings: [],
      cost_microusd: 412000,
    };
    const answers = [response(200, result), response(200, null), response(200, undefined)];
    const fetchImpl = vi.fn(async () => answers.shift() ?? response(200, null));
    const api = createDesignMockupsApi({ fetchImpl });

    expect(await api.latest(PROJECT_ID, ALTERNATIVE_ID, "token")).toEqual(result);
    expect(await api.latest(PROJECT_ID, ALTERNATIVE_ID, "token")).toBeNull();
    expect(await api.latest(PROJECT_ID, ALTERNATIVE_ID, "token")).toBeNull();
    expect(calls(fetchImpl)[0]?.url).toBe(
      `/api/v1/projects/${ENCODED_PROJECT}/design/mockups?alternative_id=${ALTERNATIVE_ID}`,
    );
  });

  it("asks for a document with its source and, when given, its entry screen", async () => {
    const document = {
      html: "<!doctype html><html></html>",
      content_hash: "c".repeat(64),
      source: "latest",
      alternative_id: ALTERNATIVE_ID,
      title: "Registro prestiti",
      entry_screen: "SCR-002",
      screens: [{ code: "SCR-001", title: "Prestiti", state: "DEFAULT" }],
    };
    const fetchImpl = vi.fn(async () => response(200, document));
    const api = createDesignMockupsApi({ fetchImpl });

    expect(
      await api.document(
        PROJECT_ID,
        { alternative_id: ALTERNATIVE_ID, source: "latest", entry_screen: "SCR-002" },
        "token",
      ),
    ).toEqual(document);
    await api.document(PROJECT_ID, { alternative_id: ALTERNATIVE_ID, source: "applied" }, "token");

    expect(calls(fetchImpl).map((call) => call.url)).toEqual([
      `/api/v1/projects/${ENCODED_PROJECT}/design/mockups/document?alternative_id=${ALTERNATIVE_ID}&source=latest&entry_screen=SCR-002`,
      `/api/v1/projects/${ENCODED_PROJECT}/design/mockups/document?alternative_id=${ALTERNATIVE_ID}&source=applied`,
    ]);
  });

  it.each([
    [409, "DESIGN_CONTEXT_CHANGED"],
    [422, "DESIGN_ALTERNATIVE_NOT_FOUND"],
    [422, "GENERATED_MOCKUP_REQUIRES_VISUAL_LANGUAGE"],
    [429, "TOO_MANY_GENERATIONS"],
    [402, "GENERATION_BUDGET_EXCEEDED"],
    [503, "GENERATION_BUDGET_UNAVAILABLE"],
    [503, "REAL_MOCKUP_MODEL_NOT_CONFIGURED"],
  ])("surfaces the refusal %i %s when a job is started", async (status, code) => {
    const payload = { detail: { code, stage: "MODEL_PROPOSAL" } };
    const api = createDesignMockupsApi({ fetchImpl: async () => response(status, payload) });

    const failure = api.startJob(
      "p",
      { design_version_id: "v", design_content_hash: "a".repeat(64), alternative_id: "x" },
      "token",
    );

    await expect(failure).rejects.toBeInstanceOf(DesignMockupsApiError);
    await expect(failure).rejects.toMatchObject({
      name: "DesignMockupsApiError",
      status,
      code,
      message: code,
      payload,
    });
  });

  it("surfaces a job or a document that does not exist", async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) =>
      String(input).includes("/jobs/")
        ? response(404, { detail: { code: "GENERATION_JOB_NOT_FOUND" } })
        : response(404, { detail: { code: "GENERATED_MOCKUP_NOT_FOUND" } }),
    );
    const api = createDesignMockupsApi({ fetchImpl });

    await expect(api.job("p", "job-1", "token")).rejects.toMatchObject({
      status: 404,
      code: "GENERATION_JOB_NOT_FOUND",
    });
    await expect(
      api.document("p", { alternative_id: "x", source: "applied" }, "token"),
    ).rejects.toMatchObject({ status: 404, code: "GENERATED_MOCKUP_NOT_FOUND" });
  });

  it("reports a failure without code with its status and an unreadable answer", async () => {
    const answers = [
      new Response("", { status: 500 }),
      new Response("<html>proxy error</html>", { status: 200 }),
    ];
    const api = createDesignMockupsApi({
      fetchImpl: async () => answers.shift() ?? new Response("", { status: 500 }),
    });

    await expect(api.capabilities("p", "token")).rejects.toMatchObject({
      status: 500,
      code: null,
      message: "Design Mockups API request failed with status 500",
    });
    await expect(api.capabilities("p", "token")).rejects.toMatchObject({
      status: 200,
      code: "INVALID_API_RESPONSE",
    });
  });

  it("refuses to call the server without an access token", async () => {
    const fetchImpl = vi.fn();
    const api = createDesignMockupsApi({ fetchImpl });

    await expect(api.latest("p", "x", "  ")).rejects.toMatchObject({
      status: 0,
      code: "ACCESS_TOKEN_REQUIRED",
    });
    expect(fetchImpl).not.toHaveBeenCalled();
    expect(() => createDesignMockupsApi({ basePath: " / " })).toThrow();
  });
});
