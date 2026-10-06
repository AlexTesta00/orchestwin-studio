import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthenticationApi } from "./contracts";
import {
  clearFollowedGenerations,
  createGenerationJobsApi,
  followedGenerationJobs,
  GENERATION_JOB_CANCELLED,
  GENERATION_JOB_NOT_FOUND,
  GENERATION_POLL_TIMEOUT,
  generationJobOf,
  GenerationJobsApiError,
  INVALID_API_RESPONSE,
  isGenerationInterrupted,
  isGenerationLost,
  onFollowedGenerationJob,
  POLL_LIMIT_MILLISECONDS,
  pollInterval,
  sendGeneration,
  type GenerationJobEvent,
  type GenerationRequestJob,
} from "./generationJobs";
import { ApiRequestError } from "./requestError";
import { useAuthStore } from "../stores/auth";

const PROJECT_ID = "00000000-0000-4000-8000-000000000010";
const JOB_ID = "00000000-0000-4000-8000-0000000000aa";
const OPERATION_URL = `/api/v1/projects/${PROJECT_ID}/requirements/proposals`;
const JOB_URL = `/api/v1/projects/${PROJECT_ID}/generation-jobs/${JOB_ID}`;
const CREATED = { status: "CREATED", version: null, issue: null };

type Step = Response | Error;

function job(overrides: Partial<GenerationRequestJob> = {}): GenerationRequestJob {
  return {
    job_id: JOB_ID,
    kind: "REQUEST",
    operation: "REQUIREMENTS_PROPOSAL",
    status: "RUNNING",
    stage: "GENERATING",
    attempt: 1,
    started_at: "2026-09-28T10:00:00+00:00",
    finished_at: null,
    alternative_id: null,
    failure: null,
    response: null,
    ...overrides,
  };
}

function finished(statusCode: number, body: unknown): GenerationRequestJob {
  return job({
    status: statusCode < 400 ? "SUCCEEDED" : "FAILED",
    stage: null,
    finished_at: "2026-09-28T10:02:00+00:00",
    response: { status_code: statusCode, body },
  });
}

function json(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function request(token = "old-token"): RequestInit {
  return {
    method: "POST",
    headers: { Accept: "application/json", Authorization: `Bearer ${token}` },
    credentials: "include",
  };
}

function server(steps: Step[], accepted: Response | (() => Response) = () => json(job(), 202)) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    void input;

    if (init?.method === "POST") {
      return typeof accepted === "function" ? accepted() : accepted;
    }

    const next = steps.shift();

    if (next === undefined) {
      return json(job());
    }

    if (next instanceof Error) {
      throw next;
    }

    return next;
  });
}

function calls(fetchMock: ReturnType<typeof server>, method: "GET" | "POST") {
  return fetchMock.mock.calls.filter(([, init]) => init?.method === method);
}

function options(fetchImpl: typeof fetch) {
  return { fetchImpl, basePath: "/api/v1", projectId: PROJECT_ID };
}

describe("sendGeneration", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    clearFollowedGenerations();
  });

  afterEach(() => {
    vi.useRealTimers();
    clearFollowedGenerations();
  });

  it("asks for a background job and returns an answer that is not 202 as it is", async () => {
    const synchronous = json(CREATED, 201);
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      void init;
      return synchronous;
    });

    const response = await sendGeneration(OPERATION_URL, request(), options(fetchMock));

    expect(response).toBe(synchronous);
    expect(fetchMock).toHaveBeenCalledOnce();
    const [input, init] = fetchMock.mock.calls[0] ?? [];
    expect(input).toBe(OPERATION_URL);
    expect(init?.method).toBe("POST");
    expect(init?.credentials).toBe("include");
    expect(init?.headers).toMatchObject({
      Accept: "application/json",
      Authorization: "Bearer old-token",
      Prefer: "respond-async",
    });
  });

  it("follows the job every two seconds and resolves with the answer it carries", async () => {
    const fetchMock = server([json(job()), json(finished(201, CREATED))]);

    const pending = sendGeneration(OPERATION_URL, request(), options(fetchMock));
    await vi.advanceTimersByTimeAsync(1999);
    expect(calls(fetchMock, "GET")).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(1);
    expect(calls(fetchMock, "GET")).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(2000);
    const response = await pending;

    expect(response.status).toBe(201);
    expect(await response.json()).toEqual(CREATED);
    expect(calls(fetchMock, "POST")).toHaveLength(1);
    const [input, init] = calls(fetchMock, "GET")[0] ?? [];
    expect(input).toBe(JOB_URL);
    expect(init?.credentials).toBe("include");
    expect(init?.headers).toMatchObject({
      Accept: "application/json",
      Authorization: "Bearer old-token",
    });
    expect(followedGenerationJobs()).toEqual([]);
  });

  it("resolves an error of the job with the status and the body of the synchronous answer", async () => {
    const refusal = { detail: { code: "USER_MODELING_APPROVAL_REQUIRED" } };
    const fetchMock = server([json(finished(409, refusal))]);

    const pending = sendGeneration(OPERATION_URL, request(), options(fetchMock));
    await vi.advanceTimersByTimeAsync(2000);
    const response = await pending;

    expect(response.ok).toBe(false);
    expect(response.status).toBe(409);
    expect(await response.json()).toEqual(refusal);
    expect(calls(fetchMock, "POST")).toHaveLength(1);
  });

  it("asks for the job again after a network error and never sends the operation twice", async () => {
    const fetchMock = server([
      new TypeError("Failed to fetch"),
      new TypeError("Failed to fetch"),
      json(finished(201, CREATED)),
    ]);

    const pending = sendGeneration(OPERATION_URL, request(), options(fetchMock));
    await vi.advanceTimersByTimeAsync(6000);
    const response = await pending;

    expect(await response.json()).toEqual(CREATED);
    expect(calls(fetchMock, "POST")).toHaveLength(1);
    expect(calls(fetchMock, "GET")).toHaveLength(3);
  });

  it("asks for the job again after a temporary refusal of the server", async () => {
    const fetchMock = server([
      json({ detail: { code: "UPSTREAM" } }, 502),
      json({ detail: { code: "TOO_MANY_REQUESTS" } }, 429),
      new Response("<html>tunnel</html>", { status: 200 }),
      json(finished(201, CREATED)),
    ]);

    const pending = sendGeneration(OPERATION_URL, request(), options(fetchMock));
    await vi.advanceTimersByTimeAsync(8000);
    const response = await pending;

    expect(response.status).toBe(201);
    expect(calls(fetchMock, "POST")).toHaveLength(1);
    expect(calls(fetchMock, "GET")).toHaveLength(4);
  });

  it("asks every two seconds for thirty seconds and every three seconds afterwards", async () => {
    const times: number[] = [];
    const startedAt = Date.now();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input;

      if (init?.method === "POST") {
        return json(job(), 202);
      }

      times.push(Date.now() - startedAt);
      return json(times.length === 20 ? finished(201, CREATED) : job());
    });

    const pending = sendGeneration(OPERATION_URL, request(), options(fetchMock));
    await vi.advanceTimersByTimeAsync(60_000);
    await pending;

    expect(times).toEqual([
      2000, 4000, 6000, 8000, 10000, 12000, 14000, 16000, 18000, 20000, 22000, 24000, 26000, 28000,
      30000, 33000, 36000, 39000, 42000, 45000,
    ]);
    expect(pollInterval(0)).toBe(2000);
    expect(pollInterval(30_000)).toBe(3000);
  });

  it("gives up after twenty minutes without sending the operation again", async () => {
    const fetchMock = server([]);

    const pending = sendGeneration(OPERATION_URL, request(), options(fetchMock));
    await vi.advanceTimersByTimeAsync(POLL_LIMIT_MILLISECONDS + 3000);
    const response = await pending;

    expect(response.status).toBe(504);
    expect(await response.json()).toEqual({ detail: { code: GENERATION_POLL_TIMEOUT } });
    expect(calls(fetchMock, "POST")).toHaveLength(1);
    expect(calls(fetchMock, "GET").length).toBeGreaterThan(400);
    expect(followedGenerationJobs()).toEqual([]);
  });

  it("reports a job that the Studio no longer knows and forgets it", async () => {
    const steps: Step[] = [json({ detail: { code: GENERATION_JOB_NOT_FOUND } }, 404)];
    const fetchMock = server(steps);
    const ends: (string | null)[] = [];
    const stop = onFollowedGenerationJob((event) => ends.push(event.ended));

    const pending = sendGeneration(OPERATION_URL, request(), options(fetchMock));
    await vi.advanceTimersByTimeAsync(2000);
    const response = await pending;
    stop();

    expect(ends).toEqual([null, "lost"]);
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ detail: { code: GENERATION_JOB_NOT_FOUND } });
    expect(followedGenerationJobs()).toEqual([]);

    steps.push(json(finished(201, CREATED)));
    const again = sendGeneration(OPERATION_URL, request(), options(fetchMock));
    await vi.advanceTimersByTimeAsync(2000);
    await again;
    expect(calls(fetchMock, "POST")).toHaveLength(2);
  });

  it("returns a refused reading and resumes the same job on the next request", async () => {
    const fetchMock = server([
      json({ detail: "invalid_authentication" }, 401),
      json(finished(201, CREATED)),
    ]);

    const refused = sendGeneration(OPERATION_URL, request("old-token"), options(fetchMock));
    await vi.advanceTimersByTimeAsync(2000);
    const first = await refused;

    expect(first.status).toBe(401);

    const resumed = sendGeneration(OPERATION_URL, request("new-token"), options(fetchMock));
    await vi.advanceTimersByTimeAsync(2000);
    const second = await resumed;

    expect(await second.json()).toEqual(CREATED);
    expect(calls(fetchMock, "POST")).toHaveLength(1);
    const [, lastInit] = calls(fetchMock, "GET")[1] ?? [];
    expect(lastInit?.headers).toMatchObject({ Authorization: "Bearer new-token" });
  });

  it("survives the refresh of the access token while it waits", async () => {
    setActivePinia(createPinia());
    const auth = useAuthStore();
    auth.accessToken = "old-token";
    const authApi: AuthenticationApi = {
      register: vi.fn(),
      login: vi.fn(),
      logout: vi.fn(),
      me: vi.fn(),
      chooseGuidanceMode: vi.fn(),
      refresh: vi.fn(async () => ({
        access_token: "new-token",
        token_type: "bearer" as const,
        expires_at: "2026-09-28T10:30:00+00:00",
        user: {
          id: "00000000-0000-4000-8000-000000000001",
          email: "owner@example.com",
          is_active: true,
          created_at: "2026-09-01T10:00:00+00:00",
          guidance_mode: "GUIDED" as const,
        },
      })),
    };
    const fetchMock = server([
      json(job()),
      json({ detail: "invalid_authentication" }, 401),
      json(job()),
      json(finished(201, CREATED)),
    ]);
    const operation = async (token: string): Promise<unknown> => {
      const response = await sendGeneration(OPERATION_URL, request(token), options(fetchMock));
      const payload: unknown = await response.json();

      if (!response.ok) {
        throw new ApiRequestError("refused", { status: response.status, code: null, payload });
      }

      return payload;
    };

    const pending = auth.withAccessToken(authApi, operation);
    await vi.advanceTimersByTimeAsync(10_000);

    await expect(pending).resolves.toEqual(CREATED);
    expect(authApi.refresh).toHaveBeenCalledOnce();
    expect(calls(fetchMock, "POST")).toHaveLength(1);
    const polls = calls(fetchMock, "GET").map(([, init]) =>
      new Headers(init?.headers).get("Authorization"),
    );
    expect(polls).toEqual([
      "Bearer old-token",
      "Bearer old-token",
      "Bearer new-token",
      "Bearer new-token",
    ]);
  });

  it("lets a second identical request wait for the same job", async () => {
    const fetchMock = server([json(job()), json(finished(201, CREATED))]);

    const first = sendGeneration(OPERATION_URL, request(), options(fetchMock));
    await vi.advanceTimersByTimeAsync(0);
    const second = sendGeneration(OPERATION_URL, request(), options(fetchMock));
    await vi.advanceTimersByTimeAsync(4000);
    const [left, right] = await Promise.all([first, second]);

    expect(left).not.toBe(right);
    expect(await left.json()).toEqual(CREATED);
    expect(await right.json()).toEqual(CREATED);
    expect(calls(fetchMock, "POST")).toHaveLength(1);
    expect(calls(fetchMock, "GET")).toHaveLength(2);
  });

  it("lets a network error of the operation itself reach the caller without a retry", async () => {
    const failure = new TypeError("Failed to fetch");
    const fetchMock = vi.fn(async () => {
      throw failure;
    });

    await expect(sendGeneration(OPERATION_URL, request(), options(fetchMock))).rejects.toBe(
      failure,
    );
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("answers an accepted request without a job as an invalid answer", async () => {
    const fetchMock = server([], () => json({ accepted: true }, 202));

    const response = await sendGeneration(OPERATION_URL, request(), options(fetchMock));

    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({ detail: { code: INVALID_API_RESPONSE } });
    expect(calls(fetchMock, "GET")).toHaveLength(0);
  });

  it("answers a job that ended without an answer with its failure code", async () => {
    const cancelled = job({
      status: "FAILED",
      stage: null,
      failure: { code: "GENERATION_JOB_CANCELLED", reasons: [] },
    });
    const fetchMock = server([json(cancelled)]);

    const pending = sendGeneration(OPERATION_URL, request(), options(fetchMock));
    await vi.advanceTimersByTimeAsync(2000);
    const response = await pending;

    expect(response.status).toBe(500);
    expect(await response.json()).toEqual({ detail: { code: "GENERATION_JOB_CANCELLED" } });
  });

  it("keeps a plain text answer of the job as it is", async () => {
    const fetchMock = server([json(finished(500, "Internal Server Error"))]);

    const pending = sendGeneration(OPERATION_URL, request(), options(fetchMock));
    await vi.advanceTimersByTimeAsync(2000);
    const response = await pending;

    expect(response.status).toBe(500);
    expect(await response.text()).toBe("Internal Server Error");
  });

  it("tells its listeners which job it follows and when it stops", async () => {
    const events: GenerationJobEvent[] = [];
    const stop = onFollowedGenerationJob((event) => events.push(event));
    const fetchMock = server([json(job({ stage: "VALIDATING" })), json(finished(201, CREATED))]);

    const pending = sendGeneration(OPERATION_URL, request(), options(fetchMock));
    await vi.advanceTimersByTimeAsync(0);
    expect(followedGenerationJobs()).toEqual([
      { projectId: PROJECT_ID, job: job(), following: true, ended: null },
    ]);
    await vi.advanceTimersByTimeAsync(4000);
    await pending;
    stop();

    expect(
      events.map((event) => [event.following, event.ended, event.job.status, event.job.stage]),
    ).toEqual([
      [true, null, "RUNNING", "GENERATING"],
      [true, null, "RUNNING", "VALIDATING"],
      [false, "finished", "SUCCEEDED", null],
    ]);
    expect(events.every((event) => event.projectId === PROJECT_ID)).toBe(true);
  });
});

describe("Generation Jobs API client", () => {
  it("reads one job of the project", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      void init;
      return json(job());
    });
    const api = createGenerationJobsApi({ fetchImpl: fetchMock });

    await expect(api.job(PROJECT_ID, JOB_ID, "token")).resolves.toEqual(job());
    const [input, init] = fetchMock.mock.calls[0] ?? [];
    expect(input).toBe(JOB_URL);
    expect(init?.method).toBe("GET");
    expect(init?.credentials).toBe("include");
    expect(init?.headers).toMatchObject({ Authorization: "Bearer token" });
  });

  it("lists the running jobs of the project and drops what is not a job", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      void init;
      return json({ items: [job(), { job_id: "" }] });
    });
    const api = createGenerationJobsApi({ fetchImpl: fetchMock });

    await expect(api.list(PROJECT_ID, "token", "RUNNING")).resolves.toEqual([job()]);
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      `/api/v1/projects/${PROJECT_ID}/generation-jobs?status=RUNNING`,
    );
  });

  it("keeps the code of a refusal", async () => {
    const api = createGenerationJobsApi({
      fetchImpl: async () => json({ detail: { code: GENERATION_JOB_NOT_FOUND } }, 404),
    });

    await expect(api.job(PROJECT_ID, JOB_ID, "token")).rejects.toMatchObject({
      name: "GenerationJobsApiError",
      status: 404,
      code: GENERATION_JOB_NOT_FOUND,
    });
  });

  it("refuses an answer that is not a list of jobs", async () => {
    const api = createGenerationJobsApi({ fetchImpl: async () => json({ jobs: [] }) });

    await expect(api.list(PROJECT_ID, "token")).rejects.toMatchObject({
      code: INVALID_API_RESPONSE,
    });
  });

  it("requires an access token", async () => {
    const api = createGenerationJobsApi({ fetchImpl: vi.fn() });

    await expect(api.list(PROJECT_ID, " ")).rejects.toBeInstanceOf(GenerationJobsApiError);
  });

  it("fills the fields that an older job does not carry", () => {
    expect(
      generationJobOf({
        job_id: JOB_ID,
        kind: "MOCKUP",
        status: "RUNNING",
        started_at: "2026-09-28T10:00:00+00:00",
      }),
    ).toMatchObject({ operation: "MOCKUP", response: null, failure: null, attempt: 1 });
    expect(generationJobOf({ job_id: JOB_ID, status: "DONE" })).toBeNull();
    expect(generationJobOf({ ...job(), operation: "SOMETHING_ELSE" })).toBeNull();
  });

  it("reads the job of a change asked for the requirements", () => {
    expect(generationJobOf({ ...job(), operation: "REQUIREMENTS_CHANGE" })).toEqual(
      job({ operation: "REQUIREMENTS_CHANGE" }),
    );
  });

  it("reads the job of a review of a commit started from the terminal", () => {
    const review = {
      ...job(),
      operation: "CODE_CHANGE_REVIEW",
      status: "SUCCEEDED",
      stage: null,
      finished_at: "2026-09-28T10:03:00+00:00",
      response: { status_code: 201, body: { status: "REVIEWED", run: { id: "run-1" } } },
    };

    expect(generationJobOf(review)).toEqual(
      job({
        operation: "CODE_CHANGE_REVIEW",
        status: "SUCCEEDED",
        stage: null,
        finished_at: "2026-09-28T10:03:00+00:00",
        response: { status_code: 201, body: { status: "REVIEWED", run: { id: "run-1" } } },
      }),
    );
  });

  it.each([
    ["TEST_PLAN", { status: "PLANNED", plan: { id: "plan-1" } }],
    ["TEST_REVIEW", { status: "REVIEWED", review: { id: "review-1" } }],
  ] as const)("reads the job of a %s started by ut test", (operation, body) => {
    const ended = {
      ...job(),
      operation,
      status: "SUCCEEDED",
      stage: null,
      finished_at: "2026-09-28T10:03:00+00:00",
      response: { status_code: 201, body },
    };

    expect(generationJobOf(ended)).toEqual(
      job({
        operation,
        status: "SUCCEEDED",
        stage: null,
        finished_at: "2026-09-28T10:03:00+00:00",
        response: { status_code: 201, body },
      }),
    );
  });

  it("reads and lists the proposal of what a twin learned started by ut twins update", async () => {
    const running = job({ operation: "TWIN_UPDATE" });
    const ended = {
      ...job(),
      operation: "TWIN_UPDATE",
      status: "SUCCEEDED",
      stage: null,
      finished_at: "2026-09-28T10:01:00+00:00",
      response: { status_code: 201, body: { status: "PROPOSED", update: { id: "update-1" } } },
    };
    const api = createGenerationJobsApi({ fetchImpl: async () => json({ items: [running] }) });

    await expect(api.list(PROJECT_ID, "token", "RUNNING")).resolves.toEqual([running]);
    expect(generationJobOf(ended)).toEqual(
      job({
        operation: "TWIN_UPDATE",
        status: "SUCCEEDED",
        stage: null,
        finished_at: "2026-09-28T10:01:00+00:00",
        response: { status_code: 201, body: { status: "PROPOSED", update: { id: "update-1" } } },
      }),
    );
  });

  it.each([
    [
      "KNOWLEDGE_ALIGNMENT",
      { run: { id: "run-1", proposals: [{ code: "ALN-001", section: "REQUIREMENTS" }] } },
    ],
    ["DESIGN_CHANGE", { revision: { status: "CREATED", diff: { id: "diff-1" } }, changes: [] }],
  ] as const)("reads and lists the job of a %s", async (operation, body) => {
    const running = job({ operation });
    const ended = {
      ...job(),
      operation,
      status: "SUCCEEDED",
      stage: null,
      finished_at: "2026-09-28T10:03:00+00:00",
      response: { status_code: 201, body },
    };
    const api = createGenerationJobsApi({ fetchImpl: async () => json({ items: [running] }) });

    await expect(api.list(PROJECT_ID, "token", "RUNNING")).resolves.toEqual([running]);
    expect(generationJobOf(ended)).toEqual(
      job({
        operation,
        status: "SUCCEEDED",
        stage: null,
        finished_at: "2026-09-28T10:03:00+00:00",
        response: { status_code: 201, body },
      }),
    );
  });

  it("lists the running plan and review of the acceptance tests started by ut test", async () => {
    const plan = job({ operation: "TEST_PLAN" });
    const review = job({
      job_id: "00000000-0000-4000-8000-0000000000ab",
      operation: "TEST_REVIEW",
    });
    const api = createGenerationJobsApi({ fetchImpl: async () => json({ items: [plan, review] }) });

    await expect(api.list(PROJECT_ID, "token", "RUNNING")).resolves.toEqual([plan, review]);
  });

  it("names a missing or cancelled job as a lost generation", () => {
    expect(isGenerationLost(GENERATION_JOB_NOT_FOUND)).toBe(true);
    expect(isGenerationLost(GENERATION_JOB_CANCELLED)).toBe(true);
    expect(isGenerationLost(GENERATION_POLL_TIMEOUT)).toBe(false);
    expect(isGenerationLost(null)).toBe(false);
    expect(isGenerationInterrupted(GENERATION_POLL_TIMEOUT)).toBe(true);
    expect(isGenerationInterrupted(GENERATION_JOB_CANCELLED)).toBe(true);
    expect(isGenerationInterrupted("TIMEOUT")).toBe(false);
  });
});
