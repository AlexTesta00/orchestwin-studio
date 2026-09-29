import { afterEach, describe, expect, it, vi } from "vitest";

import { createDesignApi, DesignApiError } from "./design";
import { clearFollowedGenerations } from "./generationJobs";

const PROJECT_ID = "00000000-0000-4000-8000-000000000010";
const DIFF_ID = "00000000-0000-4000-8000-000000000020";
const ACCESS_TOKEN = "access-token";
const JOB_ID = "00000000-0000-4000-8000-0000000000aa";

function job(response: { status_code: number; body: unknown } | null) {
  return {
    job_id: JOB_ID,
    kind: "REQUEST",
    operation: "DESIGN_PROPOSAL",
    status: response === null ? "RUNNING" : response.status_code < 400 ? "SUCCEEDED" : "FAILED",
    stage: response === null ? "GENERATING" : null,
    attempt: 1,
    started_at: "2026-09-28T10:00:00+00:00",
    finished_at: response === null ? null : "2026-09-28T10:03:06+00:00",
    alternative_id: null,
    result: null,
    failure: null,
    response,
  };
}

function response(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(payload),
  } as Response;
}

function firstCall<T>(values: readonly T[], label: string): T {
  const value = values[0];

  if (value === undefined) {
    throw new Error(`${label} was expected`);
  }

  return value;
}

describe("Design API client", () => {
  it("sends an authenticated request to the readiness endpoint", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      void init;

      return response({
        status: "DESIGN_REQUIRED",
        version: null,
        gate: null,
        has_package: false,
        package_ready_for_gate: false,
        approved_current_package: false,
      });
    });
    const api = createDesignApi({
      fetchImpl: fetchMock,
    });

    await api.readiness(PROJECT_ID, ACCESS_TOKEN);

    const [input, init] = firstCall(
      fetchMock.mock.calls as [RequestInfo | URL, RequestInit?][],
      "readiness fetch call",
    );

    expect(input).toBe(`/api/v1/projects/${PROJECT_ID}/design/readiness`);
    expect(init?.method).toBe("GET");
    expect(init?.credentials).toBe("include");
    expect(init?.headers).toMatchObject({
      Accept: "application/json",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
    });
    expect(init).not.toHaveProperty("body");
  });

  it("serializes an owner decision for a Design Package diff", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      void init;

      return response({
        status: "APPLIED",
        diff: null,
        version: null,
        issue: null,
        domain_issue: null,
        diff_persistence_status: null,
        version_persistence_status: null,
      });
    });
    const api = createDesignApi({
      fetchImpl: fetchMock,
    });

    await api.decideRevision(
      PROJECT_ID,
      DIFF_ID,
      {
        decision: "REJECT",
        reason: "The selected workflow still needs revision.",
      },
      ACCESS_TOKEN,
    );

    const [input, init] = firstCall(
      fetchMock.mock.calls as [RequestInfo | URL, RequestInit?][],
      "revision decision fetch call",
    );

    expect(input).toBe(`/api/v1/projects/${PROJECT_ID}/design/revisions/${DIFF_ID}/decision`);
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe(
      JSON.stringify({
        decision: "REJECT",
        reason: "The selected workflow still needs revision.",
      }),
    );
  });

  it("preserves backend governance conflict codes", async () => {
    const api = createDesignApi({
      fetchImpl: async () =>
        response(
          {
            detail: {
              code: "REQUIREMENTS_APPROVAL_REQUIRED",
            },
          },
          409,
        ),
    });

    await expect(api.generate(PROJECT_ID, ACCESS_TOKEN)).rejects.toEqual(
      expect.objectContaining({
        name: "DesignApiError",
        status: 409,
        code: "REQUIREMENTS_APPROVAL_REQUIRED",
      }),
    );
  });

  it("rejects requests without an in-memory access token", async () => {
    const api = createDesignApi({
      fetchImpl: vi.fn(),
    });

    await expect(api.history(PROJECT_ID, " ")).rejects.toBeInstanceOf(DesignApiError);
  });

  it.each([
    [
      "the reason of a refused proposal",
      { code: "PROPOSAL_REJECTED", proposal_issue: "UX_DESIGNER_REQUIRED" },
      "UX_DESIGNER_REQUIRED",
    ],
    ["the refusal when no reason is given", { code: "PROPOSAL_REJECTED" }, "PROPOSAL_REJECTED"],
    [
      "the refusal when the reason is null",
      { code: "PROPOSAL_REJECTED", proposal_issue: null },
      "PROPOSAL_REJECTED",
    ],
    [
      "the refusal when the reason is not text",
      { code: "PROPOSAL_REJECTED", proposal_issue: { code: "UX_DESIGNER_REQUIRED" } },
      "PROPOSAL_REJECTED",
    ],
    [
      "the refusal when the reason is empty",
      { code: "PROPOSAL_REJECTED", proposal_issue: "" },
      "PROPOSAL_REJECTED",
    ],
    [
      "any other conflict as it is",
      { code: "DESIGN_PACKAGE_ALREADY_EXISTS" },
      "DESIGN_PACKAGE_ALREADY_EXISTS",
    ],
  ])("uses as the code %s", async (_case, detail, code) => {
    const api = createDesignApi({ fetchImpl: async () => response({ detail }, 409) });

    const error = await api.generate(PROJECT_ID, ACCESS_TOKEN).catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(DesignApiError);
    expect(error).toMatchObject({ status: 409, code, message: code });
    expect((error as DesignApiError).payload).toEqual({ detail });
  });
});

describe("Design alternatives generated in the background", () => {
  const created = {
    status: "CREATED",
    version: null,
    issue: null,
    proposal_issue: null,
    persistence_status: "APPENDED",
  };

  function background(finalResponse: { status_code: number; body: unknown }) {
    return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      return init?.method === "POST" ? response(job(null), 202) : response(job(finalResponse));
    });
  }

  afterEach(() => {
    vi.useRealTimers();
    clearFollowedGenerations();
  });

  it("asks for a job and resolves with the answer the job carries", async () => {
    vi.useFakeTimers();
    const fetchMock = background({ status_code: 201, body: created });
    const api = createDesignApi({ fetchImpl: fetchMock });

    const pending = api.generate(PROJECT_ID, ACCESS_TOKEN);
    await vi.advanceTimersByTimeAsync(2000);

    await expect(pending).resolves.toEqual(created);
    const [postInput, postInit] = fetchMock.mock.calls[0] ?? [];
    expect(postInput).toBe(`/api/v1/projects/${PROJECT_ID}/design/proposals`);
    expect(postInit?.headers).toMatchObject({ Prefer: "respond-async" });
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  });

  it("throws for an error of the provider the same error as the synchronous answer", async () => {
    const refusal = { detail: { code: "TIMEOUT", stage: "MODEL_PROPOSAL" } };
    const synchronous = createDesignApi({ fetchImpl: async () => response(refusal, 503) });
    const expected = await synchronous.generate(PROJECT_ID, ACCESS_TOKEN).catch((error) => error);
    vi.useFakeTimers();
    const api = createDesignApi({ fetchImpl: background({ status_code: 503, body: refusal }) });

    const pending = api.generate(PROJECT_ID, ACCESS_TOKEN).catch((error) => error);
    await vi.advanceTimersByTimeAsync(2000);
    const actual = await pending;

    expect(actual).toBeInstanceOf(DesignApiError);
    expect(actual).toMatchObject({
      name: expected.name,
      message: expected.message,
      status: expected.status,
      code: expected.code,
      payload: expected.payload,
    });
  });

  it("throws for a refused proposal that the job carries the reason of the synchronous answer", async () => {
    const refusal = {
      detail: { code: "PROPOSAL_REJECTED", proposal_issue: "UX_DESIGNER_REQUIRED" },
    };
    const synchronous = createDesignApi({ fetchImpl: async () => response(refusal, 409) });
    const expected = await synchronous.generate(PROJECT_ID, ACCESS_TOKEN).catch((error) => error);
    vi.useFakeTimers();
    const api = createDesignApi({ fetchImpl: background({ status_code: 409, body: refusal }) });

    const pending = api.generate(PROJECT_ID, ACCESS_TOKEN).catch((error) => error);
    await vi.advanceTimersByTimeAsync(2000);
    const actual = await pending;

    expect(expected).toMatchObject({ status: 409, code: "UX_DESIGNER_REQUIRED" });
    expect(actual).toBeInstanceOf(DesignApiError);
    expect(actual).toMatchObject({
      name: expected.name,
      message: expected.message,
      status: expected.status,
      code: expected.code,
      payload: expected.payload,
    });
  });

  it("throws for an error without handler the same error as the synchronous answer", async () => {
    const synchronous = createDesignApi({
      fetchImpl: async () =>
        ({
          ok: false,
          status: 500,
          text: async () => "Internal Server Error",
        }) as Response,
    });
    const expected = await synchronous.generate(PROJECT_ID, ACCESS_TOKEN).catch((error) => error);
    vi.useFakeTimers();
    const api = createDesignApi({
      fetchImpl: background({ status_code: 500, body: "Internal Server Error" }),
    });

    const pending = api.generate(PROJECT_ID, ACCESS_TOKEN).catch((error) => error);
    await vi.advanceTimersByTimeAsync(2000);
    const actual = await pending;

    expect(actual).toBeInstanceOf(DesignApiError);
    expect(actual).toMatchObject({
      message: expected.message,
      status: expected.status,
      code: expected.code,
      payload: expected.payload,
    });
  });
});
