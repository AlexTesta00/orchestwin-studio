import { describe, expect, it, vi } from "vitest";

import type { TwinLearningPayload } from "../types/twinLearning";
import { TwinLearningApiError, createTwinLearningApi } from "./twinLearning";

const PROJECT_ID = "11111111-1111-4111-8111-111111111111";
const ACCESS_TOKEN = "test-token-not-real";

const LEARNING: TwinLearningPayload = {
  project_id: PROJECT_ID,
  update_available: true,
  twins: [
    {
      twin_id: "22222222-2222-4222-8222-222222222222",
      twin_name: "Reception staff",
      profile_version_number: 1,
      development_version_number: 2,
      label: "1.2",
      observations: [
        {
          code: "OBS-001",
          statement: "Reception staff look for a new guest at the top of the list.",
          basis: "Two findings on the acceptance tests.",
          source: "TWIN_CRITIQUE",
          about: { requirement: "REQ-003", screen: "SCR-001" },
          contradicts_profile: null,
          added_in_version: 1,
          approved_at: "2026-09-29T10:00:00+00:00",
          update_id: "33333333-3333-4333-8333-333333333333",
        },
      ],
      retired: [
        {
          code: "OBS-002",
          statement: "Reception staff print the list.",
          retired_in_version: 2,
          retired_at: "2026-09-29T11:00:00+00:00",
          reason: null,
        },
      ],
      pending_update: null,
      new_material: { changes: 1, tests: 0 },
    },
  ],
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function twin(overrides: Record<string, unknown>): TwinLearningPayload {
  return {
    ...LEARNING,
    twins: [{ ...LEARNING.twins[0]!, ...overrides }],
  } as unknown as TwinLearningPayload;
}

function observationWithout(key: string): TwinLearningPayload {
  const observation: Record<string, unknown> = { ...LEARNING.twins[0]!.observations[0]! };
  delete observation[key];
  return twin({ observations: [observation] });
}

describe("Twin Learning API client", () => {
  it("reads what the twins learned with an authenticated GET", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(LEARNING));
    const api = createTwinLearningApi({ fetchImpl });

    const learning = await api.overview(PROJECT_ID, ACCESS_TOKEN);

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const call = fetchImpl.mock.calls[0];
    expect(call?.[0]).toBe(`/api/v1/projects/${PROJECT_ID}/twin-learning`);
    expect(call?.[1]?.method).toBe("GET");
    expect(call?.[1]?.credentials).toBe("include");
    expect(call?.[1]?.headers).toEqual({
      Accept: "application/json",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
    });
    expect(call?.[1]).not.toHaveProperty("body");
    expect(learning).toEqual(LEARNING);
  });

  it("reads a project whose user modeling is not approved and a pending proposal", async () => {
    const pending = twin({
      pending_update: {
        id: "44444444-4444-4444-8444-444444444444",
        twin_id: LEARNING.twins[0]!.twin_id,
        twin_name: "Reception staff",
        created_at: "2026-09-29T12:00:00+00:00",
        locale: "en-GB",
        status: "PROPOSED",
        base: { profile_version_number: 1, development_version_number: 2 },
        comment: "From the latest critiques I learned 1 things about my group.",
        observations: [],
        material: { changes: 1, tests: 0 },
        decision: null,
        cost_microusd: 150000,
      },
    });
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ ...LEARNING, twins: [] }))
      .mockResolvedValueOnce(jsonResponse(pending));
    const api = createTwinLearningApi({ fetchImpl });

    await expect(api.overview(PROJECT_ID, ACCESS_TOKEN)).resolves.toEqual({
      ...LEARNING,
      twins: [],
    });
    await expect(api.overview(PROJECT_ID, ACCESS_TOKEN)).resolves.toEqual(pending);
  });

  it("uses the base path and encodes the project of the path", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(LEARNING));
    const api = createTwinLearningApi({ basePath: "/studio/api/v1/", fetchImpl });

    await api.overview("project 1/a", ACCESS_TOKEN);

    expect(fetchImpl.mock.calls[0]?.[0]).toBe(
      "/studio/api/v1/projects/project%201%2Fa/twin-learning",
    );
  });

  it.each([
    ["a Studio older than the route", 404, { detail: "Not Found" }],
    ["a project of another account", 404, { detail: { code: "PROJECT_NOT_FOUND" } }],
    ["a Studio that knows the path without its reading", 405, { detail: "Method Not Allowed" }],
  ])("answers nothing for %s", async (_case, status, body) => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(body, status));
    const api = createTwinLearningApi({ fetchImpl });

    await expect(api.overview(PROJECT_ID, ACCESS_TOKEN)).resolves.toBeNull();
  });

  it("keeps the typed code of a refusal and a body that is not JSON", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ detail: { code: "DATABASE_UNAVAILABLE" } }, 503))
      .mockResolvedValueOnce(new Response("Bad gateway", { status: 502 }))
      .mockResolvedValueOnce(jsonResponse({ detail: "invalid_request" }, 422));
    const api = createTwinLearningApi({ fetchImpl });

    const unavailable = api.overview(PROJECT_ID, ACCESS_TOKEN);
    await expect(unavailable).rejects.toBeInstanceOf(TwinLearningApiError);
    await expect(unavailable).rejects.toMatchObject({
      name: "TwinLearningApiError",
      message: "The twin learning request failed",
      status: 503,
      code: "DATABASE_UNAVAILABLE",
    });
    await expect(api.overview(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      status: 502,
      code: null,
      payload: "Bad gateway",
    });
    await expect(api.overview(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      status: 422,
      code: null,
      payload: { detail: "invalid_request" },
    });
  });

  it.each([
    ["a text", "<html>proxy error</html>"],
    ["a list", []],
    ["an answer without twins", { project_id: PROJECT_ID, update_available: true }],
    ["an answer without the availability", { project_id: PROJECT_ID, twins: [] }],
    ["twins that are not a list", { ...LEARNING, twins: "none" }],
    ["a twin without a label", twin({ label: 1 })],
    ["a twin without observations", twin({ observations: null })],
    ["an observation without a code", observationWithout("code")],
    ["an observation without a statement", observationWithout("statement")],
    ["an observation without where it comes from", observationWithout("source")],
    ["an observation without its date", observationWithout("approved_at")],
    ["an observation without its subjects", observationWithout("about")],
    ["a twin without retired observations", twin({ retired: undefined })],
    ["a proposal that is not an object", twin({ pending_update: "PROPOSED" })],
    ["new material without numbers", twin({ new_material: { changes: "1", tests: 0 } })],
  ])("rejects %s", async (_case, body) => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        typeof body === "string" ? new Response(body, { status: 200 }) : jsonResponse(body),
      );
    const api = createTwinLearningApi({ fetchImpl });

    await expect(api.overview(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      name: "TwinLearningApiError",
      status: 200,
      code: "INVALID_API_RESPONSE",
    });
  });

  it("refuses to call the Studio without an access token", async () => {
    const fetchImpl = vi.fn<typeof fetch>();
    const api = createTwinLearningApi({ fetchImpl });

    await expect(api.overview(PROJECT_ID, " ")).rejects.toMatchObject({
      name: "TwinLearningApiError",
      status: 0,
      code: "ACCESS_TOKEN_REQUIRED",
    });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("refuses an empty base path", () => {
    expect(() => createTwinLearningApi({ basePath: " / ", fetchImpl: vi.fn() })).toThrow(
      "Twin Learning API base path must not be empty",
    );
  });
});
