import { afterEach, describe, expect, it, vi } from "vitest";

import { clearFollowedGenerations } from "./generationJobs";
import { createRequirementsApi, RequirementsApiError } from "./requirements";

const PROJECT_ID = "00000000-0000-4000-8000-000000000010";
const ACCESS_TOKEN = "access-token";
const JOB_ID = "00000000-0000-4000-8000-0000000000aa";

function job(
  response: { status_code: number; body: unknown } | null,
  operation = "REQUIREMENTS_PROPOSAL",
) {
  return {
    job_id: JOB_ID,
    kind: "REQUEST",
    operation,
    status: response === null ? "RUNNING" : response.status_code < 400 ? "SUCCEEDED" : "FAILED",
    stage: response === null ? "GENERATING" : null,
    attempt: 1,
    started_at: "2026-09-28T10:00:00+00:00",
    finished_at: response === null ? null : "2026-09-28T10:02:00+00:00",
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

describe("Requirements API client", () => {
  it("sends an authenticated request to the readiness endpoint", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      void init;

      return response({
        status: "REQUIREMENTS_REQUIRED",
        version: null,
        gate: null,
        approved_current_specification: false,
      });
    });
    const api = createRequirementsApi({
      fetchImpl: fetchMock,
    });

    await api.readiness(PROJECT_ID, ACCESS_TOKEN);

    const [input, init] = firstCall(
      fetchMock.mock.calls as [RequestInfo | URL, RequestInit?][],
      "readiness fetch call",
    );

    expect(input).toBe(`/api/v1/projects/${PROJECT_ID}/requirements/readiness`);
    expect(init?.method).toBe("GET");
    expect(init?.credentials).toBe("include");
    expect(init?.headers).toMatchObject({
      Accept: "application/json",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
    });
    expect(init).not.toHaveProperty("body");
  });

  it("serializes a Gate 4 decision request", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      void init;

      return response({
        status: "APPLIED",
        gate: null,
        event: null,
        issue: null,
      });
    });
    const api = createRequirementsApi({
      fetchImpl: fetchMock,
    });

    await api.decideGate(
      PROJECT_ID,
      {
        action: "REQUEST_REVISION",
        reason: "Add measurable acceptance criteria.",
      },
      ACCESS_TOKEN,
    );

    const [input, init] = firstCall(
      fetchMock.mock.calls as [RequestInfo | URL, RequestInit?][],
      "decision fetch call",
    );

    expect(input).toBe(`/api/v1/projects/${PROJECT_ID}/requirements/gate/decision`);
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe(
      JSON.stringify({
        action: "REQUEST_REVISION",
        reason: "Add measurable acceptance criteria.",
      }),
    );
  });

  it("preserves backend conflict codes", async () => {
    const api = createRequirementsApi({
      fetchImpl: async () =>
        response(
          {
            detail: {
              code: "USER_MODELING_APPROVAL_REQUIRED",
            },
          },
          409,
        ),
    });

    await expect(api.generate(PROJECT_ID, ACCESS_TOKEN)).rejects.toEqual(
      expect.objectContaining({
        name: "RequirementsApiError",
        status: 409,
        code: "USER_MODELING_APPROVAL_REQUIRED",
      }),
    );
  });

  it("rejects requests without an in-memory access token", async () => {
    const api = createRequirementsApi({
      fetchImpl: vi.fn(),
    });

    await expect(api.history(PROJECT_ID, " ")).rejects.toBeInstanceOf(RequirementsApiError);
  });

  it.each([
    [
      "the reason of a refused proposal",
      { code: "PROPOSAL_REJECTED", proposal_issue: "REQUIREMENTS_ANALYST_REQUIRED" },
      "REQUIREMENTS_ANALYST_REQUIRED",
    ],
    ["the refusal when no reason is given", { code: "PROPOSAL_REJECTED" }, "PROPOSAL_REJECTED"],
    [
      "the refusal when the reason is null",
      { code: "PROPOSAL_REJECTED", proposal_issue: null },
      "PROPOSAL_REJECTED",
    ],
    [
      "the refusal when the reason is not text",
      { code: "PROPOSAL_REJECTED", proposal_issue: ["GROUNDED_INPUT_REQUIRED"] },
      "PROPOSAL_REJECTED",
    ],
    [
      "the refusal when the reason is empty",
      { code: "PROPOSAL_REJECTED", proposal_issue: "" },
      "PROPOSAL_REJECTED",
    ],
    ["any other conflict as it is", { code: "REQUIREMENTS_UNCHANGED" }, "REQUIREMENTS_UNCHANGED"],
  ])("uses as the code of a proposal and of a change %s", async (_case, detail, code) => {
    const api = createRequirementsApi({ fetchImpl: async () => response({ detail }, 409) });

    const errors = await Promise.all([
      api.generate(PROJECT_ID, ACCESS_TOKEN).catch((caught: unknown) => caught),
      api
        .requestChange(PROJECT_ID, "Add the search by name.", ACCESS_TOKEN)
        .catch((caught: unknown) => caught),
    ]);

    for (const error of errors) {
      expect(error).toBeInstanceOf(RequirementsApiError);
      expect(error).toMatchObject({ status: 409, code, message: code });
      expect((error as RequirementsApiError).payload).toEqual({ detail });
    }
  });
});

describe("Requirements generation in the background", () => {
  const created = {
    status: "CREATED",
    version: null,
    issue: null,
    proposal_issue: null,
    persistence_status: null,
  };

  afterEach(() => {
    vi.useRealTimers();
    clearFollowedGenerations();
  });

  it("asks for a job and resolves with the answer the job carries", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      return init?.method === "POST"
        ? response(job(null), 202)
        : response(job({ status_code: 201, body: created }));
    });
    const api = createRequirementsApi({ fetchImpl: fetchMock });

    const pending = api.generate(PROJECT_ID, ACCESS_TOKEN);
    await vi.advanceTimersByTimeAsync(2000);

    await expect(pending).resolves.toEqual(created);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [postInput, postInit] = fetchMock.mock.calls[0] ?? [];
    expect(postInput).toBe(`/api/v1/projects/${PROJECT_ID}/requirements/proposals`);
    expect(postInit?.headers).toMatchObject({
      Authorization: `Bearer ${ACCESS_TOKEN}`,
      Prefer: "respond-async",
    });
    expect(fetchMock.mock.calls[1]?.[0]).toBe(
      `/api/v1/projects/${PROJECT_ID}/generation-jobs/${JOB_ID}`,
    );
  });

  it("throws for a refused job the same error as the synchronous answer", async () => {
    const refusal = { detail: { code: "USER_MODELING_APPROVAL_REQUIRED" } };
    const synchronous = createRequirementsApi({ fetchImpl: async () => response(refusal, 409) });
    const expected = await synchronous.generate(PROJECT_ID, ACCESS_TOKEN).catch((error) => error);
    vi.useFakeTimers();
    const background = createRequirementsApi({
      fetchImpl: async (input: RequestInfo | URL, init?: RequestInit) => {
        void input;
        return init?.method === "POST"
          ? response(job(null), 202)
          : response(job({ status_code: 409, body: refusal }));
      },
    });

    const pending = background.generate(PROJECT_ID, ACCESS_TOKEN).catch((error) => error);
    await vi.advanceTimersByTimeAsync(2000);
    const actual = await pending;

    expect(expected).toBeInstanceOf(RequirementsApiError);
    expect(actual).toBeInstanceOf(RequirementsApiError);
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
      detail: { code: "PROPOSAL_REJECTED", proposal_issue: "REQUIREMENTS_ANALYST_REQUIRED" },
    };
    const synchronous = createRequirementsApi({ fetchImpl: async () => response(refusal, 409) });
    const expected = await synchronous.generate(PROJECT_ID, ACCESS_TOKEN).catch((error) => error);
    vi.useFakeTimers();
    const background = createRequirementsApi({
      fetchImpl: async (input: RequestInfo | URL, init?: RequestInit) => {
        void input;
        return init?.method === "POST"
          ? response(job(null), 202)
          : response(job({ status_code: 409, body: refusal }));
      },
    });

    const pending = background.generate(PROJECT_ID, ACCESS_TOKEN).catch((error) => error);
    await vi.advanceTimersByTimeAsync(2000);
    const actual = await pending;

    expect(expected).toMatchObject({ status: 409, code: "REQUIREMENTS_ANALYST_REQUIRED" });
    expect(actual).toBeInstanceOf(RequirementsApiError);
    expect(actual).toMatchObject({
      name: expected.name,
      message: expected.message,
      status: expected.status,
      code: expected.code,
      payload: expected.payload,
    });
  });

  it("returns the answer of a server that does not know background jobs", async () => {
    const fetchMock = vi.fn(async () => response(created, 201));
    const api = createRequirementsApi({ fetchImpl: fetchMock });

    await expect(api.generate(PROJECT_ID, ACCESS_TOKEN)).resolves.toEqual(created);
    expect(fetchMock).toHaveBeenCalledOnce();
  });
});

describe("Requirements written again from a request of the owner", () => {
  const CHANGE_URL = `/api/v1/projects/${PROJECT_ID}/requirements/change-requests`;
  const REQUEST = "Add the search by the name of the guest.";
  const proposed = {
    status: "CREATED",
    diff: null,
    version: null,
    issue: null,
    proposal_issue: null,
    diff_persistence_status: "APPENDED",
    version_persistence_status: null,
  };

  afterEach(() => {
    vi.useRealTimers();
    clearFollowedGenerations();
  });

  it("sends the request as a background job and resolves with the proposed revision", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      return init?.method === "POST"
        ? response(job(null, "REQUIREMENTS_CHANGE"), 202)
        : response(job({ status_code: 201, body: proposed }, "REQUIREMENTS_CHANGE"));
    });
    const api = createRequirementsApi({ fetchImpl: fetchMock });

    const pending = api.requestChange(PROJECT_ID, REQUEST, ACCESS_TOKEN);
    await vi.advanceTimersByTimeAsync(2000);

    await expect(pending).resolves.toEqual(proposed);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [postInput, postInit] = fetchMock.mock.calls[0] ?? [];
    expect(postInput).toBe(CHANGE_URL);
    expect(postInit?.method).toBe("POST");
    expect(postInit?.body).toBe(JSON.stringify({ request: REQUEST }));
    expect(postInit?.headers).toMatchObject({
      Accept: "application/json",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
      "Content-Type": "application/json",
      Prefer: "respond-async",
    });
    expect(fetchMock.mock.calls[1]?.[0]).toBe(
      `/api/v1/projects/${PROJECT_ID}/generation-jobs/${JOB_ID}`,
    );
  });

  it("returns the proposed revision of a server that answers at once", async () => {
    const fetchMock = vi.fn(async () => response(proposed, 201));
    const api = createRequirementsApi({ fetchImpl: fetchMock });

    await expect(api.requestChange(PROJECT_ID, REQUEST, ACCESS_TOKEN)).resolves.toEqual(proposed);
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("keeps the code of a refusal that the job carries", async () => {
    vi.useFakeTimers();
    const refusal = { detail: { code: "REQUIREMENTS_UNCHANGED" } };
    const api = createRequirementsApi({
      fetchImpl: async (input: RequestInfo | URL, init?: RequestInit) => {
        void input;
        return init?.method === "POST"
          ? response(job(null, "REQUIREMENTS_CHANGE"), 202)
          : response(job({ status_code: 409, body: refusal }, "REQUIREMENTS_CHANGE"));
      },
    });

    const pending = api.requestChange(PROJECT_ID, REQUEST, ACCESS_TOKEN).catch((error) => error);
    await vi.advanceTimersByTimeAsync(2000);

    await expect(pending).resolves.toMatchObject({
      name: "RequirementsApiError",
      status: 409,
      code: "REQUIREMENTS_UNCHANGED",
    });
  });

  it("keeps the reason of a refused change that the job carries", async () => {
    vi.useFakeTimers();
    const refusal = {
      detail: { code: "PROPOSAL_REJECTED", proposal_issue: "GROUNDED_INPUT_REQUIRED" },
    };
    const api = createRequirementsApi({
      fetchImpl: async (input: RequestInfo | URL, init?: RequestInit) => {
        void input;
        return init?.method === "POST"
          ? response(job(null, "REQUIREMENTS_CHANGE"), 202)
          : response(job({ status_code: 409, body: refusal }, "REQUIREMENTS_CHANGE"));
      },
    });

    const pending = api.requestChange(PROJECT_ID, REQUEST, ACCESS_TOKEN).catch((error) => error);
    await vi.advanceTimersByTimeAsync(2000);

    await expect(pending).resolves.toMatchObject({
      name: "RequirementsApiError",
      status: 409,
      code: "GROUNDED_INPUT_REQUIRED",
      payload: refusal,
    });
  });

  it("tells a server without the operation apart from requirements that do not exist", async () => {
    const missingRoute = createRequirementsApi({
      fetchImpl: async () => response({ detail: "Not Found" }, 404),
    });
    const missingRequirements = createRequirementsApi({
      fetchImpl: async () =>
        response({ detail: { code: "REQUIREMENTS_SPECIFICATION_NOT_FOUND" } }, 404),
    });

    await expect(
      missingRoute.requestChange(PROJECT_ID, REQUEST, ACCESS_TOKEN),
    ).rejects.toMatchObject({ status: 404, code: null });
    await expect(
      missingRequirements.requestChange(PROJECT_ID, REQUEST, ACCESS_TOKEN),
    ).rejects.toMatchObject({ status: 404, code: "REQUIREMENTS_SPECIFICATION_NOT_FOUND" });
  });
});
