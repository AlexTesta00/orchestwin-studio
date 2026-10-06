import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clearFollowedGenerations, type GenerationRequestJob } from "./generationJobs";
import { createKnowledgeAlignmentApi, KnowledgeAlignmentApiError } from "./knowledgeAlignment";
import {
  ALIGNMENT_PROJECT_ID as PROJECT_ID,
  applyAnswer,
  DESIGN_PROPOSAL,
  proposalList,
  REQUIREMENTS_PROPOSAL,
  RUN_SUMMARY,
  skippedProposal,
  TESTS_PROPOSAL,
} from "../test/knowledgeAlignmentFixtures";

const ACCESS_TOKEN = "test-token-not-real";
const DIFF_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
const JOB_ID = "00000000-0000-4000-8000-0000000000aa";
const ALIGNMENT_URL = `/api/v1/projects/${PROJECT_ID}/alignment`;
const JOB_URL = `/api/v1/projects/${PROJECT_ID}/generation-jobs/${JOB_ID}`;

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function job(overrides: Partial<GenerationRequestJob> = {}): GenerationRequestJob {
  return {
    job_id: JOB_ID,
    kind: "REQUEST",
    operation: "REQUIREMENTS_CHANGE",
    status: "RUNNING",
    stage: "GENERATING",
    attempt: 1,
    started_at: "2026-10-06T10:00:00+00:00",
    finished_at: null,
    alternative_id: null,
    failure: null,
    response: null,
    ...overrides,
  };
}

function ended(statusCode: number, body: unknown): GenerationRequestJob {
  return job({
    status: statusCode < 400 ? "SUCCEEDED" : "FAILED",
    stage: null,
    finished_at: "2026-10-06T10:02:00+00:00",
    response: { status_code: statusCode, body },
  });
}

function studio(outcome: GenerationRequestJob) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    void input;

    return init?.method === "POST" ? jsonResponse(job(), 202) : jsonResponse(outcome);
  });
}

function calls(fetchMock: ReturnType<typeof studio>, method: "GET" | "POST") {
  return fetchMock.mock.calls.filter(([, init]) => init?.method === method);
}

describe("Knowledge Alignment API client", () => {
  beforeEach(() => {
    clearFollowedGenerations();
  });

  afterEach(() => {
    vi.useRealTimers();
    clearFollowedGenerations();
  });

  it("reads the waiting proposals, or every proposal when asked, with an authenticated GET", async () => {
    const list = proposalList([REQUIREMENTS_PROPOSAL, DESIGN_PROPOSAL, TESTS_PROPOSAL]);
    const fetchImpl = vi.fn<typeof fetch>().mockImplementation(async () => jsonResponse(list));
    const api = createKnowledgeAlignmentApi({ fetchImpl });

    const waiting = await api.proposals(PROJECT_ID, "waiting", ACCESS_TOKEN);
    await api.proposals(PROJECT_ID, "all", ACCESS_TOKEN);

    expect(waiting).toEqual(list);
    expect(fetchImpl.mock.calls.map((call) => call[0])).toEqual([
      `${ALIGNMENT_URL}/proposals?status=waiting`,
      `${ALIGNMENT_URL}/proposals?status=all`,
    ]);
    const init = fetchImpl.mock.calls[0]?.[1];
    expect(init?.method).toBe("GET");
    expect(init?.credentials).toBe("include");
    expect(init?.headers).toEqual({
      Accept: "application/json",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
    });
    expect(init).not.toHaveProperty("body");
  });

  it("lists the runs of the project with their counts as the Studio sends them", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse({ items: [RUN_SUMMARY] }));
    const api = createKnowledgeAlignmentApi({ basePath: "/studio/api/v1/", fetchImpl });

    await expect(api.runs("project 1", ACCESS_TOKEN)).resolves.toEqual({ items: [RUN_SUMMARY] });

    expect(fetchImpl.mock.calls[0]?.[0]).toBe("/studio/api/v1/projects/project%201/alignment/runs");
    expect(fetchImpl.mock.calls[0]?.[1]?.method).toBe("GET");
  });

  it("applies a proposal asking for a background job and returns a synchronous answer as it is", async () => {
    const answer = applyAnswer(TESTS_PROPOSAL, null, null);
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(answer));
    const api = createKnowledgeAlignmentApi({ fetchImpl });

    const applied = await api.apply(PROJECT_ID, "ALN-003", null, ACCESS_TOKEN);

    expect(applied).toEqual(answer);
    expect(fetchImpl).toHaveBeenCalledOnce();
    const [url, init] = fetchImpl.mock.calls[0] ?? [];
    expect(url).toBe(`${ALIGNMENT_URL}/proposals/ALN-003/apply`);
    expect(init?.method).toBe("POST");
    expect(init?.credentials).toBe("include");
    expect(init?.headers).toEqual({
      Accept: "application/json",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
      "Content-Type": "application/json",
      Prefer: "respond-async",
    });
    expect(init?.body).toBe(JSON.stringify({ text: null }));
  });

  it("sends the text edited by the owner and follows the job until the revision is created", async () => {
    vi.useFakeTimers();
    const answer = applyAnswer(REQUIREMENTS_PROPOSAL, "Edited request.", DIFF_ID);
    const fetchMock = studio(ended(200, answer));
    const api = createKnowledgeAlignmentApi({ fetchImpl: fetchMock });

    const pending = api.apply(PROJECT_ID, "ALN-001", "Edited request.", ACCESS_TOKEN);
    await vi.advanceTimersByTimeAsync(2000);

    await expect(pending).resolves.toEqual(answer);
    expect(calls(fetchMock, "POST")).toHaveLength(1);
    expect(calls(fetchMock, "POST")[0]?.[1]?.body).toBe(
      JSON.stringify({ text: "Edited request." }),
    );
    expect(calls(fetchMock, "GET").map(([url]) => url)).toEqual([JOB_URL]);
    expect(calls(fetchMock, "GET")[0]?.[1]?.headers).toMatchObject({
      Accept: "application/json",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
    });
  });

  it("keeps the typed code of a refusal that the job carries", async () => {
    vi.useFakeTimers();
    const refusal = { detail: { code: "REQUIREMENTS_REVISION_PENDING" } };
    const fetchMock = studio(ended(409, refusal));
    const api = createKnowledgeAlignmentApi({ fetchImpl: fetchMock });

    const pending = api.apply(PROJECT_ID, "ALN-001", null, ACCESS_TOKEN);
    const refused = expect(pending).rejects.toMatchObject({
      name: "KnowledgeAlignmentApiError",
      status: 409,
      code: "REQUIREMENTS_REVISION_PENDING",
      payload: refusal,
    });
    await vi.advanceTimersByTimeAsync(2000);

    await refused;
    expect(calls(fetchMock, "POST")).toHaveLength(1);
  });

  it("skips a proposal with its reason without asking for a background job", async () => {
    const answer = { proposal: skippedProposal(DESIGN_PROPOSAL, "Already in the design.") };
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(answer));
    const api = createKnowledgeAlignmentApi({ fetchImpl });

    await expect(
      api.skip(PROJECT_ID, "ALN-002", "Already in the design.", ACCESS_TOKEN),
    ).resolves.toEqual(answer);

    const [url, init] = fetchImpl.mock.calls[0] ?? [];
    expect(url).toBe(`${ALIGNMENT_URL}/proposals/ALN-002/skip`);
    expect(init?.method).toBe("POST");
    expect(init?.credentials).toBe("include");
    expect(init?.headers).toEqual({
      Accept: "application/json",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
      "Content-Type": "application/json",
    });
    expect(init?.body).toBe(JSON.stringify({ reason: "Already in the design." }));
  });

  it("encodes the project and the code of the paths", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse({ proposal: skippedProposal(TESTS_PROPOSAL, null) }));
    const api = createKnowledgeAlignmentApi({ fetchImpl });

    await api.skip("project 1", "ALN/003", null, ACCESS_TOKEN);

    expect(fetchImpl.mock.calls[0]?.[0]).toBe(
      "/api/v1/projects/project%201/alignment/proposals/ALN%2F003/skip",
    );
    expect(fetchImpl.mock.calls[0]?.[1]?.body).toBe(JSON.stringify({ reason: null }));
  });

  it("prefers the proposal issue of a refusal and keeps the other codes of the Studio", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ detail: { code: "ALIGNMENT_PROPOSAL_DECIDED" } }, 409))
      .mockResolvedValueOnce(
        jsonResponse(
          {
            detail: {
              code: "REQUIREMENTS_CHANGE_REJECTED",
              proposal_issue: "REQUIREMENTS_UNCHANGED",
            },
          },
          409,
        ),
      )
      .mockResolvedValueOnce(
        jsonResponse({ detail: { code: "ALIGNMENT_PROPOSAL_NOT_FOUND" } }, 404),
      )
      .mockResolvedValueOnce(jsonResponse({ detail: "invalid_request", errors: [] }, 422));
    const api = createKnowledgeAlignmentApi({ fetchImpl });

    const decided = api.skip(PROJECT_ID, "ALN-001", null, ACCESS_TOKEN);
    await expect(decided).rejects.toBeInstanceOf(KnowledgeAlignmentApiError);
    await expect(decided).rejects.toMatchObject({
      name: "KnowledgeAlignmentApiError",
      status: 409,
      code: "ALIGNMENT_PROPOSAL_DECIDED",
    });
    await expect(api.apply(PROJECT_ID, "ALN-001", null, ACCESS_TOKEN)).rejects.toMatchObject({
      status: 409,
      code: "REQUIREMENTS_UNCHANGED",
    });
    await expect(api.apply(PROJECT_ID, "ALN-009", null, ACCESS_TOKEN)).rejects.toMatchObject({
      status: 404,
      code: "ALIGNMENT_PROPOSAL_NOT_FOUND",
    });
    await expect(api.proposals(PROJECT_ID, "waiting", ACCESS_TOKEN)).rejects.toMatchObject({
      status: 422,
      code: null,
      payload: { detail: "invalid_request", errors: [] },
    });
  });

  it("rejects an answer that is not a JSON object, a list without items or a decision without proposal", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(new Response("<html>proxy error</html>", { status: 200 }))
      .mockResolvedValueOnce(jsonResponse({ proposals: [] }))
      .mockResolvedValueOnce(jsonResponse({ runs: [] }))
      .mockResolvedValueOnce(jsonResponse({ applied: true }));
    const api = createKnowledgeAlignmentApi({ fetchImpl });

    await expect(api.proposals(PROJECT_ID, "waiting", ACCESS_TOKEN)).rejects.toMatchObject({
      name: "KnowledgeAlignmentApiError",
      status: 200,
      code: "INVALID_API_RESPONSE",
      payload: "<html>proxy error</html>",
    });
    await expect(api.proposals(PROJECT_ID, "all", ACCESS_TOKEN)).rejects.toMatchObject({
      code: "INVALID_API_RESPONSE",
      payload: { proposals: [] },
    });
    await expect(api.runs(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      code: "INVALID_API_RESPONSE",
      payload: { runs: [] },
    });
    await expect(api.skip(PROJECT_ID, "ALN-001", null, ACCESS_TOKEN)).rejects.toMatchObject({
      code: "INVALID_API_RESPONSE",
      payload: { applied: true },
    });
  });

  it("refuses to call the Studio without an access token", async () => {
    const fetchImpl = vi.fn<typeof fetch>();
    const api = createKnowledgeAlignmentApi({ fetchImpl });

    await expect(api.proposals(PROJECT_ID, "waiting", " ")).rejects.toMatchObject({
      name: "KnowledgeAlignmentApiError",
      status: 0,
      code: "ACCESS_TOKEN_REQUIRED",
    });
    await expect(api.apply(PROJECT_ID, "ALN-001", null, "")).rejects.toMatchObject({
      code: "ACCESS_TOKEN_REQUIRED",
    });
    await expect(api.skip(PROJECT_ID, "ALN-001", null, "   ")).rejects.toMatchObject({
      code: "ACCESS_TOKEN_REQUIRED",
    });
    await expect(api.runs(PROJECT_ID, "")).rejects.toMatchObject({
      code: "ACCESS_TOKEN_REQUIRED",
    });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("refuses an empty base path", () => {
    expect(() => createKnowledgeAlignmentApi({ basePath: " / ", fetchImpl: vi.fn() })).toThrow(
      "Knowledge Alignment API base path must not be empty",
    );
  });
});
