import { describe, expect, it, vi } from "vitest";

import type { AcceptanceTestsOverviewPayload, TestRunPayload } from "../types/acceptanceTests";
import { AcceptanceTestsApiError, createAcceptanceTestsApi } from "./acceptanceTests";

const PROJECT_ID = "11111111-1111-4111-8111-111111111111";
const ACCESS_TOKEN = "test-token-not-real";

const RUN: TestRunPayload = {
  id: "22222222-2222-4222-8222-222222222222",
  started_at: "2026-09-29T10:00:00+00:00",
  finished_at: "2026-09-29T10:04:00+00:00",
  recorded_at: "2026-09-29T10:04:05+00:00",
  application: { kind: "STATIC", address: "dist" },
  browsers: [
    { name: "chrome", version: "151.0.7922.76" },
    { name: "firefox", version: "156.0.1" },
  ],
  reference: {
    requirements_version_number: 1,
    design_version_number: 4,
    alternative_code: "DES-002",
  },
  summary: { passed: 1, failed: 0, blocked: 0, not_covered: 1, not_run: 0 },
  criteria: [
    { code: "AC-001", status: "PASSED", paths: ["TP-001"] },
    { code: "AC-002", status: "NOT_COVERED", paths: [] },
  ],
  not_covered: [{ criterion: "AC-002", reason: "It needs a manual check of the printed list." }],
  results: [
    {
      path: {
        code: "TP-001",
        heading: "Open the guest list",
        criteria: ["AC-001"],
        steps: [
          { action: "OPEN", target: null, value: "/", expect: null },
          {
            action: "CHECK",
            target: null,
            value: null,
            expect: { kind: "TEXT_VISIBLE", target: null, text: "Guests of the day" },
          },
        ],
      },
      browser: "chrome",
      status: "PASSED",
      seconds: 4.2,
      steps: [
        {
          index: 1,
          status: "DONE",
          detail: null,
          url: "http://127.0.0.1:50123/",
          title: "Guests",
          screenshot: "TP-001/chrome/01.png",
        },
        {
          index: 2,
          status: "DONE",
          detail: null,
          url: "http://127.0.0.1:50123/",
          title: "Guests",
          screenshot: "TP-001/chrome/02.png",
        },
      ],
      page_text: "Guests of the day",
    },
  ],
  critiques: [],
  reviewed_at: null,
  cost_microusd: 200000,
};

const OVERVIEW: AcceptanceTestsOverviewPayload = {
  project_id: PROJECT_ID,
  reference: {
    requirements: { version_id: "r", version_number: 1, content_hash: "a".repeat(64) },
    design: {
      version_id: "d",
      version_number: 4,
      content_hash: "b".repeat(64),
      alternative_code: "DES-002",
    },
  },
  plan_available: true,
  plans: 2,
  runs: 1,
  latest_run: RUN,
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("Acceptance Tests API client", () => {
  it("reads the overview of the acceptance tests with an authenticated GET", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(OVERVIEW));
    const api = createAcceptanceTestsApi({ fetchImpl });

    const overview = await api.overview(PROJECT_ID, ACCESS_TOKEN);

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const call = fetchImpl.mock.calls[0];
    expect(call?.[0]).toBe(`/api/v1/projects/${PROJECT_ID}/acceptance-tests`);
    expect(call?.[1]?.method).toBe("GET");
    expect(call?.[1]?.credentials).toBe("include");
    expect(call?.[1]?.headers).toEqual({
      Accept: "application/json",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
    });
    expect(call?.[1]).not.toHaveProperty("body");
    expect(overview).toEqual(OVERVIEW);
  });

  it("reads a project without runs", async () => {
    const empty: AcceptanceTestsOverviewPayload = {
      ...OVERVIEW,
      plan_available: false,
      plans: 0,
      runs: 0,
      latest_run: null,
    };
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(empty));
    const api = createAcceptanceTestsApi({ fetchImpl });

    await expect(api.overview(PROJECT_ID, ACCESS_TOKEN)).resolves.toEqual(empty);
  });

  it("reads whether the latest run is stale and the latest review of an older run", async () => {
    const reviewed: AcceptanceTestsOverviewPayload = {
      ...OVERVIEW,
      latest_run_stale: true,
      latest_review: {
        run_id: "33333333-3333-4333-8333-333333333333",
        finished_at: "2026-09-28T10:04:00+00:00",
        reviewed_at: "2026-09-28T10:06:00+00:00",
        critiques: [
          {
            twin_id: "44444444-4444-4444-8444-444444444444",
            twin_name: "Reception staff",
            verdict: "FINE",
            summary: "The list is what I need.",
            findings: [],
          },
        ],
      },
    };
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(reviewed))
      .mockResolvedValueOnce(
        jsonResponse({ ...OVERVIEW, latest_run_stale: false, latest_review: null }),
      );
    const api = createAcceptanceTestsApi({ fetchImpl });

    await expect(api.overview(PROJECT_ID, ACCESS_TOKEN)).resolves.toEqual(reviewed);
    await expect(api.overview(PROJECT_ID, ACCESS_TOKEN)).resolves.toEqual({
      ...OVERVIEW,
      latest_run_stale: false,
      latest_review: null,
    });
  });

  it("uses the base path and encodes the project of the path", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(OVERVIEW));
    const api = createAcceptanceTestsApi({ basePath: "/studio/api/v1/", fetchImpl });

    await api.overview("project 1/a", ACCESS_TOKEN);

    expect(fetchImpl.mock.calls[0]?.[0]).toBe(
      "/studio/api/v1/projects/project%201%2Fa/acceptance-tests",
    );
  });

  it("keeps the typed code of a project of another account", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse({ detail: { code: "PROJECT_NOT_FOUND" } }, 404));
    const api = createAcceptanceTestsApi({ fetchImpl });

    const missing = api.overview(PROJECT_ID, ACCESS_TOKEN);

    await expect(missing).rejects.toBeInstanceOf(AcceptanceTestsApiError);
    await expect(missing).rejects.toMatchObject({
      name: "AcceptanceTestsApiError",
      message: "The acceptance tests request failed",
      status: 404,
      code: "PROJECT_NOT_FOUND",
      payload: { detail: { code: "PROJECT_NOT_FOUND" } },
    });
  });

  it("keeps a refusal without a typed code and a body that is not JSON", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ detail: "invalid_request" }, 422))
      .mockResolvedValueOnce(new Response("Bad gateway", { status: 502 }))
      .mockResolvedValueOnce(new Response("", { status: 500 }));
    const api = createAcceptanceTestsApi({ fetchImpl });

    await expect(api.overview(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      status: 422,
      code: null,
      payload: { detail: "invalid_request" },
    });
    await expect(api.overview(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      status: 502,
      code: null,
      payload: "Bad gateway",
    });
    await expect(api.overview(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      status: 500,
      code: null,
      payload: null,
    });
  });

  it("rejects an answer that is not an overview", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(new Response("<html>proxy error</html>", { status: 200 }))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse({ project_id: PROJECT_ID }))
      .mockResolvedValueOnce(jsonResponse({ ...OVERVIEW, latest_run: "none" }));
    const api = createAcceptanceTestsApi({ fetchImpl });

    await expect(api.overview(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      name: "AcceptanceTestsApiError",
      status: 200,
      code: "INVALID_API_RESPONSE",
      payload: "<html>proxy error</html>",
    });
    await expect(api.overview(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      code: "INVALID_API_RESPONSE",
      payload: [],
    });
    await expect(api.overview(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      code: "INVALID_API_RESPONSE",
      payload: { project_id: PROJECT_ID },
    });
    await expect(api.overview(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      code: "INVALID_API_RESPONSE",
    });
  });

  it.each([
    ["a stale flag that is not a boolean", { ...OVERVIEW, latest_run_stale: "yes" }],
    ["a latest review that is not an object", { ...OVERVIEW, latest_review: "none" }],
    [
      "a latest review without critiques",
      { ...OVERVIEW, latest_review: { run_id: RUN.id, finished_at: RUN.finished_at } },
    ],
    [
      "a latest review without the date of its run",
      { ...OVERVIEW, latest_review: { run_id: RUN.id, critiques: [] } },
    ],
  ])("rejects an overview with %s", async (_case, body) => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(body));
    const api = createAcceptanceTestsApi({ fetchImpl });

    await expect(api.overview(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      name: "AcceptanceTestsApiError",
      code: "INVALID_API_RESPONSE",
      payload: body,
    });
  });

  it("refuses to call the Studio without an access token", async () => {
    const fetchImpl = vi.fn<typeof fetch>();
    const api = createAcceptanceTestsApi({ fetchImpl });

    await expect(api.overview(PROJECT_ID, " ")).rejects.toMatchObject({
      name: "AcceptanceTestsApiError",
      status: 0,
      code: "ACCESS_TOKEN_REQUIRED",
    });
    await expect(api.overview(PROJECT_ID, "")).rejects.toMatchObject({
      code: "ACCESS_TOKEN_REQUIRED",
    });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("refuses an empty base path", () => {
    expect(() => createAcceptanceTestsApi({ basePath: " / ", fetchImpl: vi.fn() })).toThrow(
      "Acceptance Tests API base path must not be empty",
    );
  });
});
