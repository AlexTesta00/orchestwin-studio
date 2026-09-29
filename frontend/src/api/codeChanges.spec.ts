import { describe, expect, it, vi } from "vitest";

import type {
  AlignmentPayload,
  ChangeReviewListPayload,
  CodeChangeListPayload,
  CodeChangePayload,
} from "../types/codeChanges";
import { CodeChangesApiError, createCodeChangesApi } from "./codeChanges";

const PROJECT_ID = "11111111-1111-4111-8111-111111111111";
const ACCESS_TOKEN = "test-token-not-real";
const COMMIT = "4f2a9c1e7b3d5a6f8e0c2b4d6f8a0c2e4b6d8f0a";

const CHANGE: CodeChangePayload = {
  commit: COMMIT,
  parent: null,
  committed_at: "2026-09-29T08:00:00+00:00",
  author: "Alex",
  message: "Add the guest list\n\nWith the empty state.",
  files: [{ path: "src/guests.js", kind: "ADDED", added: 40, removed: 0 }],
  recorded_at: "2026-09-29T08:01:00+00:00",
  review: null,
  decision: null,
};

const ALIGNMENT: AlignmentPayload = {
  project_id: PROJECT_ID,
  reference: {
    requirements: { version_id: "r", version_number: 2, content_hash: "a".repeat(64) },
    design: {
      version_id: "d",
      version_number: 3,
      content_hash: "b".repeat(64),
      alternative_code: "DES-002",
    },
  },
  aligned: null,
  pending_changes: 1,
  latest_change: CHANGE,
  tasks: [],
  review_available: true,
};

const CHANGES: CodeChangeListPayload = { items: [CHANGE] };

const REVIEWS: ChangeReviewListPayload = {
  items: [
    {
      id: "22222222-2222-4222-8222-222222222222",
      commit: COMMIT,
      reviewed_at: "2026-09-29T08:05:00+00:00",
      locale: "it-IT",
      reference: {
        requirements_version_number: 2,
        design_version_number: 3,
        alternative_code: "DES-002",
      },
      critiques: [],
      alignment: {
        status: "ALIGNED",
        summary: "Il codice segue il design.",
        affected: { requirements: [], screens: [] },
        design_request: null,
        requirements_request: null,
        code_tasks: [],
      },
      cost_microusd: 650000,
    },
  ],
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("Code Changes API client", () => {
  it("reads the alignment of the project with an authenticated GET", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(ALIGNMENT));
    const api = createCodeChangesApi({ fetchImpl });

    const alignment = await api.alignment(PROJECT_ID, ACCESS_TOKEN);

    const call = fetchImpl.mock.calls[0];
    expect(call?.[0]).toBe(`/api/v1/projects/${PROJECT_ID}/alignment`);
    expect(call?.[1]?.method).toBe("GET");
    expect(call?.[1]?.credentials).toBe("include");
    expect(call?.[1]?.headers).toEqual({
      Accept: "application/json",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
    });
    expect(call?.[1]).not.toHaveProperty("body");
    expect(alignment).toEqual(ALIGNMENT);
  });

  it("lists every recorded change, or only the pending ones when asked", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockImplementation(async () => jsonResponse(CHANGES));
    const api = createCodeChangesApi({ basePath: "/studio/api/v1/", fetchImpl });

    const every = await api.changes("project 1", ACCESS_TOKEN);
    await api.changes("project 1", ACCESS_TOKEN, true);
    await api.changes("project 1", ACCESS_TOKEN, false);

    expect(every).toEqual(CHANGES);
    expect(fetchImpl.mock.calls.map((call) => [call[0], call[1]?.method])).toEqual([
      ["/studio/api/v1/projects/project%201/code-changes", "GET"],
      ["/studio/api/v1/projects/project%201/code-changes?pending=true", "GET"],
      ["/studio/api/v1/projects/project%201/code-changes", "GET"],
    ]);
  });

  it("reads the review runs of a commit, newest first as the Studio sends them", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(REVIEWS));
    const api = createCodeChangesApi({ fetchImpl });

    const reviews = await api.reviews(PROJECT_ID, "4f2a9c1", ACCESS_TOKEN);

    expect(fetchImpl.mock.calls[0]?.[0]).toBe(
      `/api/v1/projects/${PROJECT_ID}/code-changes/4f2a9c1/reviews`,
    );
    expect(fetchImpl.mock.calls[0]?.[1]?.headers).toEqual({
      Accept: "application/json",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
    });
    expect(reviews).toEqual(REVIEWS);
  });

  it("encodes the commit of the path", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({ items: [] }));
    const api = createCodeChangesApi({ fetchImpl });

    await api.reviews(PROJECT_ID, "abc/def", ACCESS_TOKEN);

    expect(fetchImpl.mock.calls[0]?.[0]).toBe(
      `/api/v1/projects/${PROJECT_ID}/code-changes/abc%2Fdef/reviews`,
    );
  });

  it("keeps the typed codes of the refusals of the Studio", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ detail: { code: "PROJECT_NOT_FOUND" } }, 404))
      .mockResolvedValueOnce(jsonResponse({ detail: { code: "CODE_CHANGE_AMBIGUOUS" } }, 409))
      .mockResolvedValueOnce(jsonResponse({ detail: { code: "CODE_CHANGE_NOT_FOUND" } }, 404))
      .mockResolvedValueOnce(jsonResponse({ detail: "invalid_request", errors: [] }, 422));
    const api = createCodeChangesApi({ fetchImpl });

    const missing = api.alignment(PROJECT_ID, ACCESS_TOKEN);
    await expect(missing).rejects.toBeInstanceOf(CodeChangesApiError);
    await expect(missing).rejects.toMatchObject({
      name: "CodeChangesApiError",
      status: 404,
      code: "PROJECT_NOT_FOUND",
    });
    await expect(api.reviews(PROJECT_ID, "4f2a9c1", ACCESS_TOKEN)).rejects.toMatchObject({
      status: 409,
      code: "CODE_CHANGE_AMBIGUOUS",
    });
    await expect(api.reviews(PROJECT_ID, "4f2a9c1", ACCESS_TOKEN)).rejects.toMatchObject({
      status: 404,
      code: "CODE_CHANGE_NOT_FOUND",
    });
    await expect(api.changes(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      status: 422,
      code: null,
      payload: { detail: "invalid_request", errors: [] },
    });
  });

  it("rejects an answer that is not a JSON object or a list without items", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(new Response("<html>proxy error</html>", { status: 200 }))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse({ items: "none" }))
      .mockResolvedValueOnce(jsonResponse({ runs: [] }));
    const api = createCodeChangesApi({ fetchImpl });

    await expect(api.alignment(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      name: "CodeChangesApiError",
      status: 200,
      code: "INVALID_API_RESPONSE",
      payload: "<html>proxy error</html>",
    });
    await expect(api.alignment(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      code: "INVALID_API_RESPONSE",
      payload: [],
    });
    await expect(api.changes(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      code: "INVALID_API_RESPONSE",
      payload: { items: "none" },
    });
    await expect(api.reviews(PROJECT_ID, COMMIT, ACCESS_TOKEN)).rejects.toMatchObject({
      code: "INVALID_API_RESPONSE",
      payload: { runs: [] },
    });
  });

  it("refuses to call the Studio without an access token", async () => {
    const fetchImpl = vi.fn<typeof fetch>();
    const api = createCodeChangesApi({ fetchImpl });

    await expect(api.alignment(PROJECT_ID, " ")).rejects.toMatchObject({
      name: "CodeChangesApiError",
      status: 0,
      code: "ACCESS_TOKEN_REQUIRED",
    });
    await expect(api.changes(PROJECT_ID, "")).rejects.toMatchObject({
      code: "ACCESS_TOKEN_REQUIRED",
    });
    await expect(api.reviews(PROJECT_ID, COMMIT, "   ")).rejects.toMatchObject({
      code: "ACCESS_TOKEN_REQUIRED",
    });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("refuses an empty base path", () => {
    expect(() => createCodeChangesApi({ basePath: " / ", fetchImpl: vi.fn() })).toThrow(
      "Code Changes API base path must not be empty",
    );
  });
});
